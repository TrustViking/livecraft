from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

from app.llm.merges.prompt_texts import MergePromptTexts
from app.llm.merges.retry import RetryFacts, RetryMode, RetryProfile, RetrySignal

TEXTS: MergePromptTexts = MergePromptTexts.load()
NO_TEMPLATES: MergePromptTexts = dataclasses.replace(TEXTS, retry_reinforcements=MappingProxyType({}))
EXPANDED_SIGNALS: tuple[str, ...] = (
    "insufficient_expanded_body",
    "too_few_expanded_bullets",
    "overly_generic_body",
    "weak_source_coverage",
)


# --- расширенный профиль (донор: test_merge_contract_retry.py)


@pytest.mark.parametrize(
    ("signal", "focus", "fragment"),
    [
        ("insufficient_expanded_body", "body_depth", "post-hook body clearly denser"),
        ("too_few_expanded_bullets", "bullet_sufficiency", "enough distinct, meaningful bullets"),
        ("overly_generic_body", "source_specificity", "source-grounded specifics"),
        ("hook_dominates_body", "hook_restraint", "Keep the hook brief and functional"),
        ("weak_source_coverage", "source_spread", "Restore distinguishable spread across source lines or topic nodes"),
    ],
)
def test_expanded_retry_profile_targets_expected_weak_points(signal: str, focus: str, fragment: str) -> None:
    profile: RetryProfile = RetryProfile.expanded(3, (signal,), TEXTS)
    assert profile.mode is RetryMode.TARGETED
    assert profile.focus_tags == (focus,)
    assert fragment in "\n".join(profile.reinforcement_lines)


def test_three_source_targeted_retry_adds_combined_reinforcement_lines() -> None:
    text: str = "\n".join(RetryProfile.expanded(3, EXPANDED_SIGNALS, TEXTS).reinforcement_lines)
    assert "2 to 3 short agenda tracks" in text
    assert "cut generic filler bridges" in text
    assert "umbrella summary" not in text


def test_four_source_targeted_retry_adds_structured_source_specific_reinforcement() -> None:
    text: str = "\n".join(RetryProfile.expanded(4, EXPANDED_SIGNALS, TEXTS).reinforcement_lines)
    assert "2 to 3 short agenda tracks" in text
    assert "cut generic filler bridges" in text
    assert "do not collapse the post-hook body into one umbrella summary" in text
    assert "Build 2 to 3 meaningful thematic micro-blocks after the hook" in text
    assert "source-specific density, not just extra length" in text
    assert "Make every source leave a recognizable trace in the body" in text


def test_two_sources_get_only_the_signal_lines() -> None:
    profile: RetryProfile = RetryProfile.expanded(2, ("overly_generic_body",), TEXTS)
    assert profile.reinforcement_lines == TEXTS.expanded_retry["overly_generic_body"]


def test_unknown_signal_names_the_signals_and_has_no_focus() -> None:
    profile: RetryProfile = RetryProfile.expanded(2, (" odd ", "odd", "", "hook_dominates_body"), TEXTS)
    assert profile.reject_signals == ("odd", "odd", "hook_dominates_body")   # повторы снимаются до strip, как у донора
    assert profile.focus_tags == ()
    assert profile.focus_label == "none"
    assert profile.reinforcement_lines[0] == "Previous attempt was rejected: odd, odd, hook_dominates_body."


def test_no_signals_are_reported_as_unknown() -> None:
    profile: RetryProfile = RetryProfile.expanded(2, (), TEXTS)
    assert profile.reinforcement_lines[0] == "Previous attempt was rejected: unknown."
    assert profile.reject_signal_label == "none"
    assert profile.enabled


# --- направленные профили


