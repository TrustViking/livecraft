from __future__ import annotations

import pytest

from app.config.loader import ServiceTier
from app.llm.backends.openai_model import MODEL_PRICES, ModelFamily, OpenAiModel, ServiceTierRule
from app.llm.backends.openai_response import OpenAiUsage


def usage(input_tokens: int, cached: int, cache_write: int, output: int, tier: str = "default") -> OpenAiUsage:
    return OpenAiUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        cache_write_tokens=cache_write,
        output_tokens=output,
        reasoning_tokens=0,
        total_tokens=input_tokens + output,
        response_id="",
        model="",
        service_tier=tier,
    )


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("gpt-5.6-sol", ModelFamily.GPT_5),
        ("  GPT-5.4 ", ModelFamily.GPT_5),
        ("gpt-4o-mini", ModelFamily.GPT_4O),
        ("gpt-4.1", ModelFamily.GPT_41),
        ("gpt-4-turbo", ModelFamily.GPT_4),
        ("o3-mini", ModelFamily.O_SERIES),
        ("o4", ModelFamily.O_SERIES),
        ("gpt-6-astra", ModelFamily.GPT_OTHER),
        ("claude", ModelFamily.OTHER),
        ("", ModelFamily.UNKNOWN),
    ],
)
def test_family_follows_the_donor_name_rule(name: str, family: ModelFamily) -> None:
    assert OpenAiModel(name).family is family


def test_request_capabilities_by_name() -> None:
    gpt5: OpenAiModel = OpenAiModel("gpt-5.6-sol")
    assert gpt5.supports_reasoning and gpt5.supports_structured_output and not gpt5.supports_temperature
    gpt4o: OpenAiModel = OpenAiModel("gpt-4o")
    assert not gpt4o.supports_reasoning and not gpt4o.supports_temperature
    o3: OpenAiModel = OpenAiModel("o3")
    assert o3.supports_reasoning and o3.supports_temperature
    assert not OpenAiModel("").supports_structured_output


def test_snapshot_name_prices_as_its_model_and_the_alias_as_sol() -> None:
    assert OpenAiModel("gpt-5.4-2026-03-05").price == MODEL_PRICES["gpt-5.4"]
    assert OpenAiModel("GPT-5.4").price == MODEL_PRICES["gpt-5.4"]
    assert OpenAiModel("gpt-5.6").price == MODEL_PRICES["gpt-5.6-sol"]
    assert OpenAiModel("gpt-5.6-2026-08-01").price == MODEL_PRICES["gpt-5.6-sol"]
    assert OpenAiModel("gpt-9").price is None


def test_cost_counts_cached_input_and_cache_writes_separately() -> None:
    # gpt-5.6-sol: вход 4.00, кеш 0.40, запись кеша 5.00, выход 20.00 за миллион
    spent: OpenAiUsage = usage(input_tokens=1_000_000, cached=200_000, cache_write=100_000, output=50_000)
    expected: float = (700_000 * 4.00 + 200_000 * 0.40 + 100_000 * 5.00 + 50_000 * 20.00) / 1_000_000
    assert OpenAiModel("gpt-5.6-sol").cost(spent, ServiceTierRule.of("default")) == pytest.approx(expected)


def test_flex_is_half_and_fast_is_double() -> None:
    spent: OpenAiUsage = usage(input_tokens=1_000_000, cached=0, cache_write=0, output=1_000_000)
    model: OpenAiModel = OpenAiModel("gpt-5.4-2026-03-05")
    standard: float | None = model.cost(spent, ServiceTierRule.of(ServiceTier.DEFAULT))
    assert standard == pytest.approx(2.50 + 15.00)
    assert model.cost(spent, ServiceTierRule.of("flex")) == pytest.approx(standard / 2)
    assert model.cost(spent, ServiceTierRule.of(ServiceTier.FAST)) == pytest.approx(standard * 2)
    assert model.cost(spent, ServiceTierRule.of("priority")) == pytest.approx(standard * 2)
    assert model.cost(spent, ServiceTierRule.of("scale")) == pytest.approx(standard)    # незнакомый — как Standard


def test_unknown_model_has_no_cost() -> None:
    assert OpenAiModel("gpt-9").cost(usage(10, 0, 0, 10), ServiceTierRule.of("default")) is None


def test_service_tier_rule() -> None:
    assert ServiceTierRule.of("").value == "default"
    assert ServiceTierRule.of(None).request_value is None
    assert ServiceTierRule.of(ServiceTier.DEFAULT).request_value is None
    assert ServiceTierRule.of(" FLEX ").request_value == "flex"
    assert ServiceTierRule.of(ServiceTier.FLEX).is_flex
    assert not ServiceTierRule.of("fast").is_flex
