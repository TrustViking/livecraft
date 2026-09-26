from __future__ import annotations

import pytest

from app.texts.similarity import TextPair, WordRule


def test_semantic_words_are_three_letters_or_digits_in_lower_case() -> None:
    assert WordRule.SEMANTIC.words("The Kyiv-2026 vote, ok? Рада і ЄС") == ["the", "kyiv", "2026", "vote", "рада"]


def test_spaced_words_keep_their_signs() -> None:
    assert WordRule.SPACED.words("One, two  THREE.") == ["one,", "two", "three."]


def test_jaccard_is_shared_words_over_all_words() -> None:
    pair: TextPair = TextPair("alpha beta gamma", "beta gamma delta")
    assert pair.jaccard == pytest.approx(2 / 4)


def test_jaccard_of_texts_without_words_is_none() -> None:
    assert TextPair("a, b", "!!").jaccard is None
    assert TextPair("", "", WordRule.SPACED).jaccard is None


def test_rule_of_the_word_changes_the_jaccard() -> None:
    first: str = "vote, now"
    second: str = "vote now"
    assert TextPair(first, second).jaccard == 1.0
    assert TextPair(first, second, WordRule.SPACED).jaccard == pytest.approx(1 / 3)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [("abcdef", "abcxyz", 0.5), ("abc", "abcdef", 1.0), ("", "abc", 0.0), ("xyz", "abc", 0.0)],
)
def test_prefix_ratio_is_the_common_start_over_the_shorter_text(first: str, second: str, expected: float) -> None:
    assert TextPair(first, second).prefix_ratio == pytest.approx(expected)
