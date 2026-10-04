"""События плана и сверки в логе (CLAUDE.md §11): имена строк planers; канал — названием в кавычках и ником."""
from __future__ import annotations

from enum import Enum

from app.config.channel import ChannelConfig
from app.observability.log_event import LogEvent, Quoted


class PipelineEvent(str, Enum):
    SELECTION_DONE = "selection_done"
    PAIR_DECISION = "pair_decision"
    CHANNEL_SKIPPED_NOT_READY = "channel_skipped_not_ready"
    CHANNEL_UNAVAILABLE = "channel_unavailable"
    CHANNEL_PLACEHOLDERS = "channel_placeholders"
    THUMBNAIL_FROM_MEMORY = "thumbnail_from_memory"
    SPEC_FIELDS_NOT_COMPARED = "spec_fields_not_compared"
    BROADCAST_SETTING_NOT_FIXABLE = "broadcast_setting_not_fixable"
    BROADCAST_AMBIGUOUS = "broadcast_ambiguous"
    BROADCAST_MOVED = "broadcast_moved"

    def of(self, channel: ChannelConfig, **fields: object) -> LogEvent:
        """Строка события канала: название канала в кавычках, ник, затем поля события."""
        return LogEvent.of(self, channel=Quoted(channel.account_name), handle=channel.handle).extended(**fields)

    def of_slot(self, slot_id: str, channel: ChannelConfig, **fields: object) -> LogEvent:
        """Строка события эфира: slot_id, канал, затем поля события."""
        named: LogEvent = LogEvent.of(self, slot_id=slot_id, channel=Quoted(channel.account_name))
        return named.extended(handle=channel.handle, **fields)
