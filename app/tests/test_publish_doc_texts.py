"""Тексты документа объявлений (app\\publish\\doc_texts.py, CLAUDE.md §13 задача 4.4): метки таблицы на языке слота,
заголовок слота, имя документа и строки с жирными отрезками в единицах UTF-16."""
from __future__ import annotations

import pytest

from app.publish.doc_request import DocRange, InsertText, TextStyle
from app.publish.doc_texts import DocLabels, DocLine, DocLines, DocTexts
from app.tests.fixtures.publish import CREATED

TEXTS: DocTexts = DocTexts()


@pytest.mark.parametrize(
    ("language", "labels"),
    [
        ("uk", DocLabels("НАЗВА", "ОПИС", "ПРЕВ'Ю")),
        ("en", DocLabels("TITLE", "DESCRIPTION", "PREVIEW")),
        ("ru", DocLabels("НАЗВАНИЕ", "ОПИСАНИЕ", "ПРЕВЬЮ")),
        ("de", DocLabels("TITLE", "DESCRIPTION", "PREVIEW")),
    ],
)
def test_the_labels_are_in_the_slot_language_and_other_languages_get_english(language: str, labels: DocLabels) -> None:
    assert TEXTS.labels(language) == labels


def test_the_slot_heading_is_the_language_code_and_the_time() -> None:
    assert TEXTS.heading("uk", "19:00") == "UK - 19:00"


def test_the_name_is_the_date_and_the_creation_time() -> None:
    assert TEXTS.name("28-09-2026", CREATED) == "28-09-2026_Ежедневные стримы - Everyday streams_10:05"


def test_lines_insert_as_one_text_and_bold_lines_are_counted_in_utf16() -> None:
    """Строка с «❇️» — на единицу длиннее, чем знаков: жирный отрезок следующей строки сдвигается на неё."""
    lines: DocLines = DocLines((DocLine("❇️ Эфир", True), DocLine("", True), DocLine("обычная", False), DocLine("Итог", True)))
    assert lines.text == "❇️ Эфир\n\nобычная\nИтог"
    assert lines.requests(1) == (
        InsertText("❇️ Эфир\n\nобычная\nИтог", 1),
        TextStyle(DocRange(1, 22), False),
        TextStyle(DocRange(1, 8), True),
        TextStyle(DocRange(18, 22), True),
    )
