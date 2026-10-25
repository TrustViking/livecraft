"""Проект Google: годность файла клиента и ответ Google о клиенте без входа (app\\google\\oauth_client.py; CLAUDE.md
§9, §14 решение 66)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import requests

from app.google.oauth_client import ClientAnswer, OAuthClient
from app.observability.log_event import LogArea, LogValue
from app.tests.fixtures.google_client import (
    KNOWN,
    NOT_KNOWN,
    TEST_CLIENT_ID,
    TEST_PROJECT,
    TEST_SECRET,
    TOKEN_URI,
    FakeTokenEndpoint,
    FakeTokenResponse,
    client_text,
)
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg


def test_a_desktop_client_gives_its_project_and_id() -> None:
    client: OAuthClient | None = OAuthClient.of_text(client_text())
    assert client is not None
    assert (client.project_id, client.client_id, client.token_uri) == (TEST_PROJECT, TEST_CLIENT_ID, TOKEN_URI)
    assert client.label == "проект Google kanal-test" == OAuthClient.label_of(client_text())
    assert TEST_SECRET not in repr(client)


@pytest.mark.parametrize(
    "text",
    [
        client_text(kind="web"),                                            # клиент типа Web
        client_text(client_id=""),                                          # пустой client_id
        client_text(secret=""),                                             # нет секрета
        json.dumps({"installed": {"client_id": "x", "client_secret": "s"}}),     # нет token_uri и проекта
        json.dumps(["installed"]),                                          # JSON, но не файл клиента
        "client_id = x",                                                    # не JSON
    ],
)
def test_anything_but_a_desktop_client_does_not_fit(text: str) -> None:
    assert OAuthClient.of_text(text) is None
    assert OAuthClient.label_of(text) == msg.GOOGLE_PROJECT_UNFIT


def test_a_client_file_gives_the_client_and_anything_else_none(tmp_path: Path) -> None:
    """Клиент из файла: годный файл — клиент; файла нет, он не текст или не клиент Desktop — None."""
    desktop: Path = tmp_path / "any name.json"
    desktop.write_text(client_text(), encoding="utf-8")
    web: Path = tmp_path / "web.json"
    web.write_text(client_text(kind="web"), encoding="utf-8")
    binary: Path = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00")
    assert OAuthClient.of_file(desktop) == OAuthClient.of_text(client_text())
    for path in (web, binary, tmp_path / "missing.json", tmp_path):
        assert OAuthClient.of_file(path) is None


def test_google_knows_the_client_when_it_refuses_only_the_refresh_token() -> None:
    """invalid_grant — Google узнал клиент и секрет, отказал только негодному refresh_token."""
    google: FakeTokenEndpoint = FakeTokenEndpoint(answers=[KNOWN])
    client: OAuthClient | None = OAuthClient.of_text(client_text())
    assert client is not None
    assert google.probe.answer(client) is ClientAnswer.KNOWN
    assert google.urls == [TOKEN_URI]
    assert google.forms[0]["client_id"] == TEST_CLIENT_ID and google.forms[0]["grant_type"] == "refresh_token"


def test_invalid_client_means_google_does_not_know_it() -> None:
    client: OAuthClient | None = OAuthClient.of_text(client_text())
    assert client is not None
    answer: ClientAnswer = FakeTokenEndpoint(answers=[NOT_KNOWN]).probe.answer(client)
    assert answer is ClientAnswer.NOT_KNOWN and answer.log_mark is LogValue.NO
    assert answer.human.startswith("Google этот клиент не знает")


def test_no_network_is_retried_and_said_as_no_internet() -> None:
    google: FakeTokenEndpoint = FakeTokenEndpoint.offline()
    client: OAuthClient | None = OAuthClient.of_text(client_text())
    assert client is not None
    with LogCapture.on(LogArea.AUTH, logging.DEBUG) as capture:
        answer: ClientAnswer = google.probe.answer(client)
    assert answer is ClientAnswer.NO_NETWORK and answer.log_mark is LogValue.UNKNOWN
    assert "нет интернета" in answer.human
    assert len(google.urls) == 5 and len(google.sleeps) == 4            # первое обращение и четыре повтора
    assert all(TEST_SECRET not in line for line in capture.messages())


def test_a_busy_google_is_asked_again() -> None:
    google: FakeTokenEndpoint = FakeTokenEndpoint(answers=[FakeTokenResponse(503), requests.Timeout("slow"), KNOWN])
    client: OAuthClient | None = OAuthClient.of_text(client_text())
    assert client is not None
    assert google.probe.answer(client) is ClientAnswer.KNOWN
    assert len(google.urls) == 3


def test_an_answer_off_the_point_is_not_a_verdict_about_the_client() -> None:
    """Google ответил не invalid_grant и не invalid_client — о клиенте ничего не сказал: спросить не вышло."""
    google: FakeTokenEndpoint = FakeTokenEndpoint(answers=[FakeTokenResponse(400, {"error": "unsupported_grant_type"})])
    client: OAuthClient | None = OAuthClient.of_text(client_text())
    assert client is not None
    assert google.probe.answer(client) is ClientAnswer.UNAVAILABLE
    assert len(google.urls) == 1
