from __future__ import annotations

import dataclasses
import logging
import random
import traceback
from collections.abc import Iterator
from typing import Any

import openai
import pytest

from app.config.loader import LlmSettings, ReasoningEffort, ServiceTier
from app.core.retry import RetryPolicy
from app.llm.client import (
    FLEX_RETRY_DELAYS_SEC,
    PROBE_MAX_OUTPUT_TOKENS,
    LlmRequest,
    LlmResponse,
    OpenAiClient,
)
from app.llm.errors import LlmErrorKind, LlmRequestError
from app.llm.model import LlmModel, ServiceTierRule
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.tests.conftest import (
    LLM_SETTINGS,
    SUPPLIED_VALUES,
    FakeLlmSdk,
    LogCollector,
    api_error,
    connection_error,
    llm_answer,
    timeout_error,
)

KEY_TEXT: str = SUPPLIED_VALUES[SecretField.OPENAI_API_KEY]
KEY: SecretValue = SecretValue(field=SecretField.OPENAI_API_KEY, value=KEY_TEXT)
SCHEMA: dict[str, Any] = {
    "name": "merge_v2",
    "schema": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
}
DEFAULT_TIER: LlmSettings = dataclasses.replace(LLM_SETTINGS, service_tier=ServiceTier.DEFAULT)


@pytest.fixture
def llm_log() -> Iterator[LogCollector]:
    logger: logging.Logger = logging.getLogger("livecraft.llm")
    collector: LogCollector = LogCollector()
    level: int = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(level)


def make_client(sdk: FakeLlmSdk, settings: LlmSettings = LLM_SETTINGS) -> tuple[OpenAiClient, list[float]]:
    sleeps: list[float] = []
    client: OpenAiClient = OpenAiClient(
        key=KEY, settings=settings, sdk=sdk, rng=random.Random(7), sleep=sleeps.append, clock=lambda: 0.0
    )
    return client, sleeps


def request(settings: LlmSettings = LLM_SETTINGS, model: str = "gpt-5.6-sol", schema: dict[str, Any] | None = None) -> LlmRequest:
    return LlmRequest.from_settings(settings, LlmModel(model), "Промт слота: секретов тут нет", "merge", schema)


def test_kwargs_for_gpt5_with_reasoning_and_schema() -> None:
    kwargs: dict[str, Any] = request(DEFAULT_TIER, schema=SCHEMA).to_kwargs()
    assert kwargs == {
        "model": "gpt-5.6-sol",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Промт слота: секретов тут нет"}]}],
        "max_output_tokens": 8000,
        "timeout": 900.0,
        "reasoning": {"effort": "medium"},
        "text": {"format": {"type": "json_schema", "name": "merge_v2", "strict": True, "schema": SCHEMA["schema"]}},
    }


def test_flex_goes_into_kwargs_and_other_models_follow_their_capabilities() -> None:
    assert request().to_kwargs()["service_tier"] == "flex"
    gpt4o: dict[str, Any] = request(DEFAULT_TIER, model="gpt-4o").to_kwargs()
    assert "reasoning" not in gpt4o and "temperature" not in gpt4o and "service_tier" not in gpt4o
    o3: dict[str, Any] = request(DEFAULT_TIER, model="o3").to_kwargs()
    assert o3["temperature"] == 0.0 and o3["reasoning"] == {"effort": "medium"}
    unnamed_schema: dict[str, Any] = request(schema={"schema": {}}).to_kwargs()
    assert unnamed_schema["text"]["format"]["name"] == "merge_v1"
    none_effort: LlmSettings = dataclasses.replace(LLM_SETTINGS, reasoning_effort=ReasoningEffort.NONE)
    assert request(none_effort).to_kwargs()["reasoning"] == {"effort": "none"}


def test_request_repr_and_log_line_carry_no_prompt() -> None:
    subject: LlmRequest = request(schema=SCHEMA)
    assert "Промт" not in repr(subject) and "Промт" not in subject.log_line
    assert "prompt_chars=29" in subject.log_line and "structured=yes" in subject.log_line


def test_no_key_in_vault_is_not_configured() -> None:
    with pytest.raises(LlmRequestError) as caught:
        OpenAiClient.from_vault(Vault.empty(), LLM_SETTINGS)
    assert caught.value.kind is LlmErrorKind.NOT_CONFIGURED and caught.value.is_model_configuration


def test_client_takes_the_key_from_the_vault_and_creates_the_sdk_once() -> None:
    vault: Vault = Vault.empty().with_field(SecretField.OPENAI_API_KEY, KEY, VaultOrigin.OWN)
    sdk: FakeLlmSdk = FakeLlmSdk(llm_answer(), llm_answer())
    client: OpenAiClient = OpenAiClient.from_vault(vault, LLM_SETTINGS, sdk=sdk)
    assert sdk.created == []                                 # клиент SDK — только к первому запросу
    client.send(request())
    client.send(request())
    assert sdk.created == [{"api_key": KEY_TEXT, "timeout": 900.0, "max_retries": 0}]


