"""Расход токенов: один ответ и весь запуск (CLAUDE.md §2 строки про llm\\: `llm_usage_tracker.py` restreamer).

Общие объекты разъёма (`app\\llm\\backend.py`): токены и доллары. Как расход читается из ответа нейросети,
по какому тарифу и почём он посчитан, решает реализация в `app\\llm\\backends\\` — сюда она кладёт уже готовый
`RequestUsage` со стоимостью. У донора расход запуска жил в глобальном состоянии модуля
(`_RUN_LOCAL_USAGE_STATE`); здесь это объект `RunUsage`, который держит реализация (§0).
Кеш — часть входа, рассуждение модели (`thinking_tokens`) — часть выхода.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

UNKNOWN: Final[str] = "unknown"
COST_FORMAT: Final[str] = "{:.6f}"
LOG_JOINER: Final[str] = ","


@dataclass(frozen=True)
class RequestUsage:
    """Расход одного ответа, как его назвал сам ответ: модель и тариф — фактические, а не запрошенные.

    `tier` — тариф реализации, по которому посчитан ответ (пусто — у реализации тарифов нет); `label` — ярлык
    запроса; `cost_usd` — стоимость ответа, None — неизвестна (модели нет в ценах реализации).
    """

    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    thinking_tokens: int
    total_tokens: int
    response_id: str
    model: str
    tier: str
    label: str
    cost_usd: float | None

    @property
    def log_fields(self) -> str:
        return (
            f"input_tokens={self.input_tokens} cached_input_tokens={self.cached_input_tokens} "
            f"cache_write_tokens={self.cache_write_tokens} output_tokens={self.output_tokens} "
            f"thinking_tokens={self.thinking_tokens} total_tokens={self.total_tokens} "
            f"served_model={self.model or UNKNOWN} tier={self.tier or UNKNOWN} "
            f"response_id={self.response_id or UNKNOWN}"
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
    def input_tokens(self) -> int:
        return sum(usage.input_tokens for usage in self.reports)

    @property
    def cached_input_tokens(self) -> int:
        return sum(usage.cached_input_tokens for usage in self.reports)

    @property
    def cache_write_tokens(self) -> int:
        return sum(usage.cache_write_tokens for usage in self.reports)

    @property
    def output_tokens(self) -> int:
        return sum(usage.output_tokens for usage in self.reports)

    @property
    def thinking_tokens(self) -> int:
        return sum(usage.thinking_tokens for usage in self.reports)

    @property
    def tokens(self) -> int:
        return sum(usage.total_tokens for usage in self.reports)

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
    def log_line(self) -> str:
        return (
            f"llm_run_usage requests={self.requests} usage_reports={self.usage_reports} "
            f"input_tokens={self.input_tokens} cached_input_tokens={self.cached_input_tokens} "
            f"cache_write_tokens={self.cache_write_tokens} output_tokens={self.output_tokens} "
            f"thinking_tokens={self.thinking_tokens} total_tokens={self.tokens} "
            f"cost_usd={COST_FORMAT.format(self.cost_usd)} cost_known={'yes' if self.cost_known else 'no'} "
            f"models={LOG_JOINER.join(sorted(self.models)) or UNKNOWN} "
            f"tiers={LOG_JOINER.join(sorted(self.tiers)) or UNKNOWN}"
        )
