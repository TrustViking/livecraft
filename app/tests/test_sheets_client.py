from __future__ import annotations

import http.client
import logging
import random
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import pytest
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from app.core.retry import RetryPolicy
from app.google.auth import AuthError, AuthErrorReason, GoogleLogin
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.sheets import client as client_module
from app.sheets.client import SheetsReader, SheetsReadError, SheetsReadReason, SheetsTarget
from app.sheets.plan import SheetColumns, SheetPlan
from app.tests.conftest import SUPPLIED_VALUES

SHEET_ID: SecretValue = SecretValue(SecretField.SHEETS_ID, SUPPLIED_VALUES[SecretField.SHEETS_ID])
SHEET_RANGE: SecretValue = SecretValue(SecretField.SHEETS_RANGE, "Plan!B2:H")
REQUEST_URI: str = (
    f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID.reveal()}/values/"
    f"{quote(SHEET_RANGE.reveal())}?alt=json"
)
VALUES: list[list[str]] = [["Links", "Date", "Time"], ["https://youtu.be/dQw4w9WgXcQ", "16.10.2026", "19:00"]]


@dataclass
class _Resp:
    """Ответ httplib2 в том объёме, который читает HttpError."""

    status: int
    reason: str = "error"


def http_error(status: int) -> HttpError:
    """Настоящая HttpError: в её тексте — URL запроса с id таблицы и диапазоном, как в бою."""
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


class _FakeService:
    """Подделка googleapiclient: цепочка spreadsheets().values().get(...).execute() и запись вызовов."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes: Iterator[Any] = iter(outcomes)
        self.calls: list[dict[str, str]] = []

    def spreadsheets(self) -> _FakeService:
        return self

    def values(self) -> _FakeService:
        return self

    def get(self, *, spreadsheetId: str, range: str) -> _Request:  # noqa: A002 — имя параметра API
        self.calls.append({"spreadsheetId": spreadsheetId, "range": range})
        return _Request(self)


class _ZeroRandom(random.Random):
    def uniform(self, a: float, b: float) -> float:
        return a


class _Collector(logging.Handler):
    """Свой обработчик на логгере livecraft.sheets: не зависит от propagate после других тестов."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def log() -> Iterator[_Collector]:
    logger: logging.Logger = logging.getLogger("livecraft.sheets")
    collector: _Collector = _Collector()
    level: int = logger.level
    logger.setLevel(logging.DEBUG)       # setLevel, а не присваивание: он сбрасывает кеш isEnabledFor
    logger.addHandler(collector)
    yield collector
    logger.removeHandler(collector)
    logger.setLevel(level)


def reader_for(service: _FakeService, sleeps: list[float]) -> SheetsReader:
    return SheetsReader(service=service, policy=RetryPolicy(), rng=_ZeroRandom(0), sleep=sleeps.append)


def vault_with(*fields: SecretField) -> Vault:
    vault: Vault = Vault.empty()
    for name in fields:
        value: SecretValue = SHEET_ID if name is SecretField.SHEETS_ID else SHEET_RANGE
        vault = vault.with_field(name, value, VaultOrigin.SUPPLIED)
    return vault


def assert_no_secret(text: str) -> None:
    for value in (SHEET_ID.reveal(), SHEET_RANGE.reveal(), quote(SHEET_RANGE.reveal()), REQUEST_URI):
        assert value not in text


# --- успех


def test_plan_is_read_with_the_revealed_values() -> None:
    service: _FakeService = _FakeService({"range": "ignored", "values": VALUES})
    plan: SheetPlan = reader_for(service, []).read_plan(vault_with(SecretField.SHEETS_ID, SecretField.SHEETS_RANGE))
    assert plan.columns == SheetColumns(link=0, date=1, time=2)
    assert len(plan.rows) == 1
    assert service.calls == [{"spreadsheetId": SHEET_ID.reveal(), "range": SHEET_RANGE.reveal()}]


def test_empty_range_has_no_values_key() -> None:
    values: list[list[str]] = reader_for(_FakeService({"range": "x"}), []).read_values(SHEET_ID, SHEET_RANGE)
    assert values == []


def test_cells_come_back_as_strings() -> None:
    service: _FakeService = _FakeService({"values": [["Links", 1, 2.5]]})
    assert reader_for(service, []).read_values(SHEET_ID, SHEET_RANGE) == [["Links", "1", "2.5"]]


# --- повторы


def test_two_503_then_success_are_two_retries_with_policy_pauses() -> None:
    sleeps: list[float] = []
    service: _FakeService = _FakeService(http_error(503), http_error(503), {"values": VALUES})
    assert reader_for(service, sleeps).read_values(SHEET_ID, SHEET_RANGE) == VALUES
    assert len(service.calls) == 3
    policy: RetryPolicy = RetryPolicy()
    assert sleeps == [policy.delay_sec(1, _ZeroRandom(0)), policy.delay_sec(2, _ZeroRandom(0))] == [2.0, 4.0]


def test_429_on_every_attempt_is_unavailable_after_max_attempts() -> None:
    policy: RetryPolicy = RetryPolicy()
    sleeps: list[float] = []
    service: _FakeService = _FakeService(*[http_error(429)] * policy.max_attempts)
    with pytest.raises(SheetsReadError) as raised:
        reader_for(service, sleeps).read_values(SHEET_ID, SHEET_RANGE)
    assert raised.value.reason is SheetsReadReason.UNAVAILABLE
    assert raised.value.status == 429
    assert len(service.calls) == policy.max_attempts == 5
    assert len(sleeps) == policy.max_retries
    assert isinstance(raised.value.__cause__, HttpError)


