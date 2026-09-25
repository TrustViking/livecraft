from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.backends.openai_rate_limits import RateLimitSnapshot, parse_reset_seconds

NOW: float = 1_800_000_000.0


def fixed_clock() -> float:
    return NOW


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("1m30s", 90.0), ("200ms", 0.2), ("6s", 6.0), ("1h", 3600.0), ("12", 12.0), ("0.5", 0.5), (str(NOW + 42), 42.0)],
)
def test_reset_values_become_seconds(raw: str, seconds: float) -> None:
    assert parse_reset_seconds(raw, NOW) == pytest.approx(seconds)


def test_unreadable_reset_is_none_and_the_past_is_zero() -> None:
    assert parse_reset_seconds("", NOW) is None
    assert parse_reset_seconds("скоро", NOW) is None
    assert parse_reset_seconds(str(NOW - 100), NOW) == 0.0


def test_the_tightest_limits_are_taken() -> None:
    headers: dict[str, str] = {
        "X-RateLimit-Remaining-Requests": "499",
        "x-ratelimit-remaining-tokens": "29,000",
        "x-ratelimit-remaining-tokens-usage-based": "12000",
        "x-ratelimit-reset-requests": "1m30s",
        "x-ratelimit-reset-tokens": "200ms",
        "content-type": "application/json",
    }
    snapshot: RateLimitSnapshot = RateLimitSnapshot.from_headers(headers, fixed_clock)
    assert snapshot == RateLimitSnapshot(
        remaining_requests=499, remaining_tokens=12000, reset_requests_sec=90.0, reset_tokens_sec=0.2
    )
    line: str = snapshot.log_line("gpt-5.4", "merge")
    assert line == "llm_rate_limits model=gpt-5.4 label=merge rem_req=499 rem_tok=12000 reset_req=90s reset_tok=0s"


def test_headers_are_found_on_the_raw_response_or_inside_it() -> None:
    direct: RateLimitSnapshot | None = RateLimitSnapshot.from_raw_response(
        SimpleNamespace(headers={"x-ratelimit-remaining-requests": "5"}), fixed_clock
    )
    assert direct is not None and direct.remaining_requests == 5
    nested: RateLimitSnapshot | None = RateLimitSnapshot.from_raw_response(
        SimpleNamespace(response=SimpleNamespace(headers={"x-ratelimit-reset-tokens": "6s"})), fixed_clock
    )
    assert nested is not None and nested.reset_tokens_sec == 6.0 and nested.remaining_requests is None
    assert RateLimitSnapshot.from_raw_response(SimpleNamespace(), fixed_clock) is None


def test_no_ratelimit_headers_is_an_empty_snapshot() -> None:
    snapshot: RateLimitSnapshot = RateLimitSnapshot.from_headers({"content-type": "json"}, fixed_clock)
    assert snapshot.is_empty
    assert snapshot.log_line("", "") == "llm_rate_limits model=unknown label=unknown"
