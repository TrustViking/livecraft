from __future__ import annotations

import pytest

from app.texts.hashtags import (
    HASHTAG_AFTER_SPACE_PATTERN,
    HASHTAG_PATTERN,
    HASHTAG_TAIL_PATTERN,
    HASHTAG_WORD_PATTERN,
    is_hashtags_line,
)


def test_hashtag_in_text_is_not_glued_to_a_word_on_the_left() -> None:
    assert HASHTAG_PATTERN.findall("#новини і c#sharp #ai#ml") == ["#новини", "#ai"]   # «#ml» приклеен к «ai»


def test_hashtag_after_space_is_the_group() -> None:
    assert [match.group(1) for match in HASHTAG_AFTER_SPACE_PATTERN.finditer("#a text #b c#d")] == ["#a", "#b"]


def test_hashtag_word_is_the_whole_word() -> None:
    assert HASHTAG_WORD_PATTERN.fullmatch("#тег")
    assert not HASHTAG_WORD_PATTERN.fullmatch("#")
    assert not HASHTAG_WORD_PATTERN.fullmatch("тег")


def test_hashtags_at_the_end_of_a_paragraph() -> None:
    match = HASHTAG_TAIL_PATTERN.search("Текст абзаца #один  #два ")
    assert match is not None and match.group(1) == "#один  #два"
    assert HASHTAG_TAIL_PATTERN.search("#один в начале") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("#a #b", True), ("  #a\n#b ", True), ("#a b", False), ("", False), ("   ", False), ("#", False)],
)
def test_hashtags_line(text: str, expected: bool) -> None:
    assert is_hashtags_line(text) is expected
