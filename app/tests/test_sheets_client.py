from __future__ import annotations

import http.client
import logging
import random
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from app.core.retry import RetryPolicy
from app.google.auth import AuthError, AuthErrorReason, GoogleLogin
from app.observability.log_event import LogArea
from app.run.progress import StageProgress
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.sheets import client as client_module
from app.sheets.client import (
    SHEETS_FAILURES,
    SheetsCallKind,
    SheetsReader,
    SheetsReadError,
    SheetsReadReason,
    SheetsTarget,
    SheetsWriteError,
)
from app.sheets.plan import PlanProblem, SheetColumns, SheetPlan
from app.sheets.preview import OutputCell, SheetOutput, SheetWrite
from app.tests.conftest import TOKEN_VALUES
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

SHEET_ID: SecretValue = SecretValue(SecretField.SHEETS_ID, TOKEN_VALUES[SecretField.SHEETS_ID])
REQUEST_URI: str = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID.reveal()}?alt=json"
PLAN_HEADER: list[str] = ["№", "Заметки", "Links", "Date", "Time"]
VALUES: list[list[str]] = [PLAN_HEADER, ["1", "", "https://youtu.be/dQw4w9WgXcQ", "16.10.2026", "19:00"]]
TITLES: dict[str, Any] = {
    "sheets": [
        {"properties": {"sheetId": 100, "title": "Заметки", "sheetType": "GRID"}},
        {"properties": {"sheetId": 101, "title": "План стримов", "sheetType": "GRID"}},
    ]
}
HEADERS: dict[str, Any] = {
    "valueRanges": [
        {"range": "'Заметки'!A1:B1", "values": [["Дата", "Кто"]]},
        {"range": "'План стримов'!A1:E1", "values": [PLAN_HEADER]},
    ]
}


@dataclass
class _Resp:
    """Ответ httplib2 в том объёме, который читает HttpError."""

    status: int
    reason: str = "error"


def http_error(status: int) -> HttpError:
    """Настоящая HttpError: в её тексте — URL запроса с id таблицы, как в бою."""
    content: bytes = b'{"error": {"message": "request failed"}}'
    return HttpError(_Resp(status), content, uri=REQUEST_URI)  # type: ignore[arg-type]


