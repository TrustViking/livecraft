"""Правило входа оператора (app\\sheets\\operator.py, CLAUDE.md §13 задача 9.6): каким аккаунтом входить, каким вошли и
повторный вход, когда аккаунту таблица не открыта. К Google тесты не ходят: вход — на подделке входа оператора либо
настоящий код входа и клиентов на подменённом браузере (`FakeOperatorGoogle`)."""
from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from google_auth_oauthlib.flow import WSGITimeoutError
from googleapiclient.errors import HttpError

from app.google.auth import PROMPT, AuthErrorReason, GoogleLogin
from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.sheets.client import SheetsReadError, SheetsReadReason
from app.sheets.operator import OperatorAccount, OperatorDoor, OperatorPlan, OperatorSheets
from app.tests.conftest import TOKEN_VALUES
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.operator import SHEET_TITLE, FakeOperatorGoogle
from app.tests.fixtures.sheets import OPERATOR_EMAIL, FakeSheetsReader
from app.ui import messages_ru as msg

SHEET_ID: SecretValue = SecretValue(SecretField.SHEETS_ID, TOKEN_VALUES[SecretField.SHEETS_ID])
VAULT: Vault = Vault.empty().with_field(SecretField.SHEETS_ID, SHEET_ID, VaultOrigin.TOKEN)
VALUES: list[list[str]] = [["Links", "Date", "Time"], ["https://youtu.be/dQw4w9WgXcQ", "16.10.2026", "19:00"]]
TABLE_ACCOUNT: str = "table@example.com"
CHANNEL_ACCOUNT: str = "channel@example.com"
OTHER_ACCOUNT: str = "other@example.com"
LABEL: str = "sheets-plan(ab12)"


def _no_access() -> SheetsReadError:
    return SheetsReadError(SheetsReadReason.NO_ACCESS, LABEL, status=403)


def _rule(door: FakeSheetsReader, lines: list[str]) -> OperatorSheets:
    """Правило на подделке входа: строка перед браузером — «browser», строки правила — в `lines`."""
    return OperatorSheets(door, lambda: lines.append("browser"), lines.append)  # type: ignore[arg-type]


@pytest.fixture
def log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.SHEETS, logging.DEBUG) as capture:
        yield capture


@pytest.fixture
def login(livecraft_paths: LivecraftPaths) -> GoogleLogin:
    livecraft_paths.file(FileName.CLIENT_SECRET).write_text("{}", encoding="utf-8")
    return GoogleLogin.operator(livecraft_paths)


# --- правило на подделке входа


def test_a_saved_login_reads_the_plan_and_says_nothing() -> None:
    lines: list[str] = []
    door: FakeSheetsReader = FakeSheetsReader(values=VALUES)
    read: OperatorPlan = _rule(door, lines).read_plan(VAULT)
    assert read.reader is door and read.plan.columns is not None
    assert lines == [] and door.vaults == [VAULT]


def test_a_new_login_says_the_account_after_the_browser() -> None:
    lines: list[str] = []
    _rule(FakeSheetsReader(values=VALUES, announce_login=True), lines).read_plan(VAULT)
    assert lines == ["browser", msg.OPERATOR_LOGGED_IN.format(account=OPERATOR_EMAIL)]
    assert lines[-1] == f"Вход в Google: {OPERATOR_EMAIL}"


def test_an_account_without_access_logs_in_again_and_the_new_account_reads() -> None:
    lines: list[str] = []
    table: FakeSheetsReader = FakeSheetsReader(values=VALUES, account_email=TABLE_ACCOUNT)
    door: FakeSheetsReader = FakeSheetsReader(error=_no_access(), account_email=CHANNEL_ACCOUNT, relogin=table)
    read: OperatorPlan = _rule(door, lines).read_plan(VAULT)
    assert read.reader is table                              # запись в таблицу пойдёт читателем нового входа
    assert lines == [
        msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT),
        "browser",
        msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT),
    ]
    assert door.login_announced == 1                         # повторный вход — один


