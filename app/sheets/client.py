"""Чтение диапазона таблицы плана из Google Sheets (CLAUDE.md §2 контур A, §3 шаг 2.3, §9).

Только чтение (§6 инвариант 3): `spreadsheets().values().get(...)`, скоуп `spreadsheets.readonly` у входа
оператора (`app\\google\\auth.py::GoogleLogin.operator`). Разбор значений — `SheetPlan.from_values` (3.1).

Секреты (§7.4): id таблицы и диапазон лежат в сейфе и раскрываются ровно в одной точке — в параметрах
вызова API (`SheetsReader._request`). Ни значения, ни URL запроса не попадают ни в лог, ни в тексты ошибок:
там только ярлыки с отпечатком (`SecretValue.log_label`) и код ответа. Текст `HttpError` содержит URL с id
таблицы — поэтому он не пишется никуда, а исходная ошибка доступна только как `__cause__`.

Повторы — только через `RetryLoop` (§11): первое обращение и до `max_retries` повторов на 429, 5xx
и транспортных сбоях. Запасного диапазона при «Unable to parse range» нет: диапазон —
значение пользователя, своё программа не подставляет.
"""
from __future__ import annotations

import http.client
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Any, Final

from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from app.core.retry import RETRYABLE_HTTP_STATUSES, AttemptFailure, RetryLoop, RetryPolicy, RetryRun, RetryStep
from app.google.auth import AuthError, AuthErrorReason, GoogleLogin
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.secretsafe.field import SecretField
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.sheets.plan import SheetPlan
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.SHEETS)

SHEETS_API_NAME: Final[str] = "sheets"
SHEETS_API_VERSION: Final[str] = "v4"
VALUES_KEY: Final[str] = "values"
# Сбои ниже HTTP: обрыв, таймаут, SSL, сервер не найден (DNS), сбой транспорта google-auth при обновлении
# токена по ходу запроса. Повторяются с той же паузой, что и 429.
TRANSPORT_ERRORS: Final[tuple[type[Exception], ...]] = (
    OSError,
    http.client.HTTPException,
    ServerNotFoundError,
    TransportError,
)


class SheetsReadReason(str, Enum):
    """Почему таблица не прочиталась."""

    NOT_CONFIGURED = "not_configured"   # в сейфе нет id таблицы или диапазона — к Google не обращались
    AUTH = "auth"                       # вход оператора не удался или токен отозван по ходу запроса
    NO_ACCESS = "no_access"             # 401 / 403
    NOT_FOUND = "not_found"             # 404
    BAD_RANGE = "bad_range"             # 400: Google не разобрал диапазон
    REJECTED = "rejected"               # прочий неповторяемый код ответа
    UNAVAILABLE = "unavailable"         # повторы кончились на 429, 5xx или транспорте

    @classmethod
    def for_status(cls, status: int) -> SheetsReadReason:
        """Причина по коду ответа: 429 и 5xx — таблица временно недоступна, прочие коды — по таблице причин."""
        if status in RETRYABLE_HTTP_STATUSES:
            return cls.UNAVAILABLE
        return _STATUS_REASONS.get(status, cls.REJECTED)

    @property
    def human(self) -> str:
        return msg.SHEETS_READ_REASON_TEXT[self.value]

    @property
    def is_configuration(self) -> bool:
        """Сбой лечится настройкой или входом, а не повтором: это ошибка конфигурации или авторизации (§10, код 2)."""
        return self in (SheetsReadReason.NOT_CONFIGURED, SheetsReadReason.AUTH)


_STATUS_REASONS: Final[dict[int, SheetsReadReason]] = {
    HTTPStatus.BAD_REQUEST: SheetsReadReason.BAD_RANGE,
    HTTPStatus.UNAUTHORIZED: SheetsReadReason.NO_ACCESS,
    HTTPStatus.FORBIDDEN: SheetsReadReason.NO_ACCESS,
    HTTPStatus.NOT_FOUND: SheetsReadReason.NOT_FOUND,
}