def test_answer_text_usage_cost_and_limits(llm_log: LogCollector) -> None:
    headers: dict[str, str] = {"x-ratelimit-remaining-requests": "99", "x-ratelimit-reset-tokens": "1m30s"}
    sdk: FakeLlmSdk = FakeLlmSdk(llm_answer('```json\n{"title": "Эфир"}\n```', headers=headers))
    client, sleeps = make_client(sdk)
    response: LlmResponse = client.send(request(schema=SCHEMA))
    assert response.structured == {"title": "Эфир"}
    assert response.model == "gpt-5.6-sol-2026-08-01" and response.service_tier_used == "flex"
    assert response.attempts == 1 and sleeps == []
    assert response.rate_limits is not None and response.rate_limits.reset_tokens_sec == 90.0
    assert response.usage is not None and response.usage.output_tokens == 100
    # sol по flex: (800 * 4.00 + 200 * 0.40 + 100 * 20.00) / 1e6 / 2
    assert client.run_usage.cost_usd == pytest.approx((800 * 4.00 + 200 * 0.40 + 100 * 20.00) / 1e6 / 2)
    assert client.run_usage.requests == 1
    messages: list[str] = llm_log.messages()
    assert any(line.startswith("llm_rate_limits model=gpt-5.6-sol label=merge rem_req=99") for line in messages)
    assert any(line.startswith("llm_response label=merge") and "cost_usd=0.00" in line for line in messages)
    assert all("Промт" not in line and "Эфир" not in line for line in messages)


def test_plain_request_has_no_structured_payload() -> None:
    client, _ = make_client(FakeLlmSdk(llm_answer('{"title": "x"}')))
    assert client.send(request()).structured is None


def test_flex_busy_waits_20_40_80_and_then_goes_to_the_default_tier(llm_log: LogCollector) -> None:
    busy: list[Exception] = [api_error(429, "Resource unavailable", code="resource_unavailable") for _ in range(4)]
    sdk: FakeLlmSdk = FakeLlmSdk(*busy, llm_answer(service_tier="default"))
    client, sleeps = make_client(sdk)
    response: LlmResponse = client.send(request())
    assert sleeps == list(FLEX_RETRY_DELAYS_SEC) == [20.0, 40.0, 80.0]
    assert [call.get("service_tier") for call in sdk.calls] == ["flex", "flex", "flex", "flex", None]
    assert response.attempts == 5 and response.service_tier_used == "default"
    assert sum(1 for line in llm_log.messages() if line.startswith("llm_flex_unavailable")) == 3
    assert any(line.startswith("llm_flex_fallback_to_default") for line in llm_log.messages())


def test_flex_recovers_on_the_second_try_without_leaving_flex() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(api_error(429, "Resource unavailable"), llm_answer())
    client, sleeps = make_client(sdk)
    client.send(request())
    assert sleeps == [20.0]
    assert [call["service_tier"] for call in sdk.calls] == ["flex", "flex"]


def test_flex_quota_is_not_waited_out() -> None:
    client, sleeps = make_client(FakeLlmSdk(api_error(429, "You exceeded your current quota")))
    with pytest.raises(LlmRequestError) as caught:
        client.send(request())
    assert caught.value.kind is LlmErrorKind.QUOTA and sleeps == []


def test_max_output_hit_is_retried_once_with_double_limit() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(
        llm_answer('{"title": "обр', incomplete="max_output_tokens"), llm_answer('{"title": "целое"}')
    )
    client, _ = make_client(sdk, DEFAULT_TIER)
    response: LlmResponse = client.send(request(DEFAULT_TIER, schema=SCHEMA))
    assert [call["max_output_tokens"] for call in sdk.calls] == [8000, 16000]
    assert response.structured == {"title": "целое"} and response.attempts == 2
    assert client.run_usage.requests == 2                    # оплачены оба ответа


def test_max_output_hit_twice_is_returned_as_is() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(
        llm_answer("часть", incomplete="max_output_tokens"), llm_answer("часть 2", incomplete="max_output_tokens")
    )
    client, _ = make_client(sdk, DEFAULT_TIER)
    response: LlmResponse = client.send(request(DEFAULT_TIER))
    assert len(sdk.calls) == 2 and response.hit_max_output and response.text == "часть 2"


def test_empty_answer_is_an_error() -> None:
    client, _ = make_client(FakeLlmSdk(llm_answer("   ")), DEFAULT_TIER)
    with pytest.raises(LlmRequestError) as caught:
        client.send(request(DEFAULT_TIER))
    assert caught.value.kind is LlmErrorKind.EMPTY_OUTPUT


