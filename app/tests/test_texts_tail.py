"""Хвост ответа модели: строки, абзацы и сбор хвоста в конце и внутри текста."""
from __future__ import annotations

import pytest

from app.texts.description_marks import CtaLexicon, TextTail
from app.texts.hashtags import is_hashtags_line
from app.texts.tail import (
    CtaTailLine,
    EmbeddedTail,
    TailCollector,
    TailFragments,
    TailParagraph,
    TrailingTail,
    UrlTail,
    clean_double_bullet_markers,
    is_source_url_line,
)

CTA: CtaLexicon = CtaLexicon.load()
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


def test_a_cta_line_of_the_tail_may_carry_hashtags() -> None:
    with_tags: CtaTailLine = CtaTailLine("Join us tonight and share your thoughts. #live", CTA)
    assert with_tags.is_cta and with_tags.has_split_hashtags
    assert with_tags.hashtags == TextTail(text="Join us tonight and share your thoughts.", tail="#live")
    plain: CtaTailLine = CtaTailLine("Subscribe to our channel", CTA)
    assert plain.is_cta and not plain.has_split_hashtags
    assert not CtaTailLine("Facts about the vote. #live", CTA).is_cta


def test_double_bullet_markers_keep_the_first_marker() -> None:
    assert clean_double_bullet_markers(f"{NEUTRAL} {NEUTRAL} Some text") == f"{NEUTRAL} Some text"
    assert clean_double_bullet_markers(f"  {NEUTRAL} {PIN} text\n{NEUTRAL} Normal") == f"  {NEUTRAL} text\n{NEUTRAL} Normal"
    assert clean_double_bullet_markers(f"{NEUTRAL} Normal bullet") == f"{NEUTRAL} Normal bullet"


def test_hashtag_lines_merge_without_case_repeats() -> None:
    fragments: TailFragments = TailFragments(hashtag_lines=("#AI #Climate", "#ai #Ukraine", "text #x"))
    assert fragments.hashtags_line == "#AI #Climate #Ukraine #x"
    assert TailFragments().hashtags_line == ""


def test_cta_lines_dedupe_without_case_and_spaces() -> None:
    joined: TailFragments = TailFragments(cta_lines=("Join  us", "join us", "", "Share")).followed_by(TailFragments())
    assert joined.cta_lines == ("Join us", "Share")


def test_the_collector_counts_changed_and_malformed_url_lines() -> None:
    collector: TailCollector = TailCollector()
    for line in ("https://example.org/?utm_source=x", "https://[bad", "https://example.com"):
        collector.add_url_line(line)
    assert (collector.urls, collector.url_changes, collector.malformed) == (
        ["https://example.org", "https://example.com"], 1, 1
    )


# --- абзацы


def test_url_tail_takes_clean_links_and_counts_changed_and_malformed() -> None:
    paragraph: str = "Body text (https://example.org/?utm_source=x https://[bad https://example.org"
    # Открывающая скобка перед ссылками остаётся в тексте: скобка — граница, а не часть ссылки.
    assert TailParagraph.of(paragraph).url_tail == UrlTail(
        text="Body text (", urls=("https://example.org",), change_count=1, malformed=1
    )
    assert TailParagraph.of("No links here.").url_tail == UrlTail(text="No links here.")
    assert TailParagraph.of("  ").url_tail == UrlTail(text="")


def test_hashtag_tail_trims_the_text_before_it() -> None:
    assert TailParagraph.of("Body words, #one #two").hashtag_tail == TextTail(text="Body words", tail="#one #two")
    assert TailParagraph.of("Body #one words").hashtag_tail == TextTail(text="Body #one words")
    assert TailParagraph.of("").hashtag_tail == TextTail(text="")


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


# --- объединение фрагментов


def test_fragments_followed_by_keep_the_earlier_first_and_drop_repeats() -> None:
    embedded: TailFragments = TailFragments(
        cta_lines=("Join  us",),
        hashtag_lines=("#AI #news",),
        source_urls=("https://example.org", "https://youtu.be/aaaaaaaaaaa"),
        url_change_count=2,
        malformed_urls_dropped=1,
    )
    trailing: TailFragments = TailFragments(
        cta_lines=("join us", "Share"),
        hashtag_lines=("#ai #Ukraine",),
        hashtags_split_from_cta=True,
        source_urls=("https://example.org", "https://example.com"),   # ссылки хвоста уже почищены SourceLink
        url_change_count=3,
        malformed_urls_dropped=4,
    )
    joined: TailFragments = embedded.followed_by(trailing)
    assert joined.cta_lines == ("Join us", "Share")
    assert joined.hashtag_lines == ("#AI #news", "#ai #Ukraine")
    assert joined.hashtags_line == "#AI #news #Ukraine"
    assert joined.hashtags_split_from_cta
    assert joined.source_urls == ("https://example.org", "https://youtu.be/aaaaaaaaaaa", "https://example.com")
    assert (joined.url_change_count, joined.malformed_urls_dropped) == (5, 5)
    assert trailing.followed_by(embedded).cta_lines == ("join us", "Share")


def test_empty_fragments_join_to_empty_fragments() -> None:
    assert TailFragments().followed_by(TailFragments()) == TailFragments()
    assert TailFragments().hashtags_line == ""
