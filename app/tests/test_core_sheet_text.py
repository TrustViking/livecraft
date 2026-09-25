from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.sheet_text import (
    SHEET_DATE_FORMATS,
    SHEET_TIME_FORMATS,
    extract_youtube_video_id,
    is_real_local_time,
    normalize_header_name,
    normalize_youtube_link,
    parse_sheet_datetime,
)

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
VIDEO_ID: str = "dQw4w9WgXcQ"
OTHER_ID: str = "aB3_-xYz012"


@pytest.mark.parametrize(
    "date_raw",
    ["16.09.2026", "16.09.26", "16/09/2026", "16/09/26", "2026-09-16", "160926", "16092026"],
)
def test_every_date_format_of_the_donor_is_read(date_raw: str) -> None:
    moment: datetime = parse_sheet_datetime(date_raw, "19:00", KYIV)
    assert (moment.year, moment.month, moment.day) == (2026, 9, 16)


def test_the_date_formats_are_exactly_the_donor_ones() -> None:
    assert len(SHEET_DATE_FORMATS) == 7
    assert len(SHEET_TIME_FORMATS) == 6


@pytest.mark.parametrize(
    ("time_raw", "hour", "minute"),
    [("19:05", 19, 5), ("19.05", 19, 5), ("1905", 19, 5), ("19:05:45", 19, 5), ("7:05 PM", 19, 5), ("7 PM", 19, 0)],
)
def test_every_time_format_of_the_donor_is_read(time_raw: str, hour: int, minute: int) -> None:
    moment: datetime = parse_sheet_datetime("16.09.2026", time_raw, KYIV)
    assert (moment.hour, moment.minute) == (hour, minute)


def test_seconds_are_dropped() -> None:
    moment: datetime = parse_sheet_datetime("16.09.2026", "19:05:45", KYIV)
    assert moment.second == 0
    assert moment.microsecond == 0


def test_cells_are_trimmed() -> None:
    moment: datetime = parse_sheet_datetime("  16.09.2026 ", " 19:00  ", KYIV)
    assert moment == datetime(2026, 9, 16, 19, 0, tzinfo=KYIV)


@pytest.mark.parametrize(
    ("date_raw", "time_raw"),
    [("32.09.2026", "19:00"), ("16-09-2026x", "19:00"), ("завтра", "19:00"), ("16.09.2026", "25:00"),
     ("16.09.2026", "вечером"), ("", "19:00"), ("16.09.2026", "")],
)
def test_unreadable_date_or_time_is_value_error(date_raw: str, time_raw: str) -> None:
    with pytest.raises(ValueError):
        parse_sheet_datetime(date_raw, time_raw, KYIV)


def test_kyiv_offset_is_winter_and_summer() -> None:
    winter: datetime = parse_sheet_datetime("15.01.2027", "12:00", KYIV)
    summer: datetime = parse_sheet_datetime("15.07.2027", "12:00", KYIV)
    assert winter.utcoffset() == timedelta(hours=2)
    assert summer.utcoffset() == timedelta(hours=3)
    assert winter.isoformat() == "2027-01-15T12:00:00+02:00"
    assert summer.isoformat() == "2027-07-15T12:00:00+03:00"


def test_spring_forward_gap_is_not_a_real_local_time() -> None:
    assert not is_real_local_time(datetime(2026, 3, 29, 3, 30, tzinfo=KYIV))
    assert is_real_local_time(datetime(2026, 3, 29, 2, 59, tzinfo=KYIV))
    assert is_real_local_time(datetime(2026, 3, 29, 4, 0, tzinfo=KYIV))


def test_repeated_autumn_hour_is_a_real_local_time() -> None:
    assert is_real_local_time(datetime(2026, 10, 25, 3, 30, tzinfo=KYIV))
    assert is_real_local_time(datetime(2026, 10, 25, 3, 30, fold=1, tzinfo=KYIV))


def test_naive_moment_has_no_local_time_rule() -> None:
    with pytest.raises(ValueError):
        is_real_local_time(datetime(2026, 3, 29, 3, 30))


@pytest.mark.parametrize(
    "text",
    [
        f"https://youtu.be/{VIDEO_ID}",
        f"youtu.be/{VIDEO_ID}?si=abc",
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&t=42s",
        f"https://www.youtube.com/watch?feature=share&v={VIDEO_ID}",
        f"https://www.youtube.com/watch?feature=share&v={VIDEO_ID}&list=PL1",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}?feature=shared",
        f"HTTPS://WWW.YOUTUBE.COM/watch?v={VIDEO_ID}",
        VIDEO_ID,
        f"  {VIDEO_ID}  ",
        f"Стрим тут: https://youtu.be/{VIDEO_ID} — не пропустите",
    ],
)
def test_every_link_kind_of_the_donor_gives_the_id(text: str) -> None:
    assert extract_youtube_video_id(text) == VIDEO_ID
    assert normalize_youtube_link(text) == f"https://youtu.be/{VIDEO_ID}"


def test_of_two_links_the_earliest_wins_whatever_its_kind() -> None:
    first_watch: str = f"https://www.youtube.com/watch?v={VIDEO_ID} и https://youtu.be/{OTHER_ID}"
    first_short: str = f"https://youtu.be/{OTHER_ID} и https://www.youtube.com/watch?v={VIDEO_ID}"
    assert extract_youtube_video_id(first_watch) == VIDEO_ID
    assert extract_youtube_video_id(first_short) == OTHER_ID


@pytest.mark.parametrize(
    "link",
    [f"https://youtu.be/{VIDEO_ID}", f"https://www.youtube.com/watch?v={VIDEO_ID}", f"https://youtube.com/live/{VIDEO_ID}"],
)
def test_a_link_wins_over_an_earlier_bare_id(link: str) -> None:
    assert extract_youtube_video_id(f"{OTHER_ID} {link}") == VIDEO_ID


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "https://youtu.be/dQw4w9WgXc",
        "https://youtu.be/short",
        f"x{VIDEO_ID}x",
        f"{VIDEO_ID}Q",
        "https://vimeo.com/123456789",
        "просто текст без ссылки",
    ],
)
def test_no_id_is_none(text: str) -> None:
    assert extract_youtube_video_id(text) is None
    assert normalize_youtube_link(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ссылка на видео!", "ссылканавидео"),
        (" Links (YouTube) ", "linksyoutube"),
        ("Дата / Date", "датаdate"),
        ("ВРЕМЯ, час", "времячас"),
        ("Time 24h", "time24h"),
        ("—", ""),
    ],
)
def test_header_name_keeps_only_letters_and_digits(text: str, expected: str) -> None:
    assert normalize_header_name(text) == expected
