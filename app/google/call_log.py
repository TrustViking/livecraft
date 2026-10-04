"""Строка лога успешного обращения к Google Диску и Google Docs (CLAUDE.md §14 решение 38).

Клиенты Диска (app\\google\\drive.py) и Docs (app\\google\\docs.py) обращаются к API через цикл повторов
`CallFailures.call`; `CallLog` ведёт то же обращение и после ответа пишет строку «событие call=<обращение>
attempts=<попытки>». Отказ строкой не пишется здесь: его пишет тот, кто звал клиента (`drive_failed`, `docs_failed`),
— он знает, зачем звал. Адресов и значений в строке нет.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from app.core.retry import AttemptFailure, RetryLoop
from app.google.call_failure import CallFailures
from app.observability.log_event import LogArea, LogEvent, get_logger

LOGGER = get_logger(LogArea.PUBLISH)

T = TypeVar("T")


@dataclass
class CountedRequest(Generic[T]):
    """Обращение, которое считает свои попытки: цикл повторов зовёт его заново на каждой."""

    request: Callable[[], T]
    attempts: int = 0

    def __call__(self) -> T:
        self.attempts += 1
        return self.request()


@dataclass(frozen=True)
class CallLog:
    """Событие клиента и обращение: какой строкой лога отметить ответ."""

    event: Enum
    call: Enum

    def run(
        self, failures: CallFailures, loop: RetryLoop, request: Callable[[], T],
        error: Callable[[AttemptFailure], Exception],
    ) -> T:
        """Ответ обращения с повторами `loop` и строка с числом попыток; неудача — исключение вызывающего (`error`)."""
        counted: CountedRequest[T] = CountedRequest(request)
        answer: T = failures.call(loop, counted, error)
        LogEvent.of(self.event, call=self.call, attempts=counted.attempts).emit(LOGGER)
        return answer
