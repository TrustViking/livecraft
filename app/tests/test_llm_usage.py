from __future__ import annotations

import pytest

from app.llm.usage import RequestUsage, RunUsage


def usage(
    model: str = "model-a",
    tier: str = "cheap",
    label: str = "merge",
    input_tokens: int = 1000,
    cached: int = 200,
    output: int = 100,
    cost: float | None = 0.01,
) -> RequestUsage:
    return RequestUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        cache_write_tokens=0,
        output_tokens=output,
        thinking_tokens=40,
        total_tokens=input_tokens + output,
        response_id="resp_test",
        model=model,
        tier=tier,
        label=label,
        cost_usd=cost,
    )


def test_run_usage_adds_responses_up() -> None:
    run: RunUsage = RunUsage()
    run.add(usage())
    run.add(usage(model="model-b", tier="standard", label="probe", input_tokens=500, cached=0, output=50, cost=0.02))
    assert run.requests == 2 and run.tokens_known and run.cost_known
    assert (run.input_tokens, run.cached_input_tokens, run.output_tokens, run.tokens) == (1500, 200, 150, 1650)
    assert run.thinking_tokens == 80
    assert run.cost_usd == pytest.approx(0.03)
    assert run.models == {"model-a", "model-b"}
    assert run.tiers == {"cheap", "standard"}
    assert run.tier_by_request == (("merge", "cheap"), ("probe", "standard"))
    assert "requests=2" in run.log_line and "cost_usd=0.030000" in run.log_line and "cost_known=yes" in run.log_line
    assert "tiers=cheap,standard" in run.log_line


def test_unknown_price_or_usage_marks_the_cost_unknown() -> None:
    run: RunUsage = RunUsage()
    assert not run.tokens_known and run.cost_known
    run.add(usage(cost=None))
    assert not run.cost_known and run.tokens_known
    run.add(None)
    assert run.requests == 2 and run.usage_reports == 1 and not run.tokens_known


def test_a_response_without_a_tier_is_left_out_of_the_tiers() -> None:
    run: RunUsage = RunUsage()
    run.add(usage(tier=""))
    assert run.tiers == set() and run.tier_by_request == ()
    assert "tiers=unknown" in run.log_line


def test_usage_log_fields_carry_no_label_text_or_answer() -> None:
    fields: str = usage().log_fields
    assert "thinking_tokens=40" in fields and "tier=cheap" in fields and "served_model=model-a" in fields
