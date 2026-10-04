"""Запланированные эфиры одного канала глазами сверки (CLAUDE.md §6 инвариант 1).

Эфир опознаётся по минуте старта UTC и метке программы в названии привязанного потока: своя метка — он; метка другого
слота — мимо; без метки — только один на минуту, иначе все они неразличимы (AMBIGUOUS). Потоки читаются не больше раза
на (канал, поток) за запуск (`StreamReader`): опознание, заглушки обложки и сироты идут через один кеш.
Заглушки обложки канала — отпечатки из описаний потоков (`PlaceholderMark.found_in`) и картинки, повторённые у
нескольких эфиров канала: картинка эфира из них — своей обложки нет.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Final

from app.config.channel import ChannelConfig
from app.core.dates import to_minute
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.pipeline.event import PipelineEvent
from app.pipeline.orphan import MarkedBroadcast, OrphanBroadcast, OrphanKind
from app.platforms.base import BroadcastPlatform
from app.platforms.broadcast import UpcomingBroadcast
from app.platforms.placeholder import PlaceholderMark
from app.platforms.stream import StreamInfo
from app.slots.slot import SlotKey

LOGGER = get_logger(LogArea.PIPELINE)
# Картинка, одинаковая у стольких эфиров одного канала, — заглушка канала, а не своя обложка.
PLACEHOLDER_DUPLICATE_MIN: Final[int] = 2


@dataclass
class StreamReader:
    """Потоки площадки за запуск по (ключ канала, id потока); None — потока нет."""

    platform: BroadcastPlatform
    streams: dict[tuple[str, str], StreamInfo | None] = field(default_factory=dict)

    def stream(self, channel: ChannelConfig, stream_id: str | None) -> StreamInfo | None:
        if stream_id is None:
            return None
        cache_key: tuple[str, str] = (channel.key, stream_id)
        if cache_key not in self.streams:
            self.streams[cache_key] = self.platform.get_stream(channel, stream_id)
        return self.streams[cache_key]


@dataclass(frozen=True)
class CandidatePick:
    """Итог опознания на минуту старта: найденный эфир и его поток или все неразличимые кандидаты."""

    broadcast: UpcomingBroadcast | None = None
    stream: StreamInfo | None = None
    ambiguous: tuple[UpcomingBroadcast, ...] = ()   # два и более эфира без метки

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous)


@dataclass(frozen=True)
class ChannelUpcoming:
    """Запланированные эфиры канала, прочитанные этим запуском; метки читаются в поясе программы."""

    channel: ChannelConfig
    broadcasts: tuple[UpcomingBroadcast, ...]
    reader: StreamReader
    zone: tzinfo

    def stream(self, broadcast: UpcomingBroadcast) -> StreamInfo | None:
        return self.reader.stream(self.channel, broadcast.stream_id)

    def pick(self, slot_id: str, start_minute: datetime) -> CandidatePick:
        """Свой slot_id в метке → он; метка другого слота — мимо; без метки — только один, иначе все неразличимы."""
        unmarked: list[CandidatePick] = []
        for broadcast in self.broadcasts:
            if to_minute(broadcast.start_utc) != start_minute:
                continue
            stream: StreamInfo | None = self.stream(broadcast)
            marker: str | None = None if stream is None else stream.title
            if marker == slot_id:
                return CandidatePick(broadcast=broadcast, stream=stream)
            if marker is None or SlotKey.parse(marker, self.zone) is None:
                unmarked.append(CandidatePick(broadcast=broadcast, stream=stream))
        if len(unmarked) > 1:
            return CandidatePick(ambiguous=tuple(pick.broadcast for pick in unmarked if pick.broadcast is not None))
        return unmarked[0] if unmarked else CandidatePick()

    def find_placeholders(self) -> frozenset[str]:
        """Отпечатки заглушек обложки канала; одинаковая картинка на разных каналах дублем не считается."""
        from_streams: set[str] = set()
        for broadcast in self.broadcasts:
            stream: StreamInfo | None = self.stream(broadcast)
            mark: PlaceholderMark | None = None if stream is None else PlaceholderMark.found_in(stream.description)
            if mark is not None:
                from_streams.add(mark.sha)
        counts: Counter[str] = Counter(
            broadcast.thumbnail_sha for broadcast in self.broadcasts if broadcast.thumbnail_sha is not None
        )
        from_duplicates: set[str] = {sha for sha, count in counts.items() if count >= PLACEHOLDER_DUPLICATE_MIN}
        found: LogEvent = PipelineEvent.CHANNEL_PLACEHOLDERS.of(self.channel, from_streams=sorted(from_streams))
        found.extended(from_duplicates=sorted(from_duplicates)).emit(LOGGER)
        return frozenset(from_streams | from_duplicates)

    def marked(self) -> tuple[MarkedBroadcast, ...]:
        """Эфиры канала с меткой программы."""
        marked: list[MarkedBroadcast] = []
        for broadcast in self.broadcasts:
            stream: StreamInfo | None = self.stream(broadcast)
            key: SlotKey | None = None if stream is None else SlotKey.parse(stream.title, self.zone)
            if stream is not None and key is not None:
                marked.append(MarkedBroadcast(channel=self.channel, broadcast=broadcast, stream=stream, key=key))
        return tuple(marked)

    def orphans(self, known_slots: Mapping[str, datetime], shown_ids: frozenset[str]) -> tuple[OrphanBroadcast, ...]:
        """Эфиры с меткой программы без своего объекта; уже показанные в других разделах — не повторяются."""
        orphans: list[OrphanBroadcast] = []
        for marked in self.marked():
            kind: OrphanKind | None = marked.orphan_kind(known_slots)
            if marked.broadcast.broadcast_id in shown_ids or kind is None:
                continue
            orphans.append(marked.orphan(kind))
            if kind is OrphanKind.MOVED:
                marked.moved_event(known_slots[marked.marker]).emit(LOGGER)
        return tuple(orphans)
