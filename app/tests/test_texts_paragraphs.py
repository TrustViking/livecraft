from __future__ import annotations

import pytest

from app.texts.paragraphs import (
    has_duplicate_paragraphs,
    normalize_multiline_text,
    normalize_newlines,
    split_paragraphs,
    starts_with_any_prefix,
)


# --- донор: test_text_utils.py::TestSplitParagraphs
def test_split_basic() -> None:
    assert split_paragraphs("a\n\nb") == ["a", "b"]


def test_split_empty() -> None:
    assert split_paragraphs("") == []


def test_split_strips() -> None:
    assert split_paragraphs("  a  \n\n  b  ") == ["a", "b"]


def test_split_crlf() -> None:
    assert split_paragraphs("a\r\n\r\nb") == ["a", "b"]


def test_split_blank_line_of_spaces_is_a_break_and_single_newline_is_not() -> None:
    assert split_paragraphs("a\n  \t\nb\nc\n\n\n\n") == ["a", "b\nc"]


# --- донор: test_text_utils.py::TestHasDuplicateParagraphs
def test_no_dupes() -> None:
    assert has_duplicate_paragraphs("First para.\n\nSecond para.") is False


def test_exact_dupe() -> None:
    assert has_duplicate_paragraphs("Same long text here enough tokens.\n\nSame long text here enough tokens.") is True


def test_short_ignored() -> None:
    assert has_duplicate_paragraphs("Hi.\n\nHi.") is False


def test_near_duplicate_by_jaccard_counts() -> None:
    first: str = "one two three four five six seven eight nine ten"
    second: str = "one two three four five six seven eight nine eleven"   # 9 общих из 11
    assert has_duplicate_paragraphs(f"{first}\n\n{second}") is True
    assert has_duplicate_paragraphs(f"{first}\n\n{second}", jaccard_threshold=0.9) is False


def test_duplicate_is_case_and_whitespace_insensitive() -> None:
    assert has_duplicate_paragraphs("Same Long   Text here enough tokens.\n\nsame long text here\nenough tokens.") is True


def test_normalize_newlines_and_multiline() -> None:
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc"
    assert normalize_multiline_text("  a\r\n\r\nb  \r") == "a\n\nb"
    assert normalize_newlines(None) == ""   # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "prefixes", "expected"),
    [
        ("  Subscribe now", ("subscribe",), True),
        ("SUBSCRIBE", ("Subscribe",), True),
        ("Watch", ("", "  ", "watch"), True),
        ("", ("a",), False),
        ("x", ("", " "), False),
        ("Hello", ("world",), False),
    ],
)
def test_starts_with_any_prefix(text: str, prefixes: tuple[str, ...], expected: bool) -> None:
    assert starts_with_any_prefix(text, prefixes) is expected


def test_starts_with_any_prefix_options() -> None:
    assert starts_with_any_prefix("Leave   a comment", ("leave a comment",)) is False
    assert starts_with_any_prefix("Leave   a comment", ("leave a comment",), collapse_whitespace=True) is True
    assert starts_with_any_prefix("STRASSE", ("straße",), use_casefold=True) is True
    assert starts_with_any_prefix("STRASSE", ("straße",)) is False
