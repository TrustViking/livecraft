"""Часы тестов: остановленные и идущие — тест сам решает, который час и в каком поясе программа (CLAUDE.md §11)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo

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


@dataclass(frozen=True)
class RunningClock(Clock):
    """Часы, которые идут, только когда программа спит или тест их двигает: сон мгновенный, но время на часах
    проходит. `sleep` — сон программы (паузы запоминаются в `sleeps`), `advance` — время, которое прошло само."""

    start: datetime
    sleeps: list[float] = field(default_factory=list)
    shifts: list[float] = field(default_factory=list)

    @classmethod
    def at(cls, start: datetime) -> RunningClock:
        """Часы в поясе момента `start`, стоящие на нём, пока никто не спит."""
        return cls(zone=start.tzinfo, start=start)

    @property
    def seconds(self) -> float:
        """Сколько секунд прошло от `start`."""
        return sum(self.shifts)

    def now(self) -> datetime:
        return (self.start + timedelta(seconds=self.seconds)).astimezone(self.zone)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.shifts.append(seconds)

    def advance(self, seconds: float) -> None:
        self.shifts.append(seconds)
