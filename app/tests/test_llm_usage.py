from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.model import LlmModel
from app.llm.usage import RequestUsage, RunUsage, parse_int
from app.tests.conftest import llm_answer


def test_usage_is_read_from_a_response_dict() -> None:
    spent: RequestUsage | None = RequestUsage.from_response(llm_answer().parse())
    assert spent == RequestUsage(
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
    spent: RequestUsage | None = RequestUsage.from_response(response)
    assert spent is not None
    assert (spent.total_tokens, spent.cache_write_tokens, spent.cached_input_tokens, spent.reasoning_tokens) == (15, 3, 0, 0)
    assert spent.tier.value == "default"


def test_no_usage_is_none() -> None:
    assert RequestUsage.from_response({"id": "x"}) is None
    assert RequestUsage.from_response({"usage": {"input_tokens": 1}}) is None


def test_cost_uses_the_served_model_and_otherwise_the_requested_one() -> None:
    spent: RequestUsage | None = RequestUsage.from_response(llm_answer(model="gpt-5.4-2026-03-05", service_tier="default").parse())
    assert spent is not None
    requested: LlmModel = LlmModel("gpt-5.6-sol")
    assert spent.cost(requested) == LlmModel("gpt-5.4").cost(spent, spent.tier)
    anonymous: RequestUsage | None = RequestUsage.from_response(llm_answer(model="", service_tier="").parse())
    assert anonymous is not None
    assert anonymous.cost(requested) == requested.cost(anonymous, anonymous.tier)


def test_run_usage_adds_responses_up() -> None:
    run: RunUsage = RunUsage()
    first: RequestUsage | None = RequestUsage.from_response(llm_answer().parse())
    second: RequestUsage | None = RequestUsage.from_response(
        llm_answer(model="gpt-5.4", service_tier="default", input_tokens=500, cached_tokens=0, output_tokens=50).parse()
    )
    run.add(first, 0.01)
    run.add(second, 0.02)
    assert run.requests == 2 and run.tokens_known and run.cost_known
    assert (run.input_tokens, run.cached_input_tokens, run.output_tokens, run.tokens) == (1500, 200, 150, 1650)
    assert run.cost_usd == pytest.approx(0.03)
    assert run.models == {"gpt-5.6-sol-2026-08-01", "gpt-5.4"}
    assert run.service_tiers == {"flex", "default"}
    assert "requests=2" in run.log_line and "cost_usd=0.030000" in run.log_line and "cost_known=yes" in run.log_line


def test_unknown_price_or_usage_marks_the_cost_unknown() -> None:
    run: RunUsage = RunUsage()
    assert not run.tokens_known
    run.add(RequestUsage.from_response(llm_answer().parse()), None)
    assert not run.cost_known and run.tokens_known
    run.add(None, None)
    assert run.requests == 2 and run.usage_reports == 1 and not run.tokens_known


def test_parse_int() -> None:
    assert parse_int("1,234") == 1234
    assert parse_int(7.9) == 7
    assert parse_int(True) is None
    assert parse_int("1.5") is None
    assert parse_int(None) is None
    assert parse_int("-3") == -3
