"""Однократные переносы прежних ключей livecraft.json (CLAUDE.md §14 решения 39, 50, §7.4).

Ссылка на папку материалов — ресурс оператора того же рода, что таблица плана: в сейфе, а не открытой настройкой. У
тех, кто настроил программу раньше, она лежит в livecraft.json ключом `drive.folder_url` — человек не должен вводить её
заново (CLAUDE.md §1, «Поведение программы»), поэтому программа переносит её сама при любом запуске, до чтения
настроек (`DriveFolderMigration`). Ни в лог, ни в консоль ссылка не уходит: в строке лога — ярлык поля с отпечатком.

Переключателя источника текстов больше нет (решение 50: тексты — строго по линиям запуска), а его ключ
`broadcasts.text_source` в файле ломал бы разбор: программа убирает его сама при любом запуске, до чтения настроек
(`TextSourceMigration`), — строка лога, человеку делать нечего. Файл без ключа не трогается.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.files import SettingsFile
from app.config.setting_key import LegacySettingKey
from app.core.errors import os_error_reason
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths
from app.secretsafe.dpapi import DpapiUnavailable
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultLayerState, VaultLoad, VaultStore
from app.secretsafe.value import SecretValue
from app.setup.fields.secret_input import SecretInput
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)

LEGACY_DRIVE_KEY: Final[LegacySettingKey] = LegacySettingKey.DRIVE_FOLDER_URL
LEGACY_TEXT_SOURCE_KEY: Final[LegacySettingKey] = LegacySettingKey.BROADCASTS_TEXT_SOURCE
# Личный сейф, который не прочитан: запись поверх него стёрла бы введённые раньше значения — id папки туда не пишется.
UNWRITABLE_LOCAL_STATES: Final[frozenset[VaultLayerState]] = frozenset(
    {VaultLayerState.UNREADABLE, VaultLayerState.BROKEN}
)


class DriveFolderOutcome(str, Enum):
    """Чем кончился перенос ссылки на папку Диска. Значение — английский идентификатор для лога."""

    MOVED = "moved"                  # id папки — в сейфе, ключ убран из livecraft.json
    EMPTY = "empty"                  # ключ был пустым: убран, переносить нечего
    INVALID = "invalid"              # ссылка негодна: ключ убран, папку вписывает человек
    NOT_SAVED = "not_saved"          # своё значение сохранить некуда или личный сейф не читается: ключ убран
    FILE_FAILED = "file_failed"      # id в сейфе, но livecraft.json не записался: следующий запуск повторит


class DriveFolderEvent(str, Enum):
    """События переноса ссылки на папку Диска в логе."""

    MOVED = "drive_folder_migrated"
    NOT_MOVED = "drive_folder_not_migrated"


class TextSourceEvent(str, Enum):
    """События ухода ключа источника текстов в логе."""

    DROPPED = "text_source_dropped"
    NOT_DROPPED = "text_source_not_dropped"


@dataclass(frozen=True)
class DriveFolderMigrationResult:
    """Итог переноса: исход, ярлык значения с отпечатком (ссылка годна) и причина для человека. Самой ссылки нет."""

    outcome: DriveFolderOutcome
    label: str | None = None
    reason: str | None = None

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Перенесено — строка об этом; пустой ключ — ни одной; иначе причина и что сделать."""
        if self.outcome is DriveFolderOutcome.EMPTY:
            return ()
        if self.outcome is DriveFolderOutcome.MOVED:
            return (msg.DRIVE_FOLDER_MIGRATED,)
        return (msg.DRIVE_FOLDER_MIGRATION_FAILED.format(reason=self.reason),)

    @property
    def is_done(self) -> bool:
        """Папка в сейфе или переносить было нечего: человеку делать нечего."""
        return self.outcome in (DriveFolderOutcome.MOVED, DriveFolderOutcome.EMPTY)

    @property
    def event(self) -> LogEvent:
        """Строка лога: исход и ярлык с отпечатком; ни ссылки, ни текста причины."""
        name: DriveFolderEvent = DriveFolderEvent.MOVED if self.is_done else DriveFolderEvent.NOT_MOVED
        return LogEvent.of(name, outcome=self.outcome, value=self.label)

    @property
    def log_level(self) -> int:
        """Сделано — обычная строка; нет — предупреждение: папку придётся вписать в окне."""
        return logging.INFO if self.is_done else logging.WARNING