def test_no_access_twice_stops_with_the_account_and_the_action() -> None:
    lines: list[str] = []
    other: FakeSheetsReader = FakeSheetsReader(error=_no_access(), account_email=OTHER_ACCOUNT)
    door: FakeSheetsReader = FakeSheetsReader(error=_no_access(), account_email=CHANNEL_ACCOUNT, relogin=other)
    with pytest.raises(SheetsReadError) as raised:
        _rule(door, lines).read_plan(VAULT)
    error: SheetsReadError = raised.value
    assert error.reason is SheetsReadReason.ACCOUNT_REFUSED and error.status == 403 and error.label == LABEL
    assert not error.reason.is_configuration                 # код — как у отказа доступа: ошибка запуска
    assert str(error) == msg.SHEETS_READ_FAILED_STATUS.format(
        label=LABEL, reason=msg.SHEETS_READ_REASON_TEXT["account_refused"].format(detail=OTHER_ACCOUNT), status=403
    )
    assert f"аккаунту {OTHER_ACCOUNT} таблица не открыта — войдите аккаунтом, которому она открыта" in str(error)
    assert door.login_announced == 1 and len(other.vaults) == 1       # третьего входа и третьего чтения нет
    assert lines[0] == msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT)


@pytest.mark.parametrize("reason", [SheetsReadReason.NOT_FOUND, SheetsReadReason.UNAVAILABLE, SheetsReadReason.AUTH])
def test_another_failure_is_raised_as_is_without_a_second_login(reason: SheetsReadReason) -> None:
    lines: list[str] = []
    failure: SheetsReadError = SheetsReadError(reason, LABEL)
    door: FakeSheetsReader = FakeSheetsReader(error=failure)
    with pytest.raises(SheetsReadError) as raised:
        _rule(door, lines).read_plan(VAULT)
    assert raised.value is failure and lines == [] and door.login_announced == 0


def test_an_account_the_drive_does_not_name_is_said_so() -> None:
    lines: list[str] = []
    door: FakeSheetsReader = FakeSheetsReader(values=VALUES, announce_login=True, account_email=None)
    _rule(door, lines).read_plan(VAULT)
    assert OperatorAccount(None).shown == msg.OPERATOR_ACCOUNT_UNKNOWN
    assert lines[-1] == msg.OPERATOR_LOGGED_IN.format(account=msg.OPERATOR_ACCOUNT_UNKNOWN)


# --- настоящий вход на подменённом браузере


def test_the_first_login_names_the_account_to_use_and_then_the_account_used(
    login: GoogleLogin, monkeypatch: pytest.MonkeyPatch, log: LogCapture
) -> None:
    google: FakeOperatorGoogle = FakeOperatorGoogle(login, [TABLE_ACCOUNT], {TABLE_ACCOUNT}, VALUES).install(monkeypatch)
    lines: list[str] = []
    read: OperatorPlan = OperatorSheets.for_console(OperatorDoor(login), lines.append).read_plan(VAULT)
    assert read.plan.sheet_title == SHEET_TITLE and len(read.plan.rows) == 1
    assert lines == [msg.SHEETS_LOGIN_BROWSER, msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT)]
    assert "которому открыта таблица плана" in lines[0] and "не аккаунт канала YouTube" in lines[0]
    (flow,) = google.flows
    assert flow["prompt"] == PROMPT and "login_hint" not in flow        # выбор аккаунта — за человеком
    assert google.tokens_at_login == [None]
    assert f"operator_logged_in account={TABLE_ACCOUNT}" in log.messages()


def test_a_saved_login_with_access_opens_no_browser(login: GoogleLogin, monkeypatch: pytest.MonkeyPatch) -> None:
    google: FakeOperatorGoogle = FakeOperatorGoogle(login, [], {TABLE_ACCOUNT}, VALUES).install(monkeypatch)
    google.write_token(TABLE_ACCOUNT)
    lines: list[str] = []
    OperatorSheets.for_console(OperatorDoor(login), lines.append).read_plan(VAULT)
    assert lines == [] and google.flows == []


