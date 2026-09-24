"""Готовность программы к запуску — целиком и по частям выбранного режима (CLAUDE.md §8.2, §10).

Сейф, livecraft.json и channels.json читаются независимо: нет каналов — настройки всё равно прочитаны, и
части режима, которым каналы не нужны, готовы. Этот объект держит результаты чтения и сам отвечает на
вопросы о себе: готово ли всё (окно настройщика), готова ли каждая часть режима и что сделать, если нет,
что сказать громко. Печатает и выбирает код выхода только main.

Правило готовности каждой части — в одном месте, `Readiness.part`. Не готовая часть называется одной
строкой с точным действием: что задать и где. Шаблоны файлов в консоль не идут — только в лог при
сломанном файле; файлы правит настройщик.

Сводка, строки частей и строка лога не содержат ни значений, ни масок (§7.4): оператору нужно знать,
откуда значение — пришло с программой или вписано им самим, — а не само значение.
"""
from __future__ import annotations

from dataclasses import dataclass
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
from app.paths import LivecraftPaths
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.value import SecretField
from app.secretsafe.vault import Vault, VaultOrigin
from app.setup.run_mode import RunMode, RunPart
from app.ui import messages_ru as msg

LANGUAGE_JOINER: Final[str] = ", "
GAP_JOINER: Final[str] = "; "
LOG_ABSENT: Final[str] = "-"
LOG_VAULT_BROKEN: Final[str] = "broken"
LOG_CONFIG_OK: Final[str] = "ok"
LOG_CONFIG_ERROR: Final[str] = "error"
LOG_PART_JOINER: Final[str] = ","
LOG_LINE_TEMPLATE: Final[str] = "settings={settings} channels={channels} local={local} vault={vault}"
MODE_LOG_LINE_TEMPLATE: Final[str] = "mode={mode} ready={ready} blocked={blocked} not_built={not_built}"
# Что нужно каждой реализованной части из сейфа (§7.5): таблица — id и диапазон, merge — ключ OpenAI.
PLAN_VAULT_FIELDS: Final[tuple[SecretField, ...]] = (SecretField.SHEETS_ID, SecretField.SHEETS_RANGE)
MERGE_VAULT_FIELDS: Final[tuple[SecretField, ...]] = (SecretField.OPENAI_API_KEY,)


@dataclass(frozen=True)
class PartReadiness:
    """Готовность одной части режима: готова ли, реализована ли в этой версии и что сделать, если нет.

    `action` — одна строка для оператора: у не готовой части — что задать и где, у нереализованной — когда
    появится; у готовой — None. Ни значений, ни путей к файлам ключей в строке нет (§7.4).
    """

    part: RunPart
    is_ready: bool
    is_built: bool
    action: str | None

    @property
    def is_blocked(self) -> bool:
        """Часть есть в этой версии, но не настроена."""
        return self.is_built and not self.is_ready


@dataclass(frozen=True)
class ModeReadiness:
    """Готовность выбранного режима по частям — в порядке работы режима.

    Первая часть режима — его основа: в режиме А из таблицы берутся все слоты, и без чтения таблицы не
    делается ничего. Поэтому не готовая основа — это «не готово ничего», даже если у остальных частей
    всё настроено. `is_fixable_in_setup` — ложь, когда файл ключей и ссылок повреждён: окно правку такого
    файла не позволяет, открывать его незачем.
    """

    mode: RunMode
    parts: tuple[PartReadiness, ...]
    is_fixable_in_setup: bool

    @property
    def ready(self) -> tuple[PartReadiness, ...]:
        return tuple(part for part in self.parts if part.is_built and part.is_ready)

    @property
    def blocked(self) -> tuple[PartReadiness, ...]:
        return tuple(part for part in self.parts if part.is_blocked)

    @property
    def not_built(self) -> tuple[PartReadiness, ...]:
        return tuple(part for part in self.parts if not part.is_built)

    @property
    def is_nothing_ready(self) -> bool:
        """Ни одна реализованная часть не готова, либо не готова основа режима."""
        base: PartReadiness | None = self.parts[0] if self.parts else None
        return not self.ready or (base is not None and base.is_blocked)

    @property
    def lines(self) -> tuple[str, ...]:
        """Строки для консоли: по одной на каждую не готовую и каждую нереализованную часть, по порядку работы."""
        return tuple(part.action for part in self.parts if part.action is not None)

    @property
    def log_line(self) -> str:
        return MODE_LOG_LINE_TEMPLATE.format(
            mode=self.mode.value,
            ready=self._log_ids(self.ready),
            blocked=self._log_ids(self.blocked),
            not_built=self._log_ids(self.not_built),
        )

    def _log_ids(self, parts: tuple[PartReadiness, ...]) -> str:
        """Идентификаторы частей через запятую; пусто — прочерк."""
        return LOG_PART_JOINER.join(part.part.value for part in parts) or LOG_ABSENT