class SheetsEvent(str, Enum):
    """События чтения таблицы в логе."""

    READ_STARTED = "sheets_read_started"
    READ_RETRY = "sheets_read_retry"
    READ_DONE = "sheets_read_done"
    READ_FAILED = "sheets_read_failed"
    AUTH_FAILED = "sheets_auth_failed"


class SheetsReadError(Exception):
    """Таблица не прочиталась. Текст — русская строка с ярлыком таблицы и кодом ответа, без значений.

    `detail` — уже готовая для человека подробность без секретов (причина входа, названия полей сейфа).
    """

    def __init__(
        self, reason: SheetsReadReason, label: str, status: int | None = None, detail: str = ""
    ) -> None:
        self.reason: SheetsReadReason = reason
        self.label: str = label
        self.status: int | None = status
        self.detail: str = detail
        super().__init__(self.human)

    @classmethod
    def from_failure(cls, failure: AttemptFailure, label: str) -> SheetsReadError:
        """Последняя неудача чтения → ошибка. Токен отозван по ходу запроса — нужен новый вход (браузер здесь
        не открывается)."""
        reason: SheetsReadReason = SheetsReadReason(failure.reason)
        detail: str = AuthErrorReason.LOGIN_REQUIRED.human if reason is SheetsReadReason.AUTH else ""
        return cls(reason, label, failure.status, detail)

    @property
    def human(self) -> str:
        reason: str = self.reason.human.format(detail=self.detail)
        if self.status is None:
            return msg.SHEETS_READ_FAILED.format(label=self.label, reason=reason)
        return msg.SHEETS_READ_FAILED_STATUS.format(label=self.label, reason=reason, status=self.status)

    @property
    def log_line(self) -> str:
        return LogEvent.of(SheetsEvent.READ_FAILED, reason=self.reason, sheet=self.label, status=self.status).text


@dataclass(frozen=True)
class SheetsTarget:
    """Что читать: id таблицы и диапазон из сейфа — секреты, а не строки."""

    sheet_id: SecretValue
    sheet_range: SecretValue

    @classmethod
    def from_vault(cls, vault: Vault) -> SheetsTarget:
        """Оба поля из сейфа; нет хотя бы одного — SheetsReadError(NOT_CONFIGURED), к Google не обращаемся."""
        sheet_id: SecretValue | None = vault.get(SecretField.SHEETS_ID)
        sheet_range: SecretValue | None = vault.get(SecretField.SHEETS_RANGE)
        if sheet_id is None or sheet_range is None:
            absent: tuple[SecretField, ...] = vault.missing_of((SecretField.SHEETS_ID, SecretField.SHEETS_RANGE))
            label: str = sheet_id.log_label if sheet_id is not None else SecretField.SHEETS_ID.log_label
            detail: str = msg.LIST_JOINER.join(field.human_label for field in absent)
            raise SheetsReadError(SheetsReadReason.NOT_CONFIGURED, label, detail=detail)
        return cls(sheet_id=sheet_id, sheet_range=sheet_range)

    def event(self, name: SheetsEvent) -> LogEvent:
        """Строка лога о чтении этой таблицы: ярлыки с отпечатком вместо значений (§7.4)."""
        return LogEvent.of(name, sheet=self.sheet_id.log_label, range=self.sheet_range.log_label)


