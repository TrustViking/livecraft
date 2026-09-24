"""Однократный перенос ссылки на форму ключей из сейфа в livecraft.json (CLAUDE.md §14 решение 15, §7.4).

Ссылка на форму стала открытой настройкой `form.url`: она открыто уходит в пакет .bcast (решение 13).
У тех, кто настроил программу раньше, ссылка лежит в сейфе полем `key_form_url` — человек не должен вводить
её заново (Предназначение, п. 3), поэтому программа переносит её сама: при запуске, если `form.url` пуст,
а в сейфе (в любом слое) ссылка есть.

Здесь — единственная временная точка раскрытия значения этого поля (§7.4): без открытого значения его
нельзя записать в открытый файл. Точка удаляется вместе с полем на этапе «Токен доступа». Ни в лог, ни в
консоль ссылка не уходит: в строке лога — ярлык поля с отпечатком.

Порядок переноса: проверить ссылку правилом самой формы (`FormSettings.url_problem`) → записать livecraft.json
тем же загрузчиком (`save_settings_file`) → только после этого убрать поле из личного сейфа. Негодная ссылка
ничего не пишет: причина — предупреждением, ссылку человек вписывает на вкладке «Настройки запуска».
Поставочный сейф не меняется никогда (это правило `VaultStore`): поле в нём остаётся, но при заданном
`form.url` перенос больше не планируется.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.loader import FormSettings, LivecraftSettings, SettingProblem, save_settings_file
from app.observability.logging_setup import get_logger
from app.paths import LivecraftPaths
from app.secretsafe.dpapi import DpapiUnavailable
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import VaultOrigin
from app.setup.readiness import Readiness
from app.ui import messages_ru as msg

LOGGER = get_logger("setup")

LEGACY_FIELD: Final[SecretField] = SecretField.KEY_FORM_URL
LOG_LINE_TEMPLATE: Final[str] = (
    "outcome={outcome} source={source} value={label} local_cleared={local_cleared}"
)


class MigrationOutcome(str, Enum):
    """Чем кончился перенос. Значение — английский идентификатор для лога."""

    MOVED = "moved"                  # ссылка в livecraft.json
    INVALID = "invalid"              # ссылка в сейфе негодна: ничего не записано
    WRITE_FAILED = "write_failed"    # livecraft.json не записался: сейф не тронут


@dataclass(frozen=True)
class FormUrlMigrationResult:
    """Итог переноса: перенесено ли, почему нет и что сказать. Самой ссылки в объекте нет.

    `label` — ярлык поля с отпечатком (`key-form(9c2b)`): различить значения можно, прочитать нельзя (§7.4).
    `local_cleared` — поле убрано из личного сейфа; False, если его там не было или записать сейф не вышло.
    """

    outcome: MigrationOutcome
    source: VaultOrigin
    label: str
    local_cleared: bool
    reason: str | None

    @property
    def moved(self) -> bool:
        """Ссылка записана в livecraft.json."""
        return self.outcome is MigrationOutcome.MOVED

    @property
    def console_line(self) -> str:
        """Одна строка оператору: перенесено — сообщение об этом; нет — причина и что сделать."""
        if self.moved:
            return msg.FORM_URL_MIGRATED
        return msg.FORM_URL_MIGRATION_FAILED.format(reason=self.reason)

    @property
    def log_line(self) -> str:
        """Строка лога: исход, откуда ссылка, ярлык с отпечатком; ни ссылки, ни текста причины с путём."""
        return LOG_LINE_TEMPLATE.format(
            outcome=self.outcome.value,
            source=self.source.value,
            label=self.label,
            local_cleared=self.local_cleared,
        )


@dataclass(frozen=True)
class FormUrlMigration:
    """Запланированный перенос: корень установки, прочитанный сейф, настройки с пустой ссылкой на форму
    и сама ссылка из сейфа — объектом-секретом (в `repr` — маска)."""

    paths: LivecraftPaths
    vault_load: VaultLoad
    settings: LivecraftSettings
    secret: SecretValue

    @classmethod
    def plan(cls, paths: LivecraftPaths, readiness: Readiness) -> FormUrlMigration | None:
        """Перенос нужен, только если настройки прочитаны, ссылка в них пуста, а в сейфе она есть.

        Каналы переносу не нужны: ссылка — настройка livecraft.json, а не channels.json.
        """
        if readiness.settings is None or readiness.vault_load is None:
            return None
        settings: LivecraftSettings = readiness.settings
        if settings.form.is_configured:
            return None
        secret: SecretValue | None = readiness.vault_load.vault.get(LEGACY_FIELD)
        if secret is None:
            return None
        return cls(paths=paths, vault_load=readiness.vault_load, settings=settings, secret=secret)

    @property
    def source(self) -> VaultOrigin:
        """Из какого слоя сейфа ссылка: своё значение перекрывает поставочное (§7.3)."""
        origin: VaultOrigin | None = self.vault_load.vault.origin_of(LEGACY_FIELD)
        return VaultOrigin.SUPPLIED if origin is None else origin

    def run(self) -> FormUrlMigrationResult:
        """Проверить ссылку, записать livecraft.json, затем убрать поле из личного сейфа."""
        # Временная точка раскрытия (CLAUDE.md §7.4): значение уходит только в открытую настройку.
        form: FormSettings = dataclasses.replace(self.settings.form, url=self.secret.reveal())
        problem: SettingProblem | None = form.url_problem
        if problem is not None:
            return self._result(MigrationOutcome.INVALID, reason=problem.text)
        try:
            save_settings_file(self.paths.config_file, dataclasses.replace(self.settings, form=form))
        except OSError as error:
            return self._result(MigrationOutcome.WRITE_FAILED, reason=error.strerror or type(error).__name__)
        return self._result(MigrationOutcome.MOVED, reason=None, local_cleared=self._clear_local())

    def _clear_local(self) -> bool:
        """Убрать поле из личного сейфа, если оно там. Не вышло — ссылка уже в настройках, запуск идёт дальше:
        при заданном form.url перенос больше не планируется, а значение в сейфе вычёркивается из логов."""
        if self.source is not VaultOrigin.OWN:
            return False
        store: VaultStore = VaultStore.open(self.paths)
        if not store.can_save_local:
            LOGGER.warning("form_url_migration_local_kept reason=dpapi_unavailable")
            return False
        try:
            store.save_local(self.vault_load.own.without_field(LEGACY_FIELD))
        except (DpapiUnavailable, OSError) as error:
            LOGGER.warning("form_url_migration_local_kept reason=%s", type(error).__name__)
            return False
        return True

    def _result(
        self, outcome: MigrationOutcome, *, reason: str | None, local_cleared: bool = False
    ) -> FormUrlMigrationResult:
        return FormUrlMigrationResult(
            outcome=outcome,
            source=self.source,
            label=self.secret.log_label,
            local_cleared=local_cleared,
            reason=reason,
        )