def test_bullet_coverage_profile_fills_numbers_from_the_template() -> None:
    """Донор: test_four_source_retry_logs_structured_mode_and_uses_targeted_profile (строки профиля)."""
    facts: RetryFacts = RetryFacts(source_count=4, actual_bullets=3, required_bullets=5)
    profile: RetryProfile = RetryProfile.targeted(RetrySignal.INSUFFICIENT_BULLET_COVERAGE, facts, TEXTS)
    assert profile.mode is RetryMode.TARGETED
    assert profile.reject_signals == ("insufficient_bullet_coverage",)
    assert profile.focus_tags == ("bullet_coverage",)
    text: str = "\n".join(profile.reinforcement_lines)
    assert "Rewrite with at least 5" in text
    assert "Spread bullets across all 4 sources" in text
    assert "{" not in text


def test_hook_echo_uses_dedicated_retry_profile() -> None:
    """Донор: test_merge_structural_rules.py::test_hook_echo_uses_dedicated_retry_profile (без шаблона — запасные строки)."""
    profile: RetryProfile = RetryProfile.targeted(RetrySignal.HOOK_ECHO_IN_BODY, RetryFacts(), NO_TEMPLATES)
    assert profile.reject_signals == ("hook_echo_in_body",)
    assert "no_hook_echo" in profile.focus_tags
    assert profile.enabled
    assert "hook" in " ".join(profile.reinforcement_lines).lower()
    assert profile.reinforcement_lines == TEXTS.retry_fallbacks["hook_echo_in_body"]


def test_duplicate_profile_also_covers_both_cta_signals() -> None:
    profile: RetryProfile = RetryProfile.targeted(RetrySignal.DUPLICATE_PARAGRAPH, RetryFacts(), TEXTS)
    assert profile.reject_signals == ("duplicate_paragraph", "cta_as_first_paragraph", "cta_in_hook")
    assert profile.focus_label == "no_hook_duplication,hook_first"
    assert profile.reject_signal_label == "duplicate_paragraph,cta_as_first_paragraph,cta_in_hook"


def test_overloaded_profile_fills_the_overload_limits() -> None:
    profile: RetryProfile = RetryProfile.targeted(RetrySignal.OVERLOADED_BULLET, RetryFacts(overloaded_count=2), NO_TEMPLATES)
    assert profile.reinforcement_lines[0] == (
        "Previous attempt had 2 overloaded bullet(s) — single bullets listing 3+ multi-word names or spanning 280+ characters."
    )


def test_fallback_lines_fill_the_same_numbers_as_the_template() -> None:
    facts: RetryFacts = RetryFacts(actual_bullets=9, min_bullets=4, max_bullets=7, actual_paragraphs=8, max_paragraphs=4)
    compact: RetryProfile = RetryProfile.targeted(RetrySignal.COMPACT_BULLET_OVERFLOW, facts, NO_TEMPLATES)
    assert compact.reinforcement_lines[:2] == (
        "Previous attempt had 9 bullets but the compact contract allows maximum 7.",
        "RULE: For 2-source merge, the bullet block must have exactly 4 to 7 bullets.",
    )
    overflow: RetryProfile = RetryProfile.targeted(RetrySignal.PARAGRAPH_OVERFLOW, facts, NO_TEMPLATES)
    assert overflow.reinforcement_lines[0] == "Previous attempt produced 8 body paragraphs but the maximum is 4."


def test_empty_template_lines_are_skipped_and_an_empty_list_falls_back() -> None:
    texts: MergePromptTexts = dataclasses.replace(
        TEXTS,
        retry_reinforcements=MappingProxyType({"paragraph_underflow": ("  ", "  Only {x} line  "), "cta_as_first_paragraph": ("",)}),
    )
    underflow: RetryProfile = RetryProfile.targeted(RetrySignal.PARAGRAPH_UNDERFLOW, RetryFacts(), texts)
    assert underflow.reinforcement_lines == ("Only {x} line",)
    cta: RetryProfile = RetryProfile.targeted(RetrySignal.CTA_AS_FIRST_PARAGRAPH, RetryFacts(), texts)
    assert cta.reinforcement_lines == TEXTS.retry_fallbacks["cta_as_first_paragraph"]


