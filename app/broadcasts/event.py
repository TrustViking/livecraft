"""События части «эфиры» в логе (CLAUDE.md §11): имена строк planers; эфир — slot_id, названием канала и ником.

Канал в строке — значения после фазы входов (§14 решение 25); ключ потока — только маской (инвариант 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.config.channel import ChannelConfig
from app.observability.log_event import LogEvent, Quoted
from app.pipeline.plan import PlannedBroadcast
from app.platforms.broadcast import BroadcastFacts


class BroadcastsEvent(str, Enum):
    SLOT_ADMITTED = "slot_admitted"
    SLOT_NOT_ADMITTED = "slot_not_admitted"
    SLOT_NOT_ADMITTED_REASON = "slot_not_admitted_reason"
    RECORD_UNCHANGED = "record_unchanged"
    RECORDS_CLEANED = "records_cleaned"
    BROADCAST_CREATED = "broadcast_created"
    BROADCAST_REPLACED = "broadcast_replaced"
    STREAM_ATTACHED = "stream_attached"
    BROADCAST_UPDATED = "broadcast_updated"
    VIDEO_FIELDS_FIXED = "video_fields_fixed"
    VIDEO_SETTINGS_FAILED = "video_settings_failed"
    FACTS_READ_FAILED = "facts_read_failed"
    THUMBNAIL_FAILED = "thumbnail_failed"
    FORM_SEND_SKIPPED = "form_send_skipped"
    FORM_SEND = "form_send"
    PAIR_FAILED = "pair_failed"
    BROADCAST_EXPECTED = "broadcast_expected"
    BROADCAST_FOUND = "broadcast_found"
    BROADCAST_FACTS = "broadcast_facts"

    def of(self, item: PlannedBroadcast, **fields: object) -> LogEvent:
        """Строка события эфира: slot_id, канал в кавычках, ник, затем поля события."""
        channel: ChannelConfig = item.admission.channel_config(item.channel)
        named: LogEvent = LogEvent.of(self, slot_id=item.slot.slot_id, channel=Quoted(channel.account_name))
        return named.extended(handle=channel.handle, **fields)


@dataclass(frozen=True)
class FactsLog:
    """Что лежит на площадке после действий — полями строки лога `broadcast_facts`."""

    facts: BroadcastFacts

    def logged(self, event: LogEvent) -> LogEvent:
        facts: BroadcastFacts = self.facts
        return event.extended(
            privacy=facts.privacy_status,
            made_for_kids=facts.made_for_kids,
            age_restricted=facts.age_restricted,
            default_language=facts.default_language,
            default_audio_language=facts.default_audio_language,
            category_id=facts.category_id,
            bound_stream_id=facts.bound_stream_id,
            stream_marker=facts.stream_marker,
            auto_start=facts.auto_start,
            auto_stop=facts.auto_stop,
            latency=facts.latency_preference,
        )
