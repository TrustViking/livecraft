from __future__ import annotations

import pytest

from app.llm.merges.reject import RECOVERABLE_REJECT_CODES, MergeReject, MergeRejectCode, MergeRejectStage
from app.ui import messages_ru as msg

DONOR_REASON_CODES: frozenset[str] = frozenset(
    {
        "not_json_object", "missing_keys", "extra_keys", "invalid_title", "invalid_description",
        "cta_as_first_paragraph", "duplicate_paragraph", "empty", "paragraph_underflow", "paragraph_overflow",
        "unexpected_error",
        # проверка покрытия (`merge_validation.py::_validate_coverage_preserving_merge_or_raise`)
        "per_source_enumeration", "hook_echo_in_body", "cta_in_hook", "insufficient_bullet_coverage",
        "compact_bullet_overflow", "excessive_emoji_usage", "overloaded_bullet", "numbered_title_dump", "semantic_gate",
    }
)
COVERAGE_CODES: tuple[MergeRejectCode, ...] = (
    MergeRejectCode.PER_SOURCE_ENUMERATION,
    MergeRejectCode.HOOK_ECHO_IN_BODY,
    MergeRejectCode.CTA_IN_HOOK,
    MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE,
    MergeRejectCode.COMPACT_BULLET_OVERFLOW,
    MergeRejectCode.EXCESSIVE_EMOJI_USAGE,
    MergeRejectCode.OVERLOADED_BULLET,
    MergeRejectCode.NUMBERED_TITLE_DUMP,
    MergeRejectCode.SEMANTIC_GATE,
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
        MergeRejectCode.HOOK_ECHO_IN_BODY,
        MergeRejectCode.CTA_IN_HOOK,
        MergeRejectCode.COMPACT_BULLET_OVERFLOW,
        MergeRejectCode.OVERLOADED_BULLET,
    }
    assert {code.value for code in recoverable} == RECOVERABLE_REJECT_CODES


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


@pytest.mark.parametrize("code", COVERAGE_CODES)
def test_coverage_codes_are_description_validation(code: MergeRejectCode) -> None:
    assert code.is_description_validation


@pytest.mark.parametrize("code", [code for code in COVERAGE_CODES if code is not MergeRejectCode.SEMANTIC_GATE])
def test_coverage_reject_reason_is_its_own_code(code: MergeRejectCode) -> None:
    reject: MergeReject = MergeReject(code)
    assert reject.reason_codes == (code.value,)
    assert reject.reason_code == code.value


def test_semantic_gate_codes_are_normalized_like_the_donor() -> None:
    reject: MergeReject = MergeReject.semantic_gate(
        [
            " semantic_source_2_coverage_missing ",
            "script_mix_contamination",
            "semantic_source_grounding_too_low",
            "semantic_too_generic",
            "",
            "script_mix_contamination",
            "semantic_source_10_coverage_missing",
        ]
    )
    assert reject.code is MergeRejectCode.SEMANTIC_GATE
    assert reject.validation_codes == ("weak_source_coverage", "script_mix_contamination", "overly_generic_body")
    assert reject.reason_codes == reject.validation_codes
    assert reject.reason_code == "weak_source_coverage"


def test_semantic_gate_without_codes_falls_back_to_the_gate_code() -> None:
    reject: MergeReject = MergeReject.semantic_gate([])
    assert reject.reason_codes == ("semantic_gate",)
    assert reject.reason_code == "semantic_gate"
    assert MergeReject.semantic_gate(["  ", ""]).reason_codes == ("semantic_gate",)


def test_partial_source_code_names_are_not_normalized() -> None:
    assert MergeReject.normalized_validation_codes(["semantic_source_x_coverage_missing", "semantic_source_1_coverage"]) == (
        "semantic_source_x_coverage_missing",
        "semantic_source_1_coverage",
    )


def test_recoverable_when_any_reason_is_recoverable() -> None:
    assert not MergeReject.semantic_gate(["script_mix_contamination"]).is_recoverable
    assert MergeReject(MergeRejectCode.SEMANTIC_GATE, validation_codes=("x", "duplicate_paragraph")).is_recoverable
    assert MergeReject(MergeRejectCode.OVERLOADED_BULLET).is_recoverable
    assert not MergeReject(MergeRejectCode.EXCESSIVE_EMOJI_USAGE).is_recoverable


def test_semantic_gate_log_line_names_the_first_gate_code() -> None:
    line: str = MergeReject.semantic_gate(["missing_block_spacing", "script_mix_contamination"]).log_line
    assert line == (
        "reason_code=missing_block_spacing reason_codes=missing_block_spacing,script_mix_contamination "
        "recoverable=no detail=-"
    )


@pytest.mark.parametrize("code", list(MergeRejectCode))
def test_every_code_has_a_stage(code: MergeRejectCode) -> None:
    assert code.stages
    assert code.stages <= set(MergeRejectStage)


def test_codes_of_both_stages() -> None:
    both: set[MergeRejectCode] = {code for code in MergeRejectCode if len(code.stages) == 2}
    assert both == {MergeRejectCode.CTA_AS_FIRST_PARAGRAPH, MergeRejectCode.DUPLICATE_PARAGRAPH}
