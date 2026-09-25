from __future__ import annotations

import dataclasses
import random

from app.config.loader import LlmSettings
from app.llm.backends.openai import OpenAiClient
from app.llm.errors import LlmErrorKind
from app.llm.selection import ChoiceReason, ModelChoice
from app.secretsafe.value import SecretField, SecretValue
from app.tests.conftest import LLM_SETTINGS, SUPPLIED_VALUES, FakeLlmSdk, api_error, llm_answer, timeout_error
from app.ui import messages_ru as msg

KEY: SecretValue = SecretValue(field=SecretField.OPENAI_API_KEY, value=SUPPLIED_VALUES[SecretField.OPENAI_API_KEY])
DENIED: str = "Project does not have access to model"


def choose(sdk: FakeLlmSdk, settings: LlmSettings = LLM_SETTINGS) -> ModelChoice:
    client: OpenAiClient = OpenAiClient(
        key=KEY, settings=settings, sdk=sdk, rng=random.Random(1), sleep=lambda _: None, clock=lambda: 0.0
    )
    return ModelChoice.select(client, settings.model, settings.fallback_model)


def probed(sdk: FakeLlmSdk) -> list[object]:
    return [call["model"] for call in sdk.calls]


def test_primary_that_answers_is_chosen() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(llm_answer(""))
    choice: ModelChoice = choose(sdk)
    assert choice.chosen == "gpt-5.6-sol" and choice.reason is ChoiceReason.PRIMARY_CONFIRMED
    assert choice.fallback == "gpt-5.4" and choice.error is None
    assert probed(sdk) == ["gpt-5.6-sol"]
    assert choice.human == msg.LLM_CHOICE_LINE.format(model="gpt-5.6-sol", reason=ChoiceReason.PRIMARY_CONFIRMED.human)


def test_access_denial_switches_to_the_fallback() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(api_error(404, "The model does not exist", code="model_not_found"), llm_answer(""))
    choice: ModelChoice = choose(sdk)
    assert choice.chosen == "gpt-5.4" and choice.reason is ChoiceReason.FALLBACK_CONFIRMED
    assert choice.error is not None and choice.error.kind is LlmErrorKind.MODEL_NOT_FOUND
    assert probed(sdk) == ["gpt-5.6-sol", "gpt-5.4"]
    assert "llm_model_selected chosen=gpt-5.4 primary=gpt-5.6-sol fallback=gpt-5.4 reason=fallback_confirmed" in choice.log_line


def test_fallback_that_cannot_be_checked_is_kept() -> None:
    choice: ModelChoice = choose(FakeLlmSdk(api_error(403, DENIED), timeout_error()))
    assert choice.chosen == "gpt-5.4" and choice.reason is ChoiceReason.FALLBACK_UNCHECKED
    assert choice.error is not None and choice.error.kind is LlmErrorKind.TIMEOUT


def test_timeout_keeps_the_primary_unchecked_and_does_not_touch_the_fallback() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(timeout_error())
    choice: ModelChoice = choose(sdk)
    assert choice.chosen == "gpt-5.6-sol" and choice.reason is ChoiceReason.PRIMARY_UNCHECKED
    assert choice.is_usable and probed(sdk) == ["gpt-5.6-sol"]


def test_rejected_key_leaves_no_model() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(api_error(401, "Incorrect API key provided"))
    choice: ModelChoice = choose(sdk)
    assert choice.chosen is None and choice.reason is ChoiceReason.REFUSED and not choice.is_usable
    assert choice.error is not None and choice.error.kind is LlmErrorKind.AUTH
    assert probed(sdk) == ["gpt-5.6-sol"]
    assert choice.human == msg.LLM_CHOICE_REFUSED.format(reason=choice.error.human)


def test_denial_without_a_fallback_leaves_no_model() -> None:
    for fallback in ("", "  GPT-5.6-SOL "):
        settings: LlmSettings = dataclasses.replace(LLM_SETTINGS, fallback_model=fallback)
        sdk: FakeLlmSdk = FakeLlmSdk(api_error(403, DENIED))
        choice: ModelChoice = choose(sdk, settings)
        assert choice.fallback is None and choice.chosen is None and choice.reason is ChoiceReason.REFUSED
        assert probed(sdk) == ["gpt-5.6-sol"]


def test_denial_of_both_models_leaves_no_model() -> None:
    choice: ModelChoice = choose(FakeLlmSdk(api_error(403, DENIED), api_error(404, "nope", code="model_not_found")))
    assert choice.chosen is None and choice.error is not None and choice.error.kind is LlmErrorKind.MODEL_NOT_FOUND


def test_every_reason_has_a_russian_text() -> None:
    assert set(msg.LLM_CHOICE_REASON_TEXT) == {reason.value for reason in ChoiceReason}