@dataclass(frozen=True)
class DriveFolderMigration:
    """Однократный перенос ссылки на папку Google Диска из livecraft.json в сейф (§14 решение 39): при любом запуске, до
    чтения настроек — с этим ключом разбор отвергает файл. Ссылка проверяется правилом поля сейфа (`SecretInput`), id
    ложится в личный сейф своим значением; затем ключ уходит из файла — и тогда, когда ссылка негодна или сохранить её
    некуда: файл, который не разбирается, остановил бы все линии, а папку человек впишет на вкладке «Превью»."""

    paths: LivecraftPaths
    file: SettingsFile
    link: str = dataclasses.field(repr=False)

    @classmethod
    def apply(cls, paths: LivecraftPaths) -> tuple[str, ...]:
        """Перенести, если ключ в файле есть, и записать итог в лог; строки для консоли (ключа нет — ни одной)."""
        file: SettingsFile = SettingsFile.of(paths)
        link: str | None = file.legacy_value(LEGACY_DRIVE_KEY)
        if link is None:
            return ()
        result: DriveFolderMigrationResult = cls(paths=paths, file=file, link=link).run()
        result.event.emit(LOGGER, result.log_level)
        return result.console_lines

    def run(self) -> DriveFolderMigrationResult:
        """Ссылка → сейф → ключ из файла."""
        entered: SecretInput = SecretInput(field=SecretField.DRIVE_FOLDER, raw=self.link)
        secret: SecretValue | None = entered.secret
        if secret is None:
            outcome: DriveFolderOutcome = DriveFolderOutcome.EMPTY if entered.is_empty else DriveFolderOutcome.INVALID
            return self._dropped(DriveFolderMigrationResult(outcome, reason=entered.problem))
        problem: str | None = self._save(secret)
        if problem is not None:
            return self._dropped(DriveFolderMigrationResult(DriveFolderOutcome.NOT_SAVED, secret.log_label, problem))
        return self._dropped(DriveFolderMigrationResult(DriveFolderOutcome.MOVED, secret.log_label))

    def _save(self, secret: SecretValue) -> str | None:
        """id папки — своим значением в личный сейф поверх прочитанного личного слоя; не вышло — причина."""
        store: VaultStore = VaultStore.open(self.paths)
        if not store.can_save:
            return msg.SETUP_INPUT_OWN_UNAVAILABLE
        try:
            loaded: VaultLoad = store.load_for_setup()
            if loaded.local_state in UNWRITABLE_LOCAL_STATES:
                return msg.DRIVE_FOLDER_MIGRATION_LOCAL_UNREAD
            store.save_local(loaded.own.with_field(SecretField.DRIVE_FOLDER, secret, VaultOrigin.OWN))
        except DpapiUnavailable as error:
            return error.human
        except OSError as error:
            return os_error_reason(error)
        return None

    def _dropped(self, result: DriveFolderMigrationResult) -> DriveFolderMigrationResult:
        """Ключ — из файла; файл не записался — исход FILE_FAILED с причиной (id, если он в сейфе, там и останется)."""
        try:
            self.file.drop_legacy(LEGACY_DRIVE_KEY)
        except OSError as error:
            return DriveFolderMigrationResult(DriveFolderOutcome.FILE_FAILED, result.label, os_error_reason(error))
        return result


@dataclass(frozen=True)
class TextSourceMigration:
    """Уход ключа `broadcasts.text_source` из livecraft.json (§14 решение 50): при любом запуске, до чтения настроек —
    с этим ключом разбор отвергает файл. Значение не нужно: тексты эфиров решают линии запуска."""

    file: SettingsFile

    @classmethod
    def apply(cls, paths: LivecraftPaths) -> None:
        """Убрать ключ, если он в файле есть, и записать итог в лог; ключа нет — файл не трогается."""
        file: SettingsFile = SettingsFile.of(paths)
        value: str | None = file.legacy_value(LEGACY_TEXT_SOURCE_KEY)
        if value is not None:
            cls(file).drop(value)

    def drop(self, value: str) -> None:
        """Ключ — из файла; файл не записался — предупреждение в лог с причиной: о файле скажет разбор настроек."""
        try:
            self.file.drop_legacy(LEGACY_TEXT_SOURCE_KEY)
        except OSError as error:
            failed: LogEvent = LogEvent.of(TextSourceEvent.NOT_DROPPED, value=value, reason=os_error_reason(error))
            failed.emit(LOGGER, logging.WARNING)
            return
        LogEvent.of(TextSourceEvent.DROPPED, value=value).emit(LOGGER)
