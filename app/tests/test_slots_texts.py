from __future__ import annotations

import logging

from app.slots.texts import SlotProblem, SlotTextOrigin, SlotTexts, SourceText
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

MAX_CHARS: int = SlotTexts.DESCRIPTION_MAX_CHARS


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
    result: SlotTexts = SlotTexts.from_sources((SourceText("Вечерний эфир", "Опис\n\nдругий абзац"),))
    assert result == SlotTexts(
        title="Вечерний эфир", description="Опис\n\nдругий абзац", origin=SlotTextOrigin.SOURCE_SINGLE
    )


def test_several_sources_take_the_first_title_and_the_filled_descriptions_in_their_order() -> None:
    """Порядок источников даёт группа слота (порядок рядов); тексты его не меняют."""
    sources: tuple[SourceText, ...] = (
        SourceText("Первый", "опис 2"),
        SourceText("Второй", ""),
        SourceText("Третий", "опис 4"),
    )
    result: SlotTexts = SlotTexts.from_sources(sources)
    assert result == SlotTexts(title="Первый", description="опис 2\n\nопис 4", origin=SlotTextOrigin.SOURCE_COMPOSED)


def test_a_source_without_video_data_gives_empty_texts() -> None:
    """Видео без данных — пустые название и описание: слот с таким названием получит проблему, а не падение."""
    result: SlotTexts = SlotTexts.from_sources((SourceText("", ""),))
    assert result.problem is SlotProblem.EMPTY_TITLE and result.description == ""


# --- правила YouTube


def test_angle_brackets_are_replaced_in_title_and_description(slot_log: LogCapture) -> None:
    fitted: SlotTexts = texts("A <b> title", "x > y < z").for_youtube("16-10-2026_1900_uk")
    assert fitted == texts("A ‹b› title", "x › y ‹ z")
    (line,) = slot_log.messages(logging.INFO)
    assert line.startswith("slot_texts_fitted slot=16-10-2026_1900_uk replaced=4 ")
    assert "title_reason=not_trimmed description_reason=not_trimmed" in line


def test_texts_within_the_rules_stay_the_same_and_are_not_logged(slot_log: LogCapture) -> None:
    original: SlotTexts = texts("Название", "Описание")
    assert original.for_youtube() == original
    assert slot_log.messages() == []


def test_long_title_is_cut_on_a_word_boundary(slot_log: LogCapture) -> None:
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
    assert len(fitted.description) <= MAX_CHARS
    assert len(fitted.description) > MAX_CHARS - 10
    assert_cut_on_boundary(description, fitted.description)


def test_cyrillic_description_is_counted_in_characters_not_bytes(slot_log: LogCapture) -> None:
    """Боевой прогон 28-09-2026: 4322 знака кириллицы (7778 байт) резались до 2157 — теперь не режутся (решение 30)."""
    description: str = "слово " * 691 + "я" + " word" * 35
    assert len(description) == 4322 and utf8_size(description) == 7778
    assert texts("t", description).for_youtube().description == description
    assert slot_log.messages() == []


def test_description_one_character_over_is_cut(slot_log: LogCapture) -> None:
    description: str = "слово " * 833 + "abc"
    assert len(description) == MAX_CHARS + 1
    fitted: SlotTexts = texts("t", description).for_youtube()
    assert len(fitted.description) <= MAX_CHARS
    assert_cut_on_boundary(description, fitted.description)
    (line,) = slot_log.messages(logging.INFO)
    assert "description_reason=word_boundary" in line
    assert f"description_chars=5001->{len(fitted.description)}" in line


def test_description_of_exactly_5000_characters_is_untouched(slot_log: LogCapture) -> None:
    description: str = "я" * MAX_CHARS
    assert texts("t", description).for_youtube().description == description
    assert slot_log.messages() == []


