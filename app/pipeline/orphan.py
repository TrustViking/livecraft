"""Эфиры с меткой программы на площадке: сироты, перенесённые и скан каналов для --status (CLAUDE.md §6 инвариант 8).

Метка программы — slot_id в названии привязанного потока (`SlotKey.parse`). Эфир с меткой, которого не опознал ни
один объект: слота с такой меткой нет среди известных — сирота; слот известен, а эфир стоит на другой минуте —
«перенесён»: время менял владелец, программа эфир не трогает, но показывает в «Перенесён или отменён?». Эфир слота
этого запуска «по номерам» на своей минуте — «тексты не обновлялись»: тексты этого запуска на YouTube не идут
(§14 решение 32), на эфире прежние, программа его не трогает и называет в итоге эфиров. Эфир прошедшего слота на своей
минуте — не сирота. Известные слоты сверки — `KnownSlots`.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.config.channel import ChannelConfig
from app.core.dates import ISO_TIMESPEC, to_minute
from app.observability.log_event import LogEvent
from app.pipeline.event import PipelineEvent
from app.platforms.broadcast import UpcomingBroadcast
from app.platforms.error import PlatformError
from app.platforms.stream import StreamInfo
from app.slots.slot import SlotKey


class OrphanKind(str, Enum):
    """Почему эфир с меткой программы не опознан ни одним объектом."""

    ORPHAN = "orphan"   # слота с такой меткой нет среди известных
    MOVED = "moved"     # слот известен, а эфир стоит на другой минуте: время менял владелец
    KEPT = "kept"       # слот этого запуска «по номерам», эфир на своей минуте: тексты на YouTube прежние


@dataclass(frozen=True)
class KnownSlots:
    """Известные слоты сверки: `starts` — slot_id → старт всех слотов плана (будущих и прошедших); `numbered` —
    slot_id слотов этого запуска «по номерам»: их тексты на YouTube не идут."""

    starts: Mapping[str, datetime]
    numbered: frozenset[str] = frozenset()


@dataclass(frozen=True)
class OrphanBroadcast:
    """Эфир с меткой программы без своего объекта (`marked`) и почему его не опознал ни один объект."""

    marked: MarkedBroadcast
    kind: OrphanKind = OrphanKind.ORPHAN

    @property
    def channel(self) -> ChannelConfig:
        return self.marked.channel

    @property
    def broadcast(self) -> UpcomingBroadcast:
        return self.marked.broadcast

    @property
    def marker(self) -> str:
        return self.marked.marker

    @property
    def key(self) -> SlotKey:
        """Слот по метке: дата, время и язык для людей."""
        return self.marked.key

    @property
    def is_kept(self) -> bool:
        """Тексты не обновлялись: не сирота и не «перенесён или отменён?», а эфир в итоге."""
        return self.kind is OrphanKind.KEPT


@dataclass(frozen=True)
class MarkedBroadcast:
    """Эфир канала с меткой программы: поток и ключ слота по метке."""

    channel: ChannelConfig
    broadcast: UpcomingBroadcast
    stream: StreamInfo
    key: SlotKey

    @property
    def marker(self) -> str:
        return self.stream.title

    def orphan_kind(self, known: KnownSlots) -> OrphanKind | None:
        """Слота нет — сирота; слот известен, минута другая — перенесён; своя минута у слота «по номерам» — тексты
        не обновлялись; своя минута у прочих — не сирота."""
        slot_start: datetime | None = known.starts.get(self.marker)
        if slot_start is None:
            return OrphanKind.ORPHAN
        if to_minute(self.broadcast.start_utc) != to_minute(slot_start):
            return OrphanKind.MOVED
        return OrphanKind.KEPT if self.marker in known.numbered else None

    def orphan(self, kind: OrphanKind) -> OrphanBroadcast:
        return OrphanBroadcast(marked=self, kind=kind)

    def moved_event(self, slot_start: datetime) -> LogEvent:
        """Строка «перенесён»: минута эфира и минута слота в UTC."""
        return PipelineEvent.BROADCAST_MOVED.of_slot(
            self.marker,
            self.channel,
            broadcast_id=self.broadcast.broadcast_id,
            start=to_minute(self.broadcast.start_utc).isoformat(timespec=ISO_TIMESPEC),
            slot_start=to_minute(slot_start).isoformat(timespec=ISO_TIMESPEC),
        )


@dataclass(frozen=True)
class ChannelFailure:
    channel: ChannelConfig
    error: PlatformError


@dataclass(frozen=True)
class MarkedScan:
    """Все эфиры с меткой программы на каналах (--status) и каналы, которые не ответили."""

    broadcasts: tuple[MarkedBroadcast, ...]
    failures: tuple[ChannelFailure, ...]
