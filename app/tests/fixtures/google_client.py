"""Проект Google в тестах: файл клиента Google, файл входа и подделка `requests.post` выдачи токенов Google
(CLAUDE.md §9, §14 решение 66). Значения вымышленные."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import requests

from app.config.files import SettingsFile
from app.config.google import GoogleSettings
from app.google.oauth_client import ClientProbe
from app.paths import LivecraftPaths

TEST_PROJECT: str = "kanal-test"
TEST_CLIENT_ID: str = "1000-test.apps.googleusercontent.com"
TEST_SECRET: str = "GOCSPX-test-secret"
TOKEN_URI: str = "https://oauth2.googleapis.com/token"


def client_text(
    project: str = TEST_PROJECT, client_id: str = TEST_CLIENT_ID, secret: str = TEST_SECRET, kind: str = "installed"
) -> str:
    """Файл клиента — как его скачивает Google Cloud Console; `kind` — раздел вида клиента (Desktop — installed)."""
    return json.dumps({kind: {
        "client_id": client_id, "project_id": project, "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": TOKEN_URI, "client_secret": secret, "redirect_uris": ["http://localhost"],
    }})


def project_file(paths: LivecraftPaths, project: str = TEST_PROJECT) -> Path:
    """Файл проекта Google в secrets: google_project_<project>.json — так его кладёт загрузка токена."""
    return paths.received_project_file(project)


def choose_project(paths: LivecraftPaths, path: Path) -> LivecraftPaths:
    """Проект Google выбран, как в окне: путь к файлу `path` — в livecraft.json (нет файла — поставочный с этим путём);
    пути — с файлом проекта из настроек."""
    SettingsFile.of(paths).save_google(GoogleSettings(project_file=paths.shown(path)))
    return SettingsFile.placed(paths)


def login_text(client_id: str, refresh: str = "1//refresh") -> str:
    """Файл входа Google — как его пишет Credentials.to_json: в нём клиент, через который вошли."""
    return json.dumps({"token": "ya29.access", "refresh_token": refresh, "client_id": client_id, "client_secret": "s"})


class FakeTokenResponse:
    """Ответ выдачи токенов: код и тело JSON (None — тело не JSON)."""

    def __init__(self, status_code: int, payload: object = None) -> None:
        self.status_code: int = status_code
        self.payload: object = payload

    def json(self) -> object:
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


KNOWN: FakeTokenResponse = FakeTokenResponse(400, {"error": "invalid_grant", "error_description": "Bad Request"})
NOT_KNOWN: FakeTokenResponse = FakeTokenResponse(401, {"error": "invalid_client", "error_description": "not found"})


@dataclass
class FakeTokenEndpoint:
    """Подделка `requests.post` к выдаче токенов: ответы по очереди (последний — на все следующие), исключение в
    очереди — сбой связи. Адреса, тела запросов и паузы повторов записываются."""

    answers: list[FakeTokenResponse | Exception] = field(default_factory=lambda: [KNOWN])
    urls: list[str] = field(default_factory=list)
    forms: list[dict[str, str]] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)

    @classmethod
    def offline(cls) -> FakeTokenEndpoint:
        """Компьютер не находит серверы Google: каждое обращение обрывается."""
        return cls(answers=[requests.ConnectionError("Name or service not known")])

    def __call__(self, url: str, data: dict[str, str], **options: object) -> FakeTokenResponse:
        self.urls.append(url)
        self.forms.append(data)
        answer: FakeTokenResponse | Exception = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def probe(self) -> ClientProbe:
        return ClientProbe(post=self, sleep=self.sleeps.append)
