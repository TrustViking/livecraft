"""Память программы глазами прогона части «эфиры» (CLAUDE.md §6 инварианты 0, 1a, 10).

Из памяти объект получает только свою последнюю запись — результаты прошлых запусков; задания из неё не берутся.
Пишется запись, только если она изменилась (`BroadcastMemory.record_to_save`); канал без id YouTube — записи нет.
Полный запуск чистит записи слотов старше keep_days.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.broadcasts.event import BroadcastsEvent
from app.core.clock import Clock
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.pipeline.plan import PlannedBroadcast
from app.records.record_results import RecordResults
from app.records.record_store import RecordStore
from app.records.slot_record import SlotRecord, SlotStage

LOGGER = get_logger(LogArea.BROADCASTS)


@dataclass(frozen=True)
class RecordKeeper:
    """Память запуска и часы программы: момент записи — по часам в момент события."""

    store: RecordStore
    clock: Clock

    def load(self, planned: Sequence[PlannedBroadcast]) -> None:
        """Каждому объекту подтверждённого канала — его запись из памяти."""
        for item in planned:
            channel_id: str | None = item.admission.channel_id
            found: SlotRecord | None = None if channel_id is None else self.store.find(item.slot.slot_id, channel_id)
            if found is not None:
                item.memory.remember_record(found)

    def results_of(self, slot_id: str, channel_id: str | None) -> RecordResults:
        """--status: что память знает об эфире слота на канале (строка «форма» keys.txt); канал без id или записи
        нет — ничего."""
        found: SlotRecord | None = None if channel_id is None else self.store.find(slot_id, channel_id)
        return RecordResults() if found is None else found.results

    def save(self, item: PlannedBroadcast, stage: SlotStage) -> None:
        """Запись объекта, если она изменилась; сбой базы — предупреждение хранилища, объект идёт дальше."""
        channel_id: str | None = item.admission.channel_id
        if channel_id is None:
            return
        record: SlotRecord | None = item.memory.record_to_save(item.to_record(self.clock, stage))
        if record is None:
            stored: SlotStage = item.memory.recorded_stage or stage
            unchanged: LogEvent = BroadcastsEvent.RECORD_UNCHANGED.of(item, youtube_channel_id=channel_id, stage=stored)
            unchanged.emit(LOGGER, logging.DEBUG)
            return
        if self.store.save(record, requested=stage):
            item.memory.remember_record(record)

    def clean(self, keep_days: int) -> None:
        """Записи слотов старше keep_days — тот же срок, что у файлов программы."""
        border: datetime = (self.clock.now() - timedelta(days=keep_days)).astimezone(timezone.utc)
        removed: int = self.store.delete_started_before(border)
        LogEvent.of(BroadcastsEvent.RECORDS_CLEANED, removed=removed).emit(LOGGER)
