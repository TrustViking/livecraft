from __future__ import annotations

from app.core.timecode import TimecodeList
from app.resources.loader import TextResource
from app.slots.texts import TIMECODE_HEADINGS_RESOURCE

CHAPTERS: str = "Вступление к эфиру.\n\n00:00 Начало\n03:36 Главное\n15:56 Итоги\n\nПодписывайтесь на канал."


def test_a_list_of_three_timecodes_leaves_the_description_without_extra_blank_lines() -> None:
    timecodes: TimecodeList = TimecodeList(CHAPTERS)
    assert timecodes.is_list and timecodes.removed == 3
    assert timecodes.cleaned == "Вступление к эфиру.\n\nПодписывайтесь на канал."


def test_one_timecode_line_is_a_time_and_stays() -> None:
    text: str = "Анонс.\n18:00 — эфир\nДо встречи."
    timecodes: TimecodeList = TimecodeList(text)
    assert not timecodes.is_list and timecodes.removed == 0
    assert timecodes.cleaned == text


def test_every_timecode_form_counts_and_a_time_inside_a_line_does_not() -> None:
    text: str = "0:00 старт\n1:02:03 - час\n00:00:10Текст\nВ 12:30 начало\n2026:10 не время"
    assert TimecodeList(text).lines == ("0:00 старт", "1:02:03 - час", "00:00:10Текст")
    assert TimecodeList(text).cleaned == "В 12:30 начало\n2026:10 не время"


def test_a_list_at_the_start_or_the_end_leaves_no_blank_edge() -> None:
    assert TimecodeList("00:00 a\n01:00 b\n\nТекст").cleaned == "Текст"
    assert TimecodeList("Текст\n\n00:00 a\n\n01:00 b\n").cleaned == "Текст"


def test_a_list_without_blank_lines_joins_the_text_around_it_directly() -> None:
    assert TimecodeList("Итак:\n00:00 a\n01:00 b\nКонец").cleaned == "Итак:\nКонец"


def test_cleaning_twice_changes_nothing() -> None:
    once: str = TimecodeList(CHAPTERS).cleaned
    assert TimecodeList(once).cleaned == once


# --- заголовок списка (задача 9.39-К)

HEADINGS: tuple[str, ...] = TextResource(TIMECODE_HEADINGS_RESOURCE).lines


def _cleaned(text: str) -> str:
    return TimecodeList.of(text, HEADINGS).cleaned


def test_a_heading_with_a_blank_line_above_the_list_goes_with_it() -> None:
    timecodes: TimecodeList = TimecodeList.of("#Podcast\n\nTimestamps:\n\n00:00 a\n00:35 b\n\nEnd", HEADINGS)
    assert timecodes.cleaned == "#Podcast\n\nEnd"
    assert timecodes.removed == 3


def test_a_heading_with_an_emoji_and_a_dash_goes_with_the_list() -> None:
    assert _cleaned("Опис.\n\n⏱ Таймкоды —\n0:00 старт\n1:00 итог") == "Опис."
    assert _cleaned("Опис.\n\n▶️ TIME CODES:\n0:00 a\n1:00 b\n\nКінець") == "Опис.\n\nКінець"


def test_an_ordinary_line_above_the_list_stays() -> None:
    assert _cleaned("Разбор темы:\n00:00 a\n01:00 b") == "Разбор темы:"
    assert _cleaned("Chapters of the book\n00:00 a\n01:00 b") == "Chapters of the book"


def test_a_heading_over_a_single_time_line_stays() -> None:
    text: str = "Таймкоды:\n18:00 — эфир"
    timecodes: TimecodeList = TimecodeList.of(text, HEADINGS)
    assert (timecodes.cleaned, timecodes.removed) == (text, 0)


def test_only_the_line_right_above_the_first_timecode_is_a_heading() -> None:
    assert _cleaned("Главы:\nВступление\n00:00 a\n01:00 b\nРозділи") == "Главы:\nВступление\nРозділи"
