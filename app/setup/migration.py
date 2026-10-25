"""Однократные переносы прежних ключей livecraft.json (CLAUDE.md §14 решения 39, 50, 62, §7.4).

Ссылка на папку Google Диска — ресурс оператора того же рода, что таблица плана: в сейфе, а не открытой настройкой. У
тех, кто настроил программу раньше, она лежит в livecraft.json ключом `drive.folder_url` — человек не должен вводить её
заново (CLAUDE.md §1, «Поведение программы»), поэтому программа переносит её сама при любом запуске, до чтения
настроек (`DriveFolderMigration`), — в обе папки Диска: для превью и для документов объявлений (решение 60), как и
прежнее поле сейфа. Ни в лог, ни в консоль ссылка не уходит: в строке лога — ярлыки полей с отпечатком.

Переключателя источника текстов (решение 50: тексты — строго по линиям запуска) и чата поддержки (решение 62: логи —
только архив) больше нет, а их ключи `broadcasts.text_source` и `telegram.support_chat_id` в файле ломали бы разбор:
программа убирает их сама при любом запуске, до чтения настроек (`DroppedSettingKeys`), — строка лога, человеку делать
нечего. Файл без таких ключей не трогается.

Проект Google — путь к файлу клиента в livecraft.json (`google.project_file`, решение 66). У тех, кто настроил
программу раньше, пути нет, а файл лежит в secrets\\ — client_secret.json (до 9.21) или google_project_<ID>.json (9.21):
человек не должен выбирать его заново, поэтому программа подключает его сама при любом запуске, до готовности
(`ProjectConnection`): client_secret.json, если он есть, иначе единственный google_project_*.json без «.previous».
Файл не переименовывается и не копируется; подключение — строкой консоли и части «Запуск» отчёта. Путь уже задан —
ничего не делается.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.config.files import SettingsFile
from app.config.google import GoogleSettings
from app.config.setting_key import LegacySettingKey
from app.config.settings import LivecraftSettings
from app.core.errors import os_error_reason
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.paths import FileName, LivecraftPaths
from app.secretsafe.dpapi import DpapiUnavailable
from app.secretsafe.field import LegacyField, SecretField, VaultOrigin
from app.secretsafe.store import VaultLayerState, VaultLoad, VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.fields.secret_input import SecretInput
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)

LEGACY_DRIVE_KEY: Final[LegacySettingKey] = LegacySettingKey.DRIVE_FOLDER_URL
# Куда ложится ссылка: в те же поля, что и значение прежнего общего поля сейфа (§14 решение 60).
DRIVE_LINK_FIELDS: Final[tuple[SecretField, ...]] = LegacyField.DRIVE_FOLDER.successors
# Прежние ключи, значение которых не нужно: программа только убирает их из файла.
DROPPED_KEYS: Final[tuple[LegacySettingKey, ...]] = (
    LegacySettingKey.BROADCASTS_TEXT_SOURCE,
    LegacySettingKey.TELEGRAM_SUPPORT_CHAT_ID,
)
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


class ProjectConnectionEvent(str, Enum):
    """События подключения проекта Google при запуске в логе."""

    CONNECTED = "google_project_connected"
    NOT_CONNECTED = "google_project_not_connected"


class DroppedKeyEvent(str, Enum):
    """События ухода прежнего ключа в логе."""

    DROPPED = "setting_key_dropped"
    NOT_DROPPED = "setting_key_not_dropped"


@dataclass(frozen=True)
class DriveFolderMigrationResult:
    """Итог переноса: исход, ярлыки полей с отпечатком (ссылка годна) и причина для человека. Самой ссылки нет."""

    outcome: DriveFolderOutcome
    labels: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Перенесено — строка об этом; пустой ключ — ни одной; иначе причина и что сделать."""
        if self.outcome is DriveFolderOutcome.EMPTY:
            return ()
        if self.outcome is DriveFolderOutcome.MOVED:
            return (msg.DRIVE_LINK_MIGRATED,)
        return (msg.DRIVE_LINK_MIGRATION_FAILED.format(reason=self.reason),)

    @property
    def is_done(self) -> bool:
        """Папки в сейфе или переносить было нечего: человеку делать нечего."""
        return self.outcome in (DriveFolderOutcome.MOVED, DriveFolderOutcome.EMPTY)

    @property
    def event(self) -> LogEvent:
        """Строка лога: исход и ярлыки полей с отпечатком; ни ссылки, ни текста причины."""
        name: DriveFolderEvent = DriveFolderEvent.MOVED if self.is_done else DriveFolderEvent.NOT_MOVED
        return LogEvent.of(name, outcome=self.outcome, fields=self.labels)

    @property
    def log_level(self) -> int:
        """Сделано — обычная строка; нет — предупреждение: папку придётся вписать в окне."""
        return logging.INFO if self.is_done else logging.WARNING


