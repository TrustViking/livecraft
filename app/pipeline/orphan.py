"""Эфиры с меткой программы на площадке: сироты, перенесённые и скан каналов для --status (CLAUDE.md §6 инвариант 8).

Метка программы — slot_id в названии привязанного потока (`SlotKey.parse`). Эфир с меткой, которого не опознал ни
один объект: слота с такой меткой нет среди известных — сирота; слот известен, а эфир стоит на другой минуте —
«перенесён»: время менял владелец, программа эфир не трогает, но показывает в «Перенесён или отменён?». Эфир прошедшего
слота на своей минуте — не сирота.
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


@dataclass(frozen=True)
class OrphanBroadcast:
    """Эфир с меткой программы без своего объекта: `key` — слот по метке (дата, время и язык для людей)."""

    channel: ChannelConfig
    broadcast: UpcomingBroadcast
    marker: str
    key: SlotKey
    kind: OrphanKind = OrphanKind.ORPHAN


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

    def orphan_kind(self, known_slots: Mapping[str, datetime]) -> OrphanKind | None:
        """Слота нет — сирота; слот известен, минута другая — перенесён; своя минута — не сирота."""
        slot_start: datetime | None = known_slots.get(self.marker)
        if slot_start is None:
            return OrphanKind.ORPHAN
        if to_minute(self.broadcast.start_utc) != to_minute(slot_start):
            return OrphanKind.MOVED
        return None

    def orphan(self, kind: OrphanKind) -> OrphanBroadcast:
        return OrphanBroadcast(
            channel=self.channel, broadcast=self.broadcast, marker=self.marker, key=self.key, kind=kind
        )

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