def test_a_saved_login_without_access_logs_in_again_and_reads(
    login: GoogleLogin, monkeypatch: pytest.MonkeyPatch, log: LogCapture
) -> None:
    """Вошли аккаунтом канала (запуск 0.1.3, 01-10-2026): программа сама замечает отказ и даёт войти другим аккаунтом —
    файл токена руками не удаляют; прежний токен цел до удачного входа."""
    google: FakeOperatorGoogle = FakeOperatorGoogle(login, [TABLE_ACCOUNT], {TABLE_ACCOUNT}, VALUES).install(monkeypatch)
    old_token: str = google.write_token(CHANNEL_ACCOUNT)
    lines: list[str] = []
    read: OperatorPlan = OperatorSheets.for_console(OperatorDoor(login), lines.append).read_plan(VAULT)
    assert len(read.plan.rows) == 1
    assert lines == [
        msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT),
        msg.SHEETS_LOGIN_BROWSER,
        msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT),
    ]
    assert google.tokens_at_login == [old_token]             # во время входа на диске — прежний токен
    assert google.credentials(TABLE_ACCOUNT, list(login.scopes)).to_json() == login.token_file.read_text("utf-8")
    assert google.sheets_calls[0] == CHANNEL_ACCOUNT and google.sheets_calls[-1] == TABLE_ACCOUNT
    assert f"operator_access_refused account={CHANNEL_ACCOUNT} status=403 relogin=yes" in log.messages()


def test_no_access_after_the_second_login_stops_with_that_account(
    login: GoogleLogin, monkeypatch: pytest.MonkeyPatch
) -> None:
    google: FakeOperatorGoogle = FakeOperatorGoogle(login, [OTHER_ACCOUNT], {TABLE_ACCOUNT}, VALUES).install(monkeypatch)
    old_token: str = google.write_token(CHANNEL_ACCOUNT)
    lines: list[str] = []
    with pytest.raises(SheetsReadError) as raised:
        OperatorSheets.for_console(OperatorDoor(login), lines.append).read_plan(VAULT)
    assert raised.value.reason is SheetsReadReason.ACCOUNT_REFUSED and raised.value.status == 403
    assert OTHER_ACCOUNT in str(raised.value) and CHANNEL_ACCOUNT not in str(raised.value)
    assert SHEET_ID.reveal() not in str(raised.value)
    assert isinstance(raised.value.__cause__, SheetsReadError) and isinstance(raised.value.__cause__.__cause__, HttpError)
    assert lines == [
        msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT),
        msg.SHEETS_LOGIN_BROWSER,
        msg.OPERATOR_LOGGED_IN.format(account=OTHER_ACCOUNT),
    ]
    assert google.tokens_at_login == [old_token] and len(google.flows) == 1       # повторный вход — один


def test_a_second_login_that_fails_keeps_the_old_token(login: GoogleLogin, monkeypatch: pytest.MonkeyPatch) -> None:
    google: FakeOperatorGoogle = FakeOperatorGoogle(login, [], {TABLE_ACCOUNT}, VALUES).install(monkeypatch)
    google.flow_error = WSGITimeoutError("timeout")
    old_token: str = google.write_token(CHANNEL_ACCOUNT)
    with pytest.raises(SheetsReadError) as raised:
        OperatorSheets.for_console(OperatorDoor(login), [].append).read_plan(VAULT)
    assert raised.value.reason is SheetsReadReason.AUTH and raised.value.reason.is_configuration
    assert AuthErrorReason.LOGIN_TIMEOUT.human in str(raised.value)
    assert login.token_file.read_text("utf-8") == old_token


def test_a_drive_that_does_not_answer_leaves_the_account_unnamed(
    login: GoogleLogin, monkeypatch: pytest.MonkeyPatch, log: LogCapture
) -> None:
    google: FakeOperatorGoogle = FakeOperatorGoogle(login, [TABLE_ACCOUNT], {TABLE_ACCOUNT}, VALUES).install(monkeypatch)
    google.drive_error = google.http_error(403)
    lines: list[str] = []
    read: OperatorPlan = OperatorSheets.for_console(OperatorDoor(login), lines.append).read_plan(VAULT)
    assert len(read.plan.rows) == 1                           # почта не названа — таблица всё равно читается
    assert lines[-1] == msg.OPERATOR_LOGGED_IN.format(account=msg.OPERATOR_ACCOUNT_UNKNOWN)
    assert any(line.startswith("drive_failed reason=no_access call=account status=403") for line in log.messages())