@dataclass(frozen=True)
class DriveFolderMigration:
    """Однократный перенос ссылки на папку Google Диска из livecraft.json в сейф (§14 решения 39, 60): при любом запуске, до
    чтения настроек — с этим ключом разбор отвергает файл. Ссылка проверяется правилом папки Диска (`SecretInput`), id
    ложится в личный сейф своим значением обеих папок (`DRIVE_LINK_FIELDS`); затем ключ уходит из файла — и тогда, когда
    ссылка негодна или сохранить её некуда: файл, который не разбирается, остановил бы все линии, а папку человек впишет
    на вкладках «Превью» и «Google-документ»."""

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
        """Ссылка → сейф → ключ из файла. Правило ввода у обеих папок одно: ссылка годна для обеих или ни для одной."""
        entered: tuple[SecretInput, ...] = tuple(SecretInput(field=field, raw=self.link) for field in DRIVE_LINK_FIELDS)
        found: tuple[SecretValue | None, ...] = tuple(one.secret for one in entered)
        secrets: tuple[SecretValue, ...] = tuple(secret for secret in found if secret is not None)
        if not secrets:
            first: SecretInput = entered[0]
            outcome: DriveFolderOutcome = DriveFolderOutcome.EMPTY if first.is_empty else DriveFolderOutcome.INVALID
            return self._dropped(DriveFolderMigrationResult(outcome, reason=first.problem))
        labels: tuple[str, ...] = tuple(secret.log_label for secret in secrets)
        problem: str | None = self._save(secrets)
        if problem is not None:
            return self._dropped(DriveFolderMigrationResult(DriveFolderOutcome.NOT_SAVED, labels, problem))
        return self._dropped(DriveFolderMigrationResult(DriveFolderOutcome.MOVED, labels))

    def _save(self, secrets: tuple[SecretValue, ...]) -> str | None:
        """id папки — своим значением обеих папок в личный сейф поверх прочитанного личного слоя; не вышло — причина."""
        store: VaultStore = VaultStore.open(self.paths)
        if not store.can_save:
            return msg.SETUP_INPUT_OWN_UNAVAILABLE
        try:
            loaded: VaultLoad = store.load_for_setup()
            if loaded.local_state in UNWRITABLE_LOCAL_STATES:
                return msg.DRIVE_LINK_MIGRATION_LOCAL_UNREAD
            own: Vault = loaded.own
            for secret in secrets:
                own = own.with_field(secret.field, secret, VaultOrigin.OWN)
            store.save_local(own)
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
            return DriveFolderMigrationResult(DriveFolderOutcome.FILE_FAILED, result.labels, os_error_reason(error))
        return result


@dataclass(frozen=True)
class DroppedSettingKeys:
    """Уход прежних ключей livecraft.json, значение которых не нужно (`DROPPED_KEYS`: источник текстов — §14 решение 50,
    чат поддержки — §14 решение 62): при любом запуске, до чтения настроек — с ними разбор отвергает файл."""

    file: SettingsFile

    @classmethod
    def apply(cls, paths: LivecraftPaths) -> None:
        """Убрать каждый такой ключ, который в файле есть, и записать итог в лог; ключей нет — файл не трогается."""
        dropped: DroppedSettingKeys = cls(SettingsFile.of(paths))
        for key in DROPPED_KEYS:
            value: str | None = dropped.file.legacy_value(key)
            if value is not None:
                dropped.drop(key, value)

    def drop(self, key: LegacySettingKey, value: str) -> None:
        """Ключ — из файла; файл не записался — предупреждение в лог с причиной: о файле скажет разбор настроек."""
        try:
            self.file.drop_legacy(key)
        except OSError as error:
            failed: LogEvent = LogEvent.of(DroppedKeyEvent.NOT_DROPPED, key=key.value, value=value)
            failed.extended(reason=os_error_reason(error)).emit(LOGGER, logging.WARNING)
            return
        LogEvent.of(DroppedKeyEvent.DROPPED, key=key.value, value=value).emit(LOGGER)


@dataclass(frozen=True)
class ProjectConnection:
    """Подключение проекта Google, когда он не выбран (§14 решение 66): при любом запуске, до готовности."""

    paths: LivecraftPaths

    @classmethod
    def apply(cls, paths: LivecraftPaths) -> tuple[str, ...]:
        """Проект не выбран и в secrets\\ есть его файл — путь к файлу в livecraft.json; строка консоли (подключать
        нечего, путь уже задан или настройки не читаются — ни одной)."""
        file: SettingsFile = SettingsFile.of(paths)
        settings: LivecraftSettings | None = file.read().value
        found: Path | None = cls(paths).found
        if settings is None or settings.google.project_file or found is None:
            return ()
        shown: str = paths.shown(found)
        try:
            file.save_google(GoogleSettings(project_file=shown))
        except OSError as error:
            failed: LogEvent = LogEvent.of(ProjectConnectionEvent.NOT_CONNECTED, file=Quoted(shown))
            failed.extended(reason=os_error_reason(error)).emit(LOGGER, logging.WARNING)
            return ()
        LogEvent.of(ProjectConnectionEvent.CONNECTED, file=Quoted(shown)).emit(LOGGER)
        return (msg.GOOGLE_PROJECT_CONNECTED.format(path=shown),)

    @property
    def found(self) -> Path | None:
        """client_secret.json, если он есть; иначе единственный google_project_*.json без «.previous»; иначе None."""
        legacy: Path = self.paths.file(FileName.CLIENT_SECRET)
        if legacy.is_file():
            return legacy
        found: tuple[Path, ...] = self.paths.found_project_files
        return found[0] if len(found) == 1 else None
