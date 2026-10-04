"""События памяти программы в логе (CLAUDE.md §11): одно перечисление на пакет app\\records\\."""
from __future__ import annotations

from enum import Enum


class RecordEvent(str, Enum):
    """События памяти: запись легла, база не открылась или не записалась, отметка «когда появилась память»."""

    SAVED = "record_saved"
    BROKEN = "records_broken"
    RENAME_FAILED = "records_rename_failed"
    READ_FAILED = "records_read_failed"
    WRITE_FAILED = "records_write_failed"
    CLEAN_FAILED = "records_clean_failed"
    CREATED_UTC_INITIALIZED = "records_created_utc_initialized"