@dataclass(frozen=True)
class Readiness:
    """Результат чтения сейфа и конфигов одного запуска и правила «готово ли, и что сказать».

    Перехватываются только ConfigError и VaultFormatError: всё остальное — ошибка программы, и её ловит
    main.run_cli. `has_client_secret` — снимок на момент проверки: без client_secret.json к Google не ходим (§9).
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
        action: str = msg.RUN_PART_BLOCKED.format(part=part.human_label, gaps=GAP_JOINER.join(gaps))
        return PartReadiness(part=part, is_ready=False, is_built=True, action=action)

    def for_mode(self, mode: RunMode, no_llm: bool) -> ModeReadiness:
        """Готовность режима по частям в порядке его работы."""
        return ModeReadiness(
            mode=mode,
            parts=tuple(self.part(part) for part in mode.parts(no_llm)),
            is_fixable_in_setup=self.vault_error is None,
        )

    @property
    def problems(self) -> tuple[str, ...]:
        """Что мешает полной настройке — строками для оператора (окно, --check, --status): конфиги, потом сейф."""
        lines: list[str] = [self._config_problem(error) for error in self.config_errors]
        if self.vault_error is not None:
            lines.append(msg.VAULT_FILE_BROKEN.format(error=self.vault_error))
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
    def log_line(self) -> str:
        """То же для лога: состояние файлов, ярлыки с отпечатками, число каналов; ни одного значения."""
        return LOG_LINE_TEMPLATE.format(
            settings=LOG_CONFIG_OK if self.settings is not None else LOG_CONFIG_ERROR,
            channels=len(self.channels) if self.channels is not None else LOG_ABSENT,
            local=self.vault_load.local_state.value if self.vault_load is not None else LOG_ABSENT,
            vault=self.vault.log_line if self.vault is not None else LOG_VAULT_BROKEN,
        )

    # --- что не хватает части: по строке «что задать — где»

    def _gaps(self, part: RunPart) -> tuple[str, ...]:
        if part is RunPart.PLAN:
            return (*self._vault_gaps(PLAN_VAULT_FIELDS), *self._settings_gaps, *self._client_secret_gaps)
        if part is RunPart.MERGE:
            return self._vault_gaps(MERGE_VAULT_FIELDS)
        if part is RunPart.PACKAGE:
            return (*self._settings_gaps, *self._form_gaps)
        if part is RunPart.BROADCAST:
            return (*self._channels_gaps, *self._settings_gaps, *self._form_gaps)
        return ()

    def _vault_gaps(self, fields: tuple[SecretField, ...]) -> tuple[str, ...]:
        if self.vault_error is not None:
            return (msg.READINESS_GAP_VAULT_BROKEN.format(error=self.vault_error),)
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

    @property
    def _client_secret_gaps(self) -> tuple[str, ...]:
        """client_secret.json в настройщике не задаётся: действие — положить файл (§9)."""
        if self.has_client_secret:
            return ()
        return (msg.READINESS_GAP_CLIENT_SECRET.format(path=self.paths.client_secret_file),)

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
        return msg.READINESS_FIELD_ABSENT if origin is None else origin.human_label

    @property
    def _channels_line(self) -> str:
        if self.channels is None:
            return msg.READINESS_CHANNELS_ABSENT
        languages: frozenset[str] = frozenset(
            language for channel in self.channels for language in channel.languages
        )
        return msg.READINESS_CHANNELS_LINE.format(
            count=len(self.channels), languages=LANGUAGE_JOINER.join(sorted(languages))
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

