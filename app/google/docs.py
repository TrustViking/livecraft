"""Google Docs: чтение устройства документа и правки одним пакетом (CLAUDE.md §9, §13 задача 4.4, §14 решение 27).

`DocsClient` — клиент Docs v1 одного входа оператора (скоуп `documents`). Он читает документ (`document`,
documents.get) и отдаёт его устройство тем, что нужно документу объявлений: таблицы тела по порядку, у каждой — начало
и начала абзацев её ячеек (`DocsDocument`, `DocsTable`; индексы Docs — в единицах UTF-16). Правки идут пакетом
(`update`, documents.batchUpdate): запросы собирает вызывающий. Сам документ создаёт Google Диск (`DriveClient`):
так он сразу ложится в папку материалов.

Повторы — только через `RetryLoop` (§11). Правка — обращение создающее: после 5xx и обрыва неизвестно, вставил ли
Google текст, таблицу или картинку, и повтор задвоил бы их (`DocsReason.UNKNOWN`, без повтора); 429 повторяется.
Адрес сервера Google не найден или вход не обновился из-за сбоя сети — причина `DocsReason.NO_NETWORK` (и у правки:
запрос до Google не дошёл): у компьютера нет интернета.
Успешное обращение — строкой `docs_call` с числом попыток (`CallLog`, §14 решение 38); отказ — значением `DocsError`
со строкой лога (`event`), её пишет вызывающий. Текст `HttpError` не выводится никуда (в нём URL). Модуль — граница E14: здесь разбирается сырой ответ documents.get.
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Any, Final, TypeVar

from googleapiclient.discovery import Resource

from app.core.retry import RETRYABLE_HTTP_STATUSES, AttemptFailure, RetryLoop, RetryPolicy
from app.google.auth import AuthError, GoogleLogin
from app.google.call_failure import CallFailures, GoogleApi
from app.google.call_log import CallLog
from app.observability.log_event import LogEvent
from app.ui.messages import msg

T = TypeVar("T")

DOCS_API: Final[GoogleApi] = GoogleApi(name="docs", version="v1")


class DocsKey(str, Enum):
    """Поля ответа documents.get и тела documents.batchUpdate."""

    BODY = "body"
    CONTENT = "content"
    START_INDEX = "startIndex"
    TABLE = "table"
    TABLE_ROWS = "tableRows"
    TABLE_CELLS = "tableCells"
    REQUESTS = "requests"


class DocsReason(str, Enum):
    """Почему обращение к Google Docs не удалось."""

    AUTH = "auth"                       # вход оператора не удался или токен отозван по ходу запроса
    NO_ACCESS = "no_access"             # 401 / 403
    NOT_FOUND = "not_found"             # 404: документа нет
    BAD_REQUEST = "bad_request"         # 400: Docs не принял запрос (у картинки — не скачал её по адресу)
    REJECTED = "rejected"               # прочий неповторяемый код ответа
    UNAVAILABLE = "unavailable"         # повторы кончились на 429, 5xx или транспорте
    UNKNOWN = "unknown"                 # правка: 5xx или обрыв — выполнена ли, неизвестно
    NO_NETWORK = "no_network"           # адрес сервера Google не найден или вход не обновился из-за сбоя сети

    @classmethod
    def for_status(cls, status: int) -> DocsReason:
        if status in RETRYABLE_HTTP_STATUSES:
            return cls.UNAVAILABLE
        return DOCS_STATUS_REASONS.get(status, cls.REJECTED)

    @property
    def human(self) -> str:
        return msg.DOCS_REASON_TEXT[self.value]


DOCS_STATUS_REASONS: Final[dict[int, DocsReason]] = {
    HTTPStatus.BAD_REQUEST: DocsReason.BAD_REQUEST,
    HTTPStatus.UNAUTHORIZED: DocsReason.NO_ACCESS,
    HTTPStatus.FORBIDDEN: DocsReason.NO_ACCESS,
    HTTPStatus.NOT_FOUND: DocsReason.NOT_FOUND,
}
DOCS_FAILURES: Final[CallFailures] = CallFailures(
    DocsReason.for_status, DocsReason.AUTH, DocsReason.UNAVAILABLE, no_network=DocsReason.NO_NETWORK
)
DOCS_UPDATE_FAILURES: Final[CallFailures] = DOCS_FAILURES.creating(DocsReason.UNKNOWN)


class DocsCall(str, Enum):
    """Какое обращение к Docs. Значение — идентификатор для лога."""

    OPEN = "open"               # вход оператора
    DOCUMENT = "document"       # documents.get: устройство документа
    UPDATE = "update"           # documents.batchUpdate: правки пакетом


class DocsEvent(str, Enum):
    CALL = "docs_call"
    FAILED = "docs_failed"


class DocsError(Exception):
    """Обращение к Docs не удалось. Текст — строка для человека без адресов; `detail` — готовая для человека
    подробность без секретов (причина входа)."""

    def __init__(
        self, reason: DocsReason, call: DocsCall, failure: AttemptFailure | None = None, detail: str = ""
    ) -> None:
        self.reason: DocsReason = reason
        self.call: DocsCall = call
        self.failure: AttemptFailure | None = failure
        self.detail: str = detail
        super().__init__(self.human)

    @property
    def status(self) -> int | None:
        return None if self.failure is None else self.failure.status

    @property
    def human(self) -> str:
        """«Google Docs: причина (код ответа 400).»; кода нет — без скобок."""
        status: str = "" if self.status is None else msg.DOCS_FAILED_STATUS.format(status=self.status)
        return msg.DOCS_FAILED.format(reason=self.reason.human.format(detail=self.detail), status=status)

    @property
    def event(self) -> LogEvent:
        """Строка лога: причина, обращение, код ответа и имя исключения — без текста ошибки."""
        error: str | None = None if self.failure is None else self.failure.error_name
        return LogEvent.of(DocsEvent.FAILED, reason=self.reason, call=self.call, status=self.status, error=error)

    def __str__(self) -> str:
        return self.human


@dataclass(frozen=True)
class DocsTable:
    """Таблица документа: индекс её начала и начала первых абзацев ячеек — по строкам, в строке — по колонкам."""

    start_index: int
    cell_starts: tuple[int, ...]

    @classmethod
    def of(cls, element: Mapping[str, Any]) -> DocsTable:
        """Таблица из элемента тела документа с полем `table`."""
        rows: Sequence[Mapping[str, Any]] = element[DocsKey.TABLE][DocsKey.TABLE_ROWS]
        starts: tuple[int, ...] = tuple(
            int(cell[DocsKey.CONTENT][0][DocsKey.START_INDEX]) for row in rows for cell in row[DocsKey.TABLE_CELLS]
        )
        return cls(start_index=int(element[DocsKey.START_INDEX]), cell_starts=starts)


@dataclass(frozen=True)
class DocsDocument:
    """Устройство документа, которое нужно правкам: таблицы тела по порядку."""

    tables: tuple[DocsTable, ...]

    @classmethod
    def of(cls, response: Mapping[str, Any]) -> DocsDocument:
        """Документ из ответа documents.get."""
        content: Sequence[Mapping[str, Any]] = response[DocsKey.BODY][DocsKey.CONTENT]
        return cls(tables=tuple(DocsTable.of(element) for element in content if DocsKey.TABLE in element))

    @property
    def last_table(self) -> DocsTable:
        """Последняя таблица тела — та, что вставлена в конец документа последней."""
        return self.tables[-1]


@dataclass
class DocsClient:
    """Клиент Docs v1 одного входа оператора. `service` — клиент googleapiclient или подделка с теми же цепочками
    `documents().get/batchUpdate(...)`."""

    service: Resource
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def open(cls, login: GoogleLogin, on_login: Callable[[], None] | None = None) -> DocsClient:
        """Вход оператора и клиент Docs v1; вход не удался — DocsError(AUTH), а действующий вход не обновился из-за
        сбоя сети — DocsError(NO_NETWORK)."""
        auth_failed: Callable[[Enum, AuthError], DocsError] = lambda reason, error: DocsError(
            DocsReason(reason), DocsCall.OPEN, detail=error.human
        )
        return cls(service=DOCS_API.open(login, on_login, DOCS_FAILURES, auth_failed))

    def document(self, document_id: str) -> DocsDocument:
        """Устройство документа (documents.get)."""
        response: Mapping[str, Any] = self._call(
            DocsCall.DOCUMENT, lambda: self.service.documents().get(documentId=document_id).execute(), DOCS_FAILURES
        )
        return DocsDocument.of(response)

    def update(self, document_id: str, requests: Sequence[Mapping[str, object]]) -> None:
        """Правки пакетом (documents.batchUpdate) — по порядку запросов. Обращение создающее: 5xx и обрыв не
        повторяются (`DocsReason.UNKNOWN`)."""
        body: dict[str, object] = {DocsKey.REQUESTS.value: list(requests)}
        self._call(
            DocsCall.UPDATE,
            lambda: self.service.documents().batchUpdate(documentId=document_id, body=body).execute(),
            DOCS_UPDATE_FAILURES,
        )

    def _call(self, call: DocsCall, request: Callable[[], T], failures: CallFailures) -> T:
        """Одно обращение с повторами по `policy`: ответ и строка `docs_call`; повторы кончились или сбой неповторяемый
        — DocsError."""
        loop: RetryLoop = RetryLoop(self.policy, self.rng, self.sleep)
        docs_error: Callable[[AttemptFailure], DocsError] = lambda failure: DocsError(
            DocsReason(failure.reason), call, failure
        )
        return CallLog(DocsEvent.CALL, call).run(failures, loop, request, docs_error)
