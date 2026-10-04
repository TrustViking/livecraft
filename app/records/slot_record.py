"""Запись объекта запланированного эфира в памяти программы: что уже сделано на YouTube и в форме (CLAUDE.md §6).

Одна запись на (slot_id, youtube_channel_id): запись привязана к id канала на YouTube, а не к нику. Колонки поиска —
slot_start_utc (ISO-8601 UTC, только для сравнения моментов), stage, updated_at (DD-MM-YYYY HH:MM по поясу программы,
инвариант 4); поля объекта — одним JSON:

    {"schema": 1, "snapshot": {…}, "results": {…}}

snapshot — для людей и разбора, обратно не читается; results — единственное, что читается обратно (`RecordResults`).
Другой номер schema не ошибка — читаются те же имена полей.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, astuple, dataclass, field, replace
from enum import Enum
from typing import Final

from app.observability.log_event import LogEvent
from app.observability.logging_setup import mask_stream_key
from app.records.record_event import RecordEvent
from app.records.record_results import RecordResults

RECORD_SCHEMA: Final[int] = 1


class RecordKey(str, Enum):
    """Ключи верхнего уровня JSON записи."""

    SCHEMA = "schema"
    SNAPSHOT = "snapshot"
    RESULTS = "results"


class SlotStage(str, Enum):
    """Докуда дошёл объект; порядок стадий — порядок членов: ADMITTED < PUBLISHED < KEY_CONFIRMED."""

    ADMITTED = "admitted"            # допущен, записан до действий
    PUBLISHED = "published"          # эфир и ключ взяты с площадки
    KEY_CONFIRMED = "key_confirmed"  # форма подтвердила текущий ключ

    @property
    def rank(self) -> int:
        """Чтобы запись не откатывалась ниже уже достигнутого для того же ключа."""
        return list(SlotStage).index(self)

    @classmethod
    def of(cls, value: str) -> SlotStage:
        """Стадия из колонки stage; неизвестная — ADMITTED."""
        try:
            return cls(value)
        except ValueError:
            return cls.ADMITTED


@dataclass(frozen=True)
class RecordSnapshot:
    """Для людей и разбора: пишется, обратно не читается. Даты DD-MM-YYYY, время HH:MM по поясу программы."""

    date: str
    time: str
    language: str
    account_name: str
    handle: str
    title: str
    form_url: str
    decision: str
    admission_reasons: tuple[str, ...] = ()
    last_error: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecordRow:
    """Строка таблицы slots: колонки в порядке SQL-запросов памяти."""

    slot_id: str
    youtube_channel_id: str
    slot_start_utc: str
    stage: str
    updated_at: str
    record_json: str

    @property
    def values(self) -> tuple[str, ...]:
        """Значения колонок по порядку — параметры запроса."""
        return astuple(self)

    def has_same_content(self, other: RecordRow) -> bool:
        """Всё, кроме updated_at, как у другой строки."""
        return replace(self, updated_at=other.updated_at) == other


@dataclass(frozen=True)
class SlotRecord:
    """Запись объекта: ключ, стадия, момент записи, результаты и снимок для людей."""

    slot_id: str
    youtube_channel_id: str
    slot_start_utc: str          # ISO-8601 UTC — только для сравнения моментов
    stage: SlotStage
    updated_at: str              # DD-MM-YYYY HH:MM по поясу программы
    results: RecordResults
    snapshot: RecordSnapshot | None = None   # None — запись прочитана из памяти (снимок обратно не читается)
    stored: RecordRow | None = field(default=None, compare=False, repr=False)   # строка, как она лежит в памяти

    @classmethod
    def of(cls, row: RecordRow) -> SlotRecord:
        """Из строки таблицы: обратно — только results; неизвестная стадия — ADMITTED, непонятный JSON — пустые результаты."""
        try:
            payload: object = json.loads(row.record_json)
        except ValueError:
            payload = None
        results: object = payload.get(RecordKey.RESULTS.value) if isinstance(payload, Mapping) else None
        return cls(
            slot_id=row.slot_id,
            youtube_channel_id=row.youtube_channel_id,
            slot_start_utc=row.slot_start_utc,
            stage=SlotStage.of(row.stage),
            updated_at=row.updated_at,
            results=RecordResults.from_data(results),
            stored=row,
        )

    @property
    def row(self) -> RecordRow:
        """Строка, которую запись кладёт в память."""
        return RecordRow(
            self.slot_id, self.youtube_channel_id, self.slot_start_utc, self.stage.value, self.updated_at, self.record_json()
        )

    def record_json(self) -> str:
        payload: dict[str, object] = {
            RecordKey.SCHEMA.value: RECORD_SCHEMA,
            RecordKey.SNAPSHOT.value: asdict(self.snapshot) if self.snapshot is not None else {},
            RecordKey.RESULTS.value: self.results.to_data(),
        }
        return json.dumps(payload, ensure_ascii=False)

    def has_same_content(self, other: SlotRecord | None) -> bool:
        """Запись не изменилась: всё, кроме updated_at, как у последней записанной (из памяти или этим запуском).

        У записи из памяти снимка нет — сравнивается строка, как она лежит в памяти.
        """
        if other is None:
            return False
        return self.row.has_same_content(other.stored or other.row)

    def saved_event(self, requested: SlotStage | None) -> LogEvent:
        """Строка «запись легла»: ключ потока — маской; requested — если легла не та стадия, которую просил код."""
        event: LogEvent = LogEvent.of(
            RecordEvent.SAVED, slot_id=self.slot_id, youtube_channel_id=self.youtube_channel_id, stage=self.stage
        )
        if self.results.stream_key is not None:
            event = event.extended(stream_key=mask_stream_key(self.results.stream_key))
        if requested is not None and requested is not self.stage:
            event = event.extended(requested=requested)
        return event
