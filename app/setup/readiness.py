"""Готовность программы к запуску — целиком и по частям выбранного режима (CLAUDE.md §8.2, §10).

Сейф, livecraft.json и channels.json читаются независимо: нет каналов — настройки всё равно прочитаны, и
части режима, которым каналы не нужны, готовы. Этот объект держит результаты чтения и сам отвечает на
вопросы о себе: готово ли всё (окно настройщика), готова ли каждая часть режима и что сделать, если нет,
что сказать громко и что писать в лог (`Readiness.log`). Готовность режима по частям — объекты `PartReadiness`
и `ModeReadiness` (app\\run\\mode.py): что делает запуск режима, решает `ModeReadiness.step`. Печатает запуск
(app\\main.py::Launch).

Правило готовности каждой части — в одном месте, `Readiness.part`. Не готовая часть называется одной
строкой с точным действием: что задать и где. Шаблоны файлов в консоль не идут — только в лог при
сломанном файле; файлы правит настройщик.

Сводка, строки частей и строка лога не содержат ни значений, ни масок (§7.4): оператору нужно знать,
откуда значение — пришло с программой или вписано им самим, — а не само значение.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.loader import (
    ChannelConfig,
    ConfigError,
    ConfigProblem,
    LivecraftConfig,
    LivecraftSettings,
    Platform,
    Privacy,
    allowed_values,
    load_channels,
    load_settings,
)
from app.observability.log_event import LogEvent, LogValue
from app.paths import LivecraftPaths
from app.run.mode import ModeReadiness, PartReadiness, RunMode, RunPart
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.value import SecretField
from app.secretsafe.vault import Vault, VaultOrigin
from app.ui import messages_ru as msg

LOG_VAULT_BROKEN: Final[str] = "broken"
LOG_CONFIG_ERROR: Final[str] = "error"
# Что нужно каждой реализованной части из сейфа (§7.5): таблица — id и диапазон, merge — ключ OpenAI.
PLAN_VAULT_FIELDS: Final[tuple[SecretField, ...]] = (SecretField.SHEETS_ID, SecretField.SHEETS_RANGE)
MERGE_VAULT_FIELDS: Final[tuple[SecretField, ...]] = (SecretField.OPENAI_API_KEY,)


class ReadinessEvent(str, Enum):
    """События готовности в логе."""

    READINESS = "readiness"
    CONFIG_MISSING = "config_missing"
    CONFIG_ERROR = "config_error"
    CONFIG_TEMPLATE = "config_template"
    VAULT_ERROR = "vault_error"
    VAULT_LOCAL_UNREADABLE = "vault_local_unreadable"


@dataclass(frozen=True)
class Readiness:
    """Результат чтения сейфа и конфигов одного запуска и правила «готово ли, и что сказать».

    Перехватываются только ConfigError и VaultFormatError: всё остальное — ошибка программы, и её ловит
    запуск (app\\main.py::Launch.run). `has_client_secret` — снимок на момент проверки: без client_secret.json
    к Google не ходим (§9).
    """

    paths: LivecraftPaths
    settings: LivecraftSettings | None
    settings_error: ConfigError | None
    channels: tuple[ChannelConfig, ...] | None
    channels_error: ConfigError | None
    vault_load: VaultLoad | None
    vault_error: VaultFormatError | None
    has_client_secret: bool

    @classmethod
    def check(cls, paths: LivecraftPaths) -> Readiness:
        """Прочитать сейф, livecraft.json и channels.json — независимо друг от друга. Ничего не печатает."""
        vault_load: VaultLoad | None = None
        vault_error: VaultFormatError | None = None
        try:
            vault_load = VaultStore.open(paths).load()
        except VaultFormatError as error:
            vault_error = error
        settings: LivecraftSettings | None = None
        settings_error: ConfigError | None = None
        try:
            settings = load_settings(paths.config_file)
        except ConfigError as error:
            settings_error = error
        channels: tuple[ChannelConfig, ...] | None = None
        channels_error: ConfigError | None = None
        try:
            channels = load_channels(paths.channels_file)
        except ConfigError as error:
            channels_error = error
        return cls(
            paths=paths,
            settings=settings,
            settings_error=settings_error,
            channels=channels,
            channels_error=channels_error,
            vault_load=vault_load,
            vault_error=vault_error,
            has_client_secret=paths.client_secret_file.is_file(),
        )

    @property
    def config(self) -> LivecraftConfig | None:
        """Настройки и каналы одним объектом — когда прочитаны оба файла."""
        if self.settings is None or self.channels is None:
            return None
        return LivecraftConfig(settings=self.settings, channels=self.channels)

    @property
    def vault(self) -> Vault | None:
        """Сейф, если он прочитан; при файле чужого формата сейфа нет."""
        return None if self.vault_load is None else self.vault_load.vault

    @property
    def is_ready(self) -> bool:
        """Всё настроено: оба конфига прочитаны, сейф прочитан и в нём все поля. Так судит окно настройщика."""
        return self.config is not None and self.vault is not None and self.vault.is_ready

    @property
    def config_errors(self) -> tuple[ConfigError, ...]:
        """Ошибки конфигов: сначала настройки, потом каналы."""
        return tuple(error for error in (self.settings_error, self.channels_error) if error is not None)

    def part(self, part: RunPart) -> PartReadiness:
        """Готова ли часть работы. Единственное место правил готовности частей."""
        if not part.is_built:
            return PartReadiness(part=part, is_ready=False, is_built=False, action=part.not_built_line)
        gaps: tuple[str, ...] = self._gaps(part)
        if not gaps:
            return PartReadiness(part=part, is_ready=True, is_built=True, action=None)
        action: str = msg.RUN_PART_BLOCKED.format(part=part.human_label, gaps=msg.ITEM_JOINER.join(gaps))
        return PartReadiness(part=part, is_ready=False, is_built=True, action=action)

    def for_mode(self, mode: RunMode, no_llm: bool) -> ModeReadiness:
        """Готовность режима по частям в порядке его работы."""
        return ModeReadiness(
            mode=mode,
            parts=tuple(self.part(part) for part in mode.parts(no_llm)),
            is_fixable_in_setup=self.vault_error is None or self.vault_error.is_replaceable,
        )

    @property
    def problems(self) -> tuple[str, ...]:
        """Что мешает полной настройке — строками для оператора (окно, --check, --status): конфиги, потом сейф."""
        lines: list[str] = [self._config_problem(error) for error in self.config_errors]
        if self.vault_error is not None:
            lines.append(self.vault_error.human)
        elif self.vault is not None and self.vault.admission_reason is not None:
            lines.append(self.vault.admission_reason)
        return tuple(lines)

    @property
    def template_lines(self) -> tuple[str, ...]:
        """Точный шаблон сломанного конфига — для лога (DEBUG), не для консоли. Файла нет — не сломан: пусто."""
        lines: list[str] = []
        for error in self.config_errors:
            if error.kind is ConfigProblem.FILE_MISSING:
                continue
            if error.config_path == self.paths.channels_file:
                lines.extend((*self._channel_field_lines, msg.CONFIG_CHANNELS_TEMPLATE))
            else:
                lines.append(msg.CONFIG_SETTINGS_TEMPLATE)
        return tuple(lines)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Что сказать громко при любом исходе: личный сейф есть, но не прочитан (§16)."""
        if self.vault_load is not None and self.vault_load.is_local_unreadable:
            return (msg.VAULT_LOCAL_UNREADABLE,)
        return ()

    @property
    def summary_lines(self) -> tuple[str, ...]:
        """Сводка для оператора: по каждому нужному полю сейфа — откуда оно (или «нет»), настроена ли форма
        ключей, каналы и языки. Без значений; устаревшее поле сейфа (ссылка на форму) не показывается."""
        return (msg.READINESS_SUMMARY_TITLE, *self._field_lines, *self._form_lines, self._channels_line)

    @property
    def event(self) -> LogEvent:
        """То же для лога: состояние файлов, ярлыки с отпечатками, число каналов; ни одного значения."""
        return LogEvent.of(
            ReadinessEvent.READINESS,
            settings=LogValue.OK if self.settings is not None else LOG_CONFIG_ERROR,
            channels=len(self.channels) if self.channels is not None else None,
            local=self.vault_load.local_state if self.vault_load is not None else None,
            vault=self.vault.log_line if self.vault is not None else LOG_VAULT_BROKEN,
            ready=self.is_ready,
        )

    def log(self, logger: logging.Logger) -> None:
        """Готовность, ошибки конфигов, шаблоны сломанных файлов (DEBUG) и сейф — в лог; значений сейфа нет нигде."""
        self.event.emit(logger)
        for error in self.config_errors:
            if error.kind is ConfigProblem.FILE_MISSING:        # нет файла — ещё не настроено, а не сломано
                LogEvent.of(ReadinessEvent.CONFIG_MISSING, path=error.config_path).emit(logger)
                continue
            failed: LogEvent = LogEvent.of(ReadinessEvent.CONFIG_ERROR, path=error.config_path, key=error.key_path)
            failed.extended(kind=error.kind, problem=error.problem).emit(logger, logging.ERROR)
        for line in self.template_lines:          # шаблон сломанного файла — только в лог, в консоль не идёт
            LogEvent.of(ReadinessEvent.CONFIG_TEMPLATE, template=line).emit(logger, logging.DEBUG)
        vault: VaultFormatError | None = self.vault_error
        if vault is not None:
            broken: LogEvent = LogEvent.of(ReadinessEvent.VAULT_ERROR, file=vault.file_name, source=vault.source)
            broken.extended(reason=vault.reason, detail=vault.detail).emit(logger, logging.ERROR)
        if self.vault_load is not None and self.vault_load.is_local_unreadable:
            unreadable: LogEvent = LogEvent.of(ReadinessEvent.VAULT_LOCAL_UNREADABLE, working_on=VaultOrigin.SUPPLIED)
            unreadable.emit(logger, logging.WARNING)

    # --- что не хватает части: по строке «что задать — где»

    def _gaps(self, part: RunPart) -> tuple[str, ...]:
        if part is RunPart.PLAN:
            # client_secret.json в настройщике не задаётся: действие — положить файл (§9).
            client_secret: tuple[str, ...] = () if self.has_client_secret else (
                msg.READINESS_GAP_CLIENT_SECRET.format(path=self.paths.client_secret_file),
            )
            return (*self._vault_gaps(PLAN_VAULT_FIELDS), *self._settings_gaps, *client_secret)
        if part is RunPart.MERGE:
            return self._vault_gaps(MERGE_VAULT_FIELDS)
        if part is RunPart.PACKAGE:
            return (*self._settings_gaps, *self._form_gaps)
        if part is RunPart.BROADCAST:
            return (*self._channels_gaps, *self._settings_gaps, *self._form_gaps)
        return ()

    def _vault_gaps(self, fields: tuple[SecretField, ...]) -> tuple[str, ...]:
        if self.vault_error is not None:
            return (msg.READINESS_GAP_VAULT_BROKEN.format(problem=self.vault_error.problem),)
        vault: Vault = Vault.empty() if self.vault is None else self.vault
        return tuple(
            msg.READINESS_GAP_IN_SETUP.format(what=field.human_label, tab=msg.SETUP_TAB_KEYS)
            for field in fields
            if vault.get(field) is None
        )

    @property
    def _settings_gaps(self) -> tuple[str, ...]:
        if self.settings_error is None:
            return ()
        what: str = msg.READINESS_GAP_SETTINGS.format(
            key=self.settings_error.key_path, problem=self.settings_error.problem
        )
        return (msg.READINESS_GAP_IN_SETUP.format(what=what, tab=msg.SETUP_TAB_SETTINGS),)

    @property
    def _form_gaps(self) -> tuple[str, ...]:
        """Ссылка на форму — только когда настройки прочитаны: иначе о них уже сказала своя строка."""
        if self.settings is None or self.settings.form.is_configured:
            return ()
        return (msg.READINESS_GAP_IN_SETUP.format(what=msg.READINESS_GAP_FORM, tab=msg.SETUP_TAB_SETTINGS),)

    @property
    def _channels_gaps(self) -> tuple[str, ...]:
        error: ConfigError | None = self.channels_error
        if error is None:
            return ()
        what: str = (
            msg.READINESS_GAP_CHANNELS_MISSING
            if error.kind is ConfigProblem.FILE_MISSING
            else msg.READINESS_GAP_CHANNELS.format(key=error.key_path, problem=error.problem)
        )
        return (msg.READINESS_GAP_IN_SETUP.format(what=what, tab=msg.SETUP_TAB_CHANNELS),)

    # --- строки полной проверки и сводки

    def _config_problem(self, error: ConfigError) -> str:
        """Нет файла каналов — «добавьте каналы»; сломанный файл — путь, ключ, причина и где исправить."""
        is_channels: bool = error.config_path == self.paths.channels_file
        if is_channels and error.kind is ConfigProblem.FILE_MISSING:
            return msg.READINESS_CHANNELS_MISSING
        tab: str = msg.SETUP_TAB_CHANNELS if is_channels else msg.SETUP_TAB_SETTINGS
        return msg.CONFIG_FIX_IN_SETUP.format(error=error, tab=tab)

    @property
    def _field_lines(self) -> tuple[str, ...]:
        return tuple(
            msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=self._origin_label(field))
            for field in SecretField.current()
        )

    @property
    def _form_lines(self) -> tuple[str, ...]:
        """Настроена ли форма ключей — по livecraft.json (§14 решение 15); настройки не прочитаны — строки нет.

        Ссылку не печатаем: сводке достаточно «настроена / не настроена».
        """
        if self.settings is None:
            return ()
        state: str = (
            msg.READINESS_FORM_CONFIGURED if self.settings.form.is_configured else msg.READINESS_FORM_NOT_CONFIGURED
        )
        return (msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=state),)

    def _origin_label(self, field: SecretField) -> str:
        origin: VaultOrigin | None = None if self.vault is None else self.vault.origin_of(field)
        return msg.NONE_TEXT if origin is None else origin.human_label

    @property
    def _channels_line(self) -> str:
        if self.channels is None:
            return msg.READINESS_CHANNELS_ABSENT
        languages: frozenset[str] = frozenset(
            language for channel in self.channels for language in channel.languages
        )
        return msg.READINESS_CHANNELS_LINE.format(
            count=len(self.channels), languages=msg.LIST_JOINER.join(sorted(languages))
        )

    @property
    def _channel_field_lines(self) -> tuple[str, ...]:
        """Что вписать в поля channels.json; допустимые значения — те же, что проверяет загрузчик."""
        return tuple(
            line.format(
                languages=msg.CONFIG_LANGUAGES_RULE,
                privacy=allowed_values(Privacy),
                platform=allowed_values(Platform),
            )
            for line in msg.CONFIG_CHANNELS_FIELDS
        )

