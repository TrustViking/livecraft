"""Время сети для токена доступа: заголовок Date ответа сервера Google по HTTPS (CLAUDE.md §7.3, §14 решение 16).

Срок токена не должен зависеть от часов компьютера, на которых его создают или загружают: их переводит любой. Поэтому
момент создания и момент загрузки — время из ответа Google, а не «сейчас» программы. Нет сети или в ответе нет даты —
`now` отдаёт None: токен тогда не создаётся и не загружается, причину называет тот, кто спрашивал. Строка лога — без
адресов и значений: имя ошибки.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Final

import requests

from app.observability.log_event import LogArea, LogEvent, get_logger

LOGGER = get_logger(LogArea.VAULT)

TIME_URL: Final[str] = "https://www.google.com/generate_204"
TIME_REQUEST_TIMEOUT_SEC: Final[int] = 15
DATE_HEADER: Final[str] = "Date"


class NetworkTimeEvent(str, Enum):
    """События времени сети в логе."""

    READ = "network_time_read"
    FAILED = "network_time_failed"


class NetworkTimeProblem(str, Enum):
    """Почему время сети не получено. Значение — английский идентификатор для лога."""

    NO_ANSWER = "no_answer"      # запрос не дошёл: нет сети, обрыв, таймаут
    NO_DATE = "no_date"          # ответ без заголовка Date или с датой, которая не разбирается


@dataclass(frozen=True)
class NetworkTime:
    """Время по ответу Google. `head` — `requests.head` или подделка в тестах."""

    head: Callable[..., requests.Response] = requests.head

    def now(self) -> datetime | None:
        """Момент по заголовку Date (UTC); сети нет или даты нет — None, строка лога с причиной."""
        try:
            response: requests.Response = self.head(TIME_URL, timeout=TIME_REQUEST_TIMEOUT_SEC)
        except requests.RequestException as error:
            return self._failed(NetworkTimeProblem.NO_ANSWER, type(error).__name__)
        header: str | None = response.headers.get(DATE_HEADER)
        if header is None:
            return self._failed(NetworkTimeProblem.NO_DATE, DATE_HEADER)
        try:
            moment: datetime = parsedate_to_datetime(header)
        except (TypeError, ValueError) as error:
            return self._failed(NetworkTimeProblem.NO_DATE, type(error).__name__)
        LogEvent.of(NetworkTimeEvent.READ, moment=moment.isoformat()).emit(LOGGER)
        return moment

    def _failed(self, problem: NetworkTimeProblem, detail: str) -> None:
        LogEvent.of(NetworkTimeEvent.FAILED, problem=problem, detail=detail).emit(LOGGER, logging.WARNING)
        return None
