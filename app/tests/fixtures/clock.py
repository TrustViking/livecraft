"""Часы с остановленным временем: тест сам решает, который час и в каком поясе программа (CLAUDE.md §11)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo

from app.core.clock import Clock


@dataclass(frozen=True)
class StoppedClock(Clock):
    """Часы программы в поясе `zone`, остановленные на моменте `moment`."""

    moment: datetime

    @classmethod
    def at(cls, moment: datetime, zone: tzinfo | None = None) -> StoppedClock:
        """Часы на этом моменте; пояс программы — `zone`, по умолчанию — пояс самого момента."""
        return cls(zone=zone if zone is not None else moment.tzinfo, moment=moment)

    def now(self) -> datetime:
        return self.moment.astimezone(self.zone)
