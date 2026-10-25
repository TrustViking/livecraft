"""События площадки YouTube в логе (CLAUDE.md §11): имена строк planers, канал — названием в кавычках и ником.

Ключ потока в строках лога — только маской `mask_stream_key` (§6 инвариант 6).
"""
from __future__ import annotations

from enum import Enum

from app.config.channel import ChannelConfig
from app.observability.log_event import LogEvent, Quoted
from app.platforms.youtube_operation import YouTubeOperation


class YouTubeEvent(str, Enum):
    CHANNEL_DESCRIBED = "channel_described"
    BROADCASTS_LISTED = "broadcasts_listed"
    BROADCAST_WITHOUT_START = "broadcast_without_start"
    BROADCAST_INSERTED = "broadcast_inserted"
    PLACEHOLDER_CAPTURED = "thumbnail_placeholder_captured"
    BROADCAST_UPDATED = "broadcast_updated"
    VIDEO_SETTINGS_APPLIED = "video_settings_applied"
    STREAM_MARKER_SET = "stream_marker_set"
    STREAM_KEY_REJECTED = "stream_key_rejected"
    STREAM_KEY_UNEXPECTED = "stream_key_unexpected_format"
    STREAM_BOUND = "stream_bound"
    THUMBNAIL_SET = "thumbnail_set"
    PICTURE_UNAVAILABLE = "thumbnail_picture_unavailable"
    TOKEN_CREATED = "token_created"
    LOGIN_DROPPED = "login_dropped"
    CALL = "youtube_call"
    REQUEST_SKIPPED = "request_skipped"
    REQUEST_RETRY = "request_retry"
    REFUSED = "youtube_refused"
    READ_NOT_LISTED = "read_not_listed"

    def of(self, channel: ChannelConfig, **fields: object) -> LogEvent:
        """Строка события канала: название канала в кавычках, ник, затем поля события."""
        return LogEvent.of(self, channel=Quoted(channel.account_name), handle=channel.handle).extended(**fields)

    def of_operation(self, operation: YouTubeOperation, channel: ChannelConfig, **fields: object) -> LogEvent:
        """Строка события обращения: операция первой, затем канал и поля события."""
        event: LogEvent = LogEvent.of(self, operation=operation, channel=Quoted(channel.account_name))
        return event.extended(handle=channel.handle, **fields)

    def of_call(self, operation: YouTubeOperation, channel: ChannelConfig, attempts: int, **fields: object) -> LogEvent:
        """Строка обращения с попытками и единицами квоты: цена операции на число попыток (§9)."""
        return self.of_operation(operation, channel, **fields).extended(
            attempts=attempts, units=attempts * operation.quota_units
        )
