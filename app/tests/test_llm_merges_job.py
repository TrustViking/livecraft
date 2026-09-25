"""Merge одного слота: повторы с профилем по отказу, остановка по квоте и настройке модели, пропуск, итог-тексты."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from app.llm.errors import LlmErrorKind
from app.llm.merges.attempt import MergeRules
from app.llm.merges.description import MergedDescription
from app.llm.merges.job import MergeJob, MergeOutcome, MergeSkipReason, ParagraphEnforcement
from app.llm.merges.prompt import MergePrompt
from app.llm.merges.retry import RetryFacts, RetryProfile, RetrySignal
from app.llm.merges.run import MergeRun, MergeStopReason
from app.slots.builder import SlotGroup
from app.slots.slot import SlotKey
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.sources.video import SourceVideo
from app.tests.conftest import LLM_SETTINGS, LogCollector
from app.tests.test_llm_merges_attempt import (
    ADJACENT_ANSWER,
    CTA_FIRST_ANSWER,
    MODEL,
    OVERFLOW_ANSWER,
    OVERLOADED_ANSWER,
    STRONG_ANSWER,
    THIN_ANSWER,
    TITLE,
    UNDERFLOW_ANSWER,
    QueueBackend,
    answer,
    error,
)
from app.tests.test_llm_merges_check import EXPANDED_SOURCES, STRONG_BULLETS, STRONG_CLOSE, STRONG_HOOK, bullets
from app.tests.test_llm_merges_source import merge_video

RULES: MergeRules = MergeRules.load()
START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=timezone(timedelta(hours=3)))
NOT_JSON: str = "not json at all"


def group_of(pairs: tuple[tuple[str, str], ...] = EXPANDED_SOURCES, start: datetime = START) -> SlotGroup:
    videos: tuple[SourceVideo, ...] = tuple(
        merge_video(index + 2, title, body) for index, (title, body) in enumerate(pairs)
    )
    return SlotGroup.of(SlotKey(start=start, language="en"), videos)


def run_with(*replies: object) -> tuple[MergeRun, QueueBackend]:
    backend: QueueBackend = QueueBackend(replies=list(replies))
    return MergeRun(backend=backend, model=MODEL, settings=LLM_SETTINGS, rules=RULES), backend


def first_prompt(group: SlotGroup) -> MergePrompt:
    prompt: MergePrompt | object = MergePrompt.of("en", group.videos, RULES.texts)
    assert isinstance(prompt, MergePrompt)
    return prompt


@pytest.fixture
def llm_log() -> Iterator[LogCollector]:
    collector: LogCollector = LogCollector()
    logger: logging.Logger = logging.getLogger("livecraft.llm")
    logger.addHandler(collector)
    previous: int = logger.level
    logger.setLevel(logging.INFO)
    yield collector
    logger.setLevel(previous)
    logger.removeHandler(collector)


def lines_starting(log: LogCollector, event: str) -> list[str]:
    return [line for line in log.messages() if line.startswith(f"{event} ")]


# --- успех


def test_a_first_attempt_success_gives_merged_texts(llm_log: LogCollector) -> None:
    merge_run, backend = run_with(answer(STRONG_ANSWER))
    group: SlotGroup = group_of()
    outcome: MergeOutcome = MergeJob(group, merge_run).run()
    assert outcome.merged and outcome.texts.origin is SlotTextOrigin.MERGED
    assert outcome.texts.title == TITLE and outcome.texts.description.startswith(STRONG_HOOK)
    assert outcome.attempts == 1 and outcome.retries == 0 and outcome.rejected_attempts == 0
    assert outcome.reject_codes == () and outcome.skipped_reason is None and not outcome.is_final_failure
    assert len(backend.requests) == 1 and backend.requests[0].prompt == first_prompt(group).text
    context: str = f"slot={group.key.slot_id} language=en"
    assert lines_starting(llm_log, "merge_llm_primary_attempt") == [
        f"merge_llm_primary_attempt slot={group.key.slot_id} language=en model={MODEL} attempt=1 provider=fake stage=primary"
    ]
    assert lines_starting(llm_log, "merge_branch_ready") == [f"merge_branch_ready {context} generator_model={MODEL}"]
    assert lines_starting(llm_log, "merge_provider_summary") == [
        f"merge_provider_summary provider=fake model={MODEL} structured_ok=yes fallback_used=no parse_repair_used=no "
        "final_status=success"
    ]
    assert lines_starting(llm_log, "merge_post_enforcement") == [
        f"merge_post_enforcement {context} body_paragraphs_before=3 body_paragraphs_after=3 mutated=no "
        "recovery_applied=no reason=not_needed"
    ]
    assert merge_run.tally.merge_success == 1 and merge_run.tally.real_merge_blocks == 1


def test_the_input_summary_counts_sources_without_their_text(llm_log: LogCollector) -> None:
    merge_run, _ = run_with(answer(STRONG_ANSWER))
    group: SlotGroup = group_of()
    MergeJob(group, merge_run).run()
    total: int = sum(len(body) for _, body in EXPANDED_SOURCES)
    assert lines_starting(llm_log, "merge_input_summary") == [
        f"merge_input_summary slot={group.key.slot_id} language=en source_count=3 non_empty_descriptions=3 "
        f"titles_non_empty=3 source_desc_chars_total={total} source_desc_chars_passed_to_llm={total} "
        "hard_truncation=disabled merge_expected=yes merge_skip_reason=not_applicable"
    ]


# --- повтор с профилем по причине отказа


@pytest.mark.parametrize(
    ("bad_answer", "signal", "facts"),
    [
        (THIN_ANSWER, RetrySignal.INSUFFICIENT_BULLET_COVERAGE, {"actual_bullets": 3}),
        (OVERLOADED_ANSWER, RetrySignal.OVERLOADED_BULLET, {"actual_bullets": 6, "overloaded_count": 2}),
        (CTA_FIRST_ANSWER, RetrySignal.CTA_AS_FIRST_PARAGRAPH, {"overloaded_count": 1}),
        (ADJACENT_ANSWER, RetrySignal.DUPLICATE_PARAGRAPH, {"actual_bullets": 7}),
        (UNDERFLOW_ANSWER, RetrySignal.PARAGRAPH_UNDERFLOW, {"overloaded_count": 1, "actual_paragraphs": 1}),
        (OVERFLOW_ANSWER, RetrySignal.PARAGRAPH_OVERFLOW, {"overloaded_count": 1, "actual_paragraphs": 8}),
    ],
)
def test_a_rejected_attempt_is_retried_with_its_targeted_profile(
    bad_answer: str, signal: RetrySignal, facts: dict[str, int], llm_log: LogCollector
) -> None:
    merge_run, backend = run_with(answer(bad_answer), answer(STRONG_ANSWER))
    group: SlotGroup = group_of()
    outcome: MergeOutcome = MergeJob(group, merge_run).run()
    assert outcome.merged and outcome.attempts == 2 and outcome.rejected_attempts == 1 and outcome.retries == 1
    prompt: MergePrompt = first_prompt(group)
    expected_facts: RetryFacts = RetryFacts(
        source_count=3,
        required_bullets=5,
        min_bullets=prompt.contract.bullet_range_min,
        max_bullets=prompt.contract.bullet_range_max,
        max_paragraphs=prompt.contract.max_body_paragraphs,
        overloaded_count=facts.get("overloaded_count", 0),
        actual_bullets=facts.get("actual_bullets", 0),
        actual_paragraphs=facts.get("actual_paragraphs", 8),
    )
    retry: RetryProfile = RetryProfile.targeted(signal, expected_facts, RULES.texts)
    assert backend.prompts[0] == prompt.text
    assert backend.prompts[1] == prompt.with_retry(retry).text
    assert backend.prompts[1].endswith(retry.instruction_block)
    assert backend.requests[1].label == "merge_en_primary_2"
    retry_lines: list[str] = lines_starting(llm_log, "merge_llm_retry")
    assert len(retry_lines) == 1 and "retry_mode=targeted " in retry_lines[0]
    assert f"retry_reason_codes={retry.reject_signal_label} retry_focus={retry.focus_label} " in retry_lines[0]
    assert retry_lines[0].endswith("retry_structure=standard retry_source_count=3")
    assert len(lines_starting(llm_log, "merge_llm_response_invalid")) == 1


def test_the_insufficient_bullet_retry_names_the_real_bullet_count() -> None:
    """Донор подставлял 0 (диагностика не передавалась); здесь — пункты отвергнутой попытки."""
    merge_run, backend = run_with(answer(THIN_ANSWER), answer(STRONG_ANSWER))
    MergeJob(group_of(), merge_run).run()
    retry_block: str = backend.prompts[1].rsplit("RETRY INSTRUCTION:", 1)[1]
    assert "3" in retry_block and "5" in retry_block


def test_four_sources_name_the_structured_retry(llm_log: LogCollector) -> None:
    four: tuple[tuple[str, str], ...] = (*EXPANDED_SOURCES, ("Lviv grid repair logistics", "In Lviv, crews repair grids."))
    merge_run, _ = run_with(answer(UNDERFLOW_ANSWER), NOT_JSON, NOT_JSON)
    MergeJob(group_of(four), merge_run).run()
    assert "retry_structure=four_plus_structured retry_source_count=4" in lines_starting(llm_log, "merge_llm_retry")[0]


# --- число попыток


def test_two_attempts_when_no_reject_is_recoverable() -> None:
    merge_run, backend = run_with(NOT_JSON, NOT_JSON, answer(STRONG_ANSWER))
    outcome: MergeOutcome = MergeJob(group_of(), merge_run).run()
    assert not outcome.merged and outcome.attempts == 2 and len(backend.requests) == 2
    assert outcome.reject_codes == ("not_json_object",) and outcome.is_final_failure
    assert outcome.texts == SlotTexts.from_sources(group_of().videos)
    assert backend.prompts[1] == backend.prompts[0]          # обычный повтор без инструкции


def test_a_recoverable_reject_opens_the_third_attempt() -> None:
    merge_run, backend = run_with(answer(UNDERFLOW_ANSWER), NOT_JSON, answer(STRONG_ANSWER))
    outcome: MergeOutcome = MergeJob(group_of(), merge_run).run()
    assert outcome.merged and outcome.attempts == 3 and outcome.rejected_attempts == 2
    assert backend.requests[2].label == "merge_en_primary_3"


def test_three_attempts_at_most(llm_log: LogCollector) -> None:
    merge_run, backend = run_with(
        answer(UNDERFLOW_ANSWER), answer(UNDERFLOW_ANSWER), answer(UNDERFLOW_ANSWER), answer(STRONG_ANSWER)
    )
    group: SlotGroup = group_of()
    outcome: MergeOutcome = MergeJob(group, merge_run).run()
    assert not outcome.merged and outcome.attempts == 3 and len(backend.replies) == 1
    assert outcome.reject_codes == ("paragraph_underflow",)
    final: list[str] = [record.getMessage() for record in llm_log.records if record.levelno == logging.WARNING]
    assert final == [
        f"merge_llm_final_failure slot={group.key.slot_id} language=en provider=fake stage=primary "
        "code=paragraph_underflow fallback_used=no raw_response_received=yes "
        f'reason="body_paragraphs=1 allowed=2..7" raw_chars={len(answer(UNDERFLOW_ANSWER))}'
    ]
    assert lines_starting(llm_log, "merge_provider_summary")[-1].endswith("final_status=failed")


# --- сбои запроса


def test_quota_stops_the_slot_and_every_later_slot_goes_without_a_request(llm_log: LogCollector) -> None:
    merge_run, backend = run_with(error(LlmErrorKind.QUOTA), answer(STRONG_ANSWER))
    first: MergeOutcome = MergeJob(group_of(), merge_run).run()
    later_group: SlotGroup = group_of(start=START + timedelta(hours=1))
    later: MergeOutcome = MergeJob(later_group, merge_run).run()
    assert merge_run.stop_reason is MergeStopReason.QUOTA and len(backend.requests) == 1
    assert first.attempts == 1 and first.reject_codes == ("quota_exhausted",) and first.is_final_failure
    assert later.attempts == 0 and later.skipped_reason is MergeSkipReason.QUOTA_EXHAUSTED
    assert later.reject_codes == ("quota_exhausted",) and not later.is_final_failure
    assert later.texts.origin is SlotTextOrigin.SOURCE_COMPOSED
    aborted: list[str] = lines_starting(llm_log, "merge_branch_aborted_quota_exhausted")
    assert aborted == [
        f"merge_branch_aborted_quota_exhausted slot={group_of().key.slot_id} language=en",
        f"merge_branch_aborted_quota_exhausted slot={later_group.key.slot_id} language=en",
    ]
    assert "code=quota_exhausted raw_response_received=no" in lines_starting(llm_log, "merge_llm_response_invalid")[0]
    assert merge_run.tally.final_failure == 1 and merge_run.tally.fallback_merge_blocks == 2


def test_a_model_configuration_error_stops_merge_until_the_end_of_the_run(llm_log: LogCollector) -> None:
    merge_run, backend = run_with(error(LlmErrorKind.AUTH), answer(STRONG_ANSWER))
    first: MergeOutcome = MergeJob(group_of(), merge_run).run()
    later: MergeOutcome = MergeJob(group_of(start=START + timedelta(hours=1)), merge_run).run()
    assert merge_run.stop_reason is MergeStopReason.MODEL and len(backend.requests) == 1
    assert first.reject_codes == ("authentication_failed",) and first.texts.origin is SlotTextOrigin.SOURCE_COMPOSED
    assert later.skipped_reason is MergeSkipReason.MODEL_CONFIGURATION and later.attempts == 0
    assert len(lines_starting(llm_log, "merge_llm_fatal_model_error")) == 1
    assert lines_starting(llm_log, "merge_llm_response_invalid") == []
    assert len(lines_starting(llm_log, "merge_branch_aborted_model_error")) == 2


def test_another_error_is_unexpected_and_retried_without_an_instruction(llm_log: LogCollector) -> None:
    merge_run, backend = run_with(error(LlmErrorKind.TIMEOUT), answer(STRONG_ANSWER))
    outcome: MergeOutcome = MergeJob(group_of(), merge_run).run()
    assert outcome.merged and outcome.attempts == 2 and outcome.rejected_attempts == 0
    assert backend.prompts[1] == backend.prompts[0] and merge_run.stop_reason is None
    assert "code=unexpected_error raw_response_received=no" in lines_starting(llm_log, "merge_llm_response_invalid")[0]
    retry: str = lines_starting(llm_log, "merge_llm_retry")[0]
    assert "retry_mode=standard retry_reason_codes=unexpected_error retry_focus=none" in retry


# --- пропуск


def test_fewer_than_two_described_sources_skip_the_model(llm_log: LogCollector) -> None:
    merge_run, backend = run_with(answer(STRONG_ANSWER))
    pairs: tuple[tuple[str, str], ...] = (EXPANDED_SOURCES[0], ("Kharkiv rail and drone update", "  "))
    group: SlotGroup = group_of(pairs)
    outcome: MergeOutcome = MergeJob(group, merge_run).run()
    assert outcome.skipped_reason is MergeSkipReason.INSUFFICIENT_DESCRIPTIONS and backend.requests == []
    assert outcome.texts == SlotTexts.from_sources(group.videos) and outcome.reject_codes == ()
    assert not outcome.is_candidate and not outcome.is_final_failure
    assert lines_starting(llm_log, "merge_skipped") == [
        f"merge_skipped slot={group.key.slot_id} language=en non_empty_descriptions=1 reason=insufficient_descriptions"
    ]
    assert "merge_expected=no merge_skip_reason=insufficient_descriptions" in lines_starting(llm_log, "merge_input_summary")[0]
    assert merge_run.tally.merge_candidate_blocks == 0


def test_a_single_source_slot_is_never_merged_nor_enforced(llm_log: LogCollector) -> None:
    merge_run, backend = run_with(answer(STRONG_ANSWER))
    outcome: MergeOutcome = MergeJob(group_of(EXPANDED_SOURCES[:1]), merge_run).run()
    assert outcome.texts.origin is SlotTextOrigin.SOURCE_SINGLE and backend.requests == []
    assert lines_starting(llm_log, "merge_post_enforcement") == []


# --- выравнивание абзацев принятого описания


def test_enforcement_keeps_a_description_within_the_default_limit() -> None:
    enforcement: ParagraphEnforcement = ParagraphEnforcement.of(MergedDescription(STRONG_ANSWER))
    assert not enforcement.mutated and enforcement.description.text == STRONG_ANSWER
    assert (enforcement.body_paragraphs_before, enforcement.body_paragraphs_after) == (3, 3)


def test_enforcement_collapses_a_body_longer_than_four_paragraphs() -> None:
    long_body: str = "\n\n".join([STRONG_HOOK, bullets(STRONG_BULLETS), *(f"Extra {n} paragraph." for n in range(3)), STRONG_CLOSE])
    enforcement: ParagraphEnforcement = ParagraphEnforcement.of(MergedDescription(long_body))
    assert enforcement.mutated and enforcement.recovery_applied and enforcement.note == "collapsed_excess_body_paragraphs"
    assert enforcement.body_paragraphs_before == 6 and enforcement.body_paragraphs_after <= 4


def test_enforcement_of_an_empty_description_changes_nothing() -> None:
    enforcement: ParagraphEnforcement = ParagraphEnforcement.of(MergedDescription("  "))
    assert not enforcement.mutated and enforcement.note == "empty_description"
    assert enforcement.log_line("slot=s language=en") == (
        "merge_post_enforcement slot=s language=en body_paragraphs_before=0 body_paragraphs_after=0 mutated=no "
        "recovery_applied=no reason=empty_description"
    )


# --- итог и лог


def test_the_outcome_line_has_counts_and_no_texts() -> None:
    merge_run, _ = run_with(NOT_JSON, answer(STRONG_ANSWER))
    group: SlotGroup = group_of()
    outcome: MergeOutcome = MergeJob(group, merge_run).run()
    assert outcome.log_line == (
        f"merge_attempt_outcome slot={group.key.slot_id} language=en source_count=3 success=yes merge_success=1 "
        "validation_rejected=1 retry_used=1 final_failure=0 texts=merged reject_codes=none skipped=none"
    )


def test_no_model_answer_or_source_text_reaches_the_log(llm_log: LogCollector) -> None:
    merge_run, _ = run_with(answer(THIN_ANSWER), NOT_JSON, answer(OVERFLOW_ANSWER), answer(STRONG_ANSWER))
    MergeJob(group_of(), merge_run).run()
    MergeJob(group_of(start=START + timedelta(hours=1)), merge_run).run()
    joined: str = "\n".join(llm_log.messages())
    fragments: list[str] = [STRONG_HOOK[:40], STRONG_BULLETS[0], STRONG_CLOSE[:40], NOT_JSON, "Paragraph number", TITLE]
    fragments.extend(body[:40] for _, body in EXPANDED_SOURCES)
    for fragment in fragments:
        assert fragment not in joined
