"""События вывода контура B в логе (CLAUDE.md §11)."""
from __future__ import annotations

from enum import Enum


class OutputEvent(str, Enum):
    BROADCASTS_REPORT = "broadcasts_report"
    KEYS_WRITTEN = "keys_written"
    KEYS_WRITE_FAILED = "keys_write_failed"
