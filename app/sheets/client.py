"""Чтение диапазона таблицы плана из Google Sheets (CLAUDE.md §2 контур A, §3 шаг 2.3, §9).

Только чтение (§6 инвариант 3): `spreadsheets().values().get(...)`, скоуп `spreadsheets.readonly` у входа
оператора (`app\\google\\auth.py::GoogleLogin.operator`). Разбор значений — `SheetPlan.from_values` (3.1).

Секреты (§7.4): id таблицы и диапазон лежат в сейфе и раскрываются ровно в одной точке — в параметрах
вызова API (`SheetsReader._request`). Ни значения, ни URL запроса не попадают ни в лог, ни в тексты ошибок:
там только ярлыки с отпечатком (`SecretValue.log_label`) и код ответа. Текст `HttpError` содержит URL с id
таблицы — поэтому он не пишется никуда, а исходная ошибка доступна только как `__cause__`.

Повторы — только через `RetryPolicy` (§11): первое обращение и до `max_retries` повторов на 429, 5xx
и транспортных сбоях. Запасного диапазона при «Unable to parse range» нет (он был в restreamer): диапазон —
значение пользователя, своё программа не подставляет.
"""
from __future__ import annotations

import http.client
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from app.core.retry import RetryPolicy
from app.google.auth import AuthError, AuthErrorReason, GoogleLogin
from app.observability.logging_setup import get_logger
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault
from app.sheets.plan import SheetPlan
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "sheets"
LOGGER = get_logger(LOGGER_NAME)

SHEETS_API_NAME: Final[str] = "sheets"
SHEETS_API_VERSION: Final[str] = "v4"
VALUES_KEY: Final[str] = "values"
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
# Сбои ниже HTTP: обрыв, таймаут, SSL, сервер не найден (DNS), сбой транспорта google-auth при обновлении
# токена по ходу запроса. Повторяются с той же паузой, что и 429.
TRANSPORT_ERRORS: Final[tuple[type[Exception], ...]] = (
    OSError,
    http.client.HTTPException,
    ServerNotFoundError,
    TransportError,
)
FIELD_JOINER: Final[str] = ", "


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
        """Причина по коду ответа, который не повторяется."""
        return _STATUS_REASONS.get(status, cls.REJECTED)

    @property
    def human(self) -> str:
        return msg.SHEETS_READ_REASON_TEXT[self.value]


_STATUS_REASONS: Final[dict[int, SheetsReadReason]] = {
    400: SheetsReadReason.BAD_RANGE,
    401: SheetsReadReason.NO_ACCESS,
    403: SheetsReadReason.NO_ACCESS,
    404: SheetsReadReason.NOT_FOUND,
}


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

    @property
    def human(self) -> str:
        reason: str = self.reason.human.format(detail=self.detail)
        if self.status is None:
            return msg.SHEETS_READ_FAILED.format(label=self.label, reason=reason)
        return msg.SHEETS_READ_FAILED_STATUS.format(label=self.label, reason=reason, status=self.status)

    @property
    def log_line(self) -> str:
        status: str = str(self.status) if self.status is not None else "-"
        return f"reason={self.reason.value} sheet={self.label} status={status}"


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
            absent: list[str] = [
                name.human_label
                for name, value in ((SecretField.SHEETS_ID, sheet_id), (SecretField.SHEETS_RANGE, sheet_range))
                if value is None
            ]
            label: str = sheet_id.log_label if sheet_id is not None else SecretField.SHEETS_ID.log_label
            raise SheetsReadError(SheetsReadReason.NOT_CONFIGURED, label, detail=FIELD_JOINER.join(absent))
        return cls(sheet_id=sheet_id, sheet_range=sheet_range)


@dataclass(frozen=True)
class SheetsFailure:
    """Одно неудачное обращение: причина, код, повторять ли и исходная ошибка (её текст не выводится)."""

    reason: SheetsReadReason
    status: int | None
    is_retryable: bool
    cause: Exception
    detail: str = ""

    @classmethod
    def from_http(cls, error: HttpError) -> SheetsFailure:
        status: int = int(error.resp.status)
        if status in RETRYABLE_STATUSES:
            return cls(reason=SheetsReadReason.UNAVAILABLE, status=status, is_retryable=True, cause=error)
        return cls(reason=SheetsReadReason.for_status(status), status=status, is_retryable=False, cause=error)

    @classmethod
    def from_transport(cls, error: Exception) -> SheetsFailure:
        return cls(reason=SheetsReadReason.UNAVAILABLE, status=None, is_retryable=True, cause=error)

    @classmethod
    def from_refresh(cls, error: RefreshError) -> SheetsFailure:
        """Токен отозван по ходу запроса: браузер тут не открывается — нужен новый вход."""
        detail: str = AuthErrorReason.LOGIN_REQUIRED.human
        return cls(reason=SheetsReadReason.AUTH, status=None, is_retryable=False, cause=error, detail=detail)

    def to_error(self, label: str) -> SheetsReadError:
        return SheetsReadError(self.reason, label, self.status, self.detail)

    @property
    def log_line(self) -> str:
        """Код и тип ошибки; её текст не пишется — у HttpError в нём URL с id таблицы."""
        status: str = str(self.status) if self.status is not None else "-"
        return f"status={status} error={type(self.cause).__name__}"


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
            LOGGER.warning("sheets_auth_failed reason=%s detail=%s", error.reason.value, error.detail)
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
        target: str = f"sheet={sheet_id.log_label} range={sheet_range.log_label}"
        LOGGER.info("sheets_read_started %s", target)
        retry_number: int = 0
        while True:
            outcome: list[list[str]] | SheetsFailure = self._attempt(sheet_id, sheet_range)
            if not isinstance(outcome, SheetsFailure):
                LOGGER.info("sheets_read_done %s rows=%d attempts=%d", target, len(outcome), retry_number + 1)
                return outcome
            retry_number += 1
            if not outcome.is_retryable or not self.policy.has_retry_left(retry_number):
                error: SheetsReadError = outcome.to_error(sheet_id.log_label)
                LOGGER.error("sheets_read_failed %s %s attempts=%d", error.log_line, outcome.log_line, retry_number)
                raise error from outcome.cause
            delay: float = self.policy.delay_sec(retry_number, self.rng)
            LOGGER.warning(
                "sheets_read_retry %s %s retry=%d delay_sec=%.1f", target, outcome.log_line, retry_number, delay
            )
            self.sleep(delay)

    def _attempt(self, sheet_id: SecretValue, sheet_range: SecretValue) -> list[list[str]] | SheetsFailure:
        """Одно обращение: значения или неудача; неожиданное исключение — наружу, это ошибка программы."""
        try:
            response: Any = self._request(sheet_id, sheet_range)
        except HttpError as error:
            return SheetsFailure.from_http(error)
        except RefreshError as error:
            return SheetsFailure.from_refresh(error)
        except TRANSPORT_ERRORS as error:
            return SheetsFailure.from_transport(error)
        rows: Any = response.get(VALUES_KEY, []) if isinstance(response, dict) else []
        return [[str(cell) for cell in row] for row in rows]

    def _request(self, sheet_id: SecretValue, sheet_range: SecretValue) -> Any:
        """Единственная точка раскрытия id таблицы и диапазона (§7.4): значения живут только в этом вызове."""
        values: Any = self.service.spreadsheets().values()
        return values.get(spreadsheetId=sheet_id.reveal(), range=sheet_range.reveal()).execute()
