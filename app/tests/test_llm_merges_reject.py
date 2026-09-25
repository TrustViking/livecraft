from __future__ import annotations

import pytest

from app.llm.merges.reject import RECOVERABLE_REJECT_CODES, MergeReject, MergeRejectCode
from app.ui import messages_ru as msg

DONOR_REASON_CODES: frozenset[str] = frozenset(
    {
        "not_json_object", "missing_keys", "extra_keys", "invalid_title", "invalid_description",
        "cta_as_first_paragraph", "duplicate_paragraph", "empty", "paragraph_underflow", "paragraph_overflow",
        "unexpected_error",
    }
)


def test_codes_are_exactly_the_donor_reason_codes_of_this_layer() -> None:
    assert {code.value for code in MergeRejectCode} == DONOR_REASON_CODES


@pytest.mark.parametrize("code", list(MergeRejectCode))
def test_every_code_has_a_human_text(code: MergeRejectCode) -> None:
    assert code.human == msg.MERGE_REJECT_TEXT[code.value]
    assert code.human.strip()


def test_texts_have_no_codes_without_a_member() -> None:
    assert set(msg.MERGE_REJECT_TEXT) == DONOR_REASON_CODES


def test_recoverable_codes_follow_the_donor_set() -> None:
    recoverable: set[MergeRejectCode] = {code for code in MergeRejectCode if code.is_recoverable}
    assert recoverable == {
        MergeRejectCode.CTA_AS_FIRST_PARAGRAPH,
        MergeRejectCode.DUPLICATE_PARAGRAPH,
        MergeRejectCode.PARAGRAPH_UNDERFLOW,
        MergeRejectCode.PARAGRAPH_OVERFLOW,
    }
    assert "hook_echo_in_body" in RECOVERABLE_REJECT_CODES and len(RECOVERABLE_REJECT_CODES) == 8


@pytest.mark.parametrize(
    ("code", "reason_codes"),
    [
        (MergeRejectCode.CTA_AS_FIRST_PARAGRAPH, ("cta_as_first_paragraph",)),
        (MergeRejectCode.DUPLICATE_PARAGRAPH, ("duplicate_paragraph",)),
        (MergeRejectCode.DESCRIPTION_EMPTY, ("empty",)),
        (MergeRejectCode.PARAGRAPH_OVERFLOW, ()),
        (MergeRejectCode.PARAGRAPH_UNDERFLOW, ()),
        (MergeRejectCode.NOT_JSON_OBJECT, ()),
        (MergeRejectCode.UNEXPECTED, ()),
    ],
)
def test_reason_codes_like_the_donor_parse_of_the_error_text(code: MergeRejectCode, reason_codes: tuple[str, ...]) -> None:
    assert MergeReject(code).reason_codes == reason_codes


def test_log_line_has_code_codes_and_quoted_detail() -> None:
    line: str = MergeReject(MergeRejectCode.EXTRA_KEYS, "title \n,x").log_line
    assert line == 'reason_code=extra_keys reason_codes=- recoverable=no detail="title \\n,x"'
    assert "\n" not in line
    assert MergeReject(MergeRejectCode.DUPLICATE_PARAGRAPH).log_line == (
        "reason_code=duplicate_paragraph reason_codes=duplicate_paragraph recoverable=yes detail=-"
    )


def test_log_line_cuts_a_long_detail() -> None:
    assert len(MergeReject(MergeRejectCode.EXTRA_KEYS, "k" * 1000).log_line) < 300
