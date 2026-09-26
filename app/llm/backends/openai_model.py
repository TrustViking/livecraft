"""Модель OpenAI: что она умеет в запросе, тарифы и цены (CLAUDE.md §2 строки про llm\\). Только для OpenAI.

`OpenAiModel` — модель по имени: семейство и возможности запроса. `ServiceTierRule` — тариф (`service_tier`) запроса
или ответа. `OpenAiTariffs` — цены моделей за миллион токенов по тарифу Standard, псевдонимы имён и множители тарифов:
ресурс `openai_prices.json` (снимок страницы цен), читается один раз за процесс. Стоимость ответа считается по числам
токенов разъёма (`TokenCounts`).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from functools import cache
from typing import Any, Final

from app.config.settings import ServiceTier
from app.llm.usage import TokenCounts
from app.resources.loader import TextResource

PRICES_RESOURCE: Final[str] = "openai_prices.json"
TOKENS_PER_PRICE_UNIT: Final[float] = 1_000_000.0       # цены — в долларах за миллион токенов
COST_DIGITS: Final[int] = 6
UNKNOWN_TIER_MULTIPLIER: Final[float] = 1.0              # незнакомый тариф считается по Standard
TEMPERATURE_FREE_PREFIX: Final[str] = "gpt"              # моделям gpt-* температура не шлётся

# Ответ OpenAI называет модель снимком с датой (`gpt-5.4-2026-03-05`) — цена у неё та же, что у имени без даты.
SNAPSHOT_SUFFIX_PATTERN: Final[re.Pattern[str]] = re.compile(r"-\d{4}-\d{2}-\d{2}$")


class TariffKey(str, Enum):
    """Разделы и поля ресурса цен."""

    PRICES = "prices"
    ALIASES = "aliases"
    TIER_MULTIPLIERS = "tier_multipliers"
    INPUT = "input_usd"
    CACHED_INPUT = "cached_input_usd"
    CACHE_WRITE = "cache_write_usd"
    OUTPUT = "output_usd"


class ModelFamily(str, Enum):
    """Семейство модели по имени; порядок проверки префиксов важен."""

    GPT_5 = "gpt-5"
    GPT_4O = "gpt-4o"
    GPT_41 = "gpt-4.1"
    GPT_4 = "gpt-4"
    O_SERIES = "o-series"
    GPT_OTHER = "gpt-other"
    OTHER = "other"
    UNKNOWN = "unknown"

    @classmethod
    def of(cls, normalized_name: str) -> ModelFamily:
        for prefixes, family in _FAMILY_PREFIXES:
            if normalized_name.startswith(prefixes):
                return family
        return cls.OTHER if normalized_name else cls.UNKNOWN

    @property
    def supports_reasoning(self) -> bool:
        """`reasoning.effort` понимают только gpt-5 и o-серия."""
        return self in (ModelFamily.GPT_5, ModelFamily.O_SERIES)


_FAMILY_PREFIXES: Final[tuple[tuple[tuple[str, ...], ModelFamily], ...]] = (
    (("gpt-5",), ModelFamily.GPT_5),
    (("gpt-4o",), ModelFamily.GPT_4O),
    (("gpt-4.1",), ModelFamily.GPT_41),
    (("gpt-4",), ModelFamily.GPT_4),
    (("o1", "o3", "o4"), ModelFamily.O_SERIES),
    (("gpt",), ModelFamily.GPT_OTHER),
)


@dataclass(frozen=True)
class ModelPrice:
    """Доллары за миллион токенов, тариф Standard. Модель без цены записи кеша платит за запись как за вход."""

    input_usd: float
    cached_input_usd: float
    cache_write_usd: float
    output_usd: float

    @classmethod
    def of(cls, data: Mapping[str, Any]) -> ModelPrice:
        return cls(
            input_usd=float(data[TariffKey.INPUT]),
            cached_input_usd=float(data[TariffKey.CACHED_INPUT]),
            cache_write_usd=float(data[TariffKey.CACHE_WRITE]),
            output_usd=float(data[TariffKey.OUTPUT]),
        )

    def standard_cost(self, tokens: TokenCounts) -> float:
        """Стоимость по тарифу Standard: кешированный вход и запись кеша — части входа, считаются отдельно."""
        total: float = (
            tokens.uncached_input_tokens * self.input_usd
            + tokens.cached_input_tokens * self.cached_input_usd
            + tokens.cache_write_tokens * self.cache_write_usd
            + tokens.output_tokens * self.output_usd
        )
        return total / TOKENS_PER_PRICE_UNIT


@dataclass(frozen=True)
class ServiceTierRule:
    """Тариф OpenAI (`service_tier`) как строка запроса или ответа и правила над ней.

    Ответ может назвать тариф, которого нет в настройках (`auto`, `scale`), — поэтому здесь строка, а не
    `ServiceTier` из конфига. Пустое значение — тариф по умолчанию.
    """

    value: str

    @classmethod
    def of(cls, raw: str | ServiceTier | None) -> ServiceTierRule:
        text: str = raw.value if isinstance(raw, ServiceTier) else str(raw or "")
        return cls(value=text.strip().lower() or ServiceTier.DEFAULT.value)

    @property
    def is_flex(self) -> bool:
        return self.value == ServiceTier.FLEX.value

    @property
    def request_value(self) -> str | None:
        """Что слать в запросе: тариф по умолчанию не шлётся вовсе."""
        return None if self.value == ServiceTier.DEFAULT.value else self.value


@dataclass(frozen=True)
class OpenAiModel:
    """Модель по имени из настроек или из ответа: семейство и возможности запроса."""

    name: str

    @property
    def normalized(self) -> str:
        return self.name.strip().lower()

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.of(self.normalized)

    @property
    def priced_name(self) -> str:
        """Имя для поиска цены: без даты снимка."""
        return SNAPSHOT_SUFFIX_PATTERN.sub("", self.normalized)

    @property
    def supports_reasoning(self) -> bool:
        return self.family.supports_reasoning

    @property
    def supports_structured_output(self) -> bool:
        """json_schema шлётся любой названной модели: несовместимость покажет ответ 400."""
        return bool(self.normalized)

    @property
    def supports_temperature(self) -> bool:
        """Температура не шлётся моделям gpt-*: у gpt-5 рассуждение вместо неё, у gpt-4x — по замыслу правила.

        Прочим моделям шлётся; отказ «unsupported parameter: temperature» снимает её повтором (openai.py).
        """
        return not self.normalized.startswith(TEMPERATURE_FREE_PREFIX)


@dataclass(frozen=True)
class OpenAiTariffs:
    """Цены моделей (тариф Standard), псевдонимы имён и множители тарифов к цене Standard."""

    prices: Mapping[str, ModelPrice]
    aliases: Mapping[str, str]
    tier_multipliers: Mapping[str, float]

    @classmethod
    @cache
    def load(cls) -> OpenAiTariffs:
        """Снимок цен из ресурса программы; один объект на процесс."""
        data: Mapping[str, Any] = TextResource(PRICES_RESOURCE).data
        return cls(
            prices={name: ModelPrice.of(price) for name, price in data[TariffKey.PRICES].items()},
            aliases=dict(data[TariffKey.ALIASES]),
            tier_multipliers={tier: float(value) for tier, value in data[TariffKey.TIER_MULTIPLIERS].items()},
        )

    def price(self, model: OpenAiModel) -> ModelPrice | None:
        """Цена модели: имя без даты снимка, псевдоним — на свою модель; нет в снимке — None."""
        base: str = model.priced_name
        return self.prices.get(self.aliases.get(base, base))

    def multiplier(self, tier: ServiceTierRule) -> float:
        """Во сколько раз тариф дороже Standard; незнакомый тариф считается по Standard."""
        return self.tier_multipliers.get(tier.value, UNKNOWN_TIER_MULTIPLIER)

    def cost(self, model: OpenAiModel, tokens: TokenCounts, tier: ServiceTierRule) -> float | None:
        """Стоимость одного ответа в долларах; модели нет в снимке цен — None (стоимость неизвестна)."""
        price: ModelPrice | None = self.price(model)
        if price is None:
            return None
        return round(price.standard_cost(tokens) * self.multiplier(tier), COST_DIGITS)
