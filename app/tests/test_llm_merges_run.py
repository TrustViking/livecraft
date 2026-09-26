"""Merge запуска: счётчики, итоги по дням, запрос попытки, остановка и строка итога."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta

import pytest

from app.llm.backend import LlmRequest
from app.llm.errors import LlmErrorKind
from app.llm.merges.answer import MergeAnswer
from app.llm.merges.outcome import MergeOutcome
from app.llm.merges.run import MergeArtifactStatus, MergeDayBlocks, MergeStopReason, MergeTally, SlotCount
from app.observability.log_event import LogArea
from app.tests.conftest import LLM_SETTINGS
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.merges import (
    EXPANDED_SOURCES,
    NOT_JSON,
    SLOT_START,
    STRONG_ANSWER,
    UNDERFLOW_ANSWER,
    answer,
    error,
    group_of,
    job_of,
    run_with,
)

def slot(
    accepted: bool,
    date: str = "16-10-2026",
    attempts: int = 1,
    rejected: int = 0,
    recoveries: int = 0,
    candidate: bool = True,
) -> SlotCount:
    """Счёт слота: провал merge — модель спрашивали, а ответ не принят."""
    return SlotCount(
        date=date,
        answer_accepted=accepted,
        rejected_attempts=rejected,
        retries=max(attempts - 1, 0),
        final_failure=attempts > 0 and not accepted,
        paragraph_recoveries=recoveries,
        is_candidate=candidate,
    )


@pytest.fixture
def llm_log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.LLM, logging.INFO) as capture:
        yield capture


# --- счётчики


def test_the_tally_adds_the_slots_up() -> None:
    tally: MergeTally = MergeTally()
    tally.record(slot(True, attempts=2, rejected=1, recoveries=2))
    tally.record(slot(False, attempts=3, rejected=3))
    tally.record(slot(False, attempts=0))
    tally.record(slot(False, attempts=0, candidate=False))
    assert (tally.merge_success, tally.validation_rejected, tally.retry_used, tally.final_failure) == (1, 4, 3, 1)
    assert tally.paragraph_recovery_used == 2
    assert (tally.merge_candidate_blocks, tally.real_merge_blocks, tally.fallback_merge_blocks) == (3, 1, 2)
    assert tally.had_real_merge_blocks


def test_an_accepted_answer_counts_as_a_merge_success() -> None:
    tally: MergeTally = MergeTally()
    tally.record(slot(True))
    assert (tally.merge_success, tally.final_failure, tally.real_merge_blocks, tally.fallback_merge_blocks) == (1, 0, 1, 0)
    assert tally.days["16-10-2026"].status is MergeArtifactStatus.FULL


def test_a_slot_that_needed_no_merge_is_not_a_candidate() -> None:
    tally: MergeTally = MergeTally()
    tally.record(slot(False, attempts=0, candidate=False))
    tally.record(slot(False, attempts=0, candidate=False))
    assert tally.merge_candidate_blocks == 0 and tally.days == {}
    assert not tally.had_real_merge_blocks


def test_artifacts_are_counted_by_day() -> None:
    tally: MergeTally = MergeTally()
    tally.record(slot(True, date="16-10-2026"))
    tally.record(slot(True, date="17-10-2026"))
    tally.record(slot(False, date="17-10-2026", attempts=2))
    tally.record(slot(False, date="18-10-2026", attempts=2))
    assert tally.days["16-10-2026"].status is MergeArtifactStatus.FULL
    assert tally.days["17-10-2026"].status is MergeArtifactStatus.PARTIAL
    assert tally.days["18-10-2026"].status is MergeArtifactStatus.FALLBACK_ONLY
    assert (tally.full_merge_artifacts, tally.partial_merge_artifacts) == (1, 1)


def test_a_day_without_candidates_has_no_artifact() -> None:
    assert MergeDayBlocks().status is MergeArtifactStatus.NONE


def test_the_summary_line_names_every_counter_in_order() -> None:
    tally: MergeTally = MergeTally()
    tally.record(slot(True, attempts=2, rejected=1))
    assert tally.event.text == (
        "merge_run_summary merge_success=1 validation_rejected=1 retry_used=1 final_failure=0 "
        "paragraph_recovery_used=0 real_merge_blocks=1 merge_candidate_blocks=1 fallback_merge_blocks=0 "
        "full_merge_artifacts=1 partial_merge_artifacts=0 had_real_merge_blocks=yes"
    )


# --- остановка


def test_the_first_stop_reason_stays(llm_log: LogCapture) -> None:
    merge_run, _ = run_with()
    assert merge_run.stop_reason is None and merge_run.event.text.endswith(" stop_reason=-")
    merge_run.stop(MergeStopReason.QUOTA)
    merge_run.stop(MergeStopReason.MODEL)
    assert merge_run.stop_reason is MergeStopReason.QUOTA
    assert merge_run.event.text.endswith(" stop_reason=quota_exhausted")
    stopped: list[str] = [line for line in llm_log.messages() if line.startswith("merge_run_stopped ")]
    assert stopped == ["merge_run_stopped provider=fake model=gpt-x reason=quota_exhausted"]


# --- запуск из нескольких слотов


def test_a_run_of_slots_adds_up() -> None:
    merge_run, backend = run_with(
        NOT_JSON, answer(STRONG_ANSWER),                       # слот 1: отказ, затем успех
        answer(UNDERFLOW_ANSWER), NOT_JSON, NOT_JSON,           # слот 2: три отказа — тексты источников
        error(LlmErrorKind.QUOTA),                              # слот 3: квота — остановка
    )
    outcomes: list[MergeOutcome] = [
        job_of(group_of(start=SLOT_START + timedelta(hours=hour)), merge_run).run() for hour in range(4)
    ]
    outcomes.append(job_of(group_of(EXPANDED_SOURCES[:1], SLOT_START + timedelta(hours=5)), merge_run).run())
    assert [item.merged for item in outcomes] == [True, False, False, False, False]
    assert outcomes[3].skipped_reason is MergeStopReason.QUOTA
    assert outcomes[4].skipped_reason is MergeStopReason.INSUFFICIENT_DESCRIPTIONS
    assert len(backend.requests) == 6 and backend.replies == []
    assert merge_run.tally.event.text == (
        "merge_run_summary merge_success=1 validation_rejected=4 retry_used=3 final_failure=2 "
        "paragraph_recovery_used=0 real_merge_blocks=1 merge_candidate_blocks=4 fallback_merge_blocks=3 "
        "full_merge_artifacts=0 partial_merge_artifacts=1 had_real_merge_blocks=yes"
    )
    assert merge_run.event.text.endswith(" stop_reason=quota_exhausted")


# --- запрос попытки и причины остановки


def test_the_request_of_an_attempt_carries_the_model_the_settings_and_the_merge_schema() -> None:
    merge_run, _ = run_with()
    request: LlmRequest = merge_run.request("промт", "merge_en_primary_1")
    assert (request.model_name, request.label, request.prompt) == ("gpt-x", "merge_en_primary_1", "промт")
    assert request.schema is MergeAnswer.SCHEMA and request.temperature == 0.0
    assert (request.max_output_tokens, request.timeout_sec) == (LLM_SETTINGS.max_output_tokens, float(LLM_SETTINGS.timeout_sec))


def test_only_the_quota_and_the_model_stop_the_run() -> None:
    assert [reason for reason in MergeStopReason if reason.stops_the_run] == [MergeStopReason.QUOTA, MergeStopReason.MODEL]
