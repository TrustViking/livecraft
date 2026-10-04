"""Повторы сетевых обращений — одна политика и один цикл на всю программу (CLAUDE.md §11).

`RetryPolicy` — сколько раз повторять и с какой паузой: первое обращение и до четырёх повторов, пауза
удваивается от базовой, плюс случайная добавка (jitter), которая разводит повторы во времени, и потолок.
`RetryLoop` — сам цикл «обращение → неудача → пауза → повтор»: им ходят Google Sheets, превью источников,
OpenAI, Telegram и форма ключей. Что повторять, решает вызывающий: его обращение возвращает либо результат, либо
`AttemptFailure` с признаком `is_retryable`. `rng` и `sleep` — параметрами, в тестах свои.
"""
from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus
from typing import Final, Generic, TypeVar

import requests

MAX_RETRIES: Final[int] = 4             # после первого обращения — не больше стольких повторов
BASE_DELAY_SEC: Final[float] = 2.0      # пауза перед первым повтором без добавки
MAX_DELAY_SEC: Final[float] = 32.0      # потолок паузы вместе с добавкой
JITTER_MAX_SEC: Final[float] = 1.0      # случайная добавка к паузе: от 0 до стольких секунд
DELAY_GROWTH: Final[int] = 2            # каждый следующий повтор ждёт вдвое дольше
# Ответы, после которых то же обращение имеет смысл повторить: перегрузка и временные сбои сервера.
RETRYABLE_HTTP_STATUSES: Final[frozenset[int]] = frozenset(
    {
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)
# Сбои запроса requests, после которых то же обращение имеет смысл повторить: обрыв связи и таймаут.
RETRYABLE_ERRORS: Final[tuple[type[Exception], ...]] = (requests.ConnectionError, requests.Timeout)

T = TypeVar("T")


class FailureField(str, Enum):
    """Поля неудачного обращения в строке лога."""

    STATUS = "status"
    ERROR = "error"


@dataclass(frozen=True)
class RetryPolicy:
    """Паузы повторов 1–4: 2–3, 4–5, 8–9, 16–17 с."""

    max_retries: int = MAX_RETRIES
    base_delay_sec: float = BASE_DELAY_SEC
    max_delay_sec: float = MAX_DELAY_SEC
    jitter_max_sec: float = JITTER_MAX_SEC

    @property
    def max_attempts(self) -> int:
        """Обращений всего: первое и все повторы."""
        return self.max_retries + 1

    def has_retry_left(self, retry_number: int) -> bool:
        """Можно ли сделать повтор с этим номером (повторы нумеруются с 1)."""
        return 1 <= retry_number <= self.max_retries

    def delay_sec(self, retry_number: int, rng: random.Random) -> float:
        """Пауза перед повтором retry_number: удвоение от базовой плюс добавка, не больше потолка."""
        base: float = self.base_delay_sec * DELAY_GROWTH ** (retry_number - 1)
        return min(base + rng.uniform(0, self.jitter_max_sec), self.max_delay_sec)


@dataclass(frozen=True)
class AttemptFailure:
    """Одно неудачное обращение: причина вызывающего, повторять ли, код ответа и имя исключения.

    `cause` — исходная ошибка: её текст наружу не выводится (в нём бывают адреса с секретами), но она
    остаётся причиной (`__cause__`) ошибки, которую вызывающий бросит после последней неудачи.
    """

    reason: Enum
    is_retryable: bool
    status: int | None = None
    error_name: str | None = None
    cause: BaseException | None = None

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Код ответа и имя исключения — поля строки лога; самого текста ошибки в логе нет."""
        return {FailureField.STATUS.value: self.status, FailureField.ERROR.value: self.error_name}


@dataclass(frozen=True)
class RetryStep:
    """Решение о повторе: какая неудача, номер повтора (с 1) и пауза перед ним."""

    failure: AttemptFailure
    retry: int
    delay_sec: float


@dataclass(frozen=True)
class RetryRun(Generic[T]):
    """Итог цикла: результат или последняя неудача, и сколько обращений ушло всего."""

    value: T | None
    failure: AttemptFailure | None
    attempts: int


@dataclass(frozen=True)
class RetryLoop:
    """Цикл повторов по политике: обращение, при повторяемой неудаче — пауза и новое обращение."""

    policy: RetryPolicy
    rng: random.Random
    sleep: Callable[[float], None]

    def run(self, attempt: Callable[[], T | AttemptFailure], on_retry: Callable[[RetryStep], None]) -> RetryRun[T]:
        """Обращаться, пока не выйдет результат, неповторяемая неудача или повторы политики.

        Перед каждой паузой зовётся `on_retry`: строку повтора в лог пишет вызывающий — он знает, что читал.
        """
        retry: int = 0
        while True:
            outcome: T | AttemptFailure = attempt()
            if not isinstance(outcome, AttemptFailure):
                return RetryRun(value=outcome, failure=None, attempts=retry + 1)
            retry += 1
            if not outcome.is_retryable or not self.policy.has_retry_left(retry):
                return RetryRun(value=None, failure=outcome, attempts=retry)
            step: RetryStep = RetryStep(failure=outcome, retry=retry, delay_sec=self.policy.delay_sec(retry, self.rng))
            on_retry(step)
            self.sleep(step.delay_sec)
