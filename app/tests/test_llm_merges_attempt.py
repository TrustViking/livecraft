"""Одна попытка merge: запрос через разъём, разбор, проверка, итог значением и выбор следующего повтора."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from app.llm.backend import LlmRequest, LlmResponse
from app.llm.errors import LlmErrorKind, LlmRequestError
from app.llm.merges.attempt import (
    MERGE_RESPONSE_SCHEMA,
    MERGE_SCHEMA_NAME,
    OVERFLOW_PARAGRAPHS_UNKNOWN,
    OVERLOADED_COUNT_UNKNOWN,
    MergeAttempt,
    MergeAttemptResult,
    MergeRules,
    RejectedMerge,
)
from app.llm.merges.check import MergeAttemptLabel
from app.llm.merges.contract import MergeContract
from app.llm.merges.description import MergedDescription
from app.llm.merges.prompt import MergePrompt
from app.llm.merges.reject import MergeReject, MergeRejectCode
from app.llm.merges.retry import RetryFacts, RetryMode, RetryProfile, RetrySignal
from app.llm.usage import RunUsage
from app.sources.video import SourceVideo
from app.tests.conftest import LLM_SETTINGS, LogCollector
from app.tests.test_llm_merges_check import (
    EXPANDED_SOURCES,
    HOOK,
    LONG_ALPHA,
    LONG_BETA,
    STRONG_BULLETS,
    STRONG_CLOSE,
    STRONG_HOOK,
    bullets,
    sources_of,
)

RULES: MergeRules = MergeRules.load()
FAKE_BACKEND: str = "fake"
MODEL: str = "gpt-x"
TITLE: str = "Brussels, Kharkiv, Geneva: the operational agenda tonight"
STRONG_ANSWER: str = f"{STRONG_HOOK}\n\nIn this stream you'll see:\n{bullets(STRONG_BULLETS)}\n\n{STRONG_CLOSE}"
THIN_ANSWER: str = f"{STRONG_HOOK}\n\n{bullets(STRONG_BULLETS[:3])}\n\n{STRONG_CLOSE}"
OVERLOADED_ANSWER: str = f"{STRONG_HOOK}\n\n{bullets([LONG_ALPHA, LONG_BETA, *STRONG_BULLETS[:4]])}\n\n{STRONG_CLOSE}"
CTA_FIRST_ANSWER: str = f"Subscribe to the channel for more updates.\n\n{STRONG_HOOK}\n\n{bullets(STRONG_BULLETS)}"
ADJACENT_ANSWER: str = (
    f"{STRONG_HOOK}\n\n{bullets([STRONG_BULLETS[0]])}\n{bullets([STRONG_BULLETS[0] + ' again'])}\n"
    f"{bullets(STRONG_BULLETS[1:])}"
)
UNDERFLOW_ANSWER: str = "One single paragraph only."
OVERFLOW_ANSWER: str = "\n\n".join(
    f"Paragraph number {index} with its own distinct content about topic {index}." for index in range(8)
)


def answer(description: str, title: str = TITLE) -> str:
    """Ответ модели по схеме merge."""
    return json.dumps({"title": title, "description": description}, ensure_ascii=False)


def error(kind: LlmErrorKind) -> LlmRequestError:
    return LlmRequestError(kind, backend=FAKE_BACKEND, detail=kind.value)


@dataclass
class QueueBackend:
    """Нейросеть за разъёмом: сохранённые ответы по очереди; отказ — `LlmRequestError` в очереди."""

    replies: list[str | LlmRequestError] = field(default_factory=list)
    structured: bool = False
    requests: list[LlmRequest] = field(default_factory=list)
    run_usage: RunUsage = field(default_factory=RunUsage)

    @property
    def name(self) -> str:
        return FAKE_BACKEND

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        reply: str | LlmRequestError = self.replies.pop(0)
        if isinstance(reply, LlmRequestError):
            raise reply
        payload: object = json.loads(reply) if self.structured else None
        self.run_usage.add(None)
        return LlmResponse(
            text=reply,
            structured=payload if isinstance(payload, dict) else None,
            model=request.model_name,
        )

    def probe(self, model_name: str) -> LlmResponse | LlmRequestError:
        return error(LlmErrorKind.FAILED)

    @property
    def prompts(self) -> list[str]:
        return [request.prompt for request in self.requests]


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


def three_sources() -> tuple[SourceVideo, ...]:
    return sources_of(EXPANDED_SOURCES)


def prompt_for(videos: tuple[SourceVideo, ...], language: str = "en") -> MergePrompt:
    prompt: MergePrompt | object = MergePrompt.of(language, videos, RULES.texts)
    assert isinstance(prompt, MergePrompt)
    return prompt


def attempt_with(backend: QueueBackend, videos: tuple[SourceVideo, ...] | None = None, language: str = "en") -> MergeAttempt:
    sources: tuple[SourceVideo, ...] = videos if videos is not None else three_sources()
    label: MergeAttemptLabel = MergeAttemptLabel(slot_id="16-10-2026_1900_en", language=language, model=MODEL, attempt=1)
    return MergeAttempt(prompt_for(sources, language), label, sources, backend, LLM_SETTINGS, RULES)


def run_once(reply: str | LlmRequestError, structured: bool = False) -> MergeAttemptResult:
    return attempt_with(QueueBackend(replies=[reply], structured=structured)).run()


def rejected_of(result: MergeAttemptResult) -> RejectedMerge:
    assert result.rejected is not None, result
    return result.rejected


# --- запрос


def test_the_request_carries_the_merge_schema_zero_temperature_and_settings() -> None:
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)])
    attempt: MergeAttempt = attempt_with(backend)
    attempt.run()
    request: LlmRequest = backend.requests[0]
    assert request.schema is MERGE_RESPONSE_SCHEMA and request.schema["name"] == MERGE_SCHEMA_NAME == "merge_summary_v2"
    assert request.schema["schema"]["required"] == ["title", "description"]
    assert request.temperature == 0.0 and request.model_name == MODEL
    assert request.max_output_tokens == LLM_SETTINGS.max_output_tokens
    assert request.timeout_sec == float(LLM_SETTINGS.timeout_sec)
    assert request.label == "merge_en_primary_1"
    assert request.prompt == attempt.prompt.text


# --- принятый ответ


def test_a_strong_answer_is_accepted_with_its_diagnostics(llm_log: LogCollector) -> None:
    result: MergeAttemptResult = run_once(answer(STRONG_ANSWER))
    assert result.accepted is not None and result.rejected is None and result.error is None
    assert result.accepted.title == TITLE
    assert result.accepted.paragraph_count == 3 and not result.accepted.tail_recovery_applied
    assert result.accepted.diagnostics.bullet_points_count == len(STRONG_BULLETS)
    assert result.code == "" and result.codes == () and not result.is_recoverable
    assert result.raw_chars == len(answer(STRONG_ANSWER)) and result.raw_received
    messages: list[str] = llm_log.messages()
    valid: list[str] = [line for line in messages if line.startswith("merge_llm_response_valid ")]
    assert valid == [
        f"merge_llm_response_valid {result.label.prefix} title_length={len(TITLE)} "
        f"description_length={len(result.accepted.description.text)} paragraph_count=3 youtube_links_in_llm_output=0"
    ]
    assert any(line.startswith("merge_style_coverage ") for line in messages)
    assert any(line.startswith("merge_semantic_gate ") for line in messages)


def test_the_structured_payload_is_used_when_the_backend_gives_it() -> None:
    result: MergeAttemptResult = run_once(answer(STRONG_ANSWER), structured=True)
    assert result.accepted is not None


def test_homoglyphs_are_repaired_and_logged_before_the_check(llm_log: LogCollector) -> None:
    videos: tuple[SourceVideo, ...] = sources_of(EXPANDED_SOURCES[:2])
    mixed: str = "Цей eфір розбирає рішення уряду щодо бюджету та наслідки для регіонів у найближчі тижні.\n\nДругий абзац."
    attempt_with(QueueBackend(replies=[answer(mixed)]), videos, language="uk").run()
    repaired: list[str] = [line for line in llm_log.messages() if line.startswith("merge_script_mix_repaired ")]
    assert len(repaired) == 1 and "tokens_repaired=1" in repaired[0]


# --- отказы и числа для повтора


def test_a_parse_reject_has_no_description_and_no_bullets() -> None:
    result: MergeAttemptResult = run_once("not json at all")
    rejected: RejectedMerge = rejected_of(result)
    assert rejected.reject.code is MergeRejectCode.NOT_JSON_OBJECT
    assert rejected.description is None and rejected.bullet_count == 0
    assert rejected.overloaded_count == OVERLOADED_COUNT_UNKNOWN
    assert result.code == "not_json_object" and result.codes == ("not_json_object",)
    assert result.raw_chars == len("not json at all") and result.raw_received


def test_too_few_bullets_carry_the_bullet_count_of_the_rejected_attempt() -> None:
    result: MergeAttemptResult = run_once(answer(THIN_ANSWER))
    rejected: RejectedMerge = rejected_of(result)
    assert rejected.reject.code is MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE
    assert rejected.bullet_count == 3 and rejected.description is not None
    assert result.is_recoverable is False
    contract: MergeContract = prompt_for(three_sources()).contract
    retry: RetryProfile = result.next_retry(contract, 3, RULES.texts)
    facts: RetryFacts = rejected.facts(contract, 3)
    assert facts.actual_bullets == 3 and facts.required_bullets == 5 and facts.source_count == 3
    assert retry == RetryProfile.targeted(RetrySignal.INSUFFICIENT_BULLET_COVERAGE, facts, RULES.texts)


def test_overloaded_bullets_are_counted_in_the_rejected_description() -> None:
    result: MergeAttemptResult = run_once(answer(OVERLOADED_ANSWER))
    rejected: RejectedMerge = rejected_of(result)
    assert rejected.reject.code is MergeRejectCode.OVERLOADED_BULLET and result.is_recoverable
    assert rejected.overloaded_count == 2
    retry: RetryProfile = result.next_retry(prompt_for(three_sources()).contract, 3, RULES.texts)
    assert retry.reject_signals == ("overloaded_bullet",) and retry.mode is RetryMode.TARGETED


def test_paragraph_overflow_names_the_paragraph_count_of_the_attempt() -> None:
    result: MergeAttemptResult = run_once(answer(OVERFLOW_ANSWER))
    rejected: RejectedMerge = rejected_of(result)
    assert rejected.reject.code is MergeRejectCode.PARAGRAPH_OVERFLOW and rejected.reject.paragraph_count == 8
    contract: MergeContract = prompt_for(three_sources()).contract
    facts: RetryFacts = rejected.facts(contract, 3)
    assert facts.actual_paragraphs == 8 and facts.max_paragraphs == contract.max_body_paragraphs == 7
    assert result.next_retry(contract, 3, RULES.texts) == RetryProfile.targeted(
        RetrySignal.PARAGRAPH_OVERFLOW, facts, RULES.texts
    )


def test_paragraph_underflow_is_recoverable() -> None:
    result: MergeAttemptResult = run_once(answer(UNDERFLOW_ANSWER))
    rejected: RejectedMerge = rejected_of(result)
    assert rejected.reject.code is MergeRejectCode.PARAGRAPH_UNDERFLOW and rejected.reject.paragraph_count == 1
    assert result.is_recoverable
    retry: RetryProfile = result.next_retry(prompt_for(three_sources()).contract, 3, RULES.texts)
    assert retry.reject_signals == ("paragraph_underflow",)


def test_an_unknown_paragraph_count_falls_back_to_the_donor_number() -> None:
    contract: MergeContract = prompt_for(three_sources()).contract
    facts: RetryFacts = RejectedMerge(MergeReject(MergeRejectCode.PARAGRAPH_OVERFLOW)).facts(contract, 3)
    assert facts.actual_paragraphs == OVERFLOW_PARAGRAPHS_UNKNOWN == 8


@pytest.mark.parametrize(
    ("code", "signal"),
    [
        (MergeRejectCode.HOOK_ECHO_IN_BODY, RetrySignal.HOOK_ECHO_IN_BODY),
        (MergeRejectCode.CTA_IN_HOOK, RetrySignal.DUPLICATE_PARAGRAPH),
        (MergeRejectCode.DUPLICATE_PARAGRAPH, RetrySignal.DUPLICATE_PARAGRAPH),
        (MergeRejectCode.CTA_AS_FIRST_PARAGRAPH, RetrySignal.CTA_AS_FIRST_PARAGRAPH),
    ],
)
def test_each_repetition_reject_has_its_targeted_retry(code: MergeRejectCode, signal: RetrySignal) -> None:
    contract: MergeContract = prompt_for(three_sources()).contract
    rejected: RejectedMerge = RejectedMerge(MergeReject(code), MergedDescription(STRONG_ANSWER), 6)
    result: MergeAttemptResult = MergeAttemptResult(label=MergeAttemptLabel("s", "en", MODEL, 1), rejected=rejected)
    assert result.next_retry(contract, 3, RULES.texts) == RetryProfile.targeted(
        signal, rejected.facts(contract, 3), RULES.texts
    )


def test_compact_overflow_retry_names_the_bullets_and_the_contract_range() -> None:
    videos: tuple[SourceVideo, ...] = sources_of(EXPANDED_SOURCES[:2])
    contract: MergeContract = prompt_for(videos).contract
    rejected: RejectedMerge = RejectedMerge(MergeReject(MergeRejectCode.COMPACT_BULLET_OVERFLOW), None, 9)
    facts: RetryFacts = rejected.facts(contract, 2)
    assert (facts.actual_bullets, facts.min_bullets, facts.max_bullets) == (9, 4, 7)
    result: MergeAttemptResult = MergeAttemptResult(label=MergeAttemptLabel("s", "en", MODEL, 1), rejected=rejected)
    retry: RetryProfile = result.next_retry(contract, 2, RULES.texts)
    assert retry == RetryProfile.targeted(RetrySignal.COMPACT_BULLET_OVERFLOW, facts, RULES.texts)
    assert any("9" in line for line in retry.reinforcement_lines)


def test_a_reject_without_its_own_retry_gets_the_standard_retry() -> None:
    result: MergeAttemptResult = run_once(json.dumps({"title": "T"}))
    retry: RetryProfile = result.next_retry(prompt_for(three_sources()).contract, 3, RULES.texts)
    assert retry == RetryProfile.standard(("missing_keys",)) and not retry.enabled


def test_the_cta_opening_is_rejected_on_parse_and_retried_with_its_profile() -> None:
    result: MergeAttemptResult = run_once(answer(CTA_FIRST_ANSWER))
    assert rejected_of(result).reject.code is MergeRejectCode.CTA_AS_FIRST_PARAGRAPH and result.is_recoverable
    retry: RetryProfile = result.next_retry(prompt_for(three_sources()).contract, 3, RULES.texts)
    assert retry.reject_signals == ("cta_as_first_paragraph",)


def test_adjacent_repeated_bullets_are_a_duplicate_paragraph() -> None:
    result: MergeAttemptResult = run_once(answer(ADJACENT_ANSWER))
    rejected: RejectedMerge = rejected_of(result)
    assert rejected.reject.code is MergeRejectCode.DUPLICATE_PARAGRAPH and rejected.bullet_count == 7


# --- сбои запроса


def test_quota_is_an_error_value_that_stops_the_run() -> None:
    result: MergeAttemptResult = run_once(error(LlmErrorKind.QUOTA))
    assert result.error is not None and result.is_quota and not result.is_model_configuration
    assert result.code == "quota_exhausted" and result.codes == ("quota_exhausted",)
    assert result.raw_chars == 0 and not result.raw_received


@pytest.mark.parametrize("kind", [LlmErrorKind.AUTH, LlmErrorKind.MODEL_NOT_FOUND, LlmErrorKind.NOT_CONFIGURED])
def test_a_model_configuration_error_is_named_by_its_kind(kind: LlmErrorKind) -> None:
    result: MergeAttemptResult = run_once(error(kind))
    assert result.is_model_configuration and not result.is_quota
    assert result.code == kind.value


@pytest.mark.parametrize("kind", [LlmErrorKind.TIMEOUT, LlmErrorKind.SERVER, LlmErrorKind.EMPTY_OUTPUT])
def test_any_other_error_is_unexpected_and_retried_plainly(kind: LlmErrorKind) -> None:
    result: MergeAttemptResult = run_once(error(kind))
    assert not result.is_quota and not result.is_model_configuration
    assert result.code == "unexpected_error"
    retry: RetryProfile = result.next_retry(prompt_for(three_sources()).contract, 3, RULES.texts)
    assert retry == RetryProfile.standard(("unexpected_error",))


# --- строки лога


def test_the_invalid_line_has_donor_keys_and_no_answer_text() -> None:
    result: MergeAttemptResult = run_once(answer(OVERFLOW_ANSWER))
    line: str = result.invalid_line(FAKE_BACKEND)
    assert line.startswith(f"merge_llm_response_invalid {result.label.prefix} provider=fake stage=primary ")
    assert "code=paragraph_overflow raw_response_received=yes " in line
    assert 'reason="body_paragraphs=8 allowed=2..7"' in line
    assert line.endswith(f"raw_chars={len(answer(OVERFLOW_ANSWER))}")
    assert "Paragraph number" not in line


def test_no_answer_text_reaches_the_log(llm_log: LogCollector) -> None:
    for reply in (answer(STRONG_ANSWER), answer(THIN_ANSWER), answer(OVERFLOW_ANSWER), "not json at all"):
        run_once(reply)
    joined: str = "\n".join(llm_log.messages())
    for fragment in (STRONG_HOOK[:40], STRONG_BULLETS[0], STRONG_CLOSE[:40], "Paragraph number", "not json at all", HOOK):
        assert fragment not in joined


def test_merge_rules_carry_the_publication_headings() -> None:
    assert RULES.headings.official_links("uk") == "🌐 Офіційні ресурси:"
    assert RULES.headings.recommended_materials("en") == "Recommended materials:"