@pytest.mark.parametrize("status", [500, 502, 504])
def test_every_server_error_is_retried(status: int) -> None:
    service: _FakeService = _FakeService(http_error(status), {"values": VALUES})
    assert reader_for(service, []).read_values(SHEET_ID, SHEET_RANGE) == VALUES
    assert len(service.calls) == 2


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
    service: _FakeService = _FakeService(error, {"values": VALUES})
    assert reader_for(service, sleeps).read_values(SHEET_ID, SHEET_RANGE) == VALUES
    assert len(service.calls) == 2 and len(sleeps) == 1


def test_transport_errors_to_the_end_are_unavailable_without_status() -> None:
    policy: RetryPolicy = RetryPolicy()
    service: _FakeService = _FakeService(*[OSError("down")] * policy.max_attempts)
    with pytest.raises(SheetsReadError) as raised:
        reader_for(service, []).read_values(SHEET_ID, SHEET_RANGE)
    assert raised.value.reason is SheetsReadReason.UNAVAILABLE
    assert raised.value.status is None


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
        reader_for(service, sleeps).read_values(SHEET_ID, SHEET_RANGE)
    assert raised.value.reason is reason
    assert raised.value.status == status
    assert len(service.calls) == 1 and sleeps == []
    assert str(status) in str(raised.value)
    assert SHEET_ID.log_label in str(raised.value)


def test_token_revoked_during_the_request_is_auth_without_retry() -> None:
    service: _FakeService = _FakeService(RefreshError("invalid_grant"))
    with pytest.raises(SheetsReadError) as raised:
        reader_for(service, []).read_values(SHEET_ID, SHEET_RANGE)
    assert raised.value.reason is SheetsReadReason.AUTH
    assert AuthErrorReason.LOGIN_REQUIRED.human in str(raised.value)
    assert len(service.calls) == 1


# --- секреты


@pytest.mark.parametrize("status", [400, 403, 404, 429, 503])
def test_no_error_text_or_log_line_carries_the_sheet_id_range_or_url(status: int, log: _Collector) -> None:
    service: _FakeService = _FakeService(*[http_error(status)] * RetryPolicy().max_attempts)
    assert SHEET_ID.reveal() in str(http_error(status))            # подделка честная: URL с id в тексте
    with pytest.raises(SheetsReadError) as raised:
        reader_for(service, []).read_values(SHEET_ID, SHEET_RANGE)
    assert_no_secret(str(raised.value))
    assert_no_secret(repr(raised.value))
    assert log.messages
    for line in log.messages:
        assert_no_secret(line)
    assert any(line.startswith("sheets_read_failed") and f"status={status}" in line for line in log.messages)


def test_successful_read_logs_labels_and_row_count_only(log: _Collector) -> None:
    reader_for(_FakeService({"values": VALUES}), []).read_values(SHEET_ID, SHEET_RANGE)
    assert log.messages == [
        f"sheets_read_started sheet={SHEET_ID.log_label} range={SHEET_RANGE.log_label}",
        f"sheets_read_done sheet={SHEET_ID.log_label} range={SHEET_RANGE.log_label} rows=2 attempts=1",
    ]


def test_retry_is_logged_without_values(log: _Collector) -> None:
    reader_for(_FakeService(http_error(503), {"values": VALUES}), []).read_values(SHEET_ID, SHEET_RANGE)
    retries: list[str] = [line for line in log.messages if line.startswith("sheets_read_retry")]
    assert retries == [
        f"sheets_read_retry sheet={SHEET_ID.log_label} range={SHEET_RANGE.log_label} "
        "status=503 error=HttpError retry=1 delay_sec=2.0"
    ]


# --- сейф


@pytest.mark.parametrize(
    "present",
    [(SecretField.SHEETS_RANGE,), (SecretField.SHEETS_ID,), ()],
)
def test_missing_vault_field_fails_without_calling_google(present: tuple[SecretField, ...]) -> None:
    service: _FakeService = _FakeService()
    with pytest.raises(SheetsReadError) as raised:
        reader_for(service, []).read_plan(vault_with(*present))
    assert raised.value.reason is SheetsReadReason.NOT_CONFIGURED
    assert service.calls == []
    for name in SecretField:
        if name in (SecretField.SHEETS_ID, SecretField.SHEETS_RANGE) and name not in present:
            assert name.human_label in str(raised.value)
    assert_no_secret(str(raised.value))


def test_target_takes_both_secrets_from_the_vault() -> None:
    target: SheetsTarget = SheetsTarget.from_vault(vault_with(SecretField.SHEETS_ID, SecretField.SHEETS_RANGE))
    assert target.sheet_id is SHEET_ID
    assert target.sheet_range is SHEET_RANGE


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


def test_open_turns_auth_error_into_sheets_read_error(livecraft_paths: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(self: GoogleLogin, **kwargs: Any) -> None:
        raise AuthError(AuthErrorReason.CLIENT_SECRET_MISSING, "client_secret.json")

    monkeypatch.setattr(GoogleLogin, "credentials", _fail)
    with pytest.raises(SheetsReadError) as raised:
        SheetsReader.open(GoogleLogin.operator(livecraft_paths), allow_login=False)
    assert raised.value.reason is SheetsReadReason.AUTH
    assert AuthErrorReason.CLIENT_SECRET_MISSING.human in str(raised.value)
    assert isinstance(raised.value.__cause__, AuthError)


def test_every_read_reason_has_a_russian_text() -> None:
    for reason in SheetsReadReason:
        assert reason.human
    assert set(client_module.msg.SHEETS_READ_REASON_TEXT) == {reason.value for reason in SheetsReadReason}
