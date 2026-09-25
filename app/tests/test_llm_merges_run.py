"""Merge запуска: счётчики донора, артефакты по дням, остановка и строка итога."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta

import pytest

from app.llm.errors import LlmErrorKind
from app.llm.merges.job import MergeJob, MergeOutcome, MergeSkipReason
from app.llm.merges.run import MergeArtifactStatus, MergeDayBlocks, MergeStopReason, MergeTally
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.conftest import LogCollector
from app.tests.test_llm_merges_attempt import STRONG_ANSWER, UNDERFLOW_ANSWER, answer, error
from app.tests.test_llm_merges_check import EXPANDED_SOURCES
from app.tests.test_llm_merges_job import NOT_JSON, START, group_of, run_with

MERGED: SlotTexts = SlotTexts(title="T", description="D", origin=SlotTextOrigin.MERGED)
FROM_SOURCES: SlotTexts = SlotTexts(title="T", description="D", origin=SlotTextOrigin.SOURCE_COMPOSED)


def outcome(
    texts: SlotTexts,
    date: str = "16-10-2026",
    attempts: int = 1,
    rejected: int = 0,
    skipped: MergeSkipReason | None = None,
    recoveries: int = 0,
    sources: int = 3,
) -> MergeOutcome:
    return MergeOutcome(
        slot_id=f"{date}_1900_en",
        date=date,
        language="en",
        source_count=sources,
        texts=texts,
        attempts=attempts,
        rejected_attempts=rejected,
        skipped_reason=skipped,
        paragraph_recoveries=recoveries,
    )


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


# --- счётчики


def test_the_tally_counts_like_the_donor_summary() -> None:
    tally: MergeTally = MergeTally()
    tally.record(outcome(MERGED, attempts=2, rejected=1, recoveries=2))
    tally.record(outcome(FROM_SOURCES, attempts=3, rejected=3))
    tally.record(outcome(FROM_SOURCES, attempts=0, skipped=MergeSkipReason.QUOTA_EXHAUSTED))
    tally.record(outcome(FROM_SOURCES, attempts=0, skipped=MergeSkipReason.INSUFFICIENT_DESCRIPTIONS))
    assert (tally.merge_success, tally.validation_rejected, tally.retry_used, tally.final_failure) == (1, 4, 3, 1)
    assert tally.paragraph_recovery_used == 2
    assert (tally.merge_candidate_blocks, tally.real_merge_blocks, tally.fallback_merge_blocks) == (3, 1, 2)
    assert tally.had_real_merge_blocks


def test_a_slot_that_needed_no_merge_is_not_a_candidate() -> None:
    tally: MergeTally = MergeTally()
    tally.record(outcome(FROM_SOURCES, attempts=0, skipped=MergeSkipReason.INSUFFICIENT_DESCRIPTIONS))
    tally.record(outcome(FROM_SOURCES, attempts=0, skipped=MergeSkipReason.MODEL_CONFIGURATION, sources=1))
    assert tally.merge_candidate_blocks == 0 and tally.days == {}
    assert not tally.had_real_merge_blocks


def test_artifacts_are_counted_by_day() -> None:
    tally: MergeTally = MergeTally()
    tally.record(outcome(MERGED, date="16-10-2026"))
    tally.record(outcome(MERGED, date="17-10-2026"))
    tally.record(outcome(FROM_SOURCES, date="17-10-2026", attempts=2))
    tally.record(outcome(FROM_SOURCES, date="18-10-2026", attempts=2))
    assert tally.days["16-10-2026"].status is MergeArtifactStatus.FULL
    assert tally.days["17-10-2026"].status is MergeArtifactStatus.PARTIAL
    assert tally.days["18-10-2026"].status is MergeArtifactStatus.FALLBACK_ONLY
    assert (tally.full_merge_artifacts, tally.partial_merge_artifacts) == (1, 1)


def test_a_day_without_candidates_has_no_artifact() -> None:
    assert MergeDayBlocks().status is MergeArtifactStatus.NONE


def test_the_summary_line_has_the_donor_keys_in_order() -> None:
    tally: MergeTally = MergeTally()
    tally.record(outcome(MERGED, attempts=2, rejected=1))
    assert tally.log_line == (
        "merge_run_summary merge_success=1 validation_rejected=1 retry_used=1 final_failure=0 "
        "paragraph_recovery_used=0 real_merge_blocks=1 merge_candidate_blocks=1 fallback_merge_blocks=0 "
        "full_merge_artifacts=1 partial_merge_artifacts=0 had_real_merge_blocks=yes"
    )


# --- остановка


def test_the_first_stop_reason_stays(llm_log: LogCollector) -> None:
    merge_run, _ = run_with()
    assert not merge_run.is_stopped and merge_run.log_line.endswith(" stop_reason=none")
    merge_run.stop(MergeStopReason.QUOTA)
    merge_run.stop(MergeStopReason.MODEL)
    assert merge_run.is_stopped and merge_run.stop_reason is MergeStopReason.QUOTA
    assert merge_run.log_line.endswith(" stop_reason=quota_exhausted")
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
        MergeJob(group_of(start=START + timedelta(hours=hour)), merge_run).run() for hour in range(4)
    ]
    outcomes.append(MergeJob(group_of(EXPANDED_SOURCES[:1], START + timedelta(hours=5)), merge_run).run())
    assert [item.merged for item in outcomes] == [True, False, False, False, False]
    assert outcomes[3].skipped_reason is MergeSkipReason.QUOTA_EXHAUSTED
    assert outcomes[4].skipped_reason is MergeSkipReason.INSUFFICIENT_DESCRIPTIONS
    assert len(backend.requests) == 6 and backend.replies == []
    assert merge_run.tally.log_line == (
        "merge_run_summary merge_success=1 validation_rejected=4 retry_used=3 final_failure=2 "
        "paragraph_recovery_used=0 real_merge_blocks=1 merge_candidate_blocks=4 fallback_merge_blocks=3 "
        "full_merge_artifacts=0 partial_merge_artifacts=1 had_real_merge_blocks=yes"
    )
    assert merge_run.log_line.endswith(" stop_reason=quota_exhausted")