@dataclass(frozen=True)
class SheetsReader:
    """Читатель таблиц одного входа оператора.

    `service` — объект googleapiclient или подделка с той же цепочкой
    `spreadsheets().values().get(...).execute()`; `policy`, `rng` и `sleep` — параметрами, в тестах свои.
    """

    service: Any
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def open(
        cls, login: GoogleLogin, allow_login: bool = True, on_login: Callable[[], None] | None = None
    ) -> SheetsReader:
        """Вход оператора и клиент Sheets v4; вход не удался — SheetsReadError(AUTH)."""
        try:
            credentials: Any = login.credentials(allow_login=allow_login, on_login=on_login)
        except AuthError as error:
            LogEvent.of(SheetsEvent.AUTH_FAILED, reason=error.reason, detail=error.detail).emit(LOGGER, logging.WARNING)
            raise SheetsReadError(
                SheetsReadReason.AUTH, SecretField.SHEETS_ID.log_label, detail=error.human
            ) from error
        service: Any = build(SHEETS_API_NAME, SHEETS_API_VERSION, credentials=credentials, cache_discovery=False)
        return cls(service=service)

    def read_plan(self, vault: Vault) -> SheetPlan:
        """План из таблицы, которую называет сейф."""
        target: SheetsTarget = SheetsTarget.from_vault(vault)
        return SheetPlan.from_values(self.read_values(target.sheet_id, target.sheet_range))

    def read_values(self, sheet_id: SecretValue, sheet_range: SecretValue) -> list[list[str]]:
        """Значения диапазона строками; сбои 429, 5xx и транспорта — повторами по `policy`."""
        target: SheetsTarget = SheetsTarget(sheet_id=sheet_id, sheet_range=sheet_range)
        target.event(SheetsEvent.READ_STARTED).emit(LOGGER)
        run: RetryRun[list[list[str]]] = RetryLoop(self.policy, self.rng, self.sleep).run(
            lambda: self._attempt(sheet_id, sheet_range), lambda step: self._note_retry(target, step)
        )
        if run.failure is not None:
            error: SheetsReadError = SheetsReadError.from_failure(run.failure, sheet_id.log_label)
            failed: LogEvent = LogEvent.of(SheetsEvent.READ_FAILED, reason=error.reason, sheet=error.label)
            failed.extended(**run.failure.log_fields, attempts=run.attempts).emit(LOGGER, logging.ERROR)
            raise error from run.failure.cause
        rows: list[list[str]] = run.value or []
        target.event(SheetsEvent.READ_DONE).extended(rows=len(rows), attempts=run.attempts).emit(LOGGER)
        return rows

    def _note_retry(self, target: SheetsTarget, step: RetryStep) -> None:
        retry: LogEvent = target.event(SheetsEvent.READ_RETRY).extended(**step.failure.log_fields)
        retry.extended(retry=step.retry, delay_sec=round(step.delay_sec, 1)).emit(LOGGER, logging.WARNING)

    def _attempt(self, sheet_id: SecretValue, sheet_range: SecretValue) -> list[list[str]] | AttemptFailure:
        """Одно обращение: значения или неудача; неожиданное исключение — наружу, это ошибка программы.

        Текст исходной ошибки не выводится никуда — у HttpError в нём URL с id таблицы: в лог идут код и имя.
        """
        try:
            response: Any = self._request(sheet_id, sheet_range)
        except HttpError as error:
            status: int = int(error.resp.status)
            reason: SheetsReadReason = SheetsReadReason.for_status(status)
            return AttemptFailure(reason, reason is SheetsReadReason.UNAVAILABLE, status, type(error).__name__, error)
        except RefreshError as error:
            return AttemptFailure(SheetsReadReason.AUTH, False, error_name=type(error).__name__, cause=error)
        except TRANSPORT_ERRORS as error:
            return AttemptFailure(SheetsReadReason.UNAVAILABLE, True, error_name=type(error).__name__, cause=error)
        rows: Any = response.get(VALUES_KEY, []) if isinstance(response, dict) else []
        return [[str(cell) for cell in row] for row in rows]

    def _request(self, sheet_id: SecretValue, sheet_range: SecretValue) -> Any:
        """Единственная точка раскрытия id таблицы и диапазона (§7.4): значения живут только в этом вызове."""
        values: Any = self.service.spreadsheets().values()
        return values.get(spreadsheetId=sheet_id.reveal(), range=sheet_range.reveal()).execute()
