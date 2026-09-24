from __future__ import annotations

import pytest

from app.resources.loader import TextResource
from app.texts.analysis_text import clean_text_for_analysis

HINTS: tuple[str, ...] = TextResource("merge_service_hints.txt").lines


@pytest.mark.parametrize("text", ["", "   ", "\n\n\r\n", None])
def test_empty_input_is_empty(text: str | None) -> None:
    assert clean_text_for_analysis(text, HINTS) == ""   # type: ignore[arg-type]


def test_urls_are_removed_with_the_edge_punctuation() -> None:
    text: str = "Новый выпуск: https://example.org/a?b=1 - смотрим вместе, http://t.me/x ;"
    assert clean_text_for_analysis(text, HINTS) == "Новый выпуск: - смотрим вместе"   # знаки срезаются только с краёв


def test_hashtags_are_removed_but_a_hash_inside_a_word_stays() -> None:
    text: str = "#новини Разбор дня #економіка c#sharp #"
    assert clean_text_for_analysis(text, HINTS) == "Разбор дня c#sharp #"


def test_links_heading_line_keeps_its_text_without_the_colon_like_the_donor() -> None:
    """У донора строка сначала теряет двоеточие на краю, а потом сверяется с шаблоном «🌐 …:» — и не совпадает.
    Правило перенесено как есть: заголовок остаётся текстом без двоеточия."""
    text: str = "Первый абзац о главном.\n🌐 Официальные ссылки:\nВторая строка абзаца."
    assert clean_text_for_analysis(text, HINTS) == (
        "Первый абзац о главном.\n🌐 Официальные ссылки\nВторая строка абзаца."
    )


def test_paragraph_of_only_links_disappears_and_paragraphs_keep_their_break() -> None:
    text: str = "Первый абзац.\r\n\r\nhttps://a.example #тег\n\n  Третий абзац.  "
    assert clean_text_for_analysis(text, HINTS) == "Первый абзац.\n\nТретий абзац."


def test_short_service_tail_paragraphs_are_dropped_from_the_end() -> None:
    text: str = (
        "Сегодня говорим о новостях экономики и политики.\n\n"
        "Подписывайтесь на канал!\n\n"
        "Залиште коментар під відео"
    )
    assert clean_text_for_analysis(text, HINTS) == "Сегодня говорим о новостях экономики и политики."


def test_service_hint_in_the_middle_is_kept() -> None:
    text: str = "Подписывайтесь на канал!\n\nСегодня говорим о новостях экономики."
    assert clean_text_for_analysis(text, HINTS) == text


def test_long_paragraph_with_a_hint_is_not_a_service_tail() -> None:
    body: str = " ".join(["слово"] * 13) + " подпишитесь"
    assert clean_text_for_analysis(f"Начало.\n\n{body}", HINTS) == f"Начало.\n\n{body}"


def test_without_hints_no_tail_is_dropped() -> None:
    text: str = "Начало.\n\nПодписывайтесь на канал!"
    assert clean_text_for_analysis(text, ()) == text
