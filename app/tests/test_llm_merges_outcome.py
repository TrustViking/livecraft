"""Итог merge слота: история попыток, причины неудачи, счёт слота и строка итога."""
from __future__ import annotations

from app.llm.errors import LlmErrorKind
from app.llm.merges.attempt import AcceptedMerge, MergeAttemptResult, RejectedMerge
from app.llm.merges.check import MergeAttemptLabel, MergeCheck, MergeCheckRequest
from app.llm.merges.description import MergedDescription
from app.llm.merges.merge_rules import MergeRules
from app.llm.merges.outcome import AttemptHistory, MergeOutcome
from app.llm.merges.prompt import MergePrompt
from app.llm.merges.reject import MergeReject, MergeRejectCode
from app.llm.merges.retry import RetryProfile
from app.llm.merges.run import MergeStopReason, SlotCount
from app.slots.slot import SlotKey
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.sources.video import SourceVideo
from app.tests.fixtures.merges import (
    EXPANDED_SOURCES,
    MODEL,
    SLOT_START,
    STRONG_ANSWER,
    TITLE,
    error,
    sources_of,
)

RULES: MergeRules = MergeRules.load()
KEY: SlotKey = SlotKey(start=SLOT_START, language="en")
VIDEOS: tuple[SourceVideo, ...] = sources_of(EXPANDED_SOURCES)
PROMPT: MergePrompt = MergePrompt.of("en", VIDEOS, RULES.texts)
MERGED: SlotTexts = SlotTexts(title="T", description="D", origin=SlotTextOrigin.MERGED)
FROM_SOURCES: SlotTexts = SlotTexts(title="T", description="D", origin=SlotTextOrigin.SOURCE_COMPOSED)


def label(attempt: int) -> MergeAttemptLabel:
    return MergeAttemptLabel(KEY.slot_id, "en", MODEL, attempt)


def accepted(attempt: int) -> MergeAttemptResult:
    description: MergedDescription = MergedDescription(STRONG_ANSWER)
    request: MergeCheckRequest = MergeCheckRequest.of(label(attempt), TITLE, description, VIDEOS)
    check: MergeCheck = MergeCheck.of(request, description, RULES.lexicons)
    return MergeAttemptResult(label(attempt), AcceptedMerge(TITLE, check.description, check.diagnostics, 3, False))


def rejected(attempt: int, code: MergeRejectCode) -> MergeAttemptResult:
    return MergeAttemptResult(label(attempt), RejectedMerge(MergeReject(code)), raw_chars=10, raw_received=True)


def history_of(*results: MergeAttemptResult) -> AttemptHistory:
    history: AttemptHistory = AttemptHistory()
    for result in results:
        history.add(result, PROMPT, RULES)
    return history


def test_two_attempts_or_three_after_a_recoverable_reject() -> None:
    plain: AttemptHistory = history_of(rejected(1, MergeRejectCode.NOT_JSON_OBJECT))
    assert plain.can_try and plain.next_number == 2 and plain.max_attempts == 2
    assert plain.next_retry == RetryProfile.standard(("not_json_object",))
    recoverable: AttemptHistory = history_of(rejected(1, MergeRejectCode.PARAGRAPH_UNDERFLOW))
    assert recoverable.max_attempts == 3
    assert AttemptHistory().next_retry is None


def test_an_accepted_answer_quota_or_model_error_ends_the_attempts() -> None:
    assert not history_of(accepted(1)).can_try
    assert not history_of(MergeAttemptResult(label(1), error(LlmErrorKind.QUOTA).failure)).can_try
    assert not history_of(MergeAttemptResult(label(1), error(LlmErrorKind.AUTH).failure)).can_try
    assert history_of(MergeAttemptResult(label(1), error(LlmErrorKind.TIMEOUT).failure)).can_try


def test_the_outcome_of_attempts_counts_them() -> None:
    history: AttemptHistory = history_of(rejected(1, MergeRejectCode.NOT_JSON_OBJECT), accepted(2))
    outcome: MergeOutcome = MergeOutcome(KEY, 3, MERGED, history, paragraph_recoveries=1)
    assert (outcome.attempts, outcome.rejected_attempts, outcome.retries) == (2, 1, 1)
    assert outcome.answer_accepted and outcome.merged and outcome.reject_codes == () and not outcome.is_final_failure
    assert outcome.count == SlotCount(
        date=KEY.date_text, answer_accepted=True, rejected_attempts=1, retries=1, final_failure=False,
        paragraph_recoveries=1, is_candidate=True,
    )


def test_a_failed_outcome_names_the_last_reasons() -> None:
    history: AttemptHistory = history_of(rejected(1, MergeRejectCode.NOT_JSON_OBJECT), rejected(2, MergeRejectCode.MISSING_KEYS))
    outcome: MergeOutcome = MergeOutcome(KEY, 3, FROM_SOURCES, history)
    assert outcome.reject_codes == ("missing_keys",) and outcome.is_final_failure and history.last_answered is history.last


def test_a_skipped_slot_names_only_a_stop_of_the_run() -> None:
    stopped: MergeOutcome = MergeOutcome(KEY, 3, FROM_SOURCES, skipped_reason=MergeStopReason.QUOTA)
    assert stopped.reject_codes == ("quota_exhausted",) and stopped.is_candidate and not stopped.is_final_failure
    few: MergeOutcome = MergeOutcome(KEY, 3, FROM_SOURCES, skipped_reason=MergeStopReason.INSUFFICIENT_DESCRIPTIONS)
    assert few.reject_codes == () and not few.is_candidate
    assert not MergeOutcome(KEY, 1, FROM_SOURCES).is_candidate


def test_a_blocked_publication_is_an_accepted_answer_without_merged_texts() -> None:
    outcome: MergeOutcome = MergeOutcome(KEY, 3, FROM_SOURCES, history_of(accepted(1)), publish_blocked=True)
    assert outcome.answer_accepted and not outcome.merged and not outcome.is_final_failure
    assert outcome.event.text == (
        f"merge_attempt_outcome slot={KEY.slot_id} language=en source_count=3 success=yes merge_success=1 "
        "validation_rejected=0 retry_used=0 final_failure=0 publish_blocked=yes texts=source_composed reject_codes=- "
        "skipped=-"
    )
