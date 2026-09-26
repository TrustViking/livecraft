"""Готовность программы к запуску — целиком и по нуждам частей выбранного режима (CLAUDE.md §8.2, §10).

Сейф, livecraft.json и channels.json читаются независимо: нет каналов — настройки всё равно прочитаны, и
части режима, которым каналы не нужны, готовы. Итог каждого чтения — одно значение: объект или ошибка
(`ConfigRead`, `VaultRead`). Этот объект держит итоги чтения и сам отвечает на вопросы о себе: готово ли всё
(окно настройщика), удовлетворена ли каждая нужда части (`Need`) и что сделать, если нет, что сказать громко и
что писать в лог. Что делает запуск режима, решает `ModeReadiness.step` (app\\run\\mode.py); печатает запуск.

Текст нужды — в одном месте, `Readiness.gap`: одна строка «что задать и где», сколько бы частей режима её ни
ждали. Шаблоны файлов в консоль не идут — только в лог при сломанном файле; файлы правит настройщик. Окну
настройщика — свои строки (`window_line`): оно уже открыто, и советовать открыть его незачем.

Сводка, строки нужд и строка лога не содержат ни значений, ни масок (§7.4): оператору нужно знать, откуда
значение — пришло с программой или вписано им самим, — а не само значение.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.channel import ConfiguredChannels
from app.config.files import ChannelsFile, ConfigRead, SettingsFile, ShippedSettings
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings
from app.core.text_format import NEWLINE
from app.observability.log_event import LogEvent, LogValue
from app.paths import LivecraftPaths
from app.run.mode import ModeReadiness, ModeStep, Need, NeedGap, PartReadiness, RunMode, RunPart
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultRead, VaultStore
from app.secretsafe.vault import Vault
from app.ui import messages_ru as msg

LOG_VAULT_BROKEN: Final[str] = "broken"
LOG_CONFIG_ERROR: Final[str] = "error"
# Какие поля сейфа нужны нуждам сейфа (§7.5): таблице плана — id и диапазон, нейросети — ключ OpenAI.
VAULT_NEEDS: Final[dict[Need, tuple[SecretField, ...]]] = {
    Need.SHEETS_VAULT: (SecretField.SHEETS_ID, SecretField.SHEETS_RANGE),
    Need.OPENAI_VAULT: (SecretField.OPENAI_API_KEY,),
}


class ReadinessEvent(str, Enum):
    """События готовности в логе."""

    READINESS = "readiness"
    CONFIG_TEMPLATE = "config_template"


class ReadinessVoice(str, Enum):
    """Кому говорит строка проблемы: консоли запуска или окну настройщика, которое уже открыто."""

    CONSOLE = "console"
    WINDOW = "window"

    @property
    def config_fix(self) -> str:
        """Как сказать, где исправить сломанный конфиг: консоли — «в настройщике», окну — только вкладку."""
        return msg.CONFIG_FIX_IN_SETUP if self is ReadinessVoice.CONSOLE else msg.CONFIG_FIX_ON_TAB

    def vault_advice(self, error: VaultFormatError) -> str:
        """Совет по нечитаемому файлу сейфа; личный файл окно заменит сохранением на своей вкладке."""
        if self is ReadinessVoice.WINDOW and error.is_replaceable:
            return msg.VAULT_FILE_ADVICE_WINDOW
        return error.advice


@dataclass(frozen=True)
class PlanBasis:
    """С чем идёт прогон таблицы плана: прочитанные настройки и сейф — одним значением."""

    settings: LivecraftSettings
    vault: Vault


@dataclass(frozen=True)
class ReadinessSummary:
    """Сводка для оператора: по каждому нужному полю сейфа — откуда оно (или «нет»), настроена ли форма ключей,
    каналы и языки. Без значений; устаревшее поле сейфа (ссылка на форму) не показывается."""

    vault: Vault | None
    settings: LivecraftSettings | None
    channels: ConfiguredChannels | None

    @property
    def lines(self) -> tuple[str, ...]:
        return (msg.READINESS_SUMMARY_TITLE, *self._field_lines, *self._form_lines, self._channels_line)

    @property
    def _field_lines(self) -> tuple[str, ...]:
        return tuple(
            msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=self._origin_label(field))
            for field in SecretField.current()
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
    """Итоги чтения сейфа и конфигов одного запуска и правила «готово ли, и что сказать».

    `has_client_secret` — снимок на момент проверки: без client_secret.json к Google не ходим (§9).
    """

    paths: LivecraftPaths
    vault: VaultRead
    settings: ConfigRead[LivecraftSettings]
    channels: ConfigRead[ConfiguredChannels]
    has_client_secret: bool

    @classmethod
    def check(cls, paths: LivecraftPaths) -> Readiness:
        """Прочитать сейф, livecraft.json и channels.json — независимо друг от друга. Ничего не печатает."""
        return cls(
            paths=paths,
            vault=VaultRead.of(VaultStore.open(paths)),
            settings=SettingsFile.of(paths).read(),
            channels=ChannelsFile.of(paths).read(),
            has_client_secret=paths.client_secret_file.is_file(),
        )

    @property
    def is_ready(self) -> bool:
        """Всё настроено: оба конфига прочитаны, сейф прочитан и в нём все поля. Так судит окно настройщика."""
        vault: Vault | None = self.vault.vault
        has_configs: bool = self.settings.value is not None and self.channels.value is not None
        return has_configs and vault is not None and vault.is_ready

    def part(self, part: RunPart) -> PartReadiness:
        """Готовность части: каких её нужд не хватает."""
        unmet: tuple[NeedGap, ...] = tuple(
            NeedGap(need=need, text=text) for need in part.needs if (text := self.gap(need)) is not None
        )
        return PartReadiness(part=part, unmet=unmet)

    def for_mode(self, mode: RunMode, no_llm: bool) -> ModeReadiness:
        """Готовность режима по частям в порядке его работы."""
        parts: tuple[PartReadiness, ...] = tuple(self.part(part) for part in mode.parts(no_llm))
        return ModeReadiness(mode=mode, parts=parts, is_fixable_in_setup=self.vault.is_fixable_in_setup)

    def plan_basis(self, mode: ModeReadiness) -> PlanBasis | None:
        """Настройки и сейф для прогона таблицы плана — когда режим её прогоняет (`ModeStep.RUN_PLAN`); иначе None.

        Готовая таблица плана значит прочитанные настройки и сейф: прогону они приходят одним значением.
        """
        settings: LivecraftSettings | None = self.settings.value
        vault: Vault | None = self.vault.vault
        if mode.step is not ModeStep.RUN_PLAN or settings is None or vault is None:
            return None
        return PlanBasis(settings=settings, vault=vault)

    def gap(self, need: Need) -> str | None:
        """Чего не хватает нужде — одна строка «что задать и где»; нужда удовлетворена — None.

        Единственное место текста нужды. Ссылка на форму проверяется, только когда настройки прочитаны: иначе о
        них уже говорит нужда настроек. client_secret.json в настройщике не задаётся — действие: положить файл.
        """
        if need in VAULT_NEEDS:
            return self._vault_gap(VAULT_NEEDS[need])
        settings_error: ConfigError | None = self.settings.error
        channels_error: ConfigError | None = self.channels.error
        if need is Need.SETTINGS and settings_error is not None:
            what: str = msg.READINESS_GAP_SETTINGS.format(key=settings_error.key_path, problem=settings_error.problem)
            return msg.READINESS_GAP_IN_SETUP.format(what=what, tab=msg.SETUP_TAB_SETTINGS)
        if need is Need.FORM and self.settings.value is not None and not self.settings.value.form.is_configured:
            return msg.READINESS_GAP_IN_SETUP.format(what=msg.READINESS_GAP_FORM, tab=msg.SETUP_TAB_SETTINGS)
        if need is Need.CHANNELS and channels_error is not None:
            broken: str = msg.READINESS_GAP_CHANNELS.format(key=channels_error.key_path, problem=channels_error.problem)
            what = msg.READINESS_GAP_CHANNELS_MISSING if channels_error.is_file_missing else broken
            return msg.READINESS_GAP_IN_SETUP.format(what=what, tab=msg.SETUP_TAB_CHANNELS)
        if need is Need.CLIENT_SECRET and not self.has_client_secret:
            return msg.READINESS_GAP_CLIENT_SECRET.format(path=self.paths.client_secret_file)
        return None

    @property
    def problems(self) -> tuple[str, ...]:
        """Что мешает полной настройке — строками для консоли (--check, --status): конфиги, потом сейф."""
        return self._problems(ReadinessVoice.CONSOLE)

    @property
    def window_line(self) -> str:
        """Строка готовности окна настройщика: «готово» или проблемы — без совета открыть само окно."""
        if self.is_ready:
            return msg.SETUP_READY
        return NEWLINE.join(self._problems(ReadinessVoice.WINDOW))

    @property
    def warnings(self) -> tuple[str, ...]:
        """Что сказать громко при любом исходе: личный сейф есть, но не прочитан (§16)."""
        return () if self.vault.load is None else self.vault.load.warnings

    @property
    def summary_lines(self) -> tuple[str, ...]:
        """Сводка для оператора без значений: поля сейфа, форма ключей, каналы и языки."""
        summary: ReadinessSummary = ReadinessSummary(
            vault=self.vault.vault, settings=self.settings.value, channels=self.channels.value
        )
        return summary.lines

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

    def _vault_gap(self, fields: tuple[SecretField, ...]) -> str | None:
        """Нужда сейфа: файл не читается — одна строка о нём; иначе недостающие поля одной строкой."""
        if self.vault.error is not None:
            return msg.READINESS_GAP_VAULT_BROKEN.format(problem=self.vault.error.problem)
        vault: Vault | None = self.vault.vault
        absent: tuple[SecretField, ...] = fields if vault is None else vault.missing_of(fields)
        if not absent:
            return None
        what: str = msg.LIST_JOINER.join(field.human_label for field in absent)
        return msg.READINESS_GAP_IN_SETUP.format(what=what, tab=msg.SETUP_TAB_KEYS)

    def _problems(self, voice: ReadinessVoice) -> tuple[str, ...]:
        """Строки полной проверки: конфиги (нет файла каналов — «добавьте каналы»), затем сейф."""
        lines: list[str] = []
        if self.settings.error is not None:
            lines.append(voice.config_fix.format(error=self.settings.error, tab=msg.SETUP_TAB_SETTINGS))
        if self.channels.is_missing:
            lines.append(msg.READINESS_CHANNELS_MISSING)
        elif self.channels.error is not None:
            lines.append(voice.config_fix.format(error=self.channels.error, tab=msg.SETUP_TAB_CHANNELS))
        vault: Vault | None = self.vault.vault
        error: VaultFormatError | None = self.vault.error
        if error is not None:
            lines.append(msg.VAULT_FILE_BROKEN.format(problem=error.problem, advice=voice.vault_advice(error)))
        elif vault is not None and vault.admission_reason is not None:
            lines.append(vault.admission_reason)
        return tuple(lines)
