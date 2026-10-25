from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.clock import Clock
from app.tests.fixtures.clock import StoppedClock

KYIV_SUMMER: timezone = timezone(timedelta(hours=3))


def test_now_is_aware_and_in_the_zone_of_the_clock() -> None:
    now: datetime = Clock(KYIV_SUMMER).now()
    assert now.utcoffset() == timedelta(hours=3)


def test_the_utc_clock_is_in_utc() -> None:
    assert Clock.utc().now().utcoffset() == timedelta(0)


def test_local_time_is_the_calendar_time_in_the_zone_of_the_clock() -> None:
    """Момент 20-09-2026 23:30 UTC в поясе программы +03:00 — уже 21-09-2026 02:30."""
    moment: datetime = datetime(2026, 9, 20, 23, 30, tzinfo=timezone.utc)
    local = Clock(KYIV_SUMMER).local_time(moment.timestamp())
    assert (local.tm_year, local.tm_mon, local.tm_mday, local.tm_hour, local.tm_min) == (2026, 9, 21, 2, 30)


def test_a_stopped_clock_shows_its_moment_in_the_program_zone() -> None:
    clock: StoppedClock = StoppedClock.at(datetime(2026, 9, 20, 23, 30, tzinfo=timezone.utc), zone=KYIV_SUMMER)
    assert clock.now() == datetime(2026, 9, 21, 2, 30, tzinfo=KYIV_SUMMER)
    assert clock.now().utcoffset() == timedelta(hours=3)
