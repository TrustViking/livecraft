from __future__ import annotations

import pytest

from app.llm.usage import RequestUsage, RunUsage, TokenCounts
from app.observability.log_event import LogEvent


def usage(
    model: str = "model-a",
    tier: str = "cheap",
    label: str = "merge",
    tokens: TokenCounts = TokenCounts(1000, 200, 0, 100, 40, 1100),
    cost: float | None = 0.01,
) -> RequestUsage:
    return RequestUsage(tokens, response_id="resp_test", model=model, tier=tier, label=label, cost_usd=cost)


def test_token_counts_add_up_and_split_the_input() -> None:
    total: TokenCounts = TokenCounts(1000, 200, 100, 50, 10, 1050) + TokenCounts(10, 0, 0, 5, 0, 15)
    assert total == TokenCounts(1010, 200, 100, 55, 10, 1065)
    assert total.uncached_input_tokens == 710 and TokenCounts(5, 4, 3).uncached_input_tokens == 0


def test_run_usage_adds_responses_up() -> None:
    run: RunUsage = RunUsage()
    run.add(usage())
    run.add(usage(model="model-b", tier="standard", label="probe", tokens=TokenCounts(500, 0, 0, 50, 40, 550), cost=0.02))
    assert run.requests == 2 and run.tokens_known and run.cost_known
    assert run.tokens == TokenCounts(1500, 200, 0, 150, 80, 1650)
    assert run.cost_usd == pytest.approx(0.03)
    assert run.models == {"model-a", "model-b"}
    assert run.tiers == {"cheap", "standard"}
    assert run.tier_by_request == (("merge", "cheap"), ("probe", "standard"))
    assert run.event.text == (
        "llm_run_usage requests=2 usage_reports=2 input_tokens=1500 cached_input_tokens=200 cache_write_tokens=0 "
        "output_tokens=150 thinking_tokens=80 total_tokens=1650 cost_usd=0.030000 cost_known=yes "
        "models=model-a,model-b tiers=cheap,standard"
    )


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
    assert "tiers=unknown" in run.event.text


def test_usage_log_fields_carry_no_label_text_or_answer() -> None:
    fields: str = usage().extend(LogEvent.of("event")).text
    assert fields == (
        "event input_tokens=1000 cached_input_tokens=200 cache_write_tokens=0 output_tokens=100 thinking_tokens=40 "
        "total_tokens=1100 served_model=model-a tier=cheap response_id=resp_test"
    )
