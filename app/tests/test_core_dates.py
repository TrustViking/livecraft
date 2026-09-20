from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.core.dates import (
    DATE_FORMAT,
    DATETIME_FORMAT,
    FILE_STAMP_FORMAT,
    SLOT_TIME_FORMAT,
    TIME_FORMAT,
    build_slot_id,
    format_date,
    format_datetime_text,
    format_now_local,
    format_time,
    parse_date,
    parse_datetime_text,
    parse_iso_start,
    parse_local_datetime_text_utc,
    parse_time,
)

KYIV_WINTER: timezone = timezone(timedelta(hours=2))


def test_formats_are_the_ones_invariant_four_names() -> None:
    """Даты DD-MM-YYYY, время HH:MM — во всех файлах, именах и отчётах (CLAUDE.md §6, инвариант 4)."""
    assert DATE_FORMAT == "%d-%m-%Y"
    assert TIME_FORMAT == "%H:%M"
    assert DATETIME_FORMAT == "%d-%m-%Y %H:%M"
    assert FILE_STAMP_FORMAT == "%d-%m-%Y_%H%M%S"
    assert SLOT_TIME_FORMAT == "%H%M"


def test_date_goes_there_and_back() -> None:
    assert parse_date("16-09-2026") == date(2026, 9, 16)
    assert format_date(date(2026, 9, 16)) == "16-09-2026"


@pytest.mark.parametrize("bad", ["2026-09-16", "16.09.2026", "16-9-26", "", "16-13-2026"])
def test_date_in_another_shape_is_an_error(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_date(bad)


def test_time_goes_there_and_back() -> None:
    assert parse_time("19:00") == time(19, 0)
    assert format_time(time(19, 0)) == "19:00"


@pytest.mark.parametrize("bad", ["1900", "19-00", "7:00 PM", "25:00", ""])
def test_time_in_another_shape_is_an_error(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_time(bad)


def test_datetime_text_goes_there_and_back() -> None:
    moment: datetime = datetime(2026, 9, 16, 19, 0)
    assert parse_datetime_text("16-09-2026 19:00") == moment
    assert format_datetime_text(moment) == "16-09-2026 19:00"


def test_local_datetime_text_becomes_a_moment_in_utc() -> None:
    """Так читаются моменты из памяти: текст без смещения — местное время машины."""
    value: datetime = parse_local_datetime_text_utc("16-09-2026 19:00")
    assert value.tzinfo is timezone.utc
    assert value == datetime(2026, 9, 16, 19, 0).astimezone(timezone.utc)


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


def test_now_local_is_printed_in_the_datetime_format() -> None:
    assert parse_datetime_text(format_now_local()) is not None


def test_slot_id_is_date_time_language() -> None:
    """slot_id = {DD-MM-YYYY}_{HHMM}_{lang} (CLAUDE.md §4)."""
    assert build_slot_id("16-09-2026", "19:00", "uk") == "16-09-2026_1900_uk"


def test_slot_id_normalises_a_single_digit_hour() -> None:
    assert build_slot_id("01-01-2027", "09:05", "ru") == "01-01-2027_0905_ru"


@pytest.mark.parametrize(
    ("date_text", "time_text"),
    [("2026-09-16", "19:00"), ("16-09-2026", "1900"), ("", "19:00"), ("16-09-2026", "")],
)
def test_slot_id_refuses_a_wrong_date_or_time(date_text: str, time_text: str) -> None:
    with pytest.raises(ValueError):
        build_slot_id(date_text, time_text, "uk")


def test_file_stamp_is_the_name_of_the_log_and_the_report() -> None:
    """logs\\{DD-MM-YYYY}_{HHMMSS}_… — имя и лога, и отчёта (CLAUDE.md §5)."""
    moment: datetime = datetime(2026, 9, 16, 19, 5, 7, tzinfo=KYIV_WINTER)
    assert moment.strftime(FILE_STAMP_FORMAT) == "16-09-2026_190507"
