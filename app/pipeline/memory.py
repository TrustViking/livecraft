"""Память программы глазами одного эфира: прошлая запись, подтверждение этого запуска, обложка (CLAUDE.md §6
инварианты 0, 1a).

Из памяти читаются только результаты прошлых запусков — главное, какую тройку «ключ, форма, ответы» форма уже
подтвердила; задания из памяти не берутся. Моменты — DD-MM-YYYY HH:MM по часам программы (инвариант 4).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar

from app.core.clock import Clock
from app.core.dates import format_datetime_text
from app.core.youtube_video import YouTubeVideoId
from app.pipeline.match import BroadcastMatch
from app.platforms.broadcast import CreatedBroadcast
from app.records.record_results import RecordResults
from app.records.slot_record import SlotRecord, SlotStage


class RecordChannelMissing(ValueError):
    """Запись без id канала на YouTube: канал не подтверждён, а запись просят. Ошибка программы, а не площадки."""

    TEXT: ClassVar[str] = "no YouTube channel id for {slot_id}"

    def __init__(self, slot_id: str) -> None:
        super().__init__(self.TEXT.format(slot_id=slot_id))


@dataclass(frozen=True)
class ReplacedBroadcast:
    """Прежний эфир программы этого слота, чей ключ форма уже подтвердила, а этот запуск поставил новый.

    В форме на дату слота теперь два ключа: действующий — нового эфира, прежний — этого.
    """

    broadcast_id: str
    broadcast_url: str
    stream_key: str      # прежний подтверждённый формой ключ (полностью; вывод маскирует)


@dataclass
class BroadcastMemory:
    """Изменяемый намеренно: запуск дописывает подтверждение, обложку и новую запись.

    `record` — последняя записанная: прочитанная из памяти или записанная этим запуском; `confirmed` — подтверждение
    этого запуска (иначе — из записи); `thumbnail_broadcast_id` и `thumbnail_set_at` — обложка, поставленная этим
    запуском; `replaced` — эфир создан заново, а память помнила другой с подтверждённым ключом.
    """

    record: SlotRecord | None = None
    confirmed: RecordResults | None = None
    thumbnail_broadcast_id: str | None = None
    thumbnail_set_at: str | None = None
    replaced: ReplacedBroadcast | None = None

    @property
    def results(self) -> RecordResults:
        """Результаты, которые знает объект: подтверждение этого запуска, иначе — из записи."""
        if self.confirmed is not None:
            return self.confirmed
        return RecordResults() if self.record is None else self.record.results

    @property
    def recorded_stage(self) -> SlotStage | None:
        """Стадия последней записи объекта; записи нет — None."""
        return None if self.record is None else self.record.stage

    @property
    def recorded_thumbnail(self) -> str | None:
        """Эфир, которому по записи памяти обложку ставила программа."""
        return None if self.record is None else self.record.results.thumbnail_broadcast_id

    def remember_replaced(self, created: CreatedBroadcast) -> ReplacedBroadcast | None:
        """Эфир создан этим запуском, а запись памяти помнит другой эфир программы с подтверждённым ключом.

        Снимается сразу после создания, до того как новая запись памяти заменит прежнюю.
        """
        if self.record is None:
            return None
        previous: RecordResults = self.record.results
        is_other: bool = bool(previous.broadcast_id) and previous.broadcast_id != created.broadcast_id
        if not is_other or not previous.confirmed_stream_key:
            return None
        self.replaced = ReplacedBroadcast(
            broadcast_id=previous.broadcast_id,
            broadcast_url=previous.broadcast_url or YouTubeVideoId(previous.broadcast_id).watch_url,
            stream_key=previous.confirmed_stream_key,
        )
        return self.replaced

    def remember_thumbnail(self, broadcast_id: str, clock: Clock) -> None:
        """Обложка эфира поставлена: факт уйдёт в память и переживёт задержку картинки на площадке."""
        self.thumbnail_broadcast_id = broadcast_id
        self.thumbnail_set_at = format_datetime_text(clock.now())

    def record_to_save(self, record: SlotRecord) -> SlotRecord | None:
        """Новая запись объекта; None — она не отличается от последней записанной (кроме updated_at)."""
        return None if record.has_same_content(self.record) else record

    def remember_record(self, record: SlotRecord) -> None:
        """Записанное становится последней записью объекта: с ней сравнивается следующая."""
        self.record = record

    def record_results(self, match: BroadcastMatch, moment: str) -> RecordResults:
        """Результаты для записи на момент `moment`: эфир, поток и ключ этого запуска и обложка этого запуска."""
        return self._thumbnail_results(self._published_results(match, moment), match)

    def _published_results(self, match: BroadcastMatch, moment: str) -> RecordResults:
        """Эфир, поток и ключ, взятые с площадки; ключа нет — прежние из записи. Новый ключ опубликован в `moment`."""
        results: RecordResults = self.results
        key: CreatedBroadcast | None = match.key
        if key is None or not key.stream_key:
            return results
        is_same_key: bool = results.stream_key == key.stream_key and results.published_at is not None
        return replace(
            results,
            broadcast_id=key.broadcast_id,
            broadcast_url=key.broadcast_url,
            stream_id=key.stream_id,
            stream_url=key.stream_url,
            stream_key=key.stream_key,
            published_at=results.published_at if is_same_key else moment,
        )

    def _thumbnail_results(self, results: RecordResults, match: BroadcastMatch) -> RecordResults:
        """Обложка этого запуска — в запись; прежняя переносится, пока эфир тот же."""
        if self.thumbnail_broadcast_id is not None:
            return replace(
                results, thumbnail_broadcast_id=self.thumbnail_broadcast_id, thumbnail_set_at=self.thumbnail_set_at
            )
        current: str | None = match.broadcast_id
        if current is not None and results.thumbnail_broadcast_id not in (None, current):
            return replace(results, thumbnail_broadcast_id=None, thumbnail_set_at=None)
        return results
