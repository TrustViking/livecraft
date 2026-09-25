from __future__ import annotations

from app.core.safe_trim import SafeTrimResult, safe_trim_right


def test_text_within_the_limit_is_not_trimmed() -> None:
    result: SafeTrimResult = safe_trim_right("short text", max_length=10)
    assert result == SafeTrimResult(text="short text", trimmed=False, reason="not_trimmed")


def test_zero_limit_empties_the_text() -> None:
    result: SafeTrimResult = safe_trim_right("abc", max_length=0)
    assert result == SafeTrimResult(text="", trimmed=True, reason="empty_limit")


def test_zero_limit_on_empty_text_is_not_a_trim() -> None:
    result: SafeTrimResult = safe_trim_right("", max_length=0)
    assert (result.text, result.trimmed, result.reason) == ("", False, "empty_limit")


def test_none_counts_as_empty_text() -> None:
    result: SafeTrimResult = safe_trim_right(None, max_length=5)  # type: ignore[arg-type]
    assert (result.text, result.reason) == ("", "not_trimmed")


def test_sentence_boundary_wins_when_it_is_late_enough() -> None:
    result: SafeTrimResult = safe_trim_right("First sentence here. Second part is long", max_length=30)
    assert (result.text, result.reason) == ("First sentence here.", "sentence_boundary")
    assert result.trimmed is True


def test_early_sentence_end_gives_way_to_a_word_boundary() -> None:
    result: SafeTrimResult = safe_trim_right("Hi. alpha beta gamma delta", max_length=20)
    assert (result.text, result.reason) == ("Hi. alpha beta", "word_boundary")


def test_word_boundary() -> None:
    result: SafeTrimResult = safe_trim_right("alpha beta gamma delta", max_length=15)
    assert (result.text, result.reason) == ("alpha beta", "word_boundary")


def test_punctuation_counts_as_a_word_boundary() -> None:
    result: SafeTrimResult = safe_trim_right("alpha,beta,gamma,delta", max_length=15)
    assert (result.text, result.reason) == ("alpha,beta,", "word_boundary")


def test_symbol_boundary_when_no_word_boundary_is_late_enough() -> None:
    result: SafeTrimResult = safe_trim_right("ab-cdefghijklmnop", max_length=10)
    assert (result.text, result.reason) == ("ab-", "symbol_boundary")


def test_too_early_space_falls_through_to_the_symbol_boundary() -> None:
    result: SafeTrimResult = safe_trim_right("ab cdefghijklmnop", max_length=10)
    assert (result.text, result.reason) == ("ab", "symbol_boundary")


def test_one_long_token_is_dropped() -> None:
    result: SafeTrimResult = safe_trim_right("abcdefghijklmnop", max_length=5)
    assert result == SafeTrimResult(text="", trimmed=True, reason="drop_long_token")


def test_cyrillic_words_are_word_characters() -> None:
    result: SafeTrimResult = safe_trim_right("привет большой мир", max_length=12)
    assert (result.text, result.reason) == ("привет", "word_boundary")