@pytest.mark.parametrize("signal", list(RetrySignal))
def test_every_signal_has_template_and_fallback_lines(signal: RetrySignal) -> None:
    assert TEXTS.retry_reinforcements[signal.value]
    assert TEXTS.retry_fallbacks[signal.value]
    assert RetryProfile.targeted(signal, RetryFacts(), TEXTS).enabled


# --- обычный профиль и блок инструкции


def test_standard_profile_writes_no_instruction() -> None:
    """Донор: test_compact_retry_remains_standard_even_with_structured_expanded_reason_codes (профиль)."""
    profile: RetryProfile = RetryProfile.standard(("insufficient_expanded_body", "too_few_expanded_bullets"))
    assert profile.mode is RetryMode.STANDARD
    assert profile.focus_tags == ()
    assert not profile.enabled
    assert profile.instruction_block == ""


def test_standard_profile_drops_repeats_and_blanks_but_keeps_spacing() -> None:
    assert RetryProfile.standard(("a", " a", "a", "", "  ")).reject_signals == ("a", " a")
    assert RetryProfile.standard().reject_signals == ()


def test_instruction_block_lists_the_lines_under_the_header() -> None:
    profile: RetryProfile = RetryProfile(
        mode=RetryMode.TARGETED, reject_signals=("x",), focus_tags=(), reinforcement_lines=("one", "two")
    )
    assert profile.instruction_block == "RETRY INSTRUCTION:\none\ntwo"


def test_targeted_profile_without_lines_is_disabled() -> None:
    profile: RetryProfile = RetryProfile(mode=RetryMode.TARGETED, reject_signals=(), focus_tags=(), reinforcement_lines=())
    assert not profile.enabled
    assert profile.instruction_block == ""


# --- выбор профиля после отказа (донор: `MergeOrchestrator._select_retry_profile`)


@pytest.mark.parametrize(
    ("codes", "signal"),
    [
        (("paragraph_overflow", "overloaded_bullet"), RetrySignal.OVERLOADED_BULLET),
        (("cta_as_first_paragraph", "insufficient_bullet_coverage"), RetrySignal.INSUFFICIENT_BULLET_COVERAGE),
        (("hook_echo_in_body", "cta_as_first_paragraph"), RetrySignal.CTA_AS_FIRST_PARAGRAPH),
        (("duplicate_paragraph", "hook_echo_in_body"), RetrySignal.HOOK_ECHO_IN_BODY),
        (("cta_in_hook",), RetrySignal.DUPLICATE_PARAGRAPH),
        (("paragraph_underflow", "duplicate_paragraph"), RetrySignal.DUPLICATE_PARAGRAPH),
        (("paragraph_overflow", "paragraph_underflow"), RetrySignal.PARAGRAPH_UNDERFLOW),
        (("compact_bullet_overflow", "paragraph_overflow"), RetrySignal.PARAGRAPH_OVERFLOW),
        (("missing_block_spacing", "compact_bullet_overflow"), RetrySignal.COMPACT_BULLET_OVERFLOW),
    ],
)
def test_the_first_signal_in_donor_order_wins(codes: tuple[str, ...], signal: RetrySignal) -> None:
    assert RetrySignal.first_of(codes) is signal
    facts: RetryFacts = RetryFacts(source_count=3, actual_bullets=2, required_bullets=5, max_paragraphs=7)
    assert RetryProfile.after_reject(codes, facts, TEXTS) == RetryProfile.targeted(signal, facts, TEXTS)


def test_every_targeted_signal_has_a_place_in_the_order() -> None:
    assert {RetrySignal.first_of((signal.value,)) for signal in RetrySignal} == set(RetrySignal)


def test_a_reject_without_a_profile_gets_the_standard_retry_with_its_signals() -> None:
    codes: tuple[str, ...] = ("missing_block_spacing", "script_mix_contamination")
    assert RetrySignal.first_of(codes) is None
    profile: RetryProfile = RetryProfile.after_reject(codes, RetryFacts(), TEXTS)
    assert profile == RetryProfile.standard(codes) and profile.mode is RetryMode.STANDARD and not profile.enabled
