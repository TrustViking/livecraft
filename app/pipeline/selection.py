"""Отбор: слот → объекты запланированных эфиров по каналам своего языка (CLAUDE.md §3 шаг 8, §6 инвариант 0).

Два канала на один язык — два объекта (два эфира). Слот внутри min_lead_minutes не выбрасывается: у него есть канал,
значит есть и объект, просто с признаком too_late — иначе его ключ пропал бы из keys.txt ровно перед эфиром. Объект
рождается только из слота, канала и формы ключей этого слота (`PackageSlot`: в режиме Б — форма его пакета, в режиме
А — форма настроек): о прошлых запусках ему нечего помнить. Обложки — у самого слота.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from app.config.channel import ChannelConfig
from app.config.settings import LivecraftSettings
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.packages.package_slot import PackageSlot
from app.pipeline.decision import Decision
from app.pipeline.event import PipelineEvent
from app.pipeline.plan import PlannedBroadcast
from app.platforms.limits import PlatformLimits
from app.platforms.spec import BroadcastSpec
from app.slots.slot import StreamSlot

LOGGER = get_logger(LogArea.PIPELINE)


class SkipReason(str, Enum):
    NO_CHANNEL = "no_channel"  # язык слота не обслуживает ни один канал channels.json


@dataclass(frozen=True)
class SkippedSlot:
    slot: StreamSlot
    reason: SkipReason


@dataclass(frozen=True)
class SelectionRequest:
    """Из чего отбор строит объекты: слоты с формой ключей каждого, каналы, настройки, пределы площадки и «сейчас»."""

    slots: tuple[PackageSlot, ...]
    channels: tuple[ChannelConfig, ...]
    settings: LivecraftSettings
    limits: PlatformLimits
    now: datetime

    def channels_for(self, slot: StreamSlot) -> tuple[ChannelConfig, ...]:
        """Каналы, которые обслуживают язык слота."""
        return tuple(channel for channel in self.channels if slot.language in channel.languages)

    def is_too_late(self, slot: StreamSlot) -> bool:
        """До старта меньше min_lead_minutes."""
        return slot.start - self.now < timedelta(minutes=self.settings.min_lead_minutes)

    def planned(self, entry: PackageSlot, channel: ChannelConfig) -> PlannedBroadcast:
        """Объект эфира слота на канале с формой ключей слота; спека — из слота, канала, настроек и пределов
        площадки."""
        slot: StreamSlot = entry.slot
        is_too_late: bool = self.is_too_late(slot)
        return PlannedBroadcast(
            slot=slot,
            channel=channel,
            form=entry.form,
            expected=BroadcastSpec.from_slot(slot, self.limits, channel, self.settings),
            is_too_late=is_too_late,
            decision=Decision.TOO_LATE if is_too_late else Decision.CREATE,
        )


@dataclass(frozen=True)
class Selection:
    """Объекты по порядку слотов (`SlotKey.sort_key`) и названию канала; слоты без канала своего языка — отдельно."""

    planned: tuple[PlannedBroadcast, ...]
    skipped: tuple[SkippedSlot, ...]

    @classmethod
    def of(cls, request: SelectionRequest) -> Selection:
        planned: list[PlannedBroadcast] = []
        skipped: list[SkippedSlot] = []
        for entry in sorted(request.slots, key=lambda item: item.slot.key.sort_key):
            channels: tuple[ChannelConfig, ...] = request.channels_for(entry.slot)
            if not channels:
                skipped.append(SkippedSlot(entry.slot, SkipReason.NO_CHANNEL))
            planned.extend(request.planned(entry, channel) for channel in channels)
        planned.sort(key=lambda item: (*item.slot.key.sort_key, item.channel.account_name))
        selection: Selection = cls(planned=tuple(planned), skipped=tuple(skipped))
        selection.done_event.emit(LOGGER)
        return selection

    @property
    def done_event(self) -> LogEvent:
        too_late: int = sum(1 for item in self.planned if item.is_too_late)
        done: LogEvent = LogEvent.of(PipelineEvent.SELECTION_DONE, planned=len(self.planned), too_late=too_late)
        return done.extended(skipped=len(self.skipped))
