from __future__ import annotations

import pytest

from app.texts.paragraphs import (
    SENTENCE_BREAK_PATTERN,
    collapse_spaces,
    has_duplicate_paragraphs,
    nonempty_lines,
    normalize_multiline_text,
    normalize_newlines,
    split_paragraphs,
)


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


def test_paragraphs_sharing_too_few_words_are_not_duplicates() -> None:
    first: str = "one two three four five six seven eight nine ten"
    second: str = "one two three four five six seven alpha beta gamma"   # 7 общих из 13 — меньше 0.72
    assert has_duplicate_paragraphs(f"{first}\n\n{second}") is False


def test_duplicate_is_case_and_whitespace_insensitive() -> None:
    assert has_duplicate_paragraphs("Same Long   Text here enough tokens.\n\nsame long text here\nenough tokens.") is True


def test_normalize_newlines_and_multiline() -> None:
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc"
    assert normalize_multiline_text("  a\r\n\r\nb  \r") == "a\n\nb"
    assert normalize_newlines(None) == ""   # type: ignore[arg-type]


def test_nonempty_lines_are_stripped_and_blank_lines_dropped() -> None:
    assert nonempty_lines("  a \n\n   \n b") == ["a", "b"]
    assert nonempty_lines("") == []


@pytest.mark.parametrize(("text", "expected"), [("  a \t b\n c  ", "a b c"), ("", ""), ("   ", "")])
def test_collapse_spaces_leaves_single_spaces_inside(text: str, expected: str) -> None:
    assert collapse_spaces(text) == expected


def test_sentences_break_after_the_end_marks_of_safe_trim() -> None:
    assert SENTENCE_BREAK_PATTERN.split("One. Two! Three? Four… Five") == ["One.", "Two!", "Three?", "Four…", "Five"]
    assert SENTENCE_BREAK_PATTERN.split("No break,here and there") == ["No break,here and there"]
