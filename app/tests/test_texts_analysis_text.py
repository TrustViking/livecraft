from __future__ import annotations

import pytest

from app.texts.analysis_text import AnalysisTextReport, CleanedLine
from app.texts.phrase_lexicon import PhraseLexicon, ServiceHints

HINTS: ServiceHints = ServiceHints.load()
NO_HINTS: ServiceHints = ServiceHints(PhraseLexicon(()))


def cleaned(text: str, hints: ServiceHints = HINTS) -> str:
    return AnalysisTextReport.of(text, hints).text


@pytest.mark.parametrize("text", ["", "   ", "\n\n\r\n", None])
def test_empty_input_is_empty(text: str | None) -> None:
    assert cleaned(text) == ""   # type: ignore[arg-type]


def test_urls_are_removed_with_the_edge_punctuation() -> None:
    text: str = "Новый выпуск: https://example.org/a?b=1 - смотрим вместе, http://t.me/x ;"
    assert cleaned(text) == "Новый выпуск: - смотрим вместе"   # знаки срезаются только с краёв


def test_hashtags_are_removed_but_a_hash_inside_a_word_stays() -> None:
    text: str = "#новини Разбор дня #економіка c#sharp #"
    assert cleaned(text) == "Разбор дня c#sharp #"


def test_links_heading_line_drops_out_of_the_text_for_analysis() -> None:
    """Строка «🌐 …:» — заголовок ссылок, а не текст видео: по ней о языке не судят."""
    text: str = "Первый абзац о главном.\n🌐 Официальные ссылки:\nВторая строка абзаца."
    assert cleaned(text) == "Первый абзац о главном.\nВторая строка абзаца."


def test_links_heading_with_its_links_on_the_same_line_drops_out_too() -> None:
    line: CleanedLine = CleanedLine.of("🌐 Official links: https://a.example")
    assert (line.is_heading, line.is_kept, line.urls_removed) == (True, False, 1)
    assert cleaned("Факты дня.\n\n🌐 Сайт: https://a.example\nhttps://b.example") == "Факты дня."


def test_a_line_that_only_mentions_the_globe_is_kept() -> None:
    assert cleaned("🌐 Новости мира сегодня") == "🌐 Новости мира сегодня"


def test_paragraph_of_only_links_disappears_and_paragraphs_keep_their_break() -> None:
    text: str = "Первый абзац.\r\n\r\nhttps://a.example #тег\n\n  Третий абзац.  "
    assert cleaned(text) == "Первый абзац.\n\nТретий абзац."


def test_short_service_tail_paragraphs_are_dropped_from_the_end() -> None:
    text: str = (
        "Сегодня говорим о новостях экономики и политики.\n\n"
        "Подписывайтесь на канал!\n\n"
        "Залиште коментар під відео"
    )
    assert cleaned(text) == "Сегодня говорим о новостях экономики и политики."


def test_service_hint_in_the_middle_is_kept() -> None:
    text: str = "Подписывайтесь на канал!\n\nСегодня говорим о новостях экономики."
    assert cleaned(text) == text


def test_long_paragraph_with_a_hint_is_not_a_service_tail() -> None:
    body: str = " ".join(["слово"] * 13) + " подпишитесь"
    assert cleaned(f"Начало.\n\n{body}") == f"Начало.\n\n{body}"


def test_without_hints_no_tail_is_dropped() -> None:
    text: str = "Начало.\n\nПодписывайтесь на канал!"
    assert cleaned(text, NO_HINTS) == text


def test_report_counts_links_hashtags_and_dropped_paragraphs() -> None:
    text: str = (
        "Начало https://a.example и http://b.example #один\n\n"
        "https://only.example #два #три\n\n"
        "Середина текста.\n\n"
        "Подписывайтесь на канал!\n\n"
        "Смотрите подробности ниже"
    )
    assert AnalysisTextReport.of(text, HINTS) == AnalysisTextReport(
        text="Начало и\n\nСередина текста.", urls_removed=3, hashtags_removed=3, service_paragraphs_dropped=3
    )


def test_report_text_drops_the_service_tail_after_the_empty_paragraph() -> None:
    text: str = "Первый абзац https://a.example.\r\n\r\n#тег https://b.example\n\nПодписывайтесь на канал!"
    assert cleaned(text) == "Первый абзац"


def test_hashtags_are_counted_after_links_are_removed() -> None:
    """Ссылка с «#» внутри уходит целиком раньше хештегов и хештегом не считается."""
    report: AnalysisTextReport = AnalysisTextReport.of("Текст https://a.example/#part #тег", HINTS)
    assert (report.text, report.urls_removed, report.hashtags_removed) == ("Текст", 1, 1)


@pytest.mark.parametrize("text", ["", "  \r\n\r\n  "])
def test_report_of_empty_text_counts_nothing(text: str) -> None:
    assert AnalysisTextReport.of(text, HINTS) == AnalysisTextReport(
        text="", urls_removed=0, hashtags_removed=0, service_paragraphs_dropped=0
    )


def test_service_tail_rule_is_the_one_the_cleaning_uses() -> None:
    text: str = "Main paragraph with facts.\n\nSubscribe to the channel"
    assert HINTS.is_tail_paragraph("Subscribe to the channel")
    assert cleaned(text) == "Main paragraph with facts."
