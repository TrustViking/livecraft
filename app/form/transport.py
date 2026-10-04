"""Обмен с Google Forms: GET страницы формы и POST ответа одной сессией requests (CLAUDE.md §11 «Повторы»).

Сессия одна на запуск: cookies чтения и отправки общие. `get` и `post` — полями, как `post` у бота Telegram: в тестах
свои. Повторы — `RetryLoop`: обрыв связи, таймаут и коды `RETRYABLE_HTTP_STATUSES`; прочий сбой запроса — отказ сразу,
любой другой ответ (и 4xx) — как есть: что он значит, решает читатель формы или отправитель. Ответ POST просим
английским (Accept-Language и hl=en): гарантии Google не даёт, поэтому подтверждение от языка не зависит.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

import requests

from app.core.retry import (
    RETRYABLE_ERRORS,
    RETRYABLE_HTTP_STATUSES,
    AttemptFailure,
    RetryLoop,
    RetryPolicy,
    RetryRun,
    RetryStep,
)
from app.form.failure import FormEvent, FormProblem
from app.observability.log_event import LogArea, LogEvent, get_logger

LOGGER = get_logger(LogArea.FORM)

FORM_TIMEOUT_SEC: Final[float] = 30.0


class ResponseLanguage(str, Enum):
    """Как просить английскую страницу ответа: заголовок запроса и параметр адреса с одним значением."""

    HEADER = "Accept-Language"
    QUERY_KEY = "hl"
    ENGLISH = "en"


@dataclass(frozen=True)
class HttpAnswer:
    """Ответ Google Forms: код, текст страницы и конечный адрес (после редиректа forms.gle)."""

    status: int
    text: str
    url: str

    @classmethod
    def of(cls, response: requests.Response) -> HttpAnswer:
        return cls(status=int(response.status_code), text=response.text, url=str(response.url))


@dataclass(frozen=True)
class HttpRequest:
    """Одно обращение: адрес и тело ответа формы; тела нет — это GET страницы формы."""

    url: str
    body: dict[str, list[str]] | None = None

    @property
    def retry_event(self) -> FormEvent:
        return FormEvent.GET_RETRY if self.body is None else FormEvent.POST_RETRY


@dataclass(frozen=True)
class FormHttp:
    """GET и POST одной сессии; политика повторов, `rng` и `sleep` — полями: в тестах свои."""

    get: Callable[..., requests.Response]
    post: Callable[..., requests.Response]
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def session(cls) -> FormHttp:
        """Обмен на одной сессии requests: cookies страницы формы уходят вместе с ответом."""
        session: requests.Session = requests.Session()
        return cls(get=session.get, post=session.post)

    def exchange(self, request: HttpRequest) -> HttpAnswer | AttemptFailure:
        """Ответ формы или последняя неудача после повторов."""
        loop: RetryLoop = RetryLoop(self.policy, self.rng, self.sleep)
        run: RetryRun[HttpAnswer] = loop.run(
            lambda: self._attempt(request), lambda step: self._note_retry(request, step)
        )
        if run.failure is not None:
            return run.failure
        return run.value

    def _attempt(self, request: HttpRequest) -> HttpAnswer | AttemptFailure:
        """Одно обращение; текст исключения requests не берётся — только его имя."""
        try:
            response: requests.Response = self._send(request)
        except requests.RequestException as error:
            is_retryable: bool = isinstance(error, RETRYABLE_ERRORS)
            return AttemptFailure(FormProblem.TRANSPORT_FAILED, is_retryable, error_name=type(error).__name__)
        status: int = int(response.status_code)
        if status in RETRYABLE_HTTP_STATUSES:
            return AttemptFailure(FormProblem.TRANSPORT_FAILED, True, status)
        return HttpAnswer.of(response)

    def _send(self, request: HttpRequest) -> requests.Response:
        if request.body is None:
            return self.get(request.url, timeout=FORM_TIMEOUT_SEC, allow_redirects=True)
        headers: dict[str, str] = {ResponseLanguage.HEADER.value: ResponseLanguage.ENGLISH.value}
        return self.post(request.url, data=request.body, timeout=FORM_TIMEOUT_SEC, headers=headers)

    def _note_retry(self, request: HttpRequest, step: RetryStep) -> None:
        retry: LogEvent = LogEvent.of(request.retry_event, url=request.url, **step.failure.log_fields)
        retry.extended(retry=step.retry, delay_sec=round(step.delay_sec, 1)).emit(LOGGER, logging.WARNING)
