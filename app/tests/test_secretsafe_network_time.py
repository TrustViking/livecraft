from __future__ import annotations

from datetime import datetime

import pytest
import requests

from app.secretsafe.network_time import TIME_URL, NetworkTime
from app.tests.fixtures.token import NETWORK_NOW, FakeHead


def test_the_time_is_the_date_header_of_the_google_answer() -> None:
    head: FakeHead = FakeHead(NETWORK_NOW)
    moment: datetime | None = NetworkTime(head=head).now()
    assert moment == NETWORK_NOW
    assert head.urls == [TIME_URL] and TIME_URL.startswith("https://www.google.com/")


def test_no_network_gives_no_time_and_a_log_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="livecraft"):
        moment: datetime | None = NetworkTime(head=FakeHead(None, requests.ConnectionError("down"))).now()
    assert moment is None
    assert "network_time_failed problem=no_answer detail=ConnectionError" in [r.getMessage() for r in caplog.records]


@pytest.mark.parametrize("headers", [{}, {"Date": "не дата"}])
def test_an_answer_without_a_date_gives_no_time(headers: dict[str, str]) -> None:
    assert NetworkTime(head=FakeHead(None, headers=headers)).now() is None
