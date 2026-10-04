"""Таблица плана в Google Sheets: чтение плана и запись в строки видео языка и ссылок на превью (CLAUDE.md §2 контур A,
§3 шаг 2.3, §6 инвариант 3, §9, §14 решения 26, 27, 29).

Вход оператора — `app\\google\\auth.py::GoogleLogin.operator` (скоуп `spreadsheets`). Таблицу задаёт одна ссылка — id
в сейфе; лист и колонки программа находит сама, тремя обращениями: листы (`spreadsheets.get`: название и id листа),
первая строка каждого листа (`values.batchGet`) и выбранный лист целиком (`values.get`). Какой лист — план, решает
`SheetBook` (app\\sheets\\book.py); разбор значений — `SheetPlan`. Запись — только язык видео и ссылки на копии превью
(`write_outputs`): ячейки обоих выводов одним `values.batchUpdate`, затем «обрезать» у записанных ссылок
(`spreadsheets.batchUpdate`, repeatCell); что писать, решает `SheetWrite` (app\\sheets\\preview.py).

Секреты (§7.4): id таблицы лежит в сейфе и раскрывается ровно в одной точке — в методе, который выполняет запрос
(`SheetsReader._request`). Ни значение, ни URL запроса не попадают ни в лог, ни в тексты ошибок: там только ярлык с
отпечатком (`SecretValue.log_label`) и код ответа. Текст `HttpError` содержит URL с id таблицы — поэтому он не пишется
никуда, а исходная ошибка доступна только как `__cause__`. Названия листов — не секрет: они идут в лог.

Повторы — только через `RetryLoop` (§11), у каждого обращения свои: первое обращение и до `max_retries` повторов
на 429, 5xx и транспортных сбоях (`CallFailures`, app\\google\\call_failure.py). Запись повторяется так же:
те же значения и тот же формат во второй раз ничего не меняют. Перед каждым повтором — строка лога и строка хода в
консоль (`StageProgress.sheets_retry`). Повторы, кончившиеся на «адрес сервера Google не найден», — своя причина
`NO_NETWORK`: у компьютера нет интернета, а не «Google не ответил»; та же причина — когда из-за сбоя сети не
обновился действующий вход оператора (рабочий прогон 01-10-2026 21:12).

Каким аккаунтом входить и что делать, когда аккаунту входа таблица не открыта (401 / 403), решает правило входа
оператора — `OperatorSheets` (app\\sheets\\operator.py): читатель только открывается на входе (`open`; `force_reauth` —
заново в браузере) и читает.
"""
from __future__ import annotations

import dataclasses
import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Any, Final

from googleapiclient.discovery import build

from app.core.retry import RETRYABLE_HTTP_STATUSES, AttemptFailure, RetryLoop, RetryPolicy, RetryRun, RetryStep
from app.google.auth import AuthError, AuthErrorReason, GoogleLogin
from app.google.call_failure import CallFailures
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.run.progress import SILENT_PROGRESS, StageProgress, StepCount
from app.secretsafe.field import SecretField
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.sheets.book import SheetBook, SheetName, SheetTab, SheetTitles
from app.sheets.plan import SheetPlan
from app.sheets.preview import SheetWrite
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SHEETS)

SHEETS_API_NAME: Final[str] = "sheets"
SHEETS_API_VERSION: Final[str] = "v4"
# Какие поля ответа spreadsheets.get нужны: id, название и вид каждого листа (id — для записи формата ячеек).
TITLES_FIELDS: Final[str] = "sheets.properties(sheetId,title,sheetType)"
# Лист с ячейками; лист-диаграмма (OBJECT) ячеек не имеет, и запрос его первой строки Google отвергает кодом 400.
GRID_SHEET_TYPE: Final[str] = "GRID"


