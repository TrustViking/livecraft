"""Расход токенов: один ответ и весь запуск (CLAUDE.md §2 строки про llm\\: `llm_usage_tracker.py` restreamer).

У донора расход запуска жил в глобальном состоянии модуля (`_RUN_LOCAL_USAGE_STATE`); здесь это объект
`RunUsage`, который создаёт запуск и держит клиент (§0). Имена полей ответа — как у `ResponseUsage` openai:
input_tokens, input_tokens_details.{cached_tokens, cache_write_tokens}, output_tokens,
output_tokens_details.reasoning_tokens, total_tokens; кеш — часть входа, рассуждение — часть выхода.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

from app.llm.model import LlmModel, ServiceTierRule

INT_PATTERN: Final[re.Pattern[str]] = re.compile(r"-?\d+")
THOUSANDS_SEPARATOR: Final[str] = ","
UNKNOWN: Final[str] = "unknown"
COST_FORMAT: Final[str] = "{:.6f}"
LOG_JOINER: Final[str] = ","


def read_field(container: Any, name: str) -> Any:
    """Поле ответа SDK: у объекта — атрибут, у словаря — ключ; нет — None."""
    if isinstance(container, dict):
        return container.get(name)
    return getattr(container, name, None)


def parse_int(raw: Any) -> int | None:
    """Целое из числа или строки «1,234»; логическое, дробная строка и мусор — None (правило донора)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    text: str = str(raw or "").strip().replace(THOUSANDS_SEPARATOR, "")
    return int(text) if INT_PATTERN.fullmatch(text) else None


def _int_field(container: Any, name: str) -> int:
    return parse_int(read_field(container, name)) or 0


@dataclass(frozen=True)
class RequestUsage:
    """Токены одного ответа, как их назвал сам ответ: модель и тариф — фактические, а не запрошенные."""

    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    response_id: str
    model: str
    service_tier: str

    @classmethod
    def from_response(cls, response: Any) -> RequestUsage | None:
        """Расход из ответа; нет `usage` или в нём нет входа и выхода — None (расход неизвестен)."""
        usage: Any = read_field(response, "usage")
        if usage is None:
            return None
        input_tokens: int | None = parse_int(read_field(usage, "input_tokens"))
        output_tokens: int | None = parse_int(read_field(usage, "output_tokens"))
        if input_tokens is None or output_tokens is None:
            return None
        input_details: Any = read_field(usage, "input_tokens_details")
        total: int | None = parse_int(read_field(usage, "total_tokens"))
        return cls(
            input_tokens=input_tokens,
            cached_input_tokens=_int_field(input_details, "cached_tokens"),
            cache_write_tokens=_int_field(input_details, "cache_write_tokens"),
            output_tokens=output_tokens,
            reasoning_tokens=_int_field(read_field(usage, "output_tokens_details"), "reasoning_tokens"),
            total_tokens=total if total is not None else input_tokens + output_tokens,
            response_id=str(read_field(response, "id") or ""),
            model=str(read_field(response, "model") or ""),
            service_tier=str(read_field(response, "service_tier") or ""),
        )

    @property
    def tier(self) -> ServiceTierRule:
        """Тариф, по которому ответ посчитан; ответ не назвал — тариф по умолчанию."""
        return ServiceTierRule.of(self.service_tier)

    def cost(self, requested: LlmModel) -> float | None:
        """Стоимость по фактической модели ответа; ответ её не назвал — по запрошенной (правило донора)."""
        served: LlmModel = LlmModel(self.model) if self.model.strip() else requested
        return served.cost(self, self.tier)

    @property
    def log_fields(self) -> str:
        return (
            f"input_tokens={self.input_tokens} cached_input_tokens={self.cached_input_tokens} "
            f"cache_write_tokens={self.cache_write_tokens} output_tokens={self.output_tokens} "
            f"reasoning_tokens={self.reasoning_tokens} total_tokens={self.total_tokens} "
            f"served_model={self.model or UNKNOWN} service_tier={self.tier.value} "
            f"response_id={self.response_id or UNKNOWN}"
        )


@dataclass
class RunUsage:
    """Расход одного запуска: сколько ответов, токенов и долларов. Создаёт запуск; клиент только добавляет.

    `cost_known` ложно, если хоть у одного ответа нет цены или расхода: тогда `cost_usd` — нижняя граница.
    """

    requests: int = 0
    usage_reports: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True
    models: set[str] = field(default_factory=set)
    service_tiers: set[str] = field(default_factory=set)

    def add(self, usage: RequestUsage | None, cost: float | None) -> None:
        """Учесть один полученный ответ; нет расхода или цены — стоимость запуска помечается неизвестной."""
        self.requests += 1
        if usage is None:
            self.cost_known = False
            return
        self.usage_reports += 1
        if cost is None:
            self.cost_known = False
        else:
            self.cost_usd += cost
        self.input_tokens += usage.input_tokens
        self.cached_input_tokens += usage.cached_input_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_tokens += usage.reasoning_tokens
        self.tokens += usage.total_tokens
        if usage.model:
            self.models.add(usage.model)
        self.service_tiers.add(usage.tier.value)

    @property
    def tokens_known(self) -> bool:
        """Расход известен по каждому ответу запуска."""
        return self.requests > 0 and self.usage_reports == self.requests

    @property
    def log_line(self) -> str:
        return (
            f"llm_run_usage requests={self.requests} usage_reports={self.usage_reports} "
            f"input_tokens={self.input_tokens} cached_input_tokens={self.cached_input_tokens} "
            f"cache_write_tokens={self.cache_write_tokens} output_tokens={self.output_tokens} "
            f"reasoning_tokens={self.reasoning_tokens} total_tokens={self.tokens} "
            f"cost_usd={COST_FORMAT.format(self.cost_usd)} cost_known={'yes' if self.cost_known else 'no'} "
            f"models={LOG_JOINER.join(sorted(self.models)) or UNKNOWN} "
            f"service_tiers={LOG_JOINER.join(sorted(self.service_tiers)) or UNKNOWN}"
        )