def test_description_is_not_cut_inside_a_link() -> None:
    """Предел приходится на ссылку: ссылка уходит целиком, а не остаётся обрывком «https://youtu.»."""
    description: str = "a " * 2490 + "https://youtu.be/abcdefghijk more"
    fitted: SlotTexts = texts("t", description).for_youtube()
    assert fitted.description == ("a " * 2490).rstrip()
    assert "https" not in fitted.description


def test_fitting_twice_changes_nothing() -> None:
    once: SlotTexts = texts("x <" + " слово" * 40, ("слово " * 700)[:4000]).for_youtube()
    assert once.for_youtube() == once


def test_title_without_a_boundary_is_dropped_and_is_a_problem() -> None:
    fitted: SlotTexts = texts("x" * 150).for_youtube()
    assert fitted.title == ""
    assert fitted.problem is SlotProblem.EMPTY_TITLE


def test_fitted_title_is_not_a_problem() -> None:
    assert texts("Эфир").for_youtube().problem is None


def test_empty_description_is_not_a_problem() -> None:
    assert texts("Эфир", "").problem is None


def test_blank_title_is_a_problem() -> None:
    assert texts("   ").problem is SlotProblem.EMPTY_TITLE


def test_merged_texts_keep_their_origin_through_the_platform_rules() -> None:
    assert SlotTextOrigin.MERGED.value == "merged"
    merged: SlotTexts = SlotTexts(title="Название <эфира>", description="Опис", origin=SlotTextOrigin.MERGED)
    assert merged.for_youtube().origin is SlotTextOrigin.MERGED


# --- по номерам


def test_numbered_texts_list_titles_and_descriptions_with_video_numbers() -> None:
    """Merge нужен и не удался (решение 32): «1) …» по видео; видео без описания в перечне описаний нет."""
    sources: tuple[SourceText, ...] = (
        SourceText("Первое", "  опис 1  "),
        SourceText("Второе", ""),
        SourceText("Третье <live>", "опис 3"),
    )
    result: SlotTexts = SlotTexts.numbered(sources)
    assert result == SlotTexts(
        title="1) Первое\n2) Второе\n3) Третье <live>",
        description="1) опис 1\n\n3) опис 3",
        origin=SlotTextOrigin.NUMBERED,
    )
    assert not result.is_for_youtube


def test_numbered_texts_are_not_cut() -> None:
    long: str = "слово " * 1000
    result: SlotTexts = SlotTexts.numbered((SourceText("A", long), SourceText("B", long)))
    assert len(result.description) > 2 * len(long.strip())


def test_texts_other_than_numbered_are_for_youtube() -> None:
    assert all(
        SlotTexts(title="t", description="d", origin=origin).is_for_youtube
        for origin in SlotTextOrigin
        if origin is not SlotTextOrigin.NUMBERED
    )


# --- список таймкодов (решение 79)

CHAPTERS: str = "Про эфир.\n\n00:00 Начало\n03:36 Главное\n15:56 Итоги\n\nСсылки ниже."
CLEAN: str = "Про эфир.\n\nСсылки ниже."


def test_one_video_loses_its_timecode_list_and_keeps_its_title() -> None:
    result: SlotTexts = SlotTexts.from_sources((SourceText("00:00 Заголовок", CHAPTERS),))
    assert result == SlotTexts(title="00:00 Заголовок", description=CLEAN, origin=SlotTextOrigin.SOURCE_SINGLE)


def test_a_single_time_line_stays_in_the_description() -> None:
    description: str = "Анонс.\n18:00 — эфир"
    assert SlotTexts.from_sources((SourceText("t", description),)).description == description


def test_several_videos_lose_the_timecode_list_of_each() -> None:
    result: SlotTexts = SlotTexts.from_sources((SourceText("A", CHAPTERS), SourceText("B", "опис")))
    assert result.description == f"{CLEAN}\n\nопис"


