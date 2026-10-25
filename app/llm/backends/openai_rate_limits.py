"""Остаток лимитов OpenAI из заголовков ответа (CLAUDE.md §2 строки про llm\\). Только для OpenAI.

Заголовки `x-ratelimit-*` — её; в общий ответ разъёма снимок не входит, он идёт в лог. Из всех заголовков
`x-ratelimit-*` берётся самый жёсткий остаток запросов и токенов и самое близкое обнуление; обнуление приходит как
«1m30s», «200ms», «6s», число секунд или момент в секундах эпохи (`ResetText`).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from app.core.clock import Clock
from app.llm.backends.openai_response import parse_int
from app.observability.log_event import LogEvent, LogValue

HEADER_PREFIX: Final[str] = "x-ratelimit-"
MARK_REMAINING: Final[str] = "remaining"
MARK_RESET: Final[str] = "reset"
MARK_REQUESTS: Final[str] = "request"
MARK_TOKENS: Final[str] = "token"
HEADERS_ATTR: Final[str] = "headers"
ITEMS_ATTR: Final[str] = "items"
NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?")
DURATION_PART_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
UNIT_SECONDS: Final[dict[str, float]] = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
DURATION_VALUE_GROUP: Final[int] = 1
DURATION_UNIT_GROUP: Final[int] = 2
SECONDS_TEMPLATE: Final[str] = "{seconds}s"
# Число больше этого — не длительность, а момент в секундах эпохи.
EPOCH_THRESHOLD_SEC: Final[float] = 1_000_000_000.0
# Где у ответа SDK лежат заголовки: у сырого ответа, у его response или у http_response.
HEADER_HOLDERS: Final[tuple[str, ...]] = ("response", "http_response")


class RateLimitEvent(str, Enum):
    """События лимитов в логе."""

    SNAPSHOT = "llm_rate_limits"


class RateField(str, Enum):
    """Поля строки лимитов: пишутся только найденные."""

    REMAINING_REQUESTS = "rem_req"
    REMAINING_TOKENS = "rem_tok"
    RESET_REQUESTS = "reset_req"
    RESET_TOKENS = "reset_tok"


@dataclass(frozen=True)
class ResetText:
    """Значение заголовка обнуления лимита."""

    raw: str

    def seconds(self, now: float) -> float | None:
        """Секунды до обнуления от `now`: «1m30s» → 90, «200ms» → 0.2, момент эпохи — сколько до него; не читается — None."""
        text: str = self.raw.strip().lower()
        if NUMBER_PATTERN.fullmatch(text):
            value: float = float(text)
            return max(0.0, value - now) if value > EPOCH_THRESHOLD_SEC else max(0.0, value)
        parts: list[re.Match[str]] = list(DURATION_PART_PATTERN.finditer(text))
        if not parts:
            return None
        units: float = sum(
            float(part.group(DURATION_VALUE_GROUP)) * UNIT_SECONDS[part.group(DURATION_UNIT_GROUP)] for part in parts
        )
        return max(0.0, units)


@dataclass(frozen=True)
class HeaderHolder:
    """Заголовки, как их отдал SDK: словарь или объект с `items()` (httpx.Headers)."""

    found: Any

    @property
    def pairs(self) -> dict[str, str]:
        """Имя и значение каждого заголовка без краёв; пустые имена пропускаются; заголовков не видно — пусто."""
        items: Any = self.found.items if isinstance(self.found, Mapping) else getattr(self.found, ITEMS_ATTR, None)
        found: Any = items() if callable(items) else ()
        return {str(key).strip(): str(value).strip() for key, value in found if str(key).strip()}


@dataclass
class RateLimitScan:
    """Проход по заголовкам: остатки и обнуления запросов и токенов из каждого `x-ratelimit-*`."""

    now: float
    remaining_requests: list[int] = field(default_factory=list)
    remaining_tokens: list[int] = field(default_factory=list)
    reset_requests: list[float] = field(default_factory=list)
    reset_tokens: list[float] = field(default_factory=list)

    def take(self, raw_name: str, raw_value: str) -> None:
        name: str = raw_name.strip().lower()
        if not name.startswith(HEADER_PREFIX):
            return
        value: str = raw_value.strip()
        if MARK_REMAINING in name:
            self._sort(name, parse_int(value), self.remaining_requests, self.remaining_tokens)
        if MARK_RESET in name:
            self._sort(name, ResetText(value).seconds(self.now), self.reset_requests, self.reset_tokens)

    def _sort(self, name: str, value: float | None, requests: list[Any], tokens: list[Any]) -> None:
        """Значение — к запросам и (или) к токенам, как говорит имя заголовка; не прочиталось — никуда."""
        if value is not None and MARK_REQUESTS in name:
            requests.append(value)
        if value is not None and MARK_TOKENS in name:
            tokens.append(value)


@dataclass(frozen=True)
class RateLimitSnapshot:
    """Сколько осталось запросов и токенов и через сколько секунд лимиты обнулятся; None — заголовка не было."""

    remaining_requests: int | None
    remaining_tokens: int | None
    reset_requests_sec: float | None
    reset_tokens_sec: float | None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str], clock: Clock) -> RateLimitSnapshot:
        scan: RateLimitScan = RateLimitScan(now=clock.now().timestamp())     # момент эпохи — от «сейчас» программы
        for name, value in headers.items():
            scan.take(name, value)
        return cls(
            remaining_requests=min(scan.remaining_requests, default=None),
            remaining_tokens=min(scan.remaining_tokens, default=None),
            reset_requests_sec=min(scan.reset_requests, default=None),
            reset_tokens_sec=min(scan.reset_tokens, default=None),
        )

    @classmethod
    def from_raw_response(cls, raw: Any, clock: Clock) -> RateLimitSnapshot | None:
        """Снимок из сырого ответа SDK: заголовки первого, у кого они есть; заголовков нет — None."""
        holders: tuple[Any, ...] = (raw, *(getattr(raw, name, None) for name in HEADER_HOLDERS))
        attached: tuple[Any, ...] = tuple(getattr(holder, HEADERS_ATTR, None) for holder in holders)
        found: Any = next((headers for headers in attached if headers is not None), None)
        headers: dict[str, str] = HeaderHolder(found).pairs
        return cls.from_headers(headers, clock) if headers else None

    def event(self, model: str, label: str) -> LogEvent:
        """Строка лога: модель, ярлык запроса и только найденные значения, обнуления — целыми секундами."""
        present: dict[str, object] = {
            RateField.REMAINING_REQUESTS.value: self.remaining_requests,
            RateField.REMAINING_TOKENS.value: self.remaining_tokens,
            RateField.RESET_REQUESTS.value: self._seconds(self.reset_requests_sec),
            RateField.RESET_TOKENS.value: self._seconds(self.reset_tokens_sec),
        }
        found: dict[str, object] = {name: value for name, value in present.items() if value is not None}
        return LogEvent.of(RateLimitEvent.SNAPSHOT, model=model or LogValue.UNKNOWN, label=label or LogValue.UNKNOWN, **found)

    def _seconds(self, value: float | None) -> str | None:
        return SECONDS_TEMPLATE.format(seconds=round(value)) if value is not None else None
