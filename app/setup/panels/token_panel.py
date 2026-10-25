"""Токен доступа на вкладке «Токены» без окна (CLAUDE.md §8.2 п.10, §7.3, §14 решения 11, 16, 44, 45, 70, 77).

`TokenPanel` создаёт токен из значений, которые человек внёс на этой установке сам, и загружает полученный токен.
Создание: из своих значений сейфа (без раскрытия — секрет шифрует себя сам), открытых настроек (`TokenSettings`) и своих
файлов secrets\\ — только то, что выбрали ползунки значений (`TokenScope`, §14 решение 77): ползунок на каждое значение,
«Проект Google» — проект и вход оператора, «Каналы YouTube» — каналы и входы в них; какие значения есть на этой
установке, говорит `available` → время сети → один файл в tokens\\
под именем по содержимому (`TokenName`, §14 решение 66): `lvc[_<ID проекта Google>][_channels]_<DD-MM-YYYY>_<HHMMSS>`
— ID проекта, когда токен несёт проект, channels — когда несёт каналы. Имя — для людей: программа его не читает,
загрузка берёт любой файл, и переименовать токен можно, сохранив расширение .lctoken.
Загрузка: файл токена → время сети → значения ложатся слоем «из токена» (прежний слой заменяется целиком), открытые
настройки — в livecraft.json тем же разбором, что пишет окно, и отпечатками в учёт полученного (`ReceivedFiles`): в новый
токен полученная настройка не идёт, пока человек не поменяет её в окне; файлы — по правилу «полученное заменяет
полученное, своё главнее». Нет сети — ни создания, ни загрузки.

Обе работы идут в фоновом потоке окна: модель не знает ни потоков, ни Tk. Итог — `TokenVerdict`: строки для окна. В
строках и в логе нет значений — только названия полей и ярлыки с отпечатками (§7.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from app.config.files import SettingsFile
from app.config.json_node import ConfigError
from app.config.telegram import ChatTarget
from app.config.setting_key import SettingKey
from app.config.settings import LivecraftSettings
from app.core.dates import FILE_STAMP_FORMAT, format_human_datetime
from app.core.errors import os_error_reason
from app.core.text_format import NEWLINE
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.google.oauth_client import OAuthClient
from app.paths import DataDir, LivecraftPaths
from app.secretsafe.dpapi import DpapiUnavailable
from app.secretsafe.network_time import NetworkTime
from app.secretsafe.store import VaultStore
from app.secretsafe.token import (
    AccessToken,
    IssuedToken,
    TokenContent,
    TokenError,
    TokenOrder,
    TokenProblem,
)
from app.secretsafe.vault import Vault
from app.setup.panels.token_file import ReceivedFiles
from app.setup.panels.token_files import TokenFiles
from app.setup.panels.token_scope import TokenItem, TokenScope
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)

# Открытые настройки, которые несёт токен (§14 решение 16): ссылка на форму ключей, Telegram — куда слать объявления
# и чаты — и контакты для стримеров в документе объявлений.
OPEN_KEYS: Final[tuple[SettingKey, ...]] = (
    SettingKey.FORM_URL,
    SettingKey.TELEGRAM_TARGET,
    SettingKey.TELEGRAM_GROUP_CHAT_ID,
    SettingKey.TELEGRAM_PRIVATE_CHAT_ID,
    SettingKey.DOCS_CONTACTS,
)
DEFAULT_TOKEN_DAYS: Final[int] = 3
MAX_TOKEN_DAYS: Final[int] = 3650      # десять лет: дальше срок уже не срок, а timedelta переполняется


class TokenNameMark(str, Enum):
    """Части имени файла токена: начало, метка каналов и разделитель частей."""

    PREFIX = "lvc"
    CHANNELS = "channels"
    SEPARATOR = "_"


@dataclass(frozen=True)
class TokenName:
    """Имя файла токена по его содержимому: ID проекта Google, если токен несёт клиента; метка channels, если несёт
    каналы; момент создания в поясе программы (`stamp`, DD-MM-YYYY_HHMMSS)."""

    project: str | None
    has_channels: bool
    stamp: str

    @classmethod
    def of(cls, content: TokenContent, stamp: str) -> TokenName:
        files: TokenFiles = TokenFiles.of(content.files)
        client: OAuthClient | None = files.client
        project: str | None = None if client is None else client.project_id
        return cls(project=project, has_channels=files.channels is not None, stamp=stamp)

    @property
    def stem(self) -> str:
        """Имя без расширения: lvc[_<проект>][_channels]_<момент>."""
        channels: str | None = TokenNameMark.CHANNELS.value if self.has_channels else None
        parts: tuple[str | None, ...] = (TokenNameMark.PREFIX.value, self.project, channels, self.stamp)
        return TokenNameMark.SEPARATOR.value.join(part for part in parts if part)


class TokenPanelEvent(str, Enum):
    """События вкладки «Токены» в логе."""

    CREATED = "token_created"
    LOADED = "token_loaded"
    NOT_DONE = "token_not_done"


class NotDoneReason(str, Enum):
    """Почему токен не создан или не загружен, кроме отказа чтения токена (`TokenProblem`). Идентификатор для лога."""

    DAYS = "days"                    # срок — не целое число суток в пределах
    NOTHING = "nothing"              # своих значений, открытых настроек и файлов нет: передавать нечего
    NO_NETWORK = "no_network"        # время сети не получено
    WRITE = "write_failed"           # файлы токена не записались
    SETTINGS = "settings_invalid"    # открытые настройки токена не проходят разбор livecraft.json
    SAVE = "save_failed"             # значения, настройки или файлы токена не записались


@dataclass(frozen=True)
class TokenVerdict:
    """Итог создания или загрузки токена: удалось ли и строки для окна."""

    is_ok: bool
    text: str

    @classmethod
    def problem(cls, text: str) -> TokenVerdict:
        """Не удалось: причина словами — строкой со знаком «✗»."""
        return cls(is_ok=False, text=msg.CHECK_PROBLEM_LINE.format(line=text))

    @classmethod
    def failed(cls, problem: str, reason: NotDoneReason | TokenProblem) -> TokenVerdict:
        """Не удалось: причина словами — окну, её идентификатор — в лог."""
        LogEvent.of(TokenPanelEvent.NOT_DONE, reason=reason).emit(LOGGER)
        return cls.problem(problem)

    @classmethod
    def refused(cls, error: TokenError) -> TokenVerdict:
        """Токен не прочитан: причина словами — окну, подробность — в лог."""
        error.event.emit(LOGGER)
        return cls.failed(error.human, error.reason)


@dataclass(frozen=True)
class TokenSettings:
    """Открытые настройки токена: ключ настройки (значение `SettingKey`) → значение. Ключи, которых программа не знает
    (токен другой версии), не применяются."""

    values: dict[str, str]

    @classmethod
    def of(cls, settings: LivecraftSettings) -> TokenSettings:
        """Заданные ссылка на форму, чаты Telegram и контакты документа объявлений; куда слать объявления — когда чат
        этого назначения задан."""
        data: dict[str, dict[str, object]] = settings.to_data()
        values: dict[str, str] = {key.value: str(data[key.section][key.leaf]) for key in OPEN_KEYS}
        if not settings.telegram.chat_id:
            del values[SettingKey.TELEGRAM_TARGET.value]
        return cls(values={name: value for name, value in values.items() if value})

    def only(self, scope: TokenScope) -> TokenSettings:
        """Только выбранные в `scope` настройки; куда слать объявления — когда едет чат, на который оно указывает."""
        chosen: dict[str, str] = {name: value for name, value in self.values.items() if scope.carries(SettingKey(name))}
        return self._with_target(chosen)

    def own(self, received: ReceivedFiles) -> TokenSettings:
        """Только свои настройки: полученная с токеном и не изменённая в окне (`received`) уходит; куда слать
        объявления — когда остался чат, на который оно указывает."""
        target: str = SettingKey.TELEGRAM_TARGET.value
        return self._with_target({
            name: value for name, value in self.values.items()
            if name != target and not received.is_received_setting(name, value)
        })

    def arrived(self, applied: LivecraftSettings) -> TokenSettings:
        """Настройки токена так, как их прочтёт livecraft.json после загрузки (`applied`): их отпечатки — в учёт
        полученного."""
        shown: dict[str, str] = TokenSettings.of(applied).values
        return TokenSettings(values={key.value: shown[key.value] for key in self.keys if key.value in shown})

    def _with_target(self, kept: dict[str, str]) -> TokenSettings:
        """Настройки `kept` и куда слать объявления — когда среди них чат, на который оно указывает."""
        target: str | None = self.values.get(SettingKey.TELEGRAM_TARGET.value)
        if target is not None and ChatTarget(target).chat_key.value in kept:
            kept[SettingKey.TELEGRAM_TARGET.value] = target
        return TokenSettings(values=kept)

    @property
    def keys(self) -> tuple[SettingKey, ...]:
        """Известные ключи токена — в порядке `OPEN_KEYS`."""
        return tuple(key for key in OPEN_KEYS if key.value in self.values)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(msg.TOKEN_SETTING_LABELS[key.value] for key in self.keys)

    def applied(self, file: SettingsFile) -> LivecraftSettings:
        """Настройки файла, как они сейчас на диске, и настройки токена поверх — через разбор файла; негодны —
        ConfigError."""
        settings: LivecraftSettings = file.latest
        data: dict[str, object] = settings.to_data()
        for section in dict.fromkeys(key.section for key in self.keys):
            leaves: dict[str, str] = {key.leaf: self.values[key.value] for key in self.keys if key.section == section}
            data[section] = {**settings.to_data()[section], **leaves}
        return file.parse(data)


@dataclass(frozen=True)
class TokenDraft:
    """Что набрано в окне для нового токена: срок в сутках, как его набрали, и что включили ползунки значений
    (`scope`)."""

    days_text: str
    scope: TokenScope = TokenScope()

    @property
    def order(self) -> TokenOrder | None:
        """Срок; не целое число суток от 1 до MAX_TOKEN_DAYS — None."""
        text: str = self.days_text.strip()
        if not text.isdecimal() or not 1 <= int(text) <= MAX_TOKEN_DAYS:
            return None
        return TokenOrder(days=int(text))

    @property
    def problem(self) -> str:
        return msg.SETUP_TOKENS_DAYS_PROBLEM.format(maximum=MAX_TOKEN_DAYS)


@dataclass(frozen=True)
class TokenPanel:
    """Вкладка «Токены» без окна: пути установки и время сети (`network`; в тестах — подделка)."""

    paths: LivecraftPaths
    network: NetworkTime

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> TokenPanel:
        return cls(paths=paths, network=NetworkTime())

    def contents(self, own: Vault, scope: TokenScope) -> TokenContent:
        """Что сейчас войдёт в токен: из своих значений сейфа `own` (значения из чужого токена — никогда), открытых
        настроек и своих файлов (полученное с токеном — никогда) — только выбранное ползунками `scope`."""
        settings: TokenSettings = self._own_settings(ReceivedFiles.load(self.paths)).only(scope)
        return TokenContent(vault=scope.vault(own), settings=settings.values, files=scope.collect(self.paths).mapping)

    def available(self, own: Vault) -> frozenset[TokenItem]:
        """Свои значения, которые есть на этой установке: токен из одного этого ползунка что-то нёс бы."""
        received: ReceivedFiles = ReceivedFiles.load(self.paths)
        settings: TokenSettings = self._own_settings(received)
        return frozenset(item for item in TokenItem if self._carries(TokenScope.of(item), own, settings, received))

    def contents_line(self, own: Vault, scope: TokenScope) -> str:
        """Строка вкладки: что войдёт в токен — названиями; передавать нечего — так и сказать."""
        items: tuple[str, ...] = self._labels(self.contents(own, scope))
        if not items:
            return msg.SETUP_TOKENS_NOTHING
        return msg.SETUP_TOKENS_CONTENTS.format(items=msg.LIST_JOINER.join(items))

    def create(self, draft: TokenDraft, own: Vault) -> TokenVerdict:
        """Токен в tokens\\ из своих значений `own`: срок годен, передавать есть что, время сети получено — файл и строки
        итога."""
        order: TokenOrder | None = draft.order
        if order is None:
            return TokenVerdict.failed(draft.problem, NotDoneReason.DAYS)
        content: TokenContent = self.contents(own, draft.scope)
        if not self._labels(content):
            return TokenVerdict.failed(msg.SETUP_TOKENS_NOTHING, NotDoneReason.NOTHING)
        created: datetime | None = self.network.now()
        if created is None:
            return TokenVerdict.failed(TokenProblem.NO_NETWORK.human, NotDoneReason.NO_NETWORK)
        issued: IssuedToken = IssuedToken.of(content, order, created)
        name: TokenName = TokenName.of(content, self._shown_moment(created))
        stem: Path = self.paths.dir(DataDir.TOKENS) / name.stem
        try:
            stem.parent.mkdir(parents=True, exist_ok=True)
            written: Path = issued.write(stem)
        except OSError as error:
            problem: str = msg.SETUP_TOKENS_WRITE_FAILED.format(reason=os_error_reason(error))
            return TokenVerdict.failed(problem, NotDoneReason.WRITE)
        return self._created(issued, written, content, name)

    def load(self, path: Path) -> TokenVerdict:
        """Файл токена → время сети → содержимое; отказ — причина словами, иначе значения и настройки — на место."""
        try:
            token: AccessToken = AccessToken.read(path)
        except TokenError as error:
            return TokenVerdict.refused(error)
        now: datetime | None = self.network.now()
        if now is None:
            return TokenVerdict.failed(TokenProblem.NO_NETWORK.human, NotDoneReason.NO_NETWORK)
        try:
            content: TokenContent = token.open(now)
        except TokenError as error:
            return TokenVerdict.refused(error)
        return self._applied(content, token.header.valid_until)

    @property
    def _file(self) -> SettingsFile:
        return SettingsFile.of(self.paths)

    @property
    def _zone(self) -> ZoneInfo:
        """Пояс программы: в нём — имя файла токена и сроки для людей (§6, инвариант 4)."""
        return self._file.latest.zone

    def _own_settings(self, received: ReceivedFiles) -> TokenSettings:
        """Свои открытые настройки livecraft.json, как он сейчас на диске."""
        return TokenSettings.of(self._file.latest).own(received)

    def _shown_moment(self, moment: datetime) -> str:
        return moment.astimezone(self._zone).strftime(FILE_STAMP_FORMAT)

    def _carries(self, scope: TokenScope, own: Vault, settings: TokenSettings, received: ReceivedFiles) -> bool:
        """Выбор `scope` несёт хоть что-то: поле сейфа, настройку или файл."""
        return bool(scope.vault(own).entries or settings.only(scope).values or scope.files(self.paths, received))

    def _labels(self, content: TokenContent) -> tuple[str, ...]:
        """Названия того, что несёт токен: поля сейфа, открытые настройки, затем файлы."""
        fields: tuple[str, ...] = tuple(entry.secret.field.human_label for entry in content.vault.entries.values())
        return (*fields, *TokenSettings(dict(content.settings)).labels, *TokenFiles.of(content.files).labels)

    def _created(self, issued: IssuedToken, written: Path, content: TokenContent, name: TokenName) -> TokenVerdict:
        """Строки итога создания: файл, срок и что внутри."""
        until: datetime = issued.token.header.valid_until
        LogEvent.of(TokenPanelEvent.CREATED, until=until.isoformat(), project=name.project).extended(
            vault=content.vault.log_line, settings=tuple(content.settings), files=tuple(content.files)
        ).emit(LOGGER)
        lines: tuple[str, ...] = (
            msg.SETUP_TOKENS_CREATED.format(token=self.paths.shown(written)),
            msg.SETUP_TOKENS_VALID_UNTIL.format(until=format_human_datetime(until.astimezone(self._zone))),
            msg.SETUP_TOKENS_INSIDE.format(items=msg.LIST_JOINER.join(self._labels(content))),
        )
        return TokenVerdict(is_ok=True, text=NEWLINE.join(lines))

    def _applied(self, content: TokenContent, until: datetime) -> TokenVerdict:
        """Значения — слоем «из токена», открытые настройки — в livecraft.json (есть они — только тогда), файлы — на
        место (`TokenFiles.apply`, его строки — в итог); сначала разбор настроек, затем запись: негодные настройки
        ничего не меняют."""
        settings: TokenSettings = TokenSettings(dict(content.settings))
        try:
            applied: LivecraftSettings = settings.applied(self._file)
        except ConfigError as error:
            unfit: str = msg.SETUP_TOKENS_SETTINGS_FAILED.format(problem=error.problem)
            return TokenVerdict.failed(unfit, NotDoneReason.SETTINGS)
        try:
            VaultStore.open(self.paths).save_token(content.vault)
            if settings.keys:
                self._file.save(applied)
                ReceivedFiles.load(self.paths).with_settings(settings.arrived(applied).values).save()
            notes: tuple[str, ...] = TokenFiles.of(content.files).apply(self.paths)
        except DpapiUnavailable as error:
            return TokenVerdict.failed(error.human, NotDoneReason.SAVE)
        except OSError as error:
            unsaved: str = msg.SETUP_TOKENS_SAVE_FAILED.format(reason=os_error_reason(error))
            return TokenVerdict.failed(unsaved, NotDoneReason.SAVE)
        loaded: LogEvent = LogEvent.of(TokenPanelEvent.LOADED, vault=content.vault.log_line, settings=settings.keys)
        loaded.extended(files=tuple(content.files)).emit(LOGGER)
        lines: tuple[str, ...] = (
            msg.SETUP_TOKENS_LOADED.format(items=msg.LIST_JOINER.join(self._labels(content))),
            msg.SETUP_TOKENS_LOADED_UNTIL.format(until=format_human_datetime(until.astimezone(self._zone))),
            *notes,
        )
        return TokenVerdict(is_ok=True, text=NEWLINE.join(lines))