class SheetsReadReason(str, Enum):
    """Почему таблица не прочиталась."""

    NOT_CONFIGURED = "not_configured"   # в сейфе нет id таблицы — к Google не обращались
    AUTH = "auth"                       # вход оператора не удался или токен отозван по ходу запроса
    NO_ACCESS = "no_access"             # 401 / 403
    ACCOUNT_REFUSED = "account_refused"  # 401 / 403 и после повторного входа: этому аккаунту таблица не открыта
    NOT_FOUND = "not_found"             # 404
    BAD_RANGE = "bad_range"             # 400: Google не разобрал запрос
    REJECTED = "rejected"               # прочий неповторяемый код ответа
    UNAVAILABLE = "unavailable"         # повторы кончились на 429, 5xx или транспорте
    NO_NETWORK = "no_network"           # повторы кончились на «адрес сервера Google не найден»: нет интернета

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
SHEETS_FAILURES: Final[CallFailures] = CallFailures(
    SheetsReadReason.for_status, SheetsReadReason.AUTH, SheetsReadReason.UNAVAILABLE,
    no_network=SheetsReadReason.NO_NETWORK,
)


class SheetsEvent(str, Enum):
    """События чтения таблицы в логе."""

    READ_STARTED = "sheets_read_started"
    READ_RETRY = "sheets_read_retry"
    READ_DONE = "sheets_read_done"
    READ_FAILED = "sheets_read_failed"
    AUTH_FAILED = "sheets_auth_failed"


class SheetsKey(str, Enum):
    """Поля ответов Sheets API v4: листы (spreadsheets.get), первые строки (values.batchGet), значения (values.get)."""

    SHEETS = "sheets"
    PROPERTIES = "properties"
    SHEET_ID = "sheetId"
    TITLE = "title"
    SHEET_TYPE = "sheetType"
    VALUE_RANGES = "valueRanges"
    VALUES = "values"


class SheetsCallKind(str, Enum):
    """Какое обращение к таблице. Значение — идентификатор для лога."""

    TITLES = "titles"       # spreadsheets.get: названия листов
    HEADERS = "headers"     # values.batchGet: первая строка каждого листа
    VALUES = "values"       # values.get: лист плана целиком
    WRITE = "write"         # values.batchUpdate: языки видео, ссылки на превью и заголовки добавленных колонок
    CLIP = "clip"           # spreadsheets.batchUpdate: у записанных ссылок длинный текст обрезается краем ячейки

    @property
    def is_write(self) -> bool:
        return self in (SheetsCallKind.WRITE, SheetsCallKind.CLIP)


