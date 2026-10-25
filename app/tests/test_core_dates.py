from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.dates import (
    DATE_FORMAT,
    DATETIME_FORMAT,
    FILE_STAMP_FORMAT,
    SLOT_TIME_FORMAT,
    TIME_FORMAT,
    TIMESTAMP_FORMAT,
    NaiveMomentError,
    format_date,
    format_datetime_text,
    format_time,
    format_timestamp,
    parse_datetime_text,
    parse_iso_start,
    require_aware,
    to_minute,
)

KYIV_WINTER: timezone = timezone(timedelta(hours=2))


def test_formats_are_the_ones_invariant_four_names() -> None:
    """Даты DD-MM-YYYY, время HH:MM — во всех файлах, именах и отчётах (CLAUDE.md §6, инвариант 4)."""
    assert DATE_FORMAT == "%d-%m-%Y"
    assert TIME_FORMAT == "%H:%M"
    assert DATETIME_FORMAT == "%d-%m-%Y %H:%M"
    assert FILE_STAMP_FORMAT == "%d-%m-%Y_%H%M%S"
    assert SLOT_TIME_FORMAT == "%H%M"


def test_date_is_written_day_month_year() -> None:
    assert format_date(date(2026, 9, 16)) == "16-09-2026"


def test_time_is_written_hours_and_minutes() -> None:
    assert format_time(time(19, 0)) == "19:00"
    assert format_time(time(9, 5)) == "09:05"


def test_datetime_text_is_date_and_time() -> None:
    assert format_datetime_text(datetime(2026, 9, 16, 19, 0)) == "16-09-2026 19:00"


def test_datetime_text_is_read_in_the_program_zone_not_the_machine_zone() -> None:
    """`DD-MM-YYYY HH:MM` памяти — по поясу программы (инвариант 4): один текст — один момент на любой машине."""
    kyiv: ZoneInfo = ZoneInfo("Europe/Kyiv")
    winter: datetime = parse_datetime_text("16-03-2027 12:00", kyiv)
    summer: datetime = parse_datetime_text("16-07-2027 12:00", kyiv)
    assert winter.astimezone(timezone.utc) == datetime(2027, 3, 16, 10, 0, tzinfo=timezone.utc)
    assert summer.astimezone(timezone.utc) == datetime(2027, 7, 16, 9, 0, tzinfo=timezone.utc)
    assert format_datetime_text(winter) == "16-03-2027 12:00"
    with pytest.raises(ValueError):
        parse_datetime_text("2027-03-16 12:00", kyiv)


def test_iso_start_keeps_its_offset() -> None:
    """`start` слота — ISO-8601 со смещением: только для сравнения моментов с YouTube (CLAUDE.md §4)."""
    value: datetime = parse_iso_start("2026-09-16T19:00:00+03:00")
    assert value == datetime(2026, 9, 16, 19, 0, tzinfo=timezone(timedelta(hours=3)))
    assert value.astimezone(timezone.utc) == datetime(2026, 9, 16, 16, 0, tzinfo=timezone.utc)


def test_iso_start_accepts_the_z_suffix() -> None:
    assert parse_iso_start("2026-09-16T16:00:00Z") == datetime(2026, 9, 16, 16, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", ["2026-09-16T19:00:00", "2026-09-16 19:00:00", "16-09-2026 19:00"])
def test_iso_start_without_an_offset_is_an_error(bad: str) -> None:
    """Момент без смещения нельзя сравнить с минутой старта на YouTube — значит это ошибка, а не догадка."""
    with pytest.raises(ValueError):
        parse_iso_start(bad)


def test_file_stamp_is_the_name_of_the_log_and_the_report() -> None:
    """logs\\{DD-MM-YYYY}_{HHMMSS}_… — имя и лога, и отчёта (CLAUDE.md §5)."""
    moment: datetime = datetime(2026, 9, 16, 19, 5, 7, tzinfo=KYIV_WINTER)
    assert moment.strftime(FILE_STAMP_FORMAT) == "16-09-2026_190507"


# --- момент с поясом и отметка журнала


def test_an_aware_moment_passes_as_it_is() -> None:
    moment: datetime = datetime(2026, 9, 16, 19, 0, tzinfo=KYIV_WINTER)
    assert require_aware(moment) is moment


def test_a_moment_without_a_zone_is_one_error_everywhere() -> None:
    """Одна проверка «время с поясом»: одна ошибка и один текст для разработчика."""
    with pytest.raises(NaiveMomentError) as raised:
        require_aware(datetime(2026, 9, 16, 19, 0))
    assert isinstance(raised.value, ValueError)
    assert str(raised.value) == NaiveMomentError.TEXT.format(value=datetime(2026, 9, 16, 19, 0))


def test_the_iso_start_without_an_offset_is_the_same_error() -> None:
    with pytest.raises(NaiveMomentError):
        parse_iso_start("2026-09-16T19:00:00")


def test_the_journal_stamp_carries_seconds() -> None:
    """Два события одной минуты в startup.log различимы: отметка — до секунды."""
    assert format_timestamp(datetime(2026, 9, 16, 19, 5, 7, tzinfo=KYIV_WINTER)) == "16-09-2026 19:05:07"
    assert TIMESTAMP_FORMAT == f"{DATETIME_FORMAT}:%S"


def test_to_minute_drops_seconds_and_goes_to_utc() -> None:
    """Время старта сравнивается только с точностью до минуты в UTC: пояс записи и секунды роли не играют."""
    local: datetime = datetime(2027, 3, 17, 19, 0, 42, 5, tzinfo=KYIV_WINTER)
    assert to_minute(local) == datetime(2027, 3, 17, 17, 0, tzinfo=timezone.utc)
    assert to_minute(local).tzinfo is timezone.utc
