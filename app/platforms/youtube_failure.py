"""Отказ одной попытки обращения к YouTube: что поднять и как с ним поступить (CLAUDE.md §6 инвариант 9).

`YouTubeFailure` сам решает своё поведение (`behavior`) в одном порядке: пара «операция, причина» → создающий вызов
с неизвестным исходом (обрыв связи, 5xx) не повторяется → таблица причин → HTTP 5xx и 429 повторяются → прочее не
повторяется. Окончательный отказ после 5xx или обрыва — «YouTube недоступен» (`final_error`); лимит частоты
сохраняет свою причину. Причину и пояснение из тела ответа Google разбирает `GoogleErrorBody`.

Сбой ниже HTTP (`BELOW_HTTP_ERRORS`) — тоже отказ площадки, а не исключение, которое обрывает запуск: обрыв, таймаут,
DNS и сбой транспорта google-auth — `transportFailed`; токен канала, отозванный или не обновившийся по ходу запроса
(доступ живёт час), — `authFailed`.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus
from typing import Final, cast

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from app.config.channel import ChannelConfig
from app.core.retry import AttemptFailure
from app.google.call_failure import TRANSPORT_ERRORS
from app.platforms.error import PlatformCode, PlatformDetail, PlatformError
from app.platforms.youtube_operation import (
    OPERATION_REASON_BEHAVIORS,
    REASON_BEHAVIORS,
    ErrorBehavior,
    YouTubeOperation,
)

# Сбои обращения без ответа YouTube: отозванный по ходу запроса токен канала и сбои транспорта (одно определение
# на все API Google — `TRANSPORT_ERRORS`).
BELOW_HTTP_ERRORS: Final[tuple[type[Exception], ...]] = (RefreshError, *TRANSPORT_ERRORS)


class GoogleErrorKey(str, Enum):
    """Поля тела отказа Google."""

    ERROR = "error"
    ERRORS = "errors"
    REASON = "reason"
    STATUS = "status"
    MESSAGE = "message"


@dataclass(frozen=True)
class GoogleErrorBody:
    """Тело отказа Google: `{"error": {"errors": [{"reason": …}], "status": …, "message": …}}`."""

    body: Mapping[str, object]

    @classmethod
    def of(cls, content: bytes) -> GoogleErrorBody:
        """Тело не JSON или без объекта `error` — пустое: причина тогда неизвестна."""
        try:
            payload: object = json.loads(content)
        except ValueError:
            return cls({})
        error: object = payload.get(GoogleErrorKey.ERROR) if isinstance(payload, dict) else None
        return cls(error if isinstance(error, dict) else {})

    @property
    def reason(self) -> str:
        """`errors[0].reason`; списка ошибок нет — `status` (gRPC-вид ответа); ничего нет — `unknown`."""
        errors: object = self.body.get(GoogleErrorKey.ERRORS)
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            first: object = errors[0].get(GoogleErrorKey.REASON)
            return first if isinstance(first, str) and first else PlatformCode.UNKNOWN.value
        status: object = self.body.get(GoogleErrorKey.STATUS)
        return status if isinstance(status, str) and status else PlatformCode.UNKNOWN.value

    def message(self, fallback: str) -> str:
        """Пояснение Google; его нет — `fallback`."""
        message: object = self.body.get(GoogleErrorKey.MESSAGE)
        return message if isinstance(message, str) and message else fallback


@dataclass(frozen=True)
class YouTubeFailure:
    """Отказ одной попытки: операция, ошибка площадки и HTTP-код (None — ответа не было вовсе)."""

    operation: YouTubeOperation
    error: PlatformError
    http_status: int | None = None

    @classmethod
    def of_http(cls, operation: YouTubeOperation, error: HttpError) -> YouTubeFailure:
        """HTTP-код, причина из тела ответа Google (liveStreamingNotEnabled и т.п.) и пояснение."""
        status: int = int(error.resp.status)
        body: GoogleErrorBody = GoogleErrorBody.of(error.content)
        message: str = PlatformDetail.HTTP.text(status=status, detail=body.message(str(error)))
        return cls(operation, PlatformError(body.reason, message), status)

    @classmethod
    def of_error(cls, operation: YouTubeOperation, channel: ChannelConfig, error: Exception) -> YouTubeFailure:
        """Сбой ниже HTTP (`BELOW_HTTP_ERRORS`): токен канала не обновился — authFailed, прочее — transportFailed."""
        if isinstance(error, RefreshError):
            auth: str = PlatformDetail.AUTH.text(reason=type(error).__name__, detail=error)
            return cls(operation, PlatformError(PlatformCode.AUTH_FAILED, auth))
        detail: str = PlatformDetail.TRANSPORT.text(operation=operation.value, channel=channel.account_name, error=error)
        return cls(operation, PlatformError(PlatformCode.TRANSPORT_FAILED, detail))

    @classmethod
    def of_attempt(cls, operation: YouTubeOperation, attempt: AttemptFailure) -> YouTubeFailure:
        """Отказ обратно из неудачи цикла повторов (`attempt`): ошибка площадки — её причина."""
        return cls(operation, cast(PlatformError, attempt.cause), attempt.status)

    @property
    def is_unknown_outcome(self) -> bool:
        """Неизвестно, выполнил ли YouTube запрос: связь оборвалась или сервер ответил 5xx."""
        is_server_error: bool = self.http_status is not None and self.http_status >= HTTPStatus.INTERNAL_SERVER_ERROR
        return self.error.code == PlatformCode.TRANSPORT_FAILED.value or is_server_error

    @property
    def behavior(self) -> ErrorBehavior:
        """Единственное место решения; причины нет в таблицах — по HTTP-коду: 5xx и 429 повторяем, прочее — нет."""
        paired: ErrorBehavior | None = OPERATION_REASON_BEHAVIORS.get((self.operation, self.error.code))
        if paired is not None:
            return paired
        if self.operation.is_creating and self.is_unknown_outcome:
            return ErrorBehavior.CALL
        known: ErrorBehavior | None = REASON_BEHAVIORS.get(self.error.code)
        if known is not None:
            return known
        if self.http_status is not None and (
            self.http_status >= HTTPStatus.INTERNAL_SERVER_ERROR or self.http_status == HTTPStatus.TOO_MANY_REQUESTS
        ):
            return ErrorBehavior.RETRY
        return ErrorBehavior.CALL

    @property
    def final_error(self) -> PlatformError:
        """Ошибка окончательного отказа: 5xx и обрыв (после всех попыток или без повтора у создающего вызова) —
        «YouTube недоступен»; прочие — как есть."""
        if self.behavior in (ErrorBehavior.RETRY, ErrorBehavior.CALL) and self.is_unknown_outcome:
            return PlatformError(PlatformCode.TRANSPORT_FAILED, self.error.message)
        return self.error

    @property
    def attempt(self) -> AttemptFailure:
        """Неудача для цикла повторов: повторяется только поведение RETRY; ошибка площадки — причина неудачи."""
        behavior: ErrorBehavior = self.behavior
        return AttemptFailure(
            reason=behavior,
            is_retryable=behavior is ErrorBehavior.RETRY,
            status=self.http_status,
            error_name=self.error.code,
            cause=self.error,
        )