def test_network_failures_are_retried_by_the_policy() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(timeout_error(), api_error(500, "boom"), api_error(429, "slow down"), llm_answer())
    client, sleeps = make_client(sdk, DEFAULT_TIER)
    response: LlmResponse = client.send(request(DEFAULT_TIER))
    policy: RetryPolicy = RetryPolicy()
    rng: random.Random = random.Random(7)
    assert sleeps == [policy.delay_sec(number, rng) for number in (1, 2, 3)]
    assert response.attempts == 4


def test_retries_end_with_the_last_error() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(*[connection_error() for _ in range(5)])
    client, sleeps = make_client(sdk, DEFAULT_TIER)
    with pytest.raises(LlmRequestError) as caught:
        client.send(request(DEFAULT_TIER))
    assert caught.value.kind is LlmErrorKind.CONNECTION
    assert len(sdk.calls) == RetryPolicy().max_attempts == 5 and len(sleeps) == 4
    assert isinstance(caught.value.__cause__, openai.APIConnectionError)


def test_configuration_errors_are_not_retried() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(api_error(404, "The model does not exist", code="model_not_found"))
    client, sleeps = make_client(sdk)
    with pytest.raises(LlmRequestError) as caught:
        client.send(request())
    assert caught.value.kind is LlmErrorKind.MODEL_NOT_FOUND and len(sdk.calls) == 1 and sleeps == []


def test_temperature_unsupported_is_retried_without_it() -> None:
    refusal: Exception = api_error(
        400, "Unsupported parameter: 'temperature' is not supported with this model.", code="unsupported_parameter",
        param="temperature",
    )
    sdk: FakeLlmSdk = FakeLlmSdk(refusal, llm_answer(model="o3"))
    client, _ = make_client(sdk, DEFAULT_TIER)
    client.send(request(DEFAULT_TIER, model="o3"))
    assert [("temperature" in call) for call in sdk.calls] == [True, False]


def test_temperature_refusal_without_temperature_is_raised() -> None:
    refusal: Exception = api_error(400, "Unsupported parameter: 'temperature'", code="unsupported_parameter", param="temperature")
    client, _ = make_client(FakeLlmSdk(refusal), DEFAULT_TIER)
    with pytest.raises(LlmRequestError):
        client.send(request(DEFAULT_TIER))                     # gpt-5 температуру и не слал — откатывать нечего


def test_probe_is_one_cheap_call_and_returns_the_refusal() -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(api_error(403, "no access"), llm_answer("", incomplete="max_output_tokens"))
    client, sleeps = make_client(sdk)
    refused: LlmResponse | LlmRequestError = client.probe(LlmModel("gpt-5.6-sol"))
    assert isinstance(refused, LlmRequestError) and refused.kind is LlmErrorKind.ACCESS_DENIED
    passed: LlmResponse | LlmRequestError = client.probe(LlmModel("gpt-5.4"))
    assert isinstance(passed, LlmResponse)                   # обрезанный пустой ответ — доступ всё равно есть
    assert sdk.calls[1]["max_output_tokens"] == PROBE_MAX_OUTPUT_TOKENS
    assert sdk.calls[1]["timeout"] == 30.0 and "service_tier" not in sdk.calls[1]
    assert sdk.calls[1]["reasoning"] == {"effort": "medium"} and sleeps == []


def test_probe_timeout_is_not_longer_than_the_settings() -> None:
    short: LlmSettings = dataclasses.replace(LLM_SETTINGS, timeout_sec=10)
    assert LlmRequest.probe(short, LlmModel("gpt-5.4")).timeout_sec == 10.0
    assert LlmRequest.probe(short, LlmModel("gpt-5.4")).service_tier == ServiceTierRule.of("default")


def test_the_key_never_leaves_the_client(llm_log: LogCollector) -> None:
    leak: Exception = api_error(401, f"Incorrect API key provided: {KEY_TEXT}. You can find your API key at …")
    sdk: FakeLlmSdk = FakeLlmSdk(leak)
    client, _ = make_client(sdk)
    with pytest.raises(LlmRequestError) as caught:
        client.send(request())
    error: LlmRequestError = caught.value
    secret: str = KEY.reveal()
    assert sdk.created[0]["api_key"] == secret               # дошёл до SDK — и только туда
    assert secret not in str(error) and secret not in repr(error)
    assert secret not in error.detail and KEY.log_label in error.detail
    assert secret not in error.log_line
    assert secret not in repr(client) and secret not in repr(request())
    assert all(secret not in line for line in llm_log.messages())
    own_frames: str = "".join(traceback.format_exception_only(type(error), error))
    assert secret not in own_frames
