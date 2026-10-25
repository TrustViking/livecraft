"""Замечание площадки за запуск: не сбой и не эфир программы, но владелец должен о нём узнать."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlatformNoticeKind(str, Enum):
    UNDATED_BROADCAST = "undated_broadcast"   # эфир без времени старта: площадка его отбрасывает
    CHANNEL = "channel"                       # канал выровнен или его файлы не записаны: text — готовая строка


@dataclass(frozen=True)
class PlatformNotice:
    """Что заметила площадка: вид замечания, канал и эфир."""

    kind: PlatformNoticeKind
    account_name: str
    title: str
    handle: str = ""
    text: str = ""   # CHANNEL: строка предупреждения запуска целиком
