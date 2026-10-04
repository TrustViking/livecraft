"""Память программы — SQLite (stdlib sqlite3), файл secrets\\livecraft.sqlite3 (CLAUDE.md §6 инварианты 0, 1a, 10).

Одна база на запуск. Сбой базы не валит запуск: не открылась — файл переименовывается в
livecraft.sqlite3.broken-<DD-MM-YYYY_HHMMSS> (не удаляется) и создаётся новая; переименовать не вышло — работа без
записи; не записалось — WARNING и одна строка предупреждения за запуск, объект работает дальше. Только чтение
(--dry-run, --status) — на диск ничего не пишется: файла нет — пустая база в памяти. Отметки времени — по часам
программы (`Clock`, инвариант 4).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from app.core.clock import Clock
from app.core.dates import FILE_STAMP_FORMAT
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.records.record_event import RecordEvent
from app.records.record_meta import RecordMeta
from app.records.slot_record import RecordRow, SlotRecord, SlotStage
from app.ui.messages import msg

LOGGER: logging.Logger = get_logger(LogArea.RECORDS)

MEMORY_DATABASE: Final[str] = ":memory:"
READ_ONLY_URI: Final[str] = "file:{path}?mode=ro"
BROKEN_SUFFIX: Final[str] = ".broken-{stamp}"
SELECT_SQL: Final[str] = (
    "SELECT slot_id, youtube_channel_id, slot_start_utc, stage, updated_at, record_json"
    " FROM slots WHERE slot_id = ? AND youtube_channel_id = ?"
)
UPSERT_SQL: Final[str] = (
    "INSERT INTO slots (slot_id, youtube_channel_id, slot_start_utc, stage, updated_at, record_json)"
    " VALUES (?, ?, ?, ?, ?, ?)"
    " ON CONFLICT (slot_id, youtube_channel_id) DO UPDATE SET"
    " slot_start_utc = excluded.slot_start_utc, stage = excluded.stage,"
    " updated_at = excluded.updated_at, record_json = excluded.record_json"
)
DELETE_SQL: Final[str] = "DELETE FROM slots WHERE slot_start_utc < ?"


@dataclass
class RecordStore:
    """База памяти одного запуска. path — файл базы (None — только в памяти); is_new — файла не было."""

    connection: sqlite3.Connection
    path: Path | None
    is_new: bool
    is_read_only: bool
    created_utc: datetime                      # когда появилась память (aware UTC)
    warnings: list[str] = field(default_factory=list)
    is_write_failure_reported: bool = False
    is_closed: bool = False

    @classmethod
    def memory(cls, created_utc: datetime, path: Path | None = None, is_read_only: bool = False) -> RecordStore:
        """Пустая новая база в памяти: для тестов и для чтения без файла."""
        connection: sqlite3.Connection = sqlite3.connect(MEMORY_DATABASE)
        RecordMeta(connection, timezone.utc).create_schema()      # пояс не участвует: записей в новой базе нет
        return cls(connection, path, is_new=True, is_read_only=is_read_only, created_utc=created_utc)

    @classmethod
    def open(cls, path: Path, read_only: bool, clock: Clock) -> RecordStore:
        """База из файла; повреждённая — переименовывается, и создаётся новая."""
        if read_only:
            return cls._open_read_only(path, clock)
        try:
            return cls._connect(path, clock, is_new=not path.exists())
        except sqlite3.DatabaseError as error:
            return cls._replace_broken(path, clock, error)

    @classmethod
    def _connect(cls, path: Path, clock: Clock, is_new: bool) -> RecordStore:
        """Открыть на запись и проверить: не база — sqlite3.DatabaseError (соединение закрыто, файл можно переименовать)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection = sqlite3.connect(path)
        meta: RecordMeta = RecordMeta(connection, clock.zone)
        try:
            meta.create_schema()
            created_utc: datetime = meta.settled_created_utc(clock.now().astimezone(timezone.utc), is_new)
        except sqlite3.DatabaseError:
            connection.close()
            raise
        return cls(connection, path, is_new=is_new, is_read_only=False, created_utc=created_utc)

    @classmethod
    def _replace_broken(cls, path: Path, clock: Clock, error: sqlite3.DatabaseError) -> RecordStore:
        """Повреждённый файл — в .broken-<отметка>, новая база; переименовать не вышло — работа без записи."""
        renamed: Path = path.with_name(path.name + BROKEN_SUFFIX.format(stamp=clock.now().strftime(FILE_STAMP_FORMAT)))
        LogEvent.of(RecordEvent.BROKEN, path=path, renamed=renamed.name, error=error).emit(LOGGER, logging.WARNING)
        try:
            path.rename(renamed)
        except OSError as rename_error:
            LogEvent.of(RecordEvent.RENAME_FAILED, path=path, reason=rename_error).emit(LOGGER, logging.WARNING)
            return cls._unreadable(path, clock)
        store: RecordStore = cls._connect(path, clock, is_new=True)
        store.warnings.append(msg.RECORDS_BROKEN.format(path=path, renamed=renamed.name))
        return store

    @classmethod
    def _open_read_only(cls, path: Path, clock: Clock) -> RecordStore:
        """Ничего не пишет на диск: файла нет или в нём нет таблицы — пустая база в памяти; нет created_utc — по записям."""
        now_utc: datetime = clock.now().astimezone(timezone.utc)
        if not path.exists():
            return cls.memory(now_utc, path, is_read_only=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(READ_ONLY_URI.format(path=path.as_posix()), uri=True)
            meta: RecordMeta = RecordMeta(connection, clock.zone)
            if meta.has_slots:
                return cls(connection, path, is_new=False, is_read_only=True, created_utc=meta.created_utc(now_utc))
            connection.close()
            return cls.memory(now_utc, path, is_read_only=True)
        except sqlite3.DatabaseError as error:
            if connection is not None:
                connection.close()
            LogEvent.of(RecordEvent.BROKEN, path=path, renamed=None, error=error).emit(LOGGER, logging.WARNING)
            return cls._unreadable(path, clock)

    @classmethod
    def _unreadable(cls, path: Path, clock: Clock) -> RecordStore:
        """Файл памяти не читается: запуск идёт без записи, как при чтении без файла."""
        store: RecordStore = cls.memory(clock.now().astimezone(timezone.utc), path, is_read_only=True)
        store.warnings.append(msg.RECORDS_BROKEN_READ_ONLY.format(path=path))
        return store

    def take_warnings(self) -> list[str]:
        """Строки предупреждений для людей, накопленные с прошлого раза."""
        taken: list[str] = list(self.warnings)
        self.warnings.clear()
        return taken

    def find(self, slot_id: str, youtube_channel_id: str) -> SlotRecord | None:
        """Запись объекта; нет или чтение не удалось — None."""
        try:
            row: tuple[str, ...] | None = self.connection.execute(SELECT_SQL, (slot_id, youtube_channel_id)).fetchone()
        except sqlite3.Error as error:
            LogEvent.of(
                RecordEvent.READ_FAILED, slot_id=slot_id, youtube_channel_id=youtube_channel_id, reason=error
            ).emit(LOGGER, logging.WARNING)
            return None
        return None if row is None else SlotRecord.of(RecordRow(*row))

    def save(self, record: SlotRecord, requested: SlotStage | None = None) -> bool:
        """Upsert одной транзакцией; только чтение — ничего не пишет. Сбой — False и строка предупреждения один раз.

        requested — стадия, которую просил код; в лог идёт, если легла другая (стадия не откатывается).
        """
        if self.is_read_only:
            return False
        try:
            with self.connection:
                self.connection.execute(UPSERT_SQL, record.row.values)
        except (sqlite3.Error, OSError) as error:
            self._report_write_failure(record, error)
            return False
        record.saved_event(requested).emit(LOGGER)
        return True

    def delete_started_before(self, border_utc: datetime) -> int:
        """Записи слотов, начавшихся раньше границы; только чтение и сбой — 0."""
        if self.is_read_only:
            return 0
        try:
            with self.connection:
                removed: int = self.connection.execute(DELETE_SQL, (border_utc.isoformat(),)).rowcount
        except (sqlite3.Error, OSError) as error:
            LogEvent.of(RecordEvent.CLEAN_FAILED, reason=error).emit(LOGGER, logging.WARNING)
            return 0
        return max(removed, 0)

    def close(self) -> None:
        if self.is_closed:
            return
        self.is_closed = True
        self.connection.close()

    def _report_write_failure(self, record: SlotRecord, error: Exception) -> None:
        LogEvent.of(
            RecordEvent.WRITE_FAILED, slot_id=record.slot_id, youtube_channel_id=record.youtube_channel_id, reason=error
        ).emit(LOGGER, logging.WARNING)
        if self.is_write_failure_reported:
            return
        self.is_write_failure_reported = True
        self.warnings.append(msg.RECORDS_WRITE_FAILED.format(path=self.path or MEMORY_DATABASE, error=error))
