from __future__ import annotations

from app.core.safe_trim import (
    SENTENCE_END_CHARS, SafeTrimResult, TrimBoundary, TrimReason, TrimText, safe_trim_right,
)


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



def test_boundaries_are_tried_sentence_then_word_then_symbol() -> None:
    assert [boundary.reason for boundary in TrimBoundary] == [
        TrimReason.SENTENCE_BOUNDARY, TrimReason.WORD_BOUNDARY, TrimReason.SYMBOL_BOUNDARY,
    ]
    assert [boundary.min_share for boundary in TrimBoundary] == [0.6, 0.5, 0]


def test_sentence_end_marks_include_the_ellipsis() -> None:
    assert SENTENCE_END_CHARS == ".!?…"
    result: SafeTrimResult = safe_trim_right("Первая часть текста… вторая часть длинная", max_length=25)
    assert (result.text, result.reason) == ("Первая часть текста…", TrimReason.SENTENCE_BOUNDARY)


def test_boundary_earlier_than_its_share_is_not_found() -> None:
    assert TrimBoundary.SENTENCE.cut(TrimText("Hi. alpha beta gamma delta"), 20) == 0
    assert TrimBoundary.WORD.cut(TrimText("Hi. alpha beta gamma delta"), 20) == 15


def test_sentence_end_before_a_space_is_a_boundary() -> None:
    result: SafeTrimResult = safe_trim_right("Alpha beta gamma. Delta epsilon zeta", max_length=25)
    assert (result.text, result.reason) == ("Alpha beta gamma.", TrimReason.SENTENCE_BOUNDARY)


def test_dot_inside_a_word_is_not_a_sentence_end() -> None:
    """«v1.2»: за точкой не пробел — это не конец предложения, режется по слову."""
    result: SafeTrimResult = safe_trim_right("Release notes v1.2 are ready now", max_length=20)
    assert (result.text, result.reason) == ("Release notes v1.2", TrimReason.WORD_BOUNDARY)


def test_dot_inside_a_link_is_not_a_boundary() -> None:
    """Предел внутри ссылки: точка в «youtu.be», «:» и «/» — не места обрезки; ссылка уходит целиком."""
    text: str = "Intro words here. See https://youtu.be/abcdefghijk and more text"
    result: SafeTrimResult = safe_trim_right(text, max_length=40)
    assert (result.text, result.reason) == ("Intro words here. See", TrimReason.WORD_BOUNDARY)


def test_link_before_the_limit_stays_whole() -> None:
    result: SafeTrimResult = safe_trim_right("See https://youtu.be/abc then more words", max_length=30)
    assert (result.text, result.reason) == ("See https://youtu.be/abc then", TrimReason.WORD_BOUNDARY)


def test_link_ending_with_a_dot_is_cut_after_the_whole_link() -> None:
    """Ссылка с точкой в конце — одно целое: резать можно после неё, но не на точке внутри адреса."""
    text: str = "Watch the stream at https://youtu.be/abc. Next sentence is long enough"
    result: SafeTrimResult = safe_trim_right(text, max_length=50)
    assert (result.text, result.reason) == ("Watch the stream at https://youtu.be/abc.", TrimReason.SENTENCE_BOUNDARY)


def test_trim_text_knows_where_the_links_are() -> None:
    text: TrimText = TrimText("ab https://x.io/y cd")
    assert [text.is_inside_link(index) for index in (3, 4, 16, 17)] == [False, True, True, False]
    assert text.is_followed_by_space(2) and text.is_followed_by_space(20) and not text.is_followed_by_space(4)


def test_reason_is_written_by_its_value() -> None:
    assert f"{TrimReason.NOT_TRIMMED}" == "not_trimmed"
