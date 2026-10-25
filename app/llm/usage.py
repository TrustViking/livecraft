"""Расход токенов: один ответ и весь запуск (CLAUDE.md §2 строки про llm\\).

Общие объекты разъёма (`app\\llm\\backend.py`): токены и доллары. Как расход читается из ответа нейросети, по какому
тарифу и почём он посчитан, решает реализация в `app\\llm\\backends\\` — сюда она кладёт уже готовый `RequestUsage`
со стоимостью. Расход запуска — объект `RunUsage`, который держит реализация (§0). `TokenCounts` — сами числа токенов:
кеш — часть входа, рассуждение модели (`thinking_tokens`) — часть выхода.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.observability.log_event import LogEvent, LogValue

COST_FORMAT: Final[str] = "{:.6f}"


class UsageEvent(str, Enum):
    """События расхода в логе."""

    RUN = "llm_run_usage"


@dataclass(frozen=True)
class TokenCounts:
    """Токены ответа или суммы ответов: вход (с кешем и записью кеша внутри), выход (с рассуждением внутри), всего."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenCounts) -> TokenCounts:
        return TokenCounts(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            thinking_tokens=self.thinking_tokens + other.thinking_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    @property
    def uncached_input_tokens(self) -> int:
        """Вход, который не прочитан из кеша и не записан в кеш: он идёт по полной цене входа."""
        return max(0, self.input_tokens - self.cached_input_tokens - self.cache_write_tokens)

    def extend(self, event: LogEvent) -> LogEvent:
        """Строка лога `event` с числами токенов."""
        return event.extended(
            input_tokens=self.input_tokens,
            cached_input_tokens=self.cached_input_tokens,
            cache_write_tokens=self.cache_write_tokens,
            output_tokens=self.output_tokens,
            thinking_tokens=self.thinking_tokens,
            total_tokens=self.total_tokens,
        )


@dataclass(frozen=True)
class RequestUsage:
    """Расход одного ответа, как его назвал сам ответ: модель и тариф — фактические, а не запрошенные.

    `tier` — тариф реализации, по которому посчитан ответ (пусто — у реализации тарифов нет); `label` — ярлык
    запроса; `cost_usd` — стоимость ответа, None — неизвестна (модели нет в ценах реализации).
    """

    tokens: TokenCounts
    response_id: str
    model: str
    tier: str
    label: str
    cost_usd: float | None

    def extend(self, event: LogEvent) -> LogEvent:
        """Строка лога `event` с токенами, фактической моделью, тарифом и номером ответа."""
        return self.tokens.extend(event).extended(
            served_model=self.model or LogValue.UNKNOWN,
            tier=self.tier or LogValue.UNKNOWN,
            response_id=self.response_id or LogValue.UNKNOWN,
        )


@dataclass
class RunUsage:
    """Расход одного запуска: сколько обращений получили ответ и что каждый ответ сообщил о расходе.

    `requests` — сколько ответов получено; `reports` — расход тех, что его сообщили. `cost_known` ложно, если
    хоть у одного ответа нет расхода или цены: тогда `cost_usd` — нижняя граница.
    """

    requests: int = 0
    reports: list[RequestUsage] = field(default_factory=list)

    def add(self, usage: RequestUsage | None) -> None:
        """Учесть один полученный ответ; нет расхода — стоимость запуска становится неизвестной."""
        self.requests += 1
        if usage is not None:
            self.reports.append(usage)

    @property
    def usage_reports(self) -> int:
        return len(self.reports)

    @property
    def tokens_known(self) -> bool:
        """Расход известен по каждому ответу запуска."""
        return self.requests > 0 and self.usage_reports == self.requests

    @property
    def cost_known(self) -> bool:
        return self.usage_reports == self.requests and all(usage.cost_usd is not None for usage in self.reports)

    @property
    def tokens(self) -> TokenCounts:
        """Токены всех ответов, сообщивших расход."""
        return sum((usage.tokens for usage in self.reports), TokenCounts())

    @property
    def cost_usd(self) -> float:
        return sum(usage.cost_usd for usage in self.reports if usage.cost_usd is not None)

    @property
    def models(self) -> set[str]:
        return {usage.model for usage in self.reports if usage.model}

    @property
    def tiers(self) -> set[str]:
        return {usage.tier for usage in self.reports if usage.tier}

    @property
    def tier_by_request(self) -> tuple[tuple[str, str], ...]:
        """Ярлык запроса и тариф его ответа — в порядке ответов; ответ без тарифа не попадает."""
        return tuple((usage.label, usage.tier) for usage in self.reports if usage.tier)

    @property
    def event(self) -> LogEvent:
        """Строка `llm_run_usage`: ответы, токены, стоимость, модели и тарифы запуска."""
        counted: LogEvent = LogEvent.of(UsageEvent.RUN, requests=self.requests, usage_reports=self.usage_reports)
        return self.tokens.extend(counted).extended(
            cost_usd=COST_FORMAT.format(self.cost_usd),
            cost_known=self.cost_known,
            models=sorted(self.models) or LogValue.UNKNOWN,
            tiers=sorted(self.tiers) or LogValue.UNKNOWN,
        )
