from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.sheets.plan import SheetRow
from app.sheets.rows import PlanRow
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.sources.video import SourceVideo
from app.tests.conftest import LogCollector, ready_source
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
MAX_BYTES: int = SlotTexts.DESCRIPTION_MAX_BYTES
LINKS: tuple[str, ...] = (
    "https://youtu.be/dQw4w9WgXcQ",
    "https://youtu.be/aB3_-xYz012",
    "https://youtu.be/Zx9_8yW7v6U",
)


def source(row_number: int, title: str, description: str) -> SourceVideo:
    link: str = LINKS[row_number - 2]
    row: SheetRow = SheetRow(row_number=row_number, link=link, date_raw="16.10.2026", time_raw="19:00")
    return ready_source(PlanRow.admitted(row, START, link), title, description, "uk")


def texts(title: str, description: str = "") -> SlotTexts:
    return SlotTexts(title=title, description=description, origin=SlotTextOrigin.SOURCE_SINGLE)


def utf8_size(text: str) -> int:
    return len(text.encode("utf-8"))


def assert_cut_on_boundary(original: str, fitted: str) -> None:
    """Обрезанный текст — начало исходного, и за ним в исходном стоит пробел: слово не разрезано."""
    assert original.startswith(fitted)
    assert len(fitted) < len(original)
    assert original[len(fitted)].isspace()


# --- из источников


def test_one_source_gives_its_texts_as_they_are() -> None:
    result: SlotTexts = SlotTexts.from_sources((source(2, "Вечерний эфир", "Опис\n\nдругий абзац"),))
    assert result == SlotTexts(
        title="Вечерний эфир", description="Опис\n\nдругий абзац", origin=SlotTextOrigin.SOURCE_SINGLE
    )


def test_several_sources_take_the_first_row_title_and_all_descriptions_in_row_order() -> None:
    videos: tuple[SourceVideo, ...] = (
        source(4, "Третий", "опис 4"),
        source(2, "Первый", "опис 2"),
        source(3, "Второй", ""),
    )
    result: SlotTexts = SlotTexts.from_sources(videos)
    assert result == SlotTexts(title="Первый", description="опис 2\n\nопис 4", origin=SlotTextOrigin.SOURCE_COMPOSED)


def test_no_sources_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        SlotTexts.from_sources(())


# --- правила YouTube


def test_angle_brackets_are_replaced_in_title_and_description(slot_log: LogCollector) -> None:
    fitted: SlotTexts = texts("A <b> title", "x > y < z").for_youtube("16-10-2026_1900_uk")
    assert fitted == texts("A ‹b› title", "x › y ‹ z")
    (line,) = slot_log.messages(logging.INFO)
    assert line.startswith("slot_texts_fitted slot=16-10-2026_1900_uk replaced=4 ")
    assert "title_reason=not_trimmed description_reason=not_trimmed" in line


def test_texts_within_the_rules_stay_the_same_and_are_not_logged(slot_log: LogCollector) -> None:
    original: SlotTexts = texts("Название", "Описание")
    assert original.for_youtube() == original
    assert slot_log.messages() == []


def test_long_title_is_cut_on_a_word_boundary(slot_log: LogCollector) -> None:
    title: str = " ".join(["слово"] * 26)[:130]
    assert len(title) == 130
    fitted: SlotTexts = texts(title).for_youtube()
    assert 0 < len(fitted.title) <= SlotTexts.TITLE_MAX_CHARS
    assert_cut_on_boundary(title, fitted.title)
    (line,) = slot_log.messages(logging.INFO)
    assert "title_reason=word_boundary" in line
    assert f"title_chars=130->{len(fitted.title)}" in line


def test_long_latin_description_is_cut_to_5000_characters() -> None:
    description: str = ("word " * 1200)[:6000]
    fitted: SlotTexts = texts("t", description).for_youtube()
    assert len(fitted.description) <= MAX_BYTES
    assert utf8_size(fitted.description) <= MAX_BYTES
    assert len(fitted.description) > MAX_BYTES - 10
    assert_cut_on_boundary(description, fitted.description)


def test_long_cyrillic_description_is_cut_to_5000_utf8_bytes(slot_log: LogCollector) -> None:
    description: str = ("слово " * 700)[:4000]
    assert len(description) == 4000
    assert utf8_size(description) > 7000
    fitted: SlotTexts = texts("t", description).for_youtube()
    assert utf8_size(fitted.description) <= MAX_BYTES
    # предел в символах уменьшается на избыток байтов: кириллица (2 байта) даёт небольшой недобор, не больше 10 %
    assert utf8_size(fitted.description) > MAX_BYTES * 0.9
    assert_cut_on_boundary(description, fitted.description)
    (line,) = slot_log.messages(logging.INFO)
    assert "description_reason=word_boundary" in line
    assert f"description_bytes={utf8_size(description)}->{utf8_size(fitted.description)}" in line


def test_description_of_exactly_5000_bytes_is_untouched(slot_log: LogCollector) -> None:
    description: str = "я" * (MAX_BYTES // 2)
    assert utf8_size(description) == MAX_BYTES
    assert texts("t", description).for_youtube().description == description
    assert slot_log.messages() == []


def test_description_one_byte_over_is_cut() -> None:
    description: str = "слово " * 454 + "abcdefg"
    assert utf8_size(description) == MAX_BYTES + 1
    fitted: SlotTexts = texts("t", description).for_youtube()
    assert utf8_size(fitted.description) <= MAX_BYTES
    assert_cut_on_boundary(description, fitted.description)


def test_replacement_characters_are_counted_in_bytes() -> None:
    """‹ и › занимают по 3 байта: замена может вывести описание за предел, и тогда оно обрезается."""
    description: str = "a " * 2490 + "<>" * 10
    assert utf8_size(description) == MAX_BYTES
    fitted: SlotTexts = texts("t", description).for_youtube()
    assert utf8_size(fitted.description) <= MAX_BYTES
    assert "<" not in fitted.description and ">" not in fitted.description


def test_fitting_twice_changes_nothing() -> None:
    once: SlotTexts = texts("x <" + " слово" * 40, ("слово " * 700)[:4000]).for_youtube()
    assert once.for_youtube() == once


def test_title_without_a_boundary_is_dropped_and_is_a_problem() -> None:
    fitted: SlotTexts = texts("x" * 150).for_youtube()
    assert fitted.title == ""
    assert fitted.problem == msg.SLOT_EMPTY_TITLE


def test_fitted_title_is_not_a_problem() -> None:
    assert texts("Эфир").for_youtube().problem is None


def test_empty_description_is_not_a_problem() -> None:
    assert texts("Эфир", "").problem is None


def test_blank_title_is_a_problem() -> None:
    assert texts("   ").problem == msg.SLOT_EMPTY_TITLE