def test_numbered_texts_lose_the_timecode_list_of_each_video() -> None:
    result: SlotTexts = SlotTexts.numbered((SourceText("A", CHAPTERS), SourceText("B", "00:00 a\n01:00 b")))
    assert result.description == f"1) {CLEAN}"
    assert result.title == "1) A\n2) B"


def test_model_texts_lose_the_timecode_list_by_the_platform_rules(slot_log: LogCapture) -> None:
    merged: SlotTexts = SlotTexts(title="Эфир", description=CHAPTERS, origin=SlotTextOrigin.MERGED)
    assert merged.for_youtube("16-10-2026_1900_uk") == SlotTexts(
        title="Эфир", description=CLEAN, origin=SlotTextOrigin.MERGED
    )
    (line,) = slot_log.messages(logging.INFO)
    assert line.startswith("slot_texts_fitted slot=16-10-2026_1900_uk replaced=0 timecodes=3 ")


HEADED: str = "Про эфир.\n\nTimestamps:\n\n00:00 In This Episode\n00:35 Introduction\n\nСсылки ниже."


def test_the_heading_of_the_list_goes_from_video_numbered_and_model_texts() -> None:
    """Заголовок над списком таймкодов уходит вместе со списком (задача 9.39-К) у текстов всех видов."""
    assert SlotTexts.from_sources((SourceText("t", HEADED),)).description == CLEAN
    numbered: SlotTexts = SlotTexts.numbered((SourceText("A", HEADED), SourceText("B", "опис")))
    assert numbered.description == f"1) {CLEAN}\n\n2) опис"
    model: str = f"⏱ Таймкоды —\n0:00 a\n1:00 b\n\n{CLEAN}"
    merged: SlotTexts = SlotTexts(title="Эфир", description=model, origin=SlotTextOrigin.MERGED)
    assert merged.for_youtube().description == CLEAN


def test_a_heading_over_a_single_time_line_stays_in_the_description() -> None:
    description: str = "Анонс.\n\nТаймкоды:\n18:00 — эфир"
    assert SlotTexts.from_sources((SourceText("t", description),)).description == description


# --- ссылки (решение 81)

# Описания видео прогона 0.1.15: 26.10 en — «/» в конце пути, 29.10 ru — метка `?si=` у ссылки YouTube.
CLINIC_LINK: str = "https://clinic.example.org/dr-name/"
CLINIC_TEXT: str = f"Dr. Monsul talks about recovery.\n\nMore: {CLINIC_LINK}\n\n#health #recovery"
CLINIC_CLEAN: str = CLINIC_TEXT.replace(CLINIC_LINK, "https://clinic.example.org/dr-name")
YOUTUBE_TEXT: str = "Полная версия (https://youtu.be/AAAAAAAAAAA?si=AbCdEfGhIjKlMnOp).\n\n*Подпишитесь* на канал!"


def test_one_video_gives_its_links_without_the_trailing_slash_and_tracking() -> None:
    result: SlotTexts = SlotTexts.from_sources((SourceText("Recovery", CLINIC_TEXT),))
    assert result.description == CLINIC_CLEAN
    youtube: SlotTexts = SlotTexts.from_sources((SourceText("Эфир", YOUTUBE_TEXT),))
    assert youtube.description == YOUTUBE_TEXT.replace("?si=AbCdEfGhIjKlMnOp", "")


def test_numbered_texts_give_the_links_of_each_video_cleaned() -> None:
    result: SlotTexts = SlotTexts.numbered((SourceText("A", CLINIC_TEXT), SourceText("B", YOUTUBE_TEXT)))
    assert result.description == f"1) {CLINIC_CLEAN}\n\n2) {YOUTUBE_TEXT.replace('?si=AbCdEfGhIjKlMnOp', '')}"


def test_every_slot_problem_has_a_russian_text() -> None:
    for problem in SlotProblem:
        assert problem.human == msg.SLOT_PROBLEMS[problem.value] and problem.human
    assert set(msg.SLOT_PROBLEMS) == {problem.value for problem in SlotProblem}
