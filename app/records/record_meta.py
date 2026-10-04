"""Схема памяти программы и строка meta «когда появилась память» (CLAUDE.md §6 инварианты 0, 1a).

Таблица slots — одна строка на (slot_id, youtube_channel_id); таблица meta — schema_version и created_utc (ISO-8601
UTC): эфиры с меткой программы, созданные на площадке раньше, считаются уже переданными стримеру. У базы без
created_utc отметка ставится при первом открытии на запись: в базе уже есть записи — самым ранним updated_at (память
старше этого открытия), база пустая — текущим моментом. updated_at разбирается по поясу программы, а не машины: иначе
на машине в другом поясе граница сдвинулась бы.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from enum import Enum
from typing import Final

from app.core.dates import parse_datetime_text
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.records.record_event import RecordEvent

LOGGER: logging.Logger = get_logger(LogArea.RECORDS)

SCHEMA_VERSION: Final[str] = "1"
SCHEMA_SQL: Final[tuple[str, ...]] = (
    "CREATE TABLE IF NOT EXISTS slots ("
    " slot_id TEXT NOT NULL, youtube_channel_id TEXT NOT NULL, slot_start_utc TEXT NOT NULL,"
    " stage TEXT NOT NULL, updated_at TEXT NOT NULL, record_json TEXT NOT NULL,"
    " PRIMARY KEY (slot_id, youtube_channel_id))",
    "CREATE INDEX IF NOT EXISTS slots_start ON slots (slot_start_utc)",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)
# Номер схемы поднимается и у существующей базы (строки slots не трогаются).
UPSERT_META_SQL: Final[str] = (
    "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value"
)
INSERT_META_SQL: Final[str] = "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)"
SELECT_META_SQL: Final[str] = "SELECT value FROM meta WHERE key = ?"
HAS_SLOTS_SQL: Final[str] = "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'slots'"
SELECT_UPDATED_AT_SQL: Final[str] = "SELECT updated_at FROM slots"


class MetaKey(str, Enum):
    """Строки таблицы meta."""

    SCHEMA_VERSION = "schema_version"
    CREATED_UTC = "created_utc"


class CreatedSource(str, Enum):
    """Откуда взялась отметка «когда появилась память» — поле source= строки лога."""

    RECORDS = "min_updated_at"     # самый ранний updated_at записей
    NOW = "now"                    # записей нет — текущий момент


@dataclass(frozen=True)
class CreatedMoment:
    """Когда появилась память (aware UTC) и откуда это известно."""

    value: datetime
    source: CreatedSource


@dataclass(frozen=True)
class RecordMeta:
    """Схема базы памяти и отметка created_utc; `zone` — пояс программы, в нём записан updated_at."""

    connection: sqlite3.Connection
    zone: tzinfo

    def create_schema(self) -> None:
        with self.connection:
            for statement in SCHEMA_SQL:
                self.connection.execute(statement)
            self.connection.execute(UPSERT_META_SQL, (MetaKey.SCHEMA_VERSION.value, SCHEMA_VERSION))

    @property
    def has_slots(self) -> bool:
        """В базе есть таблица slots: без неё база только для чтения — пустая."""
        return self.connection.execute(HAS_SLOTS_SQL).fetchone() is not None

    def created_utc(self, now_utc: datetime) -> datetime:
        """Когда появилась память — без записи в базу: из meta, иначе по записям или `now_utc`."""
        stored: datetime | None = self._stored()
        return stored if stored is not None else self._initial(now_utc).value

    def settled_created_utc(self, now_utc: datetime, is_new: bool) -> datetime:
        """Когда появилась память; нет в meta — отметка пишется (у существующей базы — строкой лога с источником)."""
        stored: datetime | None = self._stored()
        if stored is not None:
            return stored
        initial: CreatedMoment = self._initial(now_utc)
        with self.connection:
            self.connection.execute(INSERT_META_SQL, (MetaKey.CREATED_UTC.value, initial.value.isoformat()))
        if not is_new:
            LogEvent.of(
                RecordEvent.CREATED_UTC_INITIALIZED, value=initial.value.isoformat(), source=initial.source
            ).emit(LOGGER)
        return initial.value

    def _stored(self) -> datetime | None:
        """created_utc из meta; нет строки или она не разбирается — None."""
        row: tuple[str, ...] | None = self.connection.execute(SELECT_META_SQL, (MetaKey.CREATED_UTC.value,)).fetchone()
        if row is None:
            return None
        try:
            parsed: datetime = datetime.fromisoformat(row[0])
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def _initial(self, now_utc: datetime) -> CreatedMoment:
        """Отметка «сейчас» у непустой базы сдвинула бы границу вперёд и молча записала бы ключи эфиров, созданных
        после настоящего появления памяти, как уже переданные стримеру — поэтому по самой ранней записи."""
        moments: list[datetime] = []
        for (text,) in self.connection.execute(SELECT_UPDATED_AT_SQL):
            try:
                moments.append(parse_datetime_text(text, self.zone).astimezone(timezone.utc))
            except ValueError:
                continue            # неразборчивая строка — не повод сдвигать отметку
        if moments:
            return CreatedMoment(min(moments), CreatedSource.RECORDS)
        return CreatedMoment(now_utc, CreatedSource.NOW)
