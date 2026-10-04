"""Готовность программы к запуску — целиком и по нуждам работающих линий (CLAUDE.md §8.2, §10, §14 решение 37).

Сейф, livecraft.json и channels.json читаются независимо; итог каждого чтения — объект или ошибка (`ConfigRead`,
`VaultRead`). `Readiness` сам отвечает: удовлетворена ли каждая нужда работающей линии и служебного запуска по каналам
и что сделать, если нет (`gap` — единственное место текста нужды). Линии — из прочитанных настроек (не прочитаны —
поставочные), папки ролей из настроек — сразу в путях запуска (`paths`). Что делает запуск, решает `ModeReadiness.step`
(app\\run\\line_plan.py); тем же правилом судит строка готовности окна настройщика (`is_ready`, `window_line`): всё,
что работает, готово. Шаблоны сломанных файлов — только в лог. Снимок запуска для лога (§14 решение 38) — `RunSnapshot`.
Сводка, строки нужд и лог не содержат ни значений, ни масок (§7.4).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.broadcasts import BroadcastSettings
from app.config.channel import ChannelHandle, ConfiguredChannels
from app.config.files import ChannelsFile, ConfigRead, SettingsFile, ShippedSettings
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings
from app.core.text_format import NEWLINE
from app.observability.log_event import LogEvent, LogValue, Quoted
from app.paths import DataDir, FileName, LivecraftPaths
from app.run.line_plan import LinePlan, ModeReadiness, RunScope, RunTexts
from app.run.mode import ModeStep, Need, NeedGap, PartReadiness, RunMode, RunPart
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultRead, VaultStore
from app.secretsafe.vault import Vault
from app.setup.page import NEED_PAGES
from app.ui.messages import msg

LOG_VAULT_BROKEN: Final[str] = "broken"
LOG_CONFIG_ERROR: Final[str] = "error"
# Какие поля сейфа нужны нуждам сейфа (§7.5): таблице плана — её id (лист и колонки программа находит сама,
# §14 решение 26), нейросети — ключ OpenAI, объявлениям — токен бота (им нужен ещё и чат в livecraft.json), превью на
# Диске и документу — папка материалов (§14 решение 39).
VAULT_NEEDS: Final[dict[Need, tuple[SecretField, ...]]] = {
    Need.SHEETS_VAULT: (SecretField.SHEETS_ID,),
    Need.OPENAI_VAULT: (SecretField.OPENAI_API_KEY,),
    Need.TELEGRAM: (SecretField.TELEGRAM_BOT_TOKEN,),
    Need.DRIVE_FOLDER: (SecretField.DRIVE_FOLDER,),
}


class ReadinessEvent(str, Enum):
    """События готовности и снимка запуска в логе."""

    READINESS = "readiness"
    CONFIG_TEMPLATE = "config_template"
    SNAPSHOT_SETTINGS = "run_snapshot_settings"
    SNAPSHOT_FOLDERS = "run_snapshot_folders"
    SNAPSHOT_CHANNELS = "run_snapshot_channels"
    SNAPSHOT_VAULT = "run_snapshot_vault"


@dataclass(frozen=True)
class RunBasis:
    """С чем идёт работа по линиям от любого входа: прочитанные настройки и сейф — одним значением (сейф не прочитан —
    пустой: частям, которым он нужен, тогда не хватает нужд, и они не идут); `scope` — какие части идут в запуске
    (работают и готовы) и пробный ли он; `channels` — прочитанные каналы, когда идут эфиры; иначе None."""

    settings: LivecraftSettings
    vault: Vault
    scope: RunScope
    channels: ConfiguredChannels | None = None

    def runs(self, part: RunPart) -> bool:
        """Часть работает и готова."""
        return self.scope.runs(part)


@dataclass(frozen=True)
class ChannelBasis:
    """С чем работают каналы без таблицы — режим Б и служебные запуски: прочитанные настройки и каналы."""

    settings: LivecraftSettings
    channels: ConfiguredChannels

    @classmethod
    def of(cls, readiness: Readiness) -> ChannelBasis | None:
        """Настройки и каналы, когда оба файла прочитаны; иначе None."""
        settings: LivecraftSettings | None = readiness.settings.value
        channels: ConfiguredChannels | None = readiness.channels.value
        if settings is None or channels is None:
            return None
        return cls(settings=settings, channels=channels)


@dataclass(frozen=True)
class ServiceReadiness:
    """Готовность служебного запуска по каналам (--check, --auth, --status): его нужды — `RunMode.service_needs`."""

    readiness: Readiness
    mode: RunMode

    @property
    def lines(self) -> tuple[str, ...]:
        """Строка на каждую нужду, которой не хватает; всё есть — пусто."""
        needs: tuple[Need, ...] = self.mode.service_needs
        return tuple(msg.SERVICE_NEED_BLOCKED.format(gap=gap.text) for need in needs if (gap := self.readiness.gap(need)))

    @property
    def basis(self) -> ChannelBasis | None:
        """Настройки и каналы, когда всех нужд хватает; иначе None."""
        return None if self.lines else ChannelBasis.of(self.readiness)


@dataclass(frozen=True)
class ReadinessSummary:
    """Сводка для оператора: линии работы, по каждому полю сейфа — откуда оно (или «нет»), настроена ли форма ключей,
    откуда тексты эфиров и что с повторной передачей ключей в этом запуске (`scope`), каналы и языки. Без значений."""

    vault: Vault | None
    settings: LivecraftSettings | None
    channels: ConfiguredChannels | None
    scope: RunScope

    @property
    def lines(self) -> tuple[str, ...]:
        return (
            msg.READINESS_SUMMARY_TITLE,
            *self._work_lines,
            *self._field_lines,
            *self._form_lines,
            *self._broadcast_lines,
            self._channels_line,
        )

    @property
    def _work_lines(self) -> tuple[str, ...]:
        """Работающие линии и выключенные (§14 решение 37); настройки не прочитаны — строк нет."""
        return () if self.settings is None else self.settings.lines.line_plan.summary_lines

    @property
    def _field_lines(self) -> tuple[str, ...]:
        return tuple(
            msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=self._origin_label(field))
            for field in SecretField
        )

    @property
    def _form_lines(self) -> tuple[str, ...]:
        """Настроена ли форма ключей — по livecraft.json (§14 решение 15); настройки не прочитаны — строки нет."""
        if self.settings is None:
            return ()
        configured: bool = self.settings.form.is_configured
        state: str = msg.READINESS_FORM_CONFIGURED if configured else msg.READINESS_FORM_NOT_CONFIGURED
        return (msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=state),)

    @property
    def _broadcast_lines(self) -> tuple[str, ...]:
        """Откуда тексты эфиров — по линиям запуска (`RunTexts`, §14 решение 50) и повторная передача ключей: в пробном
        запуске ключи не уходят (§14 решение 36); настройки не прочитаны — строк нет."""
        if self.settings is None:
            return ()
        broadcasts: BroadcastSettings = self.settings.broadcasts
        resend: str = msg.READINESS_RESEND_KEYS_OFF
        if broadcasts.resend_keys:
            resend = msg.READINESS_RESEND_KEYS_DRY_RUN if self.scope.dry_run else msg.READINESS_RESEND_KEYS_ON
        source: str = RunTexts(self.scope).source.human
        return (
            msg.READINESS_FIELD_LINE.format(label=msg.READINESS_TEXTS_LABEL, origin=source),
            msg.READINESS_FIELD_LINE.format(label=msg.READINESS_RESEND_KEYS_LABEL, origin=resend),
        )

    @property
    def _channels_line(self) -> str:
        if self.channels is None:
            return msg.READINESS_CHANNELS_ABSENT
        languages: str = msg.LIST_JOINER.join(self.channels.served_languages)
        return msg.READINESS_CHANNELS_LINE.format(count=len(self.channels.channels), languages=languages)

    def _origin_label(self, field: SecretField) -> str:
        origin: VaultOrigin | None = None if self.vault is None else self.vault.origin_of(field)
        return msg.NONE_TEXT if origin is None else origin.human_label


@dataclass(frozen=True)
class Readiness:
    """Итоги чтения сейфа и конфигов одного запуска и правила «готово ли, и что сказать»; `has_client_secret` —
    снимок на момент проверки: без client_secret.json к Google не ходим (§9)."""

    paths: LivecraftPaths
    vault: VaultRead
    settings: ConfigRead[LivecraftSettings]
    channels: ConfigRead[ConfiguredChannels]
    has_client_secret: bool

    @classmethod
    def check(cls, paths: LivecraftPaths) -> Readiness:
        """Прочитать сейф, livecraft.json и channels.json — независимо друг от друга. Ничего не печатает."""
        return cls.of(paths, VaultRead.of(VaultStore.open(paths)))

    @classmethod
    def of(cls, paths: LivecraftPaths, vault: VaultRead) -> Readiness:
        """Готовность на уже прочитанном сейфе (окно читает его один раз — `SetupVault`) и свежих livecraft.json и
        channels.json; прочитаны настройки — папки ролей из них в путях."""
        settings: ConfigRead[LivecraftSettings] = SettingsFile.of(paths).read()
        return cls(
            paths=paths if settings.value is None else paths.with_folders(settings.value.folders.data_folders),
            vault=vault,
            settings=settings,
            channels=ChannelsFile.of(paths).read(),
            has_client_secret=paths.file(FileName.CLIENT_SECRET).is_file(),
        )

    @property
    def is_ready(self) -> bool:
        """Всё, что работает, готово — тем же правилом, что у запуска (`ModeReadiness.is_ready`): владелец канала без
        таблицы и ключа OpenAI, у которого работают только эфиры, — «готово». Так судит окно настройщика."""
        return self.for_run().is_ready

    def part(self, part: RunPart, plan: LinePlan) -> PartReadiness:
        """Готовность части: каких её нужд в этом запуске (`LinePlan.needs_of`) не хватает."""
        needs: tuple[Need, ...] = plan.needs_of(part)
        return PartReadiness(part, tuple(gap for need in needs if (gap := self.gap(need)) is not None))

    def for_run(self) -> ModeReadiness:
        """Готовность работающих линий в порядке работы; линии — из прочитанных настроек, не прочитаны — поставочные
        (все включены)."""
        plan: LinePlan = (self.settings.value or ShippedSettings().settings).lines.line_plan
        parts: tuple[PartReadiness, ...] = tuple(self.part(part, plan) for part in plan.working)
        return ModeReadiness(plan=plan, parts=parts)

    def run_basis(self, mode: ModeReadiness, dry_run: bool) -> RunBasis | None:
        """Настройки, сейф и части, которые идут, — для работы по линиям от любого входа, когда основа готова (её
        нужда — настройки: они прочитаны); иначе None."""
        settings: LivecraftSettings | None = self.settings.value
        if mode.step is ModeStep.OPEN_SETUP or settings is None:
            return None
        vault: Vault = self.vault.vault or Vault.empty()
        channels: ConfiguredChannels | None = self.channels.value if mode.runs(RunPart.BROADCAST) else None
        return RunBasis(settings=settings, vault=vault, scope=mode.scope(dry_run), channels=channels)

    def gap(self, need: Need) -> NeedGap | None:
        """Чего не хватает нужде: что задать и где (`NeedGap`); нужда удовлетворена — None. Сейф не читается — причина и
        одно действие; нет client_secret.json — строка без вкладки: это не задаётся в окне."""
        broken: VaultFormatError | None = self.vault.error
        if need in VAULT_NEEDS and broken is not None:
            return NeedGap(need, msg.READINESS_GAP_VAULT_BROKEN.format(problem=broken.problem, advice=broken.advice))
        if need is Need.CLIENT_SECRET:
            missing: str = msg.READINESS_GAP_CLIENT_SECRET.format(path=self.paths.file(FileName.CLIENT_SECRET))
            return None if self.has_client_secret else NeedGap(need, missing)
        what: str | None = self._what(need)
        return None if what is None else NeedGap(need, NEED_PAGES[need].gap_line(what), what)

    @property
    def window_line(self) -> str:
        """Строка готовности окна настройщика: «готово» или те же строки нужд работающих линий, что у запуска."""
        mode: ModeReadiness = self.for_run()
        return msg.SETUP_READY if mode.is_ready else NEWLINE.join(mode.lines)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Что сказать громко при любом исходе: личный сейф есть, но не прочитан (§16)."""
        return () if self.vault.load is None else self.vault.load.warnings

    def summary_lines(self, scope: RunScope) -> tuple[str, ...]:
        """Сводка запуска `scope` для оператора без значений: поля сейфа, форма ключей, эфиры, каналы и языки."""
        vault: Vault | None = self.vault.vault
        return ReadinessSummary(vault, self.settings.value, self.channels.value, scope).lines

    @property
    def template_lines(self) -> tuple[str, ...]:
        """Точный шаблон сломанного конфига — для лога (DEBUG), не для консоли. Файла нет — не сломан: пусто."""
        settings: tuple[str, ...] = (ShippedSettings().template.rstrip(NEWLINE),) if self.settings.is_broken else ()
        channels: tuple[str, ...] = ChannelsFile.of(self.paths).template_lines if self.channels.is_broken else ()
        return (*settings, *channels)

    @property
    def event(self) -> LogEvent:
        """Готовность для лога: состояние файлов, ярлыки с отпечатками, число каналов; ни одного значения."""
        vault: Vault | None = self.vault.vault
        channels: ConfiguredChannels | None = self.channels.value
        return LogEvent.of(
            ReadinessEvent.READINESS,
            settings=LogValue.OK if self.settings.value is not None else LOG_CONFIG_ERROR,
            channels=None if channels is None else len(channels.channels),
            local=None if self.vault.load is None else self.vault.load.local_state,
            vault=LOG_VAULT_BROKEN if vault is None else vault.log_line,
            ready=self.is_ready,
        )

    def log(self, logger: logging.Logger) -> None:
        """Готовность, ошибки конфигов, шаблоны сломанных файлов (DEBUG) и сейф — в лог; значений сейфа нет нигде."""
        self.event.emit(logger)
        self.settings.log(logger)
        self.channels.log(logger)
        for line in self.template_lines:          # шаблон сломанного файла — только в лог, в консоль не идёт
            LogEvent.of(ReadinessEvent.CONFIG_TEMPLATE, template=line).emit(logger, logging.DEBUG)
        self.vault.log(logger)

    def _what(self, need: Need) -> str | None:
        """Что задать для нужды, без вкладки; None — нужды хватает. Ссылка на форму проверяется, только когда настройки
        прочитаны. Объявлениям мало токена бота: нужен и чат в livecraft.json — одной строкой."""
        settings: LivecraftSettings | None = self.settings.value
        if need in VAULT_NEEDS:
            vault: Vault | None = self.vault.vault
            absent: tuple[SecretField, ...] = VAULT_NEEDS[need] if vault is None else vault.missing_of(VAULT_NEEDS[need])
            if need is Need.TELEGRAM and (absent or settings is None or not settings.telegram.chat_id):
                return msg.READINESS_GAP_TELEGRAM
            return msg.LIST_JOINER.join(field.human_label for field in absent) if absent else None
        settings_error: ConfigError | None = self.settings.error
        channels_error: ConfigError | None = self.channels.error
        if need is Need.SETTINGS and settings_error is not None:
            return msg.READINESS_GAP_SETTINGS.format(key=settings_error.key_path, problem=settings_error.problem)
        if need is Need.FORM and settings is not None and not settings.form.is_configured:
            return msg.READINESS_GAP_FORM
        if need is Need.CHANNELS and channels_error is not None:
            broken: str = msg.READINESS_GAP_CHANNELS.format(key=channels_error.key_path, problem=channels_error.problem)
            return msg.READINESS_GAP_CHANNELS_MISSING if channels_error.is_file_missing else broken
        return None


