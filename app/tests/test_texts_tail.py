"""Хвост ответа модели: строки, абзацы и сбор хвоста в конце и внутри текста (донор: test_sanitizer_tail_parser.py)."""
from __future__ import annotations

import pytest

from app.texts.description_marks import CtaLexicon
from app.texts.tail import (
    EmbeddedTail,
    TailReader,
    TextTail,
    TrailingTail,
    UrlTail,
    clean_double_bullet_markers,
    dedupe_cta_lines,
    is_hashtags_line,
    is_source_url_line,
    merge_hashtag_lines,
)

CTA: CtaLexicon = CtaLexicon.load()
READER: TailReader = TailReader(CTA)
NEUTRAL: str = chr(0x1F539)
PIN: str = chr(0x1F4CC)


def trailing(text: str) -> TrailingTail:
    return TrailingTail.of(text.split("\n"), CTA)


# --- строки


@pytest.mark.parametrize(
    ("line", "expected"),
    [("https://example.com", True), ("(https://example.com).", True), ("not a url", False), ("", False),
     ("see https://example.com", False)],
)
def test_source_url_line(line: str, expected: bool) -> None:
    assert is_source_url_line(line) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [("#AI #Climate #Ukraine", True), ("This is regular text", False), ("#AI and some text", False), ("", False),
     ("#a#b", False)],
)
def test_hashtags_line(line: str, expected: bool) -> None:
    assert is_hashtags_line(line) is expected


@pytest.mark.parametrize(
    "line",
    [
        "Напишите в комментариях, какие вопросы вы считаете ключевыми.",
        "Напишіть у коментарях, що ви думаєте про це.",
        "Write a comment and share your thoughts on this topic.",
        "- Subscribe to our channel",
        "Watch the full stream here",
    ],
)
def test_standalone_cta_lines(line: str) -> None:
    assert READER.is_standalone_cta_line(line)


def test_long_factual_text_with_a_comment_word_is_not_a_standalone_cta() -> None:
    long_text: str = (
        "Юрист прокомментировал ситуацию и дал развёрнутый комментарий о позиции защиты, "
        "включая анализ доказательной базы, свидетельских показаний и процедурных нарушений, "
        "которые были допущены в ходе следствия по делу обвиняемого."
    )
    assert not READER.is_standalone_cta_line(long_text)
    assert not READER.is_standalone_cta_line("   ")


def test_double_bullet_markers_keep_the_first_marker() -> None:
    assert clean_double_bullet_markers(f"{NEUTRAL} {NEUTRAL} Some text") == f"{NEUTRAL} Some text"
    assert clean_double_bullet_markers(f"  {NEUTRAL} {PIN} text\n{NEUTRAL} Normal") == f"  {NEUTRAL} text\n{NEUTRAL} Normal"
    assert clean_double_bullet_markers(f"{NEUTRAL} Normal bullet") == f"{NEUTRAL} Normal bullet"


def test_hashtag_lines_merge_without_case_repeats() -> None:
    assert merge_hashtag_lines(["#AI #Climate", "#ai #Ukraine", "text #x"]) == "#AI #Climate #Ukraine #x"
    assert merge_hashtag_lines([]) == ""


def test_cta_lines_dedupe_without_case_and_spaces() -> None:
    assert dedupe_cta_lines(["Join  us", "join us", "", "Share"]) == ("Join us", "Share")


# --- абзацы


def test_url_tail_takes_clean_links_and_counts_changed_and_malformed() -> None:
    paragraph: str = "Body text (https://example.org/?utm_source=x https://[bad https://example.org"
    # Открывающая скобка перед ссылками остаётся в тексте — как у донора (скобка — граница, а не часть ссылки).
    assert READER.url_tail(paragraph) == UrlTail(
        text="Body text (", urls=("https://example.org",), change_count=1, malformed=1
    )
    assert READER.url_tail("No links here.") == UrlTail(text="No links here.")
    assert READER.url_tail("  ") == UrlTail(text="")


def test_hashtag_tail_trims_the_text_before_it() -> None:
    assert READER.hashtag_tail("Body words, #one #two") == TextTail(text="Body words", tail="#one #two")
    assert READER.hashtag_tail("Body #one words") == TextTail(text="Body #one words")


def test_cta_tail_takes_the_last_cta_sentence_or_the_whole_cta_paragraph() -> None:
    assert READER.cta_tail("Facts come first. Join us tonight and share your thoughts.") == TextTail(
        text="Facts come first.", tail="Join us tonight and share your thoughts."
    )
    assert READER.cta_tail("Subscribe to our channel") == TextTail(text="", tail="Subscribe to our channel")
    assert READER.cta_tail("Facts come first. More facts arrive later.") == TextTail(
        text="Facts come first. More facts arrive later."
    )


# --- хвост в конце текста


def test_trailing_tail_takes_urls_then_hashtags_then_cta_lines() -> None:
    tail: TrailingTail = trailing(
        "First paragraph text here.\n\nJoin us tonight and share your thoughts. #live\n#nano #micro\n\n"
        "https://example.org/?utm_source=x\nhttps://[bad\n"
    )
    assert tail.body_end_index == 1                     # пустые строки между телом и хвостом уходят с хвостом
    assert tail.fragments.source_urls == ("https://example.org",)
    assert tail.fragments.url_change_count == 1 and tail.fragments.malformed_urls_dropped == 1
    assert tail.fragments.hashtag_lines == ("#live", "#nano #micro")
    assert tail.fragments.cta_lines == ("Join us tonight and share your thoughts.",)
    assert tail.fragments.hashtags_split_from_cta


def test_text_without_tail_keeps_every_line() -> None:
    tail: TrailingTail = trailing("Just a paragraph.\nWith two lines.")
    assert tail.body_end_index == 2 and tail.fragments.source_urls == () and tail.fragments.cta_lines == ()


# --- хвост внутри абзацев


def test_embedded_tail_is_taken_from_each_paragraph() -> None:
    embedded: EmbeddedTail = EmbeddedTail.of(
        "Some description text. Join us tonight and share. #a #b\n\nMore facts https://example.org/page\n\n"
        "https://youtu.be/aaaaaaaaaaa",
        CTA,
    )
    assert embedded.body_text == "Some description text.\n\nMore facts"
    assert embedded.fragments.cta_lines == ("Join us tonight and share.",)
    assert embedded.fragments.hashtag_lines == ("#a #b",)
    assert embedded.fragments.hashtags_split_from_cta
    assert embedded.fragments.source_urls == ("https://example.org/page", "https://youtu.be/aaaaaaaaaaa")


def test_embedded_tail_of_a_plain_paragraph_changes_nothing() -> None:
    embedded: EmbeddedTail = EmbeddedTail.of("Some description text.", CTA)
    assert embedded.body_text == "Some description text." and embedded.fragments == EmbeddedTail.of("x", CTA).fragments
