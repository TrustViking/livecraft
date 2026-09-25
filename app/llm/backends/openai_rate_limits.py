"""Остаток лимитов OpenAI из заголовков ответа (CLAUDE.md §2 строки про llm\\: `llm_rate_limits.py` restreamer).

Только для OpenAI: заголовки `x-ratelimit-*` — её; в общий ответ разъёма снимок не входит, он идёт в лог.
Правила донора: из всех заголовков `x-ratelimit-*` берётся самый жёсткий остаток запросов и токенов и самое
близкое обнуление; обнуление приходит как «1m30s», «200ms», «6s», число секунд или момент в секундах эпохи.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.llm.backends.openai_response import parse_int

HEADER_PREFIX: Final[str] = "x-ratelimit-"
MARK_REMAINING: Final[str] = "remaining"
MARK_RESET: Final[str] = "reset"
MARK_REQUESTS: Final[str] = "request"
MARK_TOKENS: Final[str] = "token"
NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?")
DURATION_PART_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
UNIT_SECONDS: Final[dict[str, float]] = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
# Число больше этого — не длительность, а момент в секундах эпохи (правило донора).
EPOCH_THRESHOLD_SEC: Final[float] = 1_000_000_000.0
# Где у ответа SDK лежат заголовки: у сырого ответа, у его response или у http_response.
HEADER_HOLDERS: Final[tuple[str, ...]] = ("response", "http_response")
UNKNOWN: Final[str] = "unknown"


def parse_reset_seconds(raw: str, now: float) -> float | None:
    """Обнуление лимита в секундах от `now`: «1m30s» → 90, «200ms» → 0.2, момент эпохи — сколько до него."""
    text: str = str(raw or "").strip().lower()
    if not text:
        return None
    if NUMBER_PATTERN.fullmatch(text):
        value: float = float(text)
        return max(0.0, value - now) if value > EPOCH_THRESHOLD_SEC else max(0.0, value)
    parts: list[re.Match[str]] = list(DURATION_PART_PATTERN.finditer(text))
    if not parts:
        return None
    return max(0.0, sum(float(part.group(1)) * UNIT_SECONDS[part.group(2)] for part in parts))


def _header_items(holder: Any) -> Iterable[tuple[Any, Any]]:
    """Пары заголовков объекта: словарь или объект с `items()` (httpx.Headers); иначе пусто."""
    if isinstance(holder, Mapping):
        return holder.items()
    items: Any = getattr(holder, "items", None)
    return items() if callable(items) else ()


@dataclass(frozen=True)
class RateLimitSnapshot:
    """Сколько осталось запросов и токенов и через сколько секунд лимиты обнулятся; None — заголовка не было."""

    remaining_requests: int | None
    remaining_tokens: int | None
    reset_requests_sec: float | None
    reset_tokens_sec: float | None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str], clock: Callable[[], float] = time.time) -> RateLimitSnapshot:
        now: float = clock()
        remaining_requests: list[int] = []
        remaining_tokens: list[int] = []
        reset_requests: list[float] = []
        reset_tokens: list[float] = []
        for raw_name, raw_value in headers.items():
            name: str = str(raw_name or "").strip().lower()
            if not name.startswith(HEADER_PREFIX):
                continue
            value: str = str(raw_value or "").strip()
            if MARK_REMAINING in name:
                count: int | None = parse_int(value)
                if count is not None and MARK_REQUESTS in name:
                    remaining_requests.append(count)
                if count is not None and MARK_TOKENS in name:
                    remaining_tokens.append(count)
            if MARK_RESET in name:
                seconds: float | None = parse_reset_seconds(value, now)
                if seconds is not None and MARK_REQUESTS in name:
                    reset_requests.append(seconds)
                if seconds is not None and MARK_TOKENS in name:
                    reset_tokens.append(seconds)
        return cls(
            remaining_requests=min(remaining_requests, default=None),
            remaining_tokens=min(remaining_tokens, default=None),
            reset_requests_sec=min(reset_requests, default=None),
            reset_tokens_sec=min(reset_tokens, default=None),
        )

    @classmethod
    def from_raw_response(cls, raw: Any, clock: Callable[[], float] = time.time) -> RateLimitSnapshot | None:
        """Снимок из сырого ответа SDK; заголовков нет — None."""
        headers: dict[str, str] = {}
        for holder in (raw, *(getattr(raw, name, None) for name in HEADER_HOLDERS)):
            found: Any = getattr(holder, "headers", None)
            if found is not None:
                headers = {str(key).strip(): str(value).strip() for key, value in _header_items(found) if str(key).strip()}
                break
        return cls.from_headers(headers, clock) if headers else None

    @property
    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (self.remaining_requests, self.remaining_tokens, self.reset_requests_sec, self.reset_tokens_sec)
        )

    def log_line(self, model: str, label: str) -> str:
        """Строка лога: только найденные значения, обнуления — целыми секундами (как у донора)."""
        parts: list[str] = ["llm_rate_limits", f"model={model or UNKNOWN}", f"label={label or UNKNOWN}"]
        if self.remaining_requests is not None:
            parts.append(f"rem_req={self.remaining_requests}")
        if self.remaining_tokens is not None:
            parts.append(f"rem_tok={self.remaining_tokens}")
        if self.reset_requests_sec is not None:
            parts.append(f"reset_req={round(self.reset_requests_sec)}s")
        if self.reset_tokens_sec is not None:
            parts.append(f"reset_tok={round(self.reset_tokens_sec)}s")
        return " ".join(parts)
