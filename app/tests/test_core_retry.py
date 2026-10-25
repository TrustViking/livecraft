from __future__ import annotations

import random
from collections.abc import Callable
from enum import Enum
from http import HTTPStatus

import pytest

from app.core.retry import (
    BASE_DELAY_SEC,
    JITTER_MAX_SEC,
    MAX_DELAY_SEC,
    MAX_RETRIES,
    RETRYABLE_HTTP_STATUSES,
    AttemptFailure,
    RetryLoop,
    RetryPolicy,
    RetryRun,
    RetryStep,
)


class _FixedRandom(random.Random):
    """uniform всегда отдаёт заданную долю интервала: границы добавки проверяются точно."""

    def __init__(self, share: float) -> None:
        super().__init__(0)
        self._share: float = share

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self._share


def test_policy_defaults() -> None:
    policy: RetryPolicy = RetryPolicy()
    assert (policy.max_retries, policy.base_delay_sec, policy.max_delay_sec, policy.jitter_max_sec) == (
        MAX_RETRIES, BASE_DELAY_SEC, MAX_DELAY_SEC, JITTER_MAX_SEC
    ) == (4, 2.0, 32.0, 1.0)
    assert policy.max_attempts == 5


@pytest.mark.parametrize(("retry_number", "low"), [(1, 2.0), (2, 4.0), (3, 8.0), (4, 16.0)])
def test_delays_by_retry_number_with_jitter_bounds(retry_number: int, low: float) -> None:
    policy: RetryPolicy = RetryPolicy()
    assert policy.delay_sec(retry_number, _FixedRandom(0.0)) == low
    assert policy.delay_sec(retry_number, _FixedRandom(1.0)) == low + JITTER_MAX_SEC


def test_delays_with_seeded_rng_are_repeatable_and_within_bounds() -> None:
    policy: RetryPolicy = RetryPolicy()
    first: list[float] = [policy.delay_sec(number, random.Random(3)) for number in range(1, 5)]
    second: list[float] = [policy.delay_sec(number, random.Random(3)) for number in range(1, 5)]
    assert first == second
    for number, delay in enumerate(first, start=1):
        assert 2.0 * 2 ** (number - 1) <= delay <= 2.0 * 2 ** (number - 1) + 1.0


def test_delay_never_exceeds_the_ceiling() -> None:
    policy: RetryPolicy = RetryPolicy()
    assert policy.delay_sec(5, _FixedRandom(1.0)) == MAX_DELAY_SEC       # 32 + 1 → 32
    assert policy.delay_sec(10, _FixedRandom(0.0)) == MAX_DELAY_SEC


def test_has_retry_left() -> None:
    policy: RetryPolicy = RetryPolicy()
    assert [policy.has_retry_left(number) for number in range(0, 6)] == [False, True, True, True, True, False]


# --- RetryLoop: один цикл повторов для таблицы, превью и OpenAI


class _Reason(str, Enum):
    BUSY = "busy"
    REFUSED = "refused"


BUSY: AttemptFailure = AttemptFailure(_Reason.BUSY, True, HTTPStatus.SERVICE_UNAVAILABLE, "HttpError")
REFUSED: AttemptFailure = AttemptFailure(_Reason.REFUSED, False, HTTPStatus.NOT_FOUND)


def _loop(sleeps: list[float]) -> RetryLoop:
    return RetryLoop(RetryPolicy(), _FixedRandom(0.0), sleeps.append)


def _attempts(*outcomes: str | AttemptFailure) -> Callable[[], str | AttemptFailure]:
    queue: list[str | AttemptFailure] = list(outcomes)
    return lambda: queue.pop(0)


def test_a_result_at_once_is_one_attempt_without_pauses() -> None:
    sleeps: list[float] = []
    steps: list[RetryStep] = []
    run: RetryRun[str] = _loop(sleeps).run(_attempts("rows"), steps.append)
    assert (run.value, run.failure, run.attempts) == ("rows", None, 1)
    assert sleeps == [] and steps == []


def test_retryable_failures_are_repeated_with_the_policy_pauses() -> None:
    sleeps: list[float] = []
    steps: list[RetryStep] = []
    run: RetryRun[str] = _loop(sleeps).run(_attempts(BUSY, BUSY, "rows"), steps.append)
    assert (run.value, run.failure, run.attempts) == ("rows", None, 3)
    assert sleeps == [2.0, 4.0]
    assert [(step.failure, step.retry, step.delay_sec) for step in steps] == [(BUSY, 1, 2.0), (BUSY, 2, 4.0)]


def test_a_failure_that_is_not_retryable_stops_at_once() -> None:
    sleeps: list[float] = []
    run: RetryRun[str] = _loop(sleeps).run(_attempts(BUSY, REFUSED, "rows"), lambda step: None)
    assert (run.value, run.failure, run.attempts) == (None, REFUSED, 2)
    assert sleeps == [2.0]


def test_the_last_failure_comes_back_when_the_retries_run_out() -> None:
    sleeps: list[float] = []
    run: RetryRun[str] = _loop(sleeps).run(_attempts(*[BUSY] * MAX_RETRIES, BUSY), lambda step: None)
    assert (run.value, run.failure, run.attempts) == (None, BUSY, RetryPolicy().max_attempts)
    assert sleeps == [2.0, 4.0, 8.0, 16.0]


def test_the_failure_gives_its_status_and_error_name_to_the_log() -> None:
    assert BUSY.log_fields == {"status": HTTPStatus.SERVICE_UNAVAILABLE, "error": "HttpError"}
    assert REFUSED.log_fields == {"status": HTTPStatus.NOT_FOUND, "error": None}


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_overload_and_temporary_server_failures_are_retryable(status: int) -> None:
    assert status in RETRYABLE_HTTP_STATUSES


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 501])
def test_client_errors_are_not_retryable(status: int) -> None:
    assert status not in RETRYABLE_HTTP_STATUSES
