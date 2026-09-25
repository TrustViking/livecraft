from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config.loader import LlmSettings
from app.llm.backend import LlmRequest, LlmResponse
from app.llm.backends.openai import OpenAiRequest
from app.llm.backends.openai_model import OpenAiModel
from app.llm.backends.openai_response import OpenAiReply, OpenAiUsage, parse_int
from app.llm.usage import RequestUsage
from app.tests.conftest import LLM_SETTINGS, llm_answer


def openai_request(schema: dict[str, object] | None = None, settings: LlmSettings = LLM_SETTINGS) -> OpenAiRequest:
    return OpenAiRequest.of(LlmRequest.from_settings(settings, "gpt-5.6-sol", "промт", "merge", schema), settings)


def test_usage_is_read_from_a_response_dict() -> None:
    spent: OpenAiUsage | None = OpenAiUsage.from_response(llm_answer().parse())
    assert spent == OpenAiUsage(
        input_tokens=1000,
        cached_input_tokens=200,
        cache_write_tokens=0,
        output_tokens=100,
        reasoning_tokens=40,
        total_tokens=1100,
        response_id="resp_test",
        model="gpt-5.6-sol-2026-08-01",
        service_tier="flex",
    )


def test_usage_is_read_from_sdk_objects_and_total_falls_back_to_the_sum() -> None:
    response: SimpleNamespace = SimpleNamespace(
        id="r1",
        model="gpt-5.4",
        service_tier=None,
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            total_tokens=None,
            input_tokens_details=SimpleNamespace(cached_tokens=None, cache_write_tokens=3),
            output_tokens_details=None,
        ),
    )
    spent: OpenAiUsage | None = OpenAiUsage.from_response(response)
    assert spent is not None
    assert (spent.total_tokens, spent.cache_write_tokens, spent.cached_input_tokens, spent.reasoning_tokens) == (15, 3, 0, 0)
    assert spent.tier.value == "default"


def test_no_usage_is_none() -> None:
    assert OpenAiUsage.from_response({"id": "x"}) is None
    assert OpenAiUsage.from_response({"usage": {"input_tokens": 1}}) is None


def test_cost_uses_the_served_model_and_otherwise_the_requested_one() -> None:
    spent: OpenAiUsage | None = OpenAiUsage.from_response(llm_answer(model="gpt-5.4-2026-03-05", service_tier="default").parse())
    assert spent is not None
    requested: OpenAiModel = OpenAiModel("gpt-5.6-sol")
    assert spent.cost(requested) == OpenAiModel("gpt-5.4").cost(spent, spent.tier)
    anonymous: OpenAiUsage | None = OpenAiUsage.from_response(llm_answer(model="", service_tier="").parse())
    assert anonymous is not None
    assert anonymous.cost(requested) == requested.cost(anonymous, anonymous.tier)


def test_the_common_usage_carries_the_tier_the_label_and_the_price() -> None:
    spent: OpenAiUsage | None = OpenAiUsage.from_response(llm_answer().parse())
    assert spent is not None
    common: RequestUsage = spent.to_request_usage(OpenAiModel("gpt-5.6-sol"), "merge")
    assert (common.input_tokens, common.output_tokens, common.thinking_tokens, common.total_tokens) == (1000, 100, 40, 1100)
    assert (common.tier, common.label, common.model) == ("flex", "merge", "gpt-5.6-sol-2026-08-01")
    # sol по flex: (800 * 4.00 + 200 * 0.40 + 100 * 20.00) / 1e6 / 2
    assert common.cost_usd == pytest.approx((800 * 4.00 + 200 * 0.40 + 100 * 20.00) / 1e6 / 2)
    unpriced: OpenAiUsage | None = OpenAiUsage.from_response(llm_answer(model="gpt-9").parse())
    assert unpriced is not None and unpriced.to_request_usage(OpenAiModel("gpt-9"), "merge").cost_usd is None


def test_the_reply_text_comes_from_output_text_or_from_the_output_items() -> None:
    assert OpenAiReply.of({"output_text": "  прямо  "}).text == "прямо"
    pieces: dict[str, object] = {
        "output": [
            {"content": [{"type": "output_text", "text": " раз "}, {"type": "refusal", "text": "нет"}]},
            {"content": [{"type": "text", "text": "два"}]},
            {"content": None},
        ]
    }
    assert OpenAiReply.of(pieces).text == "раз\nдва"
    assert OpenAiReply.of({}).text == "" and OpenAiReply.of({}).usage is None


def test_the_reply_becomes_the_common_response() -> None:
    reply: OpenAiReply = OpenAiReply.of(llm_answer('{"title": "Эфир"}', incomplete="MAX_OUTPUT_TOKENS").parse())
    assert reply.hit_max_output and reply.incomplete_reason == "max_output_tokens"
    response: LlmResponse = reply.to_response(openai_request({"schema": {}}))
    assert response.structured == {"title": "Эфир"} and response.text == '{"title": "Эфир"}'
    assert response.model == "gpt-5.6-sol-2026-08-01"                  # модель — названная ответом
    usage: RequestUsage | None = reply.request_usage(openai_request({"schema": {}}))
    assert usage is not None and (usage.label, usage.tier) == ("merge", "flex")
    plain: LlmResponse = OpenAiReply.of(llm_answer('{"title": "x"}', model="").parse()).to_response(openai_request())
    assert plain.structured is None and plain.model == "gpt-5.6-sol"    # ответ не назвал модель — запрошенная


def test_parse_int() -> None:
    assert parse_int("1,234") == 1234
    assert parse_int(7.9) == 7
    assert parse_int(True) is None
    assert parse_int("1.5") is None
    assert parse_int(None) is None
    assert parse_int("-3") == -3
