"""Модель OpenAI: что она умеет в запросе и сколько стоит (CLAUDE.md §2 строки про llm\\). Только для OpenAI.

Правила перенесены из restreamer: семейство и возможности модели — `models\\model_compatibility.py`
(`_openai_model_family`, `*_supported`, правило имён), цены и множители тарифов — `model_pricing.py`
(`MODEL_PRICES`, `SERVICE_TIER_MULTIPLIERS`, `price_for_model`, `estimate_cost_usd`). Здесь они — поля и
методы объектов `OpenAiModel` и `ServiceTierRule`, а не свободные функции.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final

from app.config.loader import ServiceTier

if TYPE_CHECKING:      # только для аннотаций: openai_response.py сам импортирует этот модуль
    from app.llm.backends.openai_response import OpenAiUsage

TOKENS_PER_PRICE_UNIT: Final[float] = 1_000_000.0       # цены — в долларах за миллион токенов
COST_DIGITS: Final[int] = 6

# Ответ OpenAI называет модель снимком с датой (`gpt-5.4-2026-03-05`) — цена у неё та же, что у имени без даты.
SNAPSHOT_SUFFIX_PATTERN: Final[re.Pattern[str]] = re.compile(r"-\d{4}-\d{2}-\d{2}$")


class ModelFamily(str, Enum):
    """Семейство модели по имени — правило `_openai_model_family` донора; порядок проверки важен."""

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

    def standard_cost(self, usage: OpenAiUsage) -> float:
        """Стоимость ответа по тарифу Standard: кешированный вход и запись кеша — части входа, считаются отдельно."""
        uncached_input: int = max(0, usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens)
        total: float = (
            uncached_input * self.input_usd
            + usage.cached_input_tokens * self.cached_input_usd
            + usage.cache_write_tokens * self.cache_write_usd
            + usage.output_tokens * self.output_usd
        )
        return total / TOKENS_PER_PRICE_UNIT


# Снимок страницы цен OpenAI (developers.openai.com/api/docs/pricing), тариф Standard, короткий контекст.
# Перенесён из restreamer `app\llm\model_pricing.py::MODEL_PRICES` как есть — снимок сентября 2026.
# Страница поменялась — правится руками здесь и только здесь.
MODEL_PRICES: Final[dict[str, ModelPrice]] = {
    "gpt-5.2": ModelPrice(input_usd=1.75, cached_input_usd=0.175, cache_write_usd=1.75, output_usd=14.00),
    "gpt-5.4": ModelPrice(input_usd=2.50, cached_input_usd=0.25, cache_write_usd=2.50, output_usd=15.00),
    "gpt-5.5": ModelPrice(input_usd=5.00, cached_input_usd=0.50, cache_write_usd=5.00, output_usd=30.00),
    "gpt-5.6-sol": ModelPrice(input_usd=4.00, cached_input_usd=0.40, cache_write_usd=5.00, output_usd=20.00),
    "gpt-5.6-terra": ModelPrice(input_usd=2.00, cached_input_usd=0.20, cache_write_usd=2.50, output_usd=12.00),
    "gpt-5.6-luna": ModelPrice(input_usd=0.20, cached_input_usd=0.02, cache_write_usd=0.25, output_usd=1.20),
    "gpt-6-astra": ModelPrice(input_usd=10.00, cached_input_usd=1.00, cache_write_usd=12.50, output_usd=50.00),
}
# Имя без версии OpenAI отправляет на Sol (так в доноре).
MODEL_ALIASES: Final[dict[str, str]] = {"gpt-5.6": "gpt-5.6-sol"}

# Множитель к цене Standard по тарифу, который назвал ответ (тот же снимок): Flex — половина цены,
# Fast (бывший Priority, переименован в июле 2026, OpenAI принимает оба имени) — вдвое дороже.
SERVICE_TIER_MULTIPLIERS: Final[dict[str, float]] = {
    "default": 1.0,
    "auto": 1.0,
    "flex": 0.5,
    "priority": 2.0,
    "fast": 2.0,
}
UNKNOWN_TIER_MULTIPLIER: Final[float] = 1.0


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
    def multiplier(self) -> float:
        """Во сколько раз дороже Standard; незнакомый тариф считается по Standard."""
        return SERVICE_TIER_MULTIPLIERS.get(self.value, UNKNOWN_TIER_MULTIPLIER)

    @property
    def is_flex(self) -> bool:
        return self.value == ServiceTier.FLEX.value

    @property
    def request_value(self) -> str | None:
        """Что слать в запросе: тариф по умолчанию не шлётся вовсе (правило донора)."""
        return None if self.value == ServiceTier.DEFAULT.value else self.value


@dataclass(frozen=True)
class OpenAiModel:
    """Модель по имени из настроек или из ответа: семейство, возможности запроса и цена."""

    name: str

    @property
    def normalized(self) -> str:
        return self.name.strip().lower()

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.of(self.normalized)

    @property
    def supports_reasoning(self) -> bool:
        return self.family.supports_reasoning

    @property
    def supports_structured_output(self) -> bool:
        """json_schema шлётся любой названной модели: несовместимость покажет ответ 400 (правило донора)."""
        return bool(self.normalized)

    @property
    def supports_temperature(self) -> bool:
        """Температура не шлётся моделям gpt-*: у gpt-5 рассуждение вместо неё, gpt-4x — по замыслу донора.

        Прочим моделям шлётся; отказ «unsupported parameter: temperature» снимает её повтором (openai.py).
        """
        return not self.normalized.startswith("gpt")

    @property
    def price(self) -> ModelPrice | None:
        """Цена из снимка: имя без даты снимка, псевдоним — на свою модель; нет в снимке — None."""
        base: str = SNAPSHOT_SUFFIX_PATTERN.sub("", self.normalized)
        return MODEL_PRICES.get(MODEL_ALIASES.get(base, base))

    def cost(self, usage: OpenAiUsage, service_tier: ServiceTierRule) -> float | None:
        """Стоимость одного ответа в долларах; модели нет в снимке цен — None (стоимость неизвестна)."""
        price: ModelPrice | None = self.price
        if price is None:
            return None
        return round(price.standard_cost(usage) * service_tier.multiplier, COST_DIGITS)
