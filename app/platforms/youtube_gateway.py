"""Единственная точка обращения к YouTube Data API (CLAUDE.md §6 инвариант 9).

Каждое обращение: память отказов (запомненный отказ поднимается без сети и без паузы) → клиент канала (вход в
браузере — только когда его явно разрешил вызывающий) → пауза `youtube_pause_seconds` от конца прошлого обращения
(паузы повторов входят в неё) → попытка → повторы цикла `RetryLoop` по поведению отказа → окончательный отказ в
память и строка `youtube_refused`; успешное обращение — строка `youtube_call`: попытки и единицы квоты (§14 решение
38). Чтение одного объекта по id: пустой `items` — не «объекта нет», а возможная задержка площадки после записи; он
повторяется тем же циклом, после всех попыток — строка `read_not_listed` и None; найденный объект — одна строка
`youtube_call` с его id и всеми попытками чтения.
Счётчики запуска — `YouTubeUsage`. Время — только часы программы (`clock`), сон — поле `sleep`.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest

from app.config.channel import ChannelConfig
from app.core.clock import Clock
from app.core.retry import AttemptFailure, RetryLoop, RetryPolicy, RetryRun, RetryStep
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.platforms.error import PlatformCode, PlatformDetail, PlatformError
from app.platforms.youtube_event import YouTubeEvent
from app.platforms.youtube_failure import BELOW_HTTP_ERRORS, YouTubeFailure
from app.platforms.youtube_logins import ChannelLogins
from app.platforms.youtube_operation import YouTubeOperation
from app.platforms.youtube_refusal import Refusal, RefusalBook
from app.platforms.youtube_response import YouTubeResponse
from app.platforms.youtube_usage import YouTubeUsage

LOGGER = get_logger(LogArea.PLATFORMS)
DELAY_DIGITS: Final[int] = 2   # пауза повтора в строке лога — до сотых секунды

Request = Callable[[Resource], HttpRequest]


@dataclass
class YouTubeGateway:
    """Обращения к API одного запуска: входы каналов, пауза между обращениями, повторы, отказы и расход."""

    logins: ChannelLogins
    clock: Clock
    pause_sec: float
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=random.Random)
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    refusals: RefusalBook = field(default_factory=RefusalBook)
    usage: YouTubeUsage = field(default_factory=YouTubeUsage)
    last_done: datetime | None = None   # конец прошлого обращения по часам программы

    def call(
        self, channel: ChannelConfig, operation: YouTubeOperation, request: Request, allow_login: bool = False
    ) -> YouTubeResponse:
        """Ответ API и строка обращения; отказ — PlatformError (запомненный — без обращения к сети)."""
        answered: RetryRun[YouTubeResponse] = self._answered(channel, operation, request, allow_login)
        YouTubeEvent.CALL.of_call(operation, channel, answered.attempts).emit(LOGGER)
        return answered.value

    def read_by_id(
        self, channel: ChannelConfig, operation: YouTubeOperation, object_id: str, request: Request
    ) -> YouTubeResponse | None:
        """Первый элемент `items` чтения по id; пусто и после всех повторов — None. Что это значит, решает
        вызывающий. Списки по статусу сюда не ходят: у них пустой ответ нормален. Попытки строки обращения — все
        попытки этого чтения по счётчику запуска."""
        before: int = self.usage.of(operation).attempts
        run: RetryRun[YouTubeResponse] = self._loop.run(
            lambda: self._first_item(channel, operation, object_id, request),
            lambda step: self._log_retry(channel, operation, step),
        )
        if run.value is not None:
            attempts: int = self.usage.of(operation).attempts - before
            YouTubeEvent.CALL.of_call(operation, channel, attempts, object_id=object_id).emit(LOGGER)
            return run.value
        not_listed: LogEvent = YouTubeEvent.READ_NOT_LISTED.of_operation(
            operation, channel, object_id=object_id, attempts=run.attempts
        )
        not_listed.emit(LOGGER, logging.WARNING)
        return None

    def require_by_id(
        self, channel: ChannelConfig, operation: YouTubeOperation, object_id: str, request: Request
    ) -> YouTubeResponse:
        """То же чтение, но без объекта работать нечем: пусто после всех повторов — PlatformError(notListed)."""
        found: YouTubeResponse | None = self.read_by_id(channel, operation, object_id, request)
        if found is None:
            raise self._not_listed(operation, object_id)
        return found

    @property
    def _loop(self) -> RetryLoop:
        return RetryLoop(self.policy, self.rng, self.sleep)

    def _answered(
        self, channel: ChannelConfig, operation: YouTubeOperation, request: Request, allow_login: bool
    ) -> RetryRun[YouTubeResponse]:
        """Итог цикла с ответом; отказ — PlatformError (запомненный — без обращения к сети)."""
        remembered: Refusal | None = self.refusals.find(channel.key, operation)
        if remembered is not None:
            skipped: LogEvent = YouTubeEvent.REQUEST_SKIPPED.of_operation(
                operation, channel, reason=remembered.error.code, behavior=remembered.behavior
            )
            skipped.emit(LOGGER)
            raise remembered.error
        service: Resource = self._service(channel, operation, allow_login)
        run: RetryRun[YouTubeResponse] = self._loop.run(
            lambda: self._attempt(channel, operation, service, request),
            lambda step: self._log_retry(channel, operation, step),
        )
        if run.failure is not None:
            raise self._refuse(channel, YouTubeFailure.of_attempt(operation, run.failure))
        return run

    def _service(self, channel: ChannelConfig, operation: YouTubeOperation, allow_login: bool) -> Resource:
        """Клиент канала; отказ входа — такой же отказ, как у запроса (authFailed → канал). Запрещённый вход — не
        отказ YouTube: не запоминается и в лог отказов не пишется."""
        try:
            return self.logins.service(channel, allow_login)
        except PlatformError as error:
            if error.code == PlatformCode.LOGIN_REQUIRED.value:
                raise
            raise self._refuse(channel, YouTubeFailure(operation, error)) from error

    def _attempt(
        self, channel: ChannelConfig, operation: YouTubeOperation, service: Resource, request: Request
    ) -> YouTubeResponse | AttemptFailure:
        """Одна попытка после остатка паузы от конца прошлого обращения (перед первым ждать нечего): ответ или неудача
        для цикла повторов; конец попытки — отсчёт следующей паузы."""
        if self.pause_sec > 0 and self.last_done is not None:
            remaining: float = self.pause_sec - (self.clock.now() - self.last_done).total_seconds()
            if remaining > 0:
                self.sleep(remaining)
        self.usage.attempted(operation)
        try:
            answer: object = request(service).execute()
        except HttpError as error:
            return YouTubeFailure.of_http(operation, error).attempt
        except BELOW_HTTP_ERRORS as error:
            return YouTubeFailure.of_error(operation, channel, error).attempt
        finally:
            self.last_done = self.clock.now()
        return YouTubeResponse.of(operation, answer)

    def _first_item(
        self, channel: ChannelConfig, operation: YouTubeOperation, object_id: str, request: Request
    ) -> YouTubeResponse | AttemptFailure:
        items: tuple[YouTubeResponse, ...] = self._answered(channel, operation, request, False).value.items()
        if items:
            return items[0]
        self.usage.empty_answer(operation)
        return YouTubeFailure(operation, self._not_listed(operation, object_id)).attempt

    def _not_listed(self, operation: YouTubeOperation, object_id: str) -> PlatformError:
        """Площадка не отдала объект по id и после всех повторов."""
        detail: str = PlatformDetail.NOT_LISTED.text(
            operation=operation.value, object_id=object_id, attempts=self.policy.max_attempts
        )
        return PlatformError(PlatformCode.NOT_LISTED, detail)

    def _log_retry(self, channel: ChannelConfig, operation: YouTubeOperation, step: RetryStep) -> None:
        retry: LogEvent = YouTubeEvent.REQUEST_RETRY.of_operation(
            operation,
            channel,
            retry=step.retry,
            max_retries=self.policy.max_retries,
            delay_sec=round(step.delay_sec, DELAY_DIGITS),
            http_status=step.failure.status,
            reason=step.failure.error_name,
        )
        retry.emit(LOGGER, logging.WARNING)
        self.usage.retried(operation)

    def _refuse(self, channel: ChannelConfig, failure: YouTubeFailure) -> PlatformError:
        """Окончательный отказ: запомнить по поведению, записать строку и вернуть ошибку для raise."""
        refusal: Refusal = self.refusals.remember(channel.key, failure)
        refused: LogEvent = YouTubeEvent.REFUSED.of_operation(
            failure.operation,
            channel,
            http_status=failure.http_status,
            reason=refusal.error.code,
            behavior=failure.behavior,
            message=Quoted(refusal.error.message),
        )
        refused.emit(LOGGER, logging.WARNING)
        self.usage.refused(failure.operation)
        return refusal.error
