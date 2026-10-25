"""Разметка жирного `*…*` в тексте слота (app\\texts\\bold_marks.py, CLAUDE.md §14 решение 63): что считается разметкой,
что остаётся звёздочками, текст без звёздочек."""
from __future__ import annotations

import pytest

from app.texts.bold_marks import BoldPart, BoldText


def test_a_mark_in_cyrillic_is_one_bold_part_without_stars() -> None:
    text: BoldText = BoldText.of("*Тема ефіру:* огляд новин")
    assert text.parts == (BoldPart("Тема ефіру:", is_bold=True), BoldPart(" огляд новин", is_bold=False))
    assert text.plain == "Тема ефіру: огляд новин"


def test_two_marks_in_one_line_and_a_mark_before_punctuation() -> None:
    text: BoldText = BoldText.of("Гості: *Іван* та *Марія*.")
    assert text.parts == (
        BoldPart("Гості: ", False), BoldPart("Іван", True), BoldPart(" та ", False), BoldPart("Марія", True),
        BoldPart(".", False),
    )


@pytest.mark.parametrize("marker", ["📌 ", "• ", "🔹 "])
def test_a_mark_after_an_emoji_or_a_bullet(marker: str) -> None:
    text: BoldText = BoldText.of(f"{marker}*Featured Speakers & Highlights:*\nдалі")
    assert text.parts == (
        BoldPart(marker, False), BoldPart("Featured Speakers & Highlights:", True), BoldPart("\nдалі", False)
    )


def test_marks_on_several_lines_each_close_on_their_own_line() -> None:
    text: BoldText = BoldText.of("*Раз*\n*Два* три")
    assert [(part.text, part.is_bold) for part in text.parts] == [
        ("Раз", True), ("\n", False), ("Два", True), (" три", False)
    ]


@pytest.mark.parametrize(
    "line",
    [
        "5*3*2",                 # открывающая не после пробела
        "a * b * c",             # пробел сразу после открывающей
        "**",                    # между звёздочками пусто
        "* x*",                  # пробел после открывающей
        "*x",                    # закрывающей нет
        "*x *",                  # пробел перед закрывающей
        "*перший\nдругий*",      # звёздочки через перевод строки
        "*x*y",                  # за закрывающей буква
        "**жирний**",            # двойные звёздочки — не наша разметка
    ],
)
def test_stars_that_are_not_a_mark_stay_as_they_are(line: str) -> None:
    text: BoldText = BoldText.of(line)
    assert text.parts == (BoldPart(line, False),) and text.plain == line


def test_an_empty_text_has_no_parts() -> None:
    assert BoldText.of("").parts == () and BoldText.of("").plain == ""


def test_an_unmarked_text_keeps_its_stars() -> None:
    """Текст программы (метка, ссылка) не разбирается: звёздочки в нём — не разметка."""
    assert BoldText.unmarked("*метка*").parts == (BoldPart("*метка*", False),)
    assert BoldText.unmarked("").parts == ()
