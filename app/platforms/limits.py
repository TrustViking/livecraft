"""Что задаёт сама площадка: пределы текстов эфира и постоянные настройки эфира программы на ней (CLAUDE.md §4)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformLimits:
    """Пределы длины названия и описания и постоянные настройки эфира.

    Спека берёт их отсюда, чтобы отправляемое и сравниваемое совпадали по построению.
    """

    title_max_chars: int
    description_max_chars: int
    auto_stop: bool               # enableAutoStop: эфир завершается сам, когда поток пропал
    latency_preference: str       # latencyPreference