class _Request:
    def __init__(self, service: _FakeService) -> None:
        self._service: _FakeService = service

    def execute(self) -> Any:
        outcome: Any = next(self._service.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeValues:
    def __init__(self, service: _FakeService) -> None:
        self._service: _FakeService = service

    def batchGet(self, *, spreadsheetId: str, ranges: list[str]) -> _Request:  # noqa: N802, N803 — имена API
        return self._service.called(SheetsCallKind.HEADERS, spreadsheetId, tuple(ranges))

    def get(self, *, spreadsheetId: str, range: str) -> _Request:  # noqa: A002, N803 — имена API
        return self._service.called(SheetsCallKind.VALUES, spreadsheetId, (range,))

    def batchUpdate(self, *, spreadsheetId: str, body: dict[str, Any]) -> _Request:  # noqa: N802, N803 — имена API
        return self._service.called(SheetsCallKind.WRITE, spreadsheetId, (), body)


class _FakeSpreadsheets:
    def __init__(self, service: _FakeService) -> None:
        self._service: _FakeService = service

    def get(self, *, spreadsheetId: str, fields: str) -> _Request:  # noqa: N803 — имя API
        assert fields == client_module.TITLES_FIELDS
        return self._service.called(SheetsCallKind.TITLES, spreadsheetId, ())

    def values(self) -> _FakeValues:
        return _FakeValues(self._service)

    def batchUpdate(self, *, spreadsheetId: str, body: dict[str, Any]) -> _Request:  # noqa: N802, N803 — имена API
        return self._service.called(SheetsCallKind.CLIP, spreadsheetId, (), body)


@dataclass(frozen=True)
class _Call:
    kind: SheetsCallKind
    spreadsheet_id: str
    ranges: tuple[str, ...]
    body: Any = None


class _FakeService:
    """Подделка googleapiclient: три цепочки обращений, исходы — по очереди, вызовы — в запись."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes: Iterator[Any] = iter(outcomes)
        self.calls: list[_Call] = []

    def spreadsheets(self) -> _FakeSpreadsheets:
        return _FakeSpreadsheets(self)

    def called(self, kind: SheetsCallKind, spreadsheet_id: str, ranges: tuple[str, ...], body: Any = None) -> _Request:
        self.calls.append(_Call(kind, spreadsheet_id, ranges, body))
        return _Request(self)

    @property
    def kinds(self) -> list[SheetsCallKind]:
        return [call.kind for call in self.calls]


class _ZeroRandom(random.Random):
    def uniform(self, a: float, b: float) -> float:
        return a


@pytest.fixture
def log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.SHEETS, logging.DEBUG) as capture:
        yield capture


def reader_for(service: _FakeService, sleeps: list[float]) -> SheetsReader:
    return SheetsReader(service=service, policy=RetryPolicy(), rng=_ZeroRandom(0), sleep=sleeps.append)


def vault_with_table() -> Vault:
    return Vault.empty().with_field(SecretField.SHEETS_ID, SHEET_ID, VaultOrigin.TOKEN)


def read(service: _FakeService, sleeps: list[float] | None = None) -> SheetPlan:
    return reader_for(service, [] if sleeps is None else sleeps).read_plan(vault_with_table())


def assert_no_secret(text: str) -> None:
    for value in (SHEET_ID.reveal(), REQUEST_URI):
        assert value not in text


# --- успех и выбор листа


def test_the_plan_is_the_first_sheet_with_all_three_columns_read_in_three_calls() -> None:
    service: _FakeService = _FakeService(TITLES, HEADERS, {"range": "'План стримов'!A1:E2", "values": VALUES})
    plan: SheetPlan = read(service)
    assert plan.sheet_title == "План стримов"
    assert plan.columns == SheetColumns(link=2, date=3, time=4)
    assert len(plan.rows) == 1 and plan.problem is None
    assert service.calls == [
        _Call(SheetsCallKind.TITLES, SHEET_ID.reveal(), ()),
        _Call(SheetsCallKind.HEADERS, SHEET_ID.reveal(), ("'Заметки'!1:1", "'План стримов'!1:1")),
        _Call(SheetsCallKind.VALUES, SHEET_ID.reveal(), ("'План стримов'",)),
    ]


def test_no_suitable_sheet_is_a_plan_problem_without_the_third_call() -> None:
    headers: dict[str, Any] = {"valueRanges": [{"values": [["Дата", "Кто"]]}, {"values": [["Links", "Date"]]}]}
    service: _FakeService = _FakeService(TITLES, headers)
    plan: SheetPlan = read(service)
    assert service.kinds == [SheetsCallKind.TITLES, SheetsCallKind.HEADERS]
    assert plan.problem is PlanProblem.HEADER_UNKNOWN
    assert plan.sheet_title == "План стримов"          # две колонки из трёх — ближе, чем одна
    assert "«План стримов»" in plan.problem_text and "время" in plan.problem_text


def test_a_chart_sheet_is_not_asked_for_its_first_row() -> None:
    titles: dict[str, Any] = {
        "sheets": [
            {"properties": {"sheetId": 102, "title": "Диаграмма", "sheetType": "OBJECT"}},
            {"properties": {"sheetId": 103, "title": "План", "sheetType": "GRID"}},
        ]
    }
    service: _FakeService = _FakeService(titles, {"valueRanges": [{"values": [PLAN_HEADER]}]}, {"values": VALUES})
    assert read(service).sheet_title == "План"
    assert service.calls[1].ranges == ("'План'!1:1",)


def test_an_empty_first_row_and_cells_come_back_as_strings() -> None:
    titles: dict[str, Any] = {"sheets": [{"properties": {"sheetId": 104, "title": "Пусто"}}, {"properties": {"sheetId": 105, "title": "План"}}]}
    headers: dict[str, Any] = {"valueRanges": [{"range": "'Пусто'!A1:Z1"}, {"values": [["Links", "Date", "Time"]]}]}
    values: dict[str, Any] = {"values": [["Links", "Date", "Time"], ["https://youtu.be/dQw4w9WgXcQ", 16, 19.5]]}
    plan: SheetPlan = read(_FakeService(titles, headers, values))
    assert plan.sheet_title == "План"
    assert (plan.rows[0].date_raw, plan.rows[0].time_raw) == ("16", "19.5")


def test_a_plan_sheet_without_rows_is_an_empty_plan() -> None:
    plan: SheetPlan = read(_FakeService(TITLES, HEADERS, {"values": [PLAN_HEADER]}))
    assert plan.problem is PlanProblem.EMPTY


def test_the_plan_carries_the_id_of_its_sheet() -> None:
    plan: SheetPlan = read(_FakeService(TITLES, HEADERS, {"values": VALUES}))
    assert plan.sheet_id == TITLES["sheets"][1]["properties"]["sheetId"]
    assert client_module.TITLES_FIELDS == "sheets.properties(sheetId,title,sheetType)"


# --- запись языка видео и ссылок на превью (§14 решения 27, 29)


def _sheet_write(**values: list[OutputCell]) -> SheetWrite:
    """Лист плана без колонок языка и превью: добавленные колонки — F и G."""
    plan: SheetPlan = SheetPlan.from_values("План стримов", 42, VALUES)
    return SheetWrite.of(plan, {SheetOutput(name): cells for name, cells in values.items()})


def _preview_write() -> SheetWrite:
    """Одна ссылка на превью и язык той же строки."""
    link: OutputCell = OutputCell(2, "https://drive.google.com/uc?export=download&id=f1")
    return _sheet_write(preview=[link], language=[OutputCell(2, "ru")])


def test_languages_and_links_are_written_in_one_call_then_clipped_through_the_one_reveal_point() -> None:
    service: _FakeService = _FakeService({}, {})
    write: SheetWrite = _preview_write()
    reader_for(service, []).write_outputs(vault_with_table(), write)
    assert service.calls == [
        _Call(SheetsCallKind.WRITE, SHEET_ID.reveal(), (), write.values_body),
        _Call(SheetsCallKind.CLIP, SHEET_ID.reveal(), (), write.clip_body),
    ]


def test_languages_alone_are_written_without_the_clip_call() -> None:
    service: _FakeService = _FakeService({})
    write: SheetWrite = _sheet_write(language=[OutputCell(2, "uk")])
    reader_for(service, []).write_outputs(vault_with_table(), write)
    assert service.calls == [_Call(SheetsCallKind.WRITE, SHEET_ID.reveal(), (), write.values_body)]


def test_a_write_that_fails_says_the_table_was_not_written_without_the_id(log: LogCapture) -> None:
    service: _FakeService = _FakeService(http_error(403))
    with pytest.raises(SheetsWriteError) as raised:
        reader_for(service, []).write_outputs(vault_with_table(), _preview_write())
    assert raised.value.reason is SheetsReadReason.NO_ACCESS
    reason: str = SheetsReadReason.NO_ACCESS.human.format(detail="")
    assert str(raised.value) == msg.SHEETS_WRITE_FAILED_STATUS.format(label=SHEET_ID.log_label, reason=reason, status=403)
    assert service.kinds == [SheetsCallKind.WRITE]                 # «обрезать» после сбоя записи не спрашивают
    assert_no_secret(str(raised.value))
    for line in log.messages():
        assert_no_secret(line)


def test_a_write_is_retried_like_a_read() -> None:
    sleeps: list[float] = []
    service: _FakeService = _FakeService(http_error(503), {}, {})
    reader_for(service, sleeps).write_outputs(vault_with_table(), _preview_write())
    assert service.kinds == [SheetsCallKind.WRITE, SheetsCallKind.WRITE, SheetsCallKind.CLIP]
    assert len(sleeps) == 1


# --- повторы


def test_two_503_then_success_are_two_retries_with_policy_pauses() -> None:
    sleeps: list[float] = []
    service: _FakeService = _FakeService(http_error(503), http_error(503), TITLES, HEADERS, {"values": VALUES})
    assert read(service, sleeps).columns is not None
    assert service.kinds == [SheetsCallKind.TITLES] * 3 + [SheetsCallKind.HEADERS, SheetsCallKind.VALUES]
    policy: RetryPolicy = RetryPolicy()
    assert sleeps == [policy.delay_sec(1, _ZeroRandom(0)), policy.delay_sec(2, _ZeroRandom(0))] == [2.0, 4.0]


def test_every_call_has_its_own_retries() -> None:
    sleeps: list[float] = []
    service: _FakeService = _FakeService(TITLES, http_error(503), HEADERS, http_error(500), {"values": VALUES})
    assert read(service, sleeps).columns is not None
    assert len(service.calls) == 5 and len(sleeps) == 2


def test_429_on_every_attempt_is_unavailable_after_max_attempts() -> None:
    policy: RetryPolicy = RetryPolicy()
    sleeps: list[float] = []
    service: _FakeService = _FakeService(*[http_error(429)] * policy.max_attempts)
    with pytest.raises(SheetsReadError) as raised:
        read(service, sleeps)
    assert raised.value.reason is SheetsReadReason.UNAVAILABLE
    assert raised.value.status == 429
    assert len(service.calls) == policy.max_attempts == 5
    assert len(sleeps) == policy.max_retries
    assert isinstance(raised.value.__cause__, HttpError)


@pytest.mark.parametrize("status", [500, 502, 504])
def test_every_server_error_is_retried(status: int) -> None:
    service: _FakeService = _FakeService(http_error(status), TITLES, HEADERS, {"values": VALUES})
    assert read(service).columns is not None
    assert len(service.calls) == 4


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError(10054, "reset"),
        TimeoutError("timed out"),
        http.client.RemoteDisconnected("gone"),
        ServerNotFoundError("Unable to find the server"),
        TransportError("no network"),
    ],
)
def test_transport_errors_are_retried(error: Exception) -> None:
    sleeps: list[float] = []
    service: _FakeService = _FakeService(TITLES, HEADERS, error, {"values": VALUES})
    assert read(service, sleeps).columns is not None
    assert len(service.calls) == 4 and len(sleeps) == 1


def test_transport_errors_to_the_end_are_unavailable_without_status() -> None:
    policy: RetryPolicy = RetryPolicy()
    service: _FakeService = _FakeService(*[OSError("down")] * policy.max_attempts)
    with pytest.raises(SheetsReadError) as raised:
        read(service)
    assert raised.value.reason is SheetsReadReason.UNAVAILABLE
    assert raised.value.status is None


# --- нет связи и строки повторов (§13 задача 9.6)


def test_a_server_that_is_not_found_to_the_end_is_no_network(log: LogCapture) -> None:
    """Запуски 01-10-2026 17:50 и 18:35: компьютер не находил адрес Google — это не «Google не ответил»."""
    policy: RetryPolicy = RetryPolicy()
    sleeps: list[float] = []
    service: _FakeService = _FakeService(*[ServerNotFoundError("Unable to find the server")] * policy.max_attempts)
    with pytest.raises(SheetsReadError) as raised:
        read(service, sleeps)
    assert raised.value.reason is SheetsReadReason.NO_NETWORK and raised.value.status is None
    assert not raised.value.reason.is_configuration
    assert len(service.calls) == policy.max_attempts and len(sleeps) == policy.max_retries       # повторяется, как 503
    assert str(raised.value) == msg.SHEETS_READ_FAILED.format(
        label=SHEET_ID.log_label, reason=msg.SHEETS_READ_REASON_TEXT["no_network"]
    )
    assert "компьютер не находит серверы Google — нет интернета" in str(raised.value)
    (failed,) = [line for line in log.messages() if line.startswith("sheets_read_failed")]
    assert "reason=no_network" in failed and "error=ServerNotFoundError attempts=5" in failed


def test_a_server_not_found_once_is_retried_and_the_plan_is_read() -> None:
    sleeps: list[float] = []
    service: _FakeService = _FakeService(ServerNotFoundError("x"), TITLES, HEADERS, {"values": VALUES})
    assert read(service, sleeps).columns is not None and len(sleeps) == 1


def test_503_to_the_end_is_still_unavailable() -> None:
    service: _FakeService = _FakeService(*[http_error(503)] * RetryPolicy().max_attempts)
    with pytest.raises(SheetsReadError) as raised:
        read(service)
    assert raised.value.reason is SheetsReadReason.UNAVAILABLE and raised.value.status == 503
    assert "Google не ответил и после повторов" in str(raised.value)


def test_the_last_failure_names_the_reason_when_failures_differ() -> None:
    """Связь пропала на последней попытке — нет связи; появилась, но Google ответил 503 — Google не ответил."""
    lost: _FakeService = _FakeService(*[http_error(503)] * 4, ServerNotFoundError("x"))
    with pytest.raises(SheetsReadError) as raised:
        read(lost)
    assert raised.value.reason is SheetsReadReason.NO_NETWORK
    back: _FakeService = _FakeService(*[ServerNotFoundError("x")] * 4, http_error(503))
    with pytest.raises(SheetsReadError) as raised:
        read(back)
    assert raised.value.reason is SheetsReadReason.UNAVAILABLE


def test_every_retry_is_a_console_line_with_its_number() -> None:
    """До 9.6 пять попыток чтения шли до полутора минут в тишине."""
    record: ConsoleRecord = ConsoleRecord()
    policy: RetryPolicy = RetryPolicy()
    service: _FakeService = _FakeService(*[ServerNotFoundError("x")] * policy.max_attempts)
    reader: SheetsReader = reader_for(service, []).reporting(StageProgress(record.console))
    with pytest.raises(SheetsReadError):
        reader.read_plan(vault_with_table())
    assert record.lines == [
        msg.PROGRESS_SHEETS_RETRY.format(place=retry, total=policy.max_retries) for retry in (1, 2, 3, 4)
    ]
    assert record.lines[0] == "Google не ответил — повтор 1 из 4."


def test_a_read_without_retries_and_a_reader_without_a_console_say_nothing() -> None:
    record: ConsoleRecord = ConsoleRecord()
    service: _FakeService = _FakeService(TITLES, HEADERS, {"values": VALUES})
    reader_for(service, []).reporting(StageProgress(record.console)).read_plan(vault_with_table())
    read(_FakeService(http_error(503), TITLES, HEADERS, {"values": VALUES}))        # без консоли — молчит
    assert record.lines == []


def test_a_retried_write_says_the_line_too() -> None:
    record: ConsoleRecord = ConsoleRecord()
    service: _FakeService = _FakeService(http_error(503), {}, {})
    reader: SheetsReader = reader_for(service, []).reporting(StageProgress(record.console))
    reader.write_outputs(vault_with_table(), _preview_write())
    assert record.lines == [msg.PROGRESS_SHEETS_RETRY.format(place=1, total=4)]


# --- без повторов


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (403, SheetsReadReason.NO_ACCESS),
        (401, SheetsReadReason.NO_ACCESS),
        (404, SheetsReadReason.NOT_FOUND),
        (400, SheetsReadReason.BAD_RANGE),
        (409, SheetsReadReason.REJECTED),
    ],
)
def test_other_statuses_fail_at_once(status: int, reason: SheetsReadReason) -> None:
    sleeps: list[float] = []
    service: _FakeService = _FakeService(http_error(status))
    with pytest.raises(SheetsReadError) as raised:
        read(service, sleeps)
    assert raised.value.reason is reason
    assert raised.value.status == status
    assert len(service.calls) == 1 and sleeps == []
    assert str(status) in str(raised.value)
    assert SHEET_ID.log_label in str(raised.value)


def test_no_access_on_the_list_of_sheets_stops_before_the_first_rows() -> None:
    service: _FakeService = _FakeService(http_error(403))
    with pytest.raises(SheetsReadError) as raised:
        read(service)
    assert raised.value.reason is SheetsReadReason.NO_ACCESS
    assert service.kinds == [SheetsCallKind.TITLES]


def test_token_revoked_during_the_request_is_auth_without_retry() -> None:
    service: _FakeService = _FakeService(RefreshError("invalid_grant"))
    with pytest.raises(SheetsReadError) as raised:
        read(service)
    assert raised.value.reason is SheetsReadReason.AUTH
    assert AuthErrorReason.LOGIN_REQUIRED.human in str(raised.value)
    assert len(service.calls) == 1


# --- секреты


@pytest.mark.parametrize("status", [400, 403, 404, 429, 503])
def test_no_error_text_or_log_line_carries_the_sheet_id_or_url(status: int, log: LogCapture) -> None:
    service: _FakeService = _FakeService(TITLES, *[http_error(status)] * RetryPolicy().max_attempts)
    assert SHEET_ID.reveal() in str(http_error(status))            # подделка честная: URL с id в тексте
    with pytest.raises(SheetsReadError) as raised:
        read(service)
    assert_no_secret(str(raised.value))
    assert_no_secret(repr(raised.value))
    assert log.messages()
    for line in log.messages():
        assert_no_secret(line)
    assert any(line.startswith("sheets_read_failed") and f"status={status}" in line for line in log.messages())


def test_a_successful_read_logs_labels_calls_and_sheet_ranges_only(log: LogCapture) -> None:
    read(_FakeService(TITLES, HEADERS, {"values": VALUES}))
    sheet: str = SHEET_ID.log_label
    assert [line for line in log.messages() if line.startswith("sheets_read")] == [
        f"sheets_read_started sheet={sheet} call=titles ranges=-",
        f"sheets_read_done sheet={sheet} call=titles ranges=- attempts=1",
        f"sheets_read_started sheet={sheet} call=headers ranges='Заметки'!1:1,'План стримов'!1:1",
        f"sheets_read_done sheet={sheet} call=headers ranges='Заметки'!1:1,'План стримов'!1:1 attempts=1",
        f"sheets_read_started sheet={sheet} call=values ranges='План стримов'",
        f"sheets_read_done sheet={sheet} call=values ranges='План стримов' attempts=1",
    ]


def test_retry_is_logged_without_values(log: LogCapture) -> None:
    read(_FakeService(http_error(503), TITLES, HEADERS, {"values": VALUES}))
    retries: list[str] = [line for line in log.messages() if line.startswith("sheets_read_retry")]
    assert retries == [
        f"sheets_read_retry sheet={SHEET_ID.log_label} call=titles ranges=- "
        "status=503 error=HttpError retry=1 delay_sec=2.0"
    ]


def test_the_failed_line_names_reason_call_status_and_attempts_once(log: LogCapture) -> None:
    service: _FakeService = _FakeService(*[http_error(503)] * 5)
    with pytest.raises(SheetsReadError):
        read(service)
    (failed,) = [line for line in log.messages() if line.startswith("sheets_read_failed")]
    assert failed == (
        f"sheets_read_failed reason=unavailable sheet={SHEET_ID.log_label} call=titles status=503 error=HttpError "
        "attempts=5"
    )


# --- сейф


def test_missing_table_fails_without_calling_google() -> None:
    service: _FakeService = _FakeService()
    with pytest.raises(SheetsReadError) as raised:
        reader_for(service, []).read_plan(Vault.empty())
    assert raised.value.reason is SheetsReadReason.NOT_CONFIGURED
    assert service.calls == []
    assert SheetsReadReason.NOT_CONFIGURED.human in str(raised.value)


def test_target_takes_the_table_from_the_vault() -> None:
    assert SheetsTarget.from_vault(vault_with_table()).sheet_id is SHEET_ID


# --- открытие


def test_open_builds_sheets_v4_with_the_operator_credentials(
    livecraft_paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials: object = object()
    built: list[dict[str, Any]] = []
    monkeypatch.setattr(GoogleLogin, "credentials", lambda self, **kwargs: credentials)
    monkeypatch.setattr(
        client_module,
        "build",
        lambda name, version, **kwargs: built.append({"name": name, "version": version, **kwargs}) or "service",
    )
    reader: SheetsReader = SheetsReader.open(GoogleLogin.operator(livecraft_paths))
    assert reader.service == "service"
    assert built == [{"name": "sheets", "version": "v4", "credentials": credentials, "cache_discovery": False}]


def test_open_again_goes_to_the_browser_past_the_token(livecraft_paths: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный вход оператора: вход в браузере без чтения токена; обычный вход токен читает."""
    asked: list[dict[str, Any]] = []
    monkeypatch.setattr(GoogleLogin, "credentials", lambda self, **options: asked.append(options) or object())
    monkeypatch.setattr(client_module, "build", lambda name, version, **options: "service")
    login: GoogleLogin = GoogleLogin.operator(livecraft_paths)
    SheetsReader.open(login)
    SheetsReader.open(login, force_reauth=True)
    assert [options["force_reauth"] for options in asked] == [False, True]
    assert all(options["allow_login"] for options in asked)


def test_open_turns_auth_error_into_sheets_read_error(livecraft_paths: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(self: GoogleLogin, **kwargs: Any) -> None:
        raise AuthError(AuthErrorReason.CLIENT_SECRET_MISSING, "client_secret.json")

    monkeypatch.setattr(GoogleLogin, "credentials", _fail)
    with pytest.raises(SheetsReadError) as raised:
        SheetsReader.open(GoogleLogin.operator(livecraft_paths), allow_login=False)
    assert raised.value.reason is SheetsReadReason.AUTH
    assert AuthErrorReason.CLIENT_SECRET_MISSING.human in str(raised.value)
    assert isinstance(raised.value.__cause__, AuthError)


def test_a_login_that_is_not_refreshed_without_network_is_no_network_not_a_setup_problem(
    livecraft_paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Рабочий прогон 01-10-2026 21:12: адрес oauth2.googleapis.com не найден при обновлении входа — это нет связи
    (код 1, лечится повтором запуска), а не «не удалось войти» (код 2, настройка)."""
    def _fail(self: GoogleLogin, **kwargs: Any) -> None:
        raise AuthError(AuthErrorReason.REFRESH_FAILED, "sheets.token.json: TransportError")

    monkeypatch.setattr(GoogleLogin, "credentials", _fail)
    with pytest.raises(SheetsReadError) as raised:
        SheetsReader.open(GoogleLogin.operator(livecraft_paths))
    assert raised.value.reason is SheetsReadReason.NO_NETWORK and not raised.value.reason.is_configuration
    assert "компьютер не находит серверы Google" in str(raised.value)
    others: list[AuthErrorReason] = [reason for reason in AuthErrorReason if reason is not AuthErrorReason.REFRESH_FAILED]
    assert {SHEETS_FAILURES.login_reason(reason) for reason in others} == {SheetsReadReason.AUTH}


def test_every_read_reason_has_a_russian_text() -> None:
    for reason in SheetsReadReason:
        assert reason.human
    assert set(client_module.msg.SHEETS_READ_REASON_TEXT) == {reason.value for reason in SheetsReadReason}


def test_only_setup_and_login_failures_are_configuration() -> None:
    """Таблица не настроена или вход не удался — лечится настройкой, а не повтором: код 2 и у прогона, и у пробника."""
    configuration: set[SheetsReadReason] = {reason for reason in SheetsReadReason if reason.is_configuration}
    assert configuration == {SheetsReadReason.NOT_CONFIGURED, SheetsReadReason.AUTH}


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (429, SheetsReadReason.UNAVAILABLE),
        (503, SheetsReadReason.UNAVAILABLE),
        (400, SheetsReadReason.BAD_RANGE),
        (403, SheetsReadReason.NO_ACCESS),
        (404, SheetsReadReason.NOT_FOUND),
        (418, SheetsReadReason.REJECTED),
    ],
)
def test_the_reason_of_a_status_is_one_rule(status: int, reason: SheetsReadReason) -> None:
    """Код ответа → причина одним правилом; повторяется ровно то, что временно недоступно."""
    assert SheetsReadReason.for_status(status) is reason
