"""Google оператора без Google: подменённый поток входа в браузере и клиенты Sheets и Drive на его токене.

Вход, токен и клиенты — настоящий код программы (`GoogleLogin`, `SheetsReader`, `DriveClient`); подменены только
браузер (`InstalledAppFlow`) и сборка клиентов API (`build`). «Человек» входит в браузере очередным аккаунтом из
`logins`; токен доступа подделки — почта аккаунта, по ней клиенты знают, кто спрашивает: таблица открыта только
аккаунтам из `allowed`, Диск называет почту аккаунта.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from app.google import auth as auth_module
from app.google import call_failure as call_failure_module
from app.google.auth import GoogleLogin
from app.sheets import client as client_module

SHEET_TITLE: str = "План стримов"
FAR_EXPIRY: str = "2999-01-01T00:00:00Z"


@dataclass
class _Resp:
    """Ответ httplib2 в том объёме, который читает HttpError."""

    status: int
    reason: str = "error"


@dataclass
class _Answer:
    """Запрос API подделки: ответ или исключение — при выполнении."""

    result: Any

    def execute(self) -> Any:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class _Values:
    google: FakeOperatorGoogle
    account: str

    def batchGet(self, **request: Any) -> _Answer:  # noqa: N802 — имя API
        return self.google.sheets_answer(self.account, {"valueRanges": [{"values": self.google.values[:1]}]})

    def get(self, **request: Any) -> _Answer:
        return self.google.sheets_answer(self.account, {"values": self.google.values})


@dataclass
class _Spreadsheets:
    google: FakeOperatorGoogle
    account: str

    def get(self, **request: Any) -> _Answer:
        titles: dict[str, Any] = {"sheets": [{"properties": {"sheetId": 7, "title": SHEET_TITLE}}]}
        return self.google.sheets_answer(self.account, titles)

    def values(self) -> _Values:
        return _Values(self.google, self.account)


@dataclass
class _About:
    google: FakeOperatorGoogle
    account: str

    def get(self, **request: Any) -> _Answer:
        if self.google.drive_error is not None:
            return _Answer(self.google.drive_error)
        return _Answer({"user": {"emailAddress": self.account}})


@dataclass
class _Service:
    """Клиент API подделки на токене аккаунта: и Sheets, и Drive."""

    google: FakeOperatorGoogle
    account: str

    def spreadsheets(self) -> _Spreadsheets:
        return _Spreadsheets(self.google, self.account)

    def about(self) -> _About:
        return _About(self.google, self.account)


class _Flow:
    """Подмена InstalledAppFlow: «человек» входит очередным аккаунтом Google подделки."""

    google: FakeOperatorGoogle

    def __init__(self, scopes: list[str]) -> None:
        self.scopes: list[str] = scopes

    @classmethod
    def from_client_secrets_file(cls, path: str, scopes: list[str]) -> _Flow:
        return cls(scopes)

    def run_local_server(self, **options: Any) -> Credentials:
        return self.google.browser_login(self.scopes, options)


@dataclass
class FakeOperatorGoogle:
    """Google оператора в памяти. `logins` — аккаунты, которыми входят в браузере, по очереди; `allowed` — аккаунты,
    которым открыта таблица; `values` — лист плана; `sheets_errors` — исключения на следующие обращения к таблице
    (вперёд ответа); `drive_error` — Диск не называет почту; `flow_error` — вход в браузере не удаётся. В запись:
    параметры каждого входа в браузере (`flows`), токен оператора на диске в момент каждого входа (`tokens_at_login`)
    и аккаунт каждого обращения к таблице (`sheets_calls`)."""

    login: GoogleLogin
    logins: list[str]
    allowed: set[str]
    values: list[list[str]]
    sheets_errors: list[Exception] = field(default_factory=list)
    drive_error: Exception | None = None
    flow_error: Exception | None = None
    flows: list[dict[str, Any]] = field(default_factory=list)
    tokens_at_login: list[str | None] = field(default_factory=list)
    sheets_calls: list[str] = field(default_factory=list)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeOperatorGoogle:
        """Подменить браузер входа и сборку клиентов Sheets и Drive этой подделкой."""
        flow: type[_Flow] = type("_BoundFlow", (_Flow,), {"google": self})
        monkeypatch.setattr(auth_module, "InstalledAppFlow", flow)
        monkeypatch.setattr(client_module, "build", self.build)
        monkeypatch.setattr(call_failure_module, "build", self.build)
        return self

    def build(self, name: str, version: str, **options: Any) -> _Service:
        return _Service(self, options["credentials"].token)

    def write_token(self, account: str) -> str:
        """Действующий токен оператора на диске — как после прошлого входа этим аккаунтом; вернуть текст файла."""
        text: str = self.credentials(account, list(self.login.scopes)).to_json()
        self.login.token_file.write_text(text, encoding="utf-8")
        return text

    def credentials(self, account: str, scopes: list[str]) -> Credentials:
        """Настоящие учётные данные google-auth: токен доступа — почта аккаунта, срок — в далёком будущем."""
        info: dict[str, Any] = {
            "token": account, "refresh_token": "r", "client_id": "c", "client_secret": "s", "scopes": scopes,
            "expiry": FAR_EXPIRY,
        }
        return Credentials.from_authorized_user_info(json.loads(json.dumps(info)))

    def browser_login(self, scopes: list[str], options: dict[str, Any]) -> Credentials:
        self.flows.append(options)
        token: str | None = None
        if self.login.token_file.is_file():
            token = self.login.token_file.read_text(encoding="utf-8")
        self.tokens_at_login.append(token)
        if self.flow_error is not None:
            raise self.flow_error
        return self.credentials(self.logins.pop(0), scopes)

    def sheets_answer(self, account: str, answer: dict[str, Any]) -> _Answer:
        self.sheets_calls.append(account)
        if self.sheets_errors:
            return _Answer(self.sheets_errors.pop(0))
        if account not in self.allowed:
            return _Answer(self.http_error(403))
        return _Answer(answer)

    def http_error(self, status: int) -> HttpError:
        """Настоящая HttpError: в её тексте — адрес запроса, как в бою."""
        content: bytes = b'{"error": {"message": "request failed"}}'
        return HttpError(_Resp(status), content, uri="https://sheets.googleapis.com/v4/spreadsheets/x")  # type: ignore[arg-type]
