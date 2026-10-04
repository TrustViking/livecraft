"""Время сети в тестах токена доступа: подделка `requests.head` с заголовком Date, отказ сети и выбор файла в окне."""
from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

import requests

from app.secretsafe.network_time import NetworkTime

# Момент ответа Google в тестах: 29.09.2026 12:00 UTC (15:00 по Киеву).
NETWORK_NOW: datetime = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class FakeTimeResponse:
    """Ответ сервера: только заголовки."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers: dict[str, str] = headers


class FakeHead:
    """Подделка `requests.head`: отвечает датой `moment`, отказывает исключением `error`; адреса — в `urls`."""

    def __init__(self, moment: datetime | None, error: Exception | None = None, headers: dict[str, str] | None = None) -> None:
        self.moment: datetime | None = moment
        self.error: Exception | None = error
        self.headers: dict[str, str] | None = headers
        self.urls: list[str] = []

    def __call__(self, url: str, **options: object) -> FakeTimeResponse:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        if self.headers is not None:
            return FakeTimeResponse(self.headers)
        assert self.moment is not None
        return FakeTimeResponse({"Date": format_datetime(self.moment.astimezone(UTC), usegmt=True)})


def network_at(moment: datetime = NETWORK_NOW) -> NetworkTime:
    """Сеть есть, Google отвечает этим моментом."""
    return NetworkTime(head=FakeHead(moment))


def network_down() -> NetworkTime:
    """Сети нет: запрос обрывается."""
    return NetworkTime(head=FakeHead(None, requests.ConnectionError("no route to host")))


class FakePicker:
    """Выбор файла на вкладке «Токены» без диалога: None — человек закрыл диалог."""

    def __init__(self, token: Path | None) -> None:
        self.chosen_token: Path | None = token

    def token(self) -> Path | None:
        return self.chosen_token
