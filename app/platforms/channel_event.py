"""События каналов и паспорта каналов в логе (CLAUDE.md §11): имена строк planers, канал — названием в кавычках и ником."""
from __future__ import annotations

from enum import Enum

from app.config.channel import ChannelConfig
from app.observability.log_event import LogEvent, Quoted


class ChannelEvent(str, Enum):
    CHANNEL_REFUSED = "channel_refused"
    LOGIN_PHASE_DONE = "login_phase_done"
    LOGIN_STARTED = "login_started"
    LOGIN_FAILED = "login_failed"
    LOGIN_TIMEOUT = "login_timeout"
    LOGIN_WRONG_CHANNEL = "login_wrong_channel"
    LOGIN_CONFIRMED = "login_confirmed"
    TOKEN_SAVE_FAILED = "token_save_failed"
    TOKEN_REJECTED = "token_rejected"
    SYNC_SKIPPED = "channel_sync_skipped"
    ALIGN_SKIPPED = "channel_align_skipped"
    TOKEN_RENAME_SKIPPED = "token_rename_skipped"
    TOKEN_RESTORE_FAILED = "token_restore_failed"
    CHANNELS_WRITE_FAILED = "channels_write_failed"
    CHANNEL_ALIGNED = "channel_aligned"
    PASSPORT_UNREADABLE = "passport_unreadable"
    PASSPORT_SAVED = "passport_saved"
    PASSPORT_WRITE_FAILED = "passport_write_failed"

    def of(self, channel: ChannelConfig, **fields: object) -> LogEvent:
        """Строка события канала: название канала в кавычках, ник, затем поля события."""
        return LogEvent.of(self, channel=Quoted(channel.account_name), handle=channel.handle).extended(**fields)
