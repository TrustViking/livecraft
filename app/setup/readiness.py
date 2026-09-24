"""Готовность программы к запуску: сейф и оба конфига прочитаны, всего хватает (CLAUDE.md §8.2).

Правило §8.2: нет сейфа и нет обязательных полей — обычный запуск не начинается, код 2 и строка «запустите
livecraft.bat --setup». Этот объект держит результаты чтения и сам отвечает на вопросы о себе: готово ли,
что не так, какой шаблон показать, что сказать громко. Печатает и выбирает код выхода только main.

Сводка и строка лога не содержат ни значений, ни масок (§7.4): оператору нужно знать, откуда значение —
пришло с программой или вписано им самим, — а не само значение.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.config.loader import (
    ConfigError,
    LivecraftConfig,
    Platform,
    Privacy,
    allowed_values,
    load_livecraft_config,
)
from app.paths import LivecraftPaths
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.value import SecretField
from app.secretsafe.vault import Vault, VaultOrigin
from app.ui import messages_ru as msg

LANGUAGE_JOINER: Final[str] = ", "
LOG_ABSENT: Final[str] = "-"
LOG_VAULT_BROKEN: Final[str] = "broken"
LOG_CONFIG_OK: Final[str] = "ok"
LOG_CONFIG_ERROR: Final[str] = "error"
LOG_LINE_TEMPLATE: Final[str] = "config={config} channels={channels} local={local} vault={vault}"


@dataclass(frozen=True)
class Readiness:
    """Результат чтения сейфа и конфигов одного запуска и правила «готово ли, и что сказать».

    `paths` — поле, потому что какой шаблон показать, решается сравнением пути сломанного конфига с путями
    установки. Перехватываются только ConfigError и VaultFormatError: всё остальное — ошибка программы,
    и её ловит main.run_cli.
    """

    paths: LivecraftPaths
    config: LivecraftConfig | None
    config_error: ConfigError | None
    vault_load: VaultLoad | None
    vault_error: VaultFormatError | None

    @classmethod
    def check(cls, paths: LivecraftPaths) -> Readiness:
        """Прочитать сейф, затем оба конфига. Ничего не печатает."""
        vault_load: VaultLoad | None = None
        vault_error: VaultFormatError | None = None
        try:
            vault_load = VaultStore.open(paths).load()
        except VaultFormatError as error:
            vault_error = error
        config: LivecraftConfig | None = None
        config_error: ConfigError | None = None
        try:
            config = load_livecraft_config(paths.config_file, paths.channels_file)
        except ConfigError as error:
            config_error = error
        return cls(
            paths=paths, config=config, config_error=config_error, vault_load=vault_load, vault_error=vault_error
        )

    @property
    def vault(self) -> Vault | None:
        """Сейф, если он прочитан; при файле чужого формата сейфа нет."""
        return None if self.vault_load is None else self.vault_load.vault

    @property
    def is_ready(self) -> bool:
        """Конфиги прочитаны, сейф прочитан и в нём все поля."""
        return self.config is not None and self.vault is not None and self.vault.is_ready

    @property
    def problems(self) -> tuple[str, ...]:
        """Что мешает запуску — русскими строками для оператора: сначала конфиг, потом сейф."""
        lines: list[str] = []
        if self.config_error is not None:
            lines.append(str(self.config_error))
        if self.vault_error is not None:
            lines.append(msg.VAULT_FILE_BROKEN.format(error=self.vault_error))
        elif self.vault is not None and self.vault.admission_reason is not None:
            lines.append(self.vault.admission_reason)
        return tuple(lines)

    @property
    def template_lines(self) -> tuple[str, ...]:
        """Точный шаблон сломанного конфига — только когда нет файла или поля (ConfigError.is_template_needed)."""
        error: ConfigError | None = self.config_error
        if error is None or not error.is_template_needed:
            return ()
        if error.config_path == self.paths.channels_file:
            return (
                msg.CONFIG_CHANNELS_HINT.format(path=error.config_path),
                *self._channel_field_lines,
                msg.CONFIG_CHANNELS_TEMPLATE,
            )
        return (msg.CONFIG_SETTINGS_HINT.format(path=error.config_path), msg.CONFIG_SETTINGS_TEMPLATE)

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
        """То же для лога: ярлыки с отпечатками, состояние личного файла, число каналов; ни одного значения."""
        return LOG_LINE_TEMPLATE.format(
            config=LOG_CONFIG_OK if self.config is not None else LOG_CONFIG_ERROR,
            channels=len(self.config.channels) if self.config is not None else LOG_ABSENT,
            local=self.vault_load.local_state.value if self.vault_load is not None else LOG_ABSENT,
            vault=self.vault.log_line if self.vault is not None else LOG_VAULT_BROKEN,
        )

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
        if self.config is None:
            return ()
        state: str = (
            msg.READINESS_FORM_CONFIGURED
            if self.config.settings.form.is_configured
            else msg.READINESS_FORM_NOT_CONFIGURED
        )
        return (msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=state),)

    def _origin_label(self, field: SecretField) -> str:
        origin: VaultOrigin | None = None if self.vault is None else self.vault.origin_of(field)
        return msg.READINESS_FIELD_ABSENT if origin is None else origin.human_label

    @property
    def _channels_line(self) -> str:
        if self.config is None:
            return msg.READINESS_CHANNELS_ABSENT
        return msg.READINESS_CHANNELS_LINE.format(
            count=len(self.config.channels),
            languages=LANGUAGE_JOINER.join(sorted(self.config.served_languages)),
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
