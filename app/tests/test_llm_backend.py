"""Разъём нейросети: общие объекты не знают про OpenAI, выбор модели работает с любой реализацией разъёма."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.llm.backend import (
    DEFAULT_TEMPERATURE,
    PROBE_LABEL,
    PROBE_MAX_OUTPUT_TOKENS,
    LlmBackend,
    LlmRequest,
    LlmResponse,
)
from app.llm.errors import LlmErrorKind, LlmRequestError
from app.llm.selection import ChoiceReason, ModelChoice
from app.llm.usage import RequestUsage, RunUsage
from app.tests.conftest import LLM_SETTINGS

FAKE_BACKEND: str = "fake"
NEUTRAL_MODULES: tuple[str, ...] = ("backend.py", "selection.py", "usage.py")
BACKEND_WORDS: tuple[str, ...] = ("openai", "flex", "service_tier", "reasoning")


@dataclass
class FakeBackend:
    """Реализация разъёма без OpenAI: на пробу каждой модели — заранее заданный отказ или ответ."""

    refusals: dict[str, LlmErrorKind] = field(default_factory=dict)
    run_usage: RunUsage = field(default_factory=RunUsage)
    probed: list[str] = field(default_factory=list)
    completed: list[LlmRequest] = field(default_factory=list)

    @property
    def name(self) -> str:
        return FAKE_BACKEND

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.completed.append(request)
        return self._answer(request.model_name, request.label)

    def probe(self, model_name: str) -> LlmResponse | LlmRequestError:
        self.probed.append(model_name)
        kind: LlmErrorKind | None = self.refusals.get(model_name)
        if kind is not None:
            return LlmRequestError(kind, backend=FAKE_BACKEND)
        return self._answer(model_name, PROBE_LABEL)

    def _answer(self, model_name: str, label: str) -> LlmResponse:
        usage: RequestUsage = RequestUsage(
            input_tokens=3, cached_input_tokens=0, cache_write_tokens=0, output_tokens=1, thinking_tokens=0,
            total_tokens=4, response_id="r", model=model_name, tier="", label=label, cost_usd=0.0,
        )
        self.run_usage.add(usage)
        return LlmResponse(text="OK", structured=None, model=model_name, incomplete_reason="", usage=usage, attempts=1)


def test_the_fake_is_an_llm_backend() -> None:
    assert isinstance(FakeBackend(), LlmBackend)


def test_the_primary_that_answers_is_chosen() -> None:
    backend: FakeBackend = FakeBackend()
    choice: ModelChoice = ModelChoice.select(backend, " model-main ", "model-spare")
    assert choice.chosen == "model-main" and choice.reason is ChoiceReason.PRIMARY_CONFIRMED
    assert choice.fallback == "model-spare" and backend.probed == ["model-main"]


def test_access_denial_goes_to_the_fallback() -> None:
    backend: FakeBackend = FakeBackend(refusals={"model-main": LlmErrorKind.ACCESS_DENIED})
    choice: ModelChoice = ModelChoice.select(backend, "model-main", "model-spare")
    assert choice.chosen == "model-spare" and choice.reason is ChoiceReason.FALLBACK_CONFIRMED
    assert choice.error is not None and choice.error.backend == FAKE_BACKEND
    assert backend.probed == ["model-main", "model-spare"]


def test_another_failure_keeps_the_primary_unchecked() -> None:
    for kind in (LlmErrorKind.TIMEOUT, LlmErrorKind.RATE_LIMIT, LlmErrorKind.SERVER):
        backend: FakeBackend = FakeBackend(refusals={"model-main": kind})
        choice: ModelChoice = ModelChoice.select(backend, "model-main", "model-spare")
        assert choice.chosen == "model-main" and choice.reason is ChoiceReason.PRIMARY_UNCHECKED
        assert backend.probed == ["model-main"]


def test_a_configuration_failure_leaves_no_model() -> None:
    backend: FakeBackend = FakeBackend(refusals={"model-main": LlmErrorKind.AUTH})
    choice: ModelChoice = ModelChoice.select(backend, "model-main", "model-spare")
    assert choice.chosen is None and choice.reason is ChoiceReason.REFUSED and not choice.is_usable


def test_the_same_fallback_in_another_case_is_no_fallback() -> None:
    backend: FakeBackend = FakeBackend(refusals={"Model-Main": LlmErrorKind.MODEL_NOT_FOUND})
    choice: ModelChoice = ModelChoice.select(backend, "Model-Main", " model-main ")
    assert choice.fallback is None and choice.chosen is None and backend.probed == ["Model-Main"]


def test_the_request_has_no_fields_of_a_particular_backend() -> None:
    names: set[str] = {item.name for item in dataclasses.fields(LlmRequest)}
    assert names == {"prompt", "model_name", "max_output_tokens", "label", "timeout_sec", "schema", "temperature"}
    assert not any(word in name for name in names for word in BACKEND_WORDS)


def test_the_request_from_settings_and_the_probe() -> None:
    request: LlmRequest = LlmRequest.from_settings(LLM_SETTINGS, "model-a", "промт", "merge")
    assert (request.max_output_tokens, request.timeout_sec, request.temperature) == (8000, 900.0, DEFAULT_TEMPERATURE)
    assert "промт" not in repr(request) and not request.is_structured
    probe: LlmRequest = LlmRequest.probe("model-a", 10)
    assert (probe.max_output_tokens, probe.timeout_sec, probe.label) == (PROBE_MAX_OUTPUT_TOKENS, 10.0, PROBE_LABEL)
    assert LlmRequest.probe("model-a", 900).timeout_sec == 30.0


def test_the_response_log_line_carries_the_notes_but_no_text() -> None:
    response: LlmResponse = LlmResponse(
        text="секретный ответ", structured=None, model="m", incomplete_reason="", usage=None, attempts=2,
        notes=("one", "two"),
    )
    assert "notes=one,two" in response.log_line and "секретный" not in response.log_line
    assert "секретный" not in repr(response)


@pytest.mark.parametrize("module", NEUTRAL_MODULES)
def test_neutral_modules_name_no_backend(module: str) -> None:
    text: str = (Path(__file__).resolve().parents[1] / "llm" / module).read_text(encoding="utf-8").lower()
    assert not [word for word in BACKEND_WORDS if word in text]
    assert "app.llm.backends" not in text
