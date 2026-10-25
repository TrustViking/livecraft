"""Файл входа Google и проект, через который вход сделан (app\\google\\login_file.py; CLAUDE.md §14 решение 67)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.google.login_file import LoginFile
from app.google.oauth_client import OAuthClient
from app.tests.fixtures.google_client import TEST_CLIENT_ID, client_text, login_text

OTHER_CLIENT_ID: str = "2000-other.apps.googleusercontent.com"


def _client() -> OAuthClient:
    client: OAuthClient | None = OAuthClient.of_text(client_text())
    assert client is not None
    return client


def _file(tmp_path: Path, text: str) -> Path:
    path: Path = tmp_path / "@Kanal.X.token.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_login_through_the_project_is_through_it(tmp_path: Path) -> None:
    login: LoginFile = LoginFile.of(_file(tmp_path, login_text(TEST_CLIENT_ID)))
    assert login.client_id == TEST_CLIENT_ID
    assert login.exists and login.is_through(_client())


def test_a_login_through_another_project_is_not_through_this_one(tmp_path: Path) -> None:
    login: LoginFile = LoginFile.of(_file(tmp_path, login_text(OTHER_CLIENT_ID)))
    assert login.client_id == OTHER_CLIENT_ID
    assert login.exists and not login.is_through(_client())


@pytest.mark.parametrize(
    "text",
    [
        "not json",                                                       # не JSON
        json.dumps(["client_id"]),                                        # JSON, но не файл входа
        json.dumps({"token": "x", "refresh_token": "y"}),                # нет id клиента
        json.dumps({"token": "x", "client_id": ""}),                     # пустой id клиента
        json.dumps({"token": "x", "client_id": 7}),                      # id клиента не строка
    ],
)
def test_a_file_without_a_client_is_no_login(tmp_path: Path, text: str) -> None:
    login: LoginFile = LoginFile.of(_file(tmp_path, text))
    assert login.client_id is None
    assert not login.exists and not login.is_through(_client())


def test_a_missing_file_is_no_login(tmp_path: Path) -> None:
    login: LoginFile = LoginFile.of(tmp_path / "sheets.token.json")
    assert login == LoginFile(path=tmp_path / "sheets.token.json", client_id=None)
    assert not login.exists and not login.is_through(_client())