@dataclass(frozen=True)
class RunSnapshot:
    """Снимок запуска для лога (§14 решение 38): livecraft.json целиком (значений сейфа в нём нет), линии, папки ролей,
    каналы и сейф — ярлыками с отпечатками (§7.4). Файл, который не прочитался, — словом «error»."""

    readiness: Readiness

    @property
    def events(self) -> tuple[LogEvent, ...]:
        readiness: Readiness = self.readiness
        settings: LivecraftSettings | None = readiness.settings.value
        vault: Vault | None = readiness.vault.vault
        paths: LivecraftPaths = readiness.paths
        return (
            LogEvent.of(ReadinessEvent.SNAPSHOT_SETTINGS, settings=self._quoted(settings and settings.to_data())),
            readiness.for_run().snapshot,
            LogEvent.of(
                ReadinessEvent.SNAPSHOT_FOLDERS,
                packages=paths.dir(DataDir.BCAST), docs=paths.dir(DataDir.DOCS), images=paths.dir(DataDir.IMAGE),
            ),
            LogEvent.of(ReadinessEvent.SNAPSHOT_CHANNELS, channels=self._quoted(self._channels)),
            LogEvent.of(ReadinessEvent.SNAPSHOT_VAULT, vault=Quoted(vault.log_line if vault else LOG_VAULT_BROKEN)),
        )

    @property
    def _channels(self) -> list[dict[str, object]] | None:
        """Каналы: поля channels.json и есть ли файл токена входа; файл не прочитан — None."""
        channels: ConfiguredChannels | None = self.readiness.channels.value
        paths: LivecraftPaths = self.readiness.paths
        return None if channels is None else [
            dict(channel.to_data(), token=paths.token_file(ChannelHandle.of(channel.handle).token_file_stem).is_file())
            for channel in channels.channels
        ]

    def _quoted(self, data: object) -> Quoted | str:
        """Данные JSON в кавычках (кириллица как есть); файл не прочитался — «error»."""
        return LOG_CONFIG_ERROR if data is None else Quoted(json.dumps(data, ensure_ascii=False))