class SheetsReadError(Exception):
    """Таблица не прочиталась. Текст — строка для человека с ярлыком таблицы и кодом ответа, без значений.

    `detail` — уже готовая для человека подробность без секретов (причина входа).
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
            return self.failed_text.format(label=self.label, reason=reason)
        return self.failed_status_text.format(label=self.label, reason=reason, status=self.status)

    @property
    def failed_text(self) -> str:
        """Строка для человека без кода ответа: {label} и {reason}."""
        return msg.SHEETS_READ_FAILED

    @property
    def failed_status_text(self) -> str:
        """Строка для человека с кодом ответа: {label}, {reason} и {status}."""
        return msg.SHEETS_READ_FAILED_STATUS

    @property
    def log_line(self) -> str:
        return LogEvent.of(SheetsEvent.READ_FAILED, reason=self.reason, sheet=self.label, status=self.status).text


class SheetsWriteError(SheetsReadError):
    """Язык видео и ссылки на превью не записались: та же причина, что у чтения, и своя строка для человека."""

    @property
    def failed_text(self) -> str:
        return msg.SHEETS_WRITE_FAILED

    @property
    def failed_status_text(self) -> str:
        return msg.SHEETS_WRITE_FAILED_STATUS


@dataclass(frozen=True)
class SheetsCall:
    """Одно обращение к таблице: что сделать, какие диапазоны в нотации A1 (названия листов — не секрет) и тело
    запроса записи."""

    kind: SheetsCallKind
    ranges: tuple[str, ...] = ()
    body: Mapping[str, object] = field(default_factory=dict)

    def request(self, spreadsheets: Any, spreadsheet_id: str) -> Any:
        """Запрос API, ещё не выполненный: листы, первые строки, один лист целиком, запись ссылок или формат."""
        if self.kind is SheetsCallKind.TITLES:
            return spreadsheets.get(spreadsheetId=spreadsheet_id, fields=TITLES_FIELDS)
        if self.kind is SheetsCallKind.HEADERS:
            return spreadsheets.values().batchGet(spreadsheetId=spreadsheet_id, ranges=list(self.ranges))
        if self.kind is SheetsCallKind.WRITE:
            return spreadsheets.values().batchUpdate(spreadsheetId=spreadsheet_id, body=dict(self.body))
        if self.kind is SheetsCallKind.CLIP:
            return spreadsheets.batchUpdate(spreadsheetId=spreadsheet_id, body=dict(self.body))
        (sheet_range,) = self.ranges
        return spreadsheets.values().get(spreadsheetId=spreadsheet_id, range=sheet_range)

    @property
    def error_type(self) -> type[SheetsReadError]:
        """Какой ошибкой кончается неудача: записи — своей, со строкой про запись в таблицу."""
        return SheetsWriteError if self.kind.is_write else SheetsReadError


@dataclass(frozen=True)
class SheetsTarget:
    """Что читать: id таблицы из сейфа — секрет, а не строка."""

    sheet_id: SecretValue

    @classmethod
    def from_vault(cls, vault: Vault) -> SheetsTarget:
        """id таблицы из сейфа; нет его — SheetsReadError(NOT_CONFIGURED), к Google не обращаемся."""
        sheet_id: SecretValue | None = vault.get(SecretField.SHEETS_ID)
        if sheet_id is None:
            raise SheetsReadError(SheetsReadReason.NOT_CONFIGURED, SecretField.SHEETS_ID.log_label)
        return cls(sheet_id=sheet_id)

    def event(self, name: SheetsEvent, call: SheetsCall) -> LogEvent:
        """Строка лога об обращении к этой таблице: ярлык с отпечатком вместо id (§7.4), вид обращения и диапазоны."""
        return LogEvent.of(name, sheet=self.sheet_id.log_label, call=call.kind, ranges=call.ranges)


@dataclass(frozen=True)
class SheetsReader:
    """Читатель таблиц одного входа оператора; он же пишет в строки видео язык и ссылки на превью.

    `service` — объект googleapiclient или подделка с теми же цепочками `spreadsheets().get(...)`,
    `spreadsheets().batchUpdate(...)`, `spreadsheets().values().batchGet(...)`, `.get(...)` и `.batchUpdate(...)`;
    `policy`, `rng` и `sleep` — параметрами, в тестах свои; `progress` — строка в консоль перед каждым повтором
    обращения (без консоли молчит).
    """

    service: Any
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep
    progress: StageProgress = SILENT_PROGRESS

    @classmethod
    def open(
        cls,
        login: GoogleLogin,
        allow_login: bool = True,
        on_login: Callable[[], None] | None = None,
        force_reauth: bool = False,
    ) -> SheetsReader:
        """Вход оператора и клиент Sheets v4; вход не удался — SheetsReadError(AUTH), а действующий вход не
        обновился из-за сбоя сети — SheetsReadError(NO_NETWORK). `force_reauth` — вход в браузере заново, мимо
        токена: прежний токен заменяет только удачный вход."""
        try:
            credentials: Any = login.credentials(
                allow_login=allow_login, force_reauth=force_reauth, on_login=on_login
            )
        except AuthError as error:
            LogEvent.of(SheetsEvent.AUTH_FAILED, reason=error.reason, detail=error.detail).emit(LOGGER, logging.WARNING)
            raise SheetsReadError(
                SheetsReadReason(SHEETS_FAILURES.login_reason(error.reason)), SecretField.SHEETS_ID.log_label,
                detail=error.human,
            ) from error
        service: Any = build(SHEETS_API_NAME, SHEETS_API_VERSION, credentials=credentials, cache_discovery=False)
        return cls(service=service)

    def reporting(self, progress: StageProgress) -> SheetsReader:
        """Тот же читатель, который говорит о повторах обращения строками хода `progress`."""
        return dataclasses.replace(self, progress=progress)

    def read_plan(self, vault: Vault) -> SheetPlan:
        """План из таблицы, которую называет сейф: листы → первые строки → лист плана целиком.

        Подходящего листа нет — третьего обращения нет: план без колонок с ближайшего листа.
        """
        target: SheetsTarget = SheetsTarget.from_vault(vault)
        titles: SheetTitles = self._titles(target)
        book: SheetBook = titles.book(self._first_rows(target, titles))
        tab: SheetTab | None = book.plan_tab
        if tab is None:
            return book.closest.unrecognized
        return tab.plan(self._values(target, tab))

    def write_outputs(self, vault: Vault, write: SheetWrite) -> None:
        """Запись в таблицу, которую называет сейф: ячейки выводов одним обращением, затем «обрезать» у записанных
        ссылок на превью; ссылок нет — второго обращения нет."""
        target: SheetsTarget = SheetsTarget.from_vault(vault)
        self._call(target, SheetsCall(SheetsCallKind.WRITE, body=write.values_body))
        if write.has_clip:
            self._call(target, SheetsCall(SheetsCallKind.CLIP, body=write.clip_body))

    def _titles(self, target: SheetsTarget) -> SheetTitles:
        """Листы с ячейками в порядке таблицы: название и id."""
        response: Any = self._call(target, SheetsCall(SheetsCallKind.TITLES))
        properties: list[Any] = [sheet[SheetsKey.PROPERTIES] for sheet in response.get(SheetsKey.SHEETS, [])]
        return SheetTitles(
            tuple(
                SheetName(title=str(item[SheetsKey.TITLE]), sheet_id=int(item[SheetsKey.SHEET_ID]))
                for item in properties
                if item.get(SheetsKey.SHEET_TYPE, GRID_SHEET_TYPE) == GRID_SHEET_TYPE
            )
        )

    def _first_rows(self, target: SheetsTarget, titles: SheetTitles) -> list[list[str]]:
        """Первая строка каждого листа — в порядке листов; пустая строка листа — пустой список."""
        response: Any = self._call(target, SheetsCall(SheetsCallKind.HEADERS, titles.header_ranges))
        return [
            self._cells(value_range.get(SheetsKey.VALUES, [[]])[0])
            for value_range in response.get(SheetsKey.VALUE_RANGES, [])
        ]

    def _values(self, target: SheetsTarget, tab: SheetTab) -> list[list[str]]:
        """Лист целиком строками, с первой строки и колонки A."""
        response: Any = self._call(target, SheetsCall(SheetsCallKind.VALUES, (tab.values_range,)))
        return [self._cells(row) for row in response.get(SheetsKey.VALUES, [])]

    def _cells(self, row: list[Any]) -> list[str]:
        return [str(cell) for cell in row]

    def _call(self, target: SheetsTarget, call: SheetsCall) -> Any:
        """Одно обращение с повторами по `policy`: ответ API; повторы кончились или сбой неповторяемый —
        SheetsReadError."""
        target.event(SheetsEvent.READ_STARTED, call).emit(LOGGER)
        run: RetryRun[Any] = RetryLoop(self.policy, self.rng, self.sleep).run(
            lambda: SHEETS_FAILURES.attempt(lambda: self._request(target, call)),
            lambda step: self._note_retry(target, call, step),
        )
        if run.failure is not None:
            error: SheetsReadError = call.error_type.from_failure(run.failure, target.sheet_id.log_label)
            failed: LogEvent = LogEvent.of(SheetsEvent.READ_FAILED, reason=error.reason, sheet=error.label)
            failed.extended(call=call.kind, **run.failure.log_fields, attempts=run.attempts).emit(LOGGER, logging.ERROR)
            raise error from run.failure.cause
        target.event(SheetsEvent.READ_DONE, call).extended(attempts=run.attempts).emit(LOGGER)
        return run.value

    def _note_retry(self, target: SheetsTarget, call: SheetsCall, step: RetryStep) -> None:
        retry: LogEvent = target.event(SheetsEvent.READ_RETRY, call).extended(**step.failure.log_fields)
        retry.extended(retry=step.retry, delay_sec=round(step.delay_sec, 1)).emit(LOGGER, logging.WARNING)
        self.progress.sheets_retry(StepCount(step.retry, self.policy.max_retries))

    def _request(self, target: SheetsTarget, call: SheetsCall) -> Any:
        """Единственная точка раскрытия id таблицы (§7.4): значение живёт только в этом выполняемом запросе."""
        return call.request(self.service.spreadsheets(), target.sheet_id.reveal()).execute()
