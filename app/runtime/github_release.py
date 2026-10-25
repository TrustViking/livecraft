"""Выпуски внешних бинарников на GitHub: номер последнего выпуска и сам файл выпуска (CLAUDE.md §13 задача 9.27).

Номер — ответ API GitHub о последнем выпуске; файл — читается потоком кусками по `DOWNLOAD_CHUNK_BYTES`: файл yt-dlp —
около 18 МБ, архив deno — больше, на медленной связи это минуты, и без строк хода человек решает, что программа
зависла. По ходу чтения `DownloadWatch` говорит строку начала (с размером, если GitHub его назвал) и строку на каждой
четверти файла (25, 50, 75 %). Сеть — requests с повторами `RetryLoop` (§11) на обрыве, таймауте, 429 и 5xx; обрыв
посреди файла — та же повторяемая неудача, что обрыв до ответа: попытка читает файл заново, и счёт хода начинается
заново. Отказ — причина `ToolProblem` (app\\runtime\\deno_updater.py ставит выпуск на место рабочего бинарника).
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, TypeVar

import requests

from app.core.retry import (
    RETRYABLE_ERRORS,
    RETRYABLE_HTTP_STATUSES,
    AttemptFailure,
    RetryLoop,
    RetryPolicy,
    RetryRun,
    RetryStep,
)
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.runtime.log_archive import BYTES_PER_MEGABYTE
from app.ui.messages import msg
from app.version import APP_NAME

LOGGER = get_logger(LogArea.RUNTIME)

DOWNLOAD_TIMEOUT_SEC: Final[float] = 60.0
DOWNLOAD_CHUNK_BYTES: Final[int] = 1 << 16      # кусок чтения файла выпуска
DOWNLOAD_STEPS: Final[int] = 4                  # строка хода на каждой четверти файла: 25, 50, 75 %
VERSION_PREFIXES: Final[str] = "vV"             # тег выпуска «v2.9.6» — номер без буквы
# Обрыв посреди файла: requests отдаёт его из iter_content как ChunkedEncodingError или ConnectionError.
STREAM_ERRORS: Final[tuple[type[Exception], ...]] = (*RETRYABLE_ERRORS, requests.exceptions.ChunkedEncodingError)

T = TypeVar("T")


class ToolProblem(str, Enum):
    """Почему проверка бинарника не состоялась. Значение — ключ `msg.TOOL_PROBLEMS`."""

    NO_ANSWER = "no_answer"                  # нет сети, обрыв, таймаут; 429 и 5xx — и после повторов
    REFUSED = "refused"                      # прочий отказ GitHub
    NO_VERSION = "no_version"                # ответ GitHub без номера последней версии
    BROKEN_DOWNLOAD = "broken_download"      # скачанное — не архив, или файл из него не назвал ожидаемую версию
    NOT_WRITTEN = "not_written"              # новый файл не встал на место рабочего: сбой диска, файл занят
    SELF_UPDATE_FAILED = "self_update_failed"    # yt-dlp -U не справился: код не 0, таймаут, не запустился

    @property
    def human(self) -> str:
        return msg.TOOL_PROBLEMS[self.value]


class ReleaseEvent(str, Enum):
    """События обращений к GitHub в логе."""

    REQUEST_RETRY = "tool_request_retry"
    REQUEST_FAILED = "tool_request_failed"


class ReleaseKey(str, Enum):
    """Поля ответа GitHub о выпуске и заголовки запроса и ответа."""

    TAG = "tag_name"
    USER_AGENT = "User-Agent"          # без него API GitHub отказывает
    CONTENT_LENGTH = "Content-Length"  # размер файла выпуска; нет — размер не известен


GITHUB_HEADERS: Final[dict[str, str]] = {ReleaseKey.USER_AGENT.value: APP_NAME}


@dataclass
class DownloadMeter:
    """Ход одной попытки загрузки: размер файла (None — не известен), сколько прочитано и сколько четвертей уже
    названо. Строку говорит, только когда прочитанное дошло до новой четверти, а файл ещё не прочитан весь: конец
    файла называет итог обновления."""

    watch: DownloadWatch
    size: int | None
    done: int = 0
    told: int = 0

    def add(self, count: int) -> None:
        """Прочитано ещё `count` байт."""
        self.done += count
        if self.size is None or self.done >= self.size:
            return
        reached: int = self.done * DOWNLOAD_STEPS // self.size
        if reached > self.told:
            self.told = reached
            self.watch.say(msg.PROGRESS_TOOL_DOWNLOAD_PART.format(
                tool=self.watch.tool, done=self.watch.megabytes(self.done), size=self.watch.megabytes(self.size),
            ))


@dataclass(frozen=True)
class DownloadWatch:
    """Кто скачивается и куда говорить ход: имя бинарника, версия выпуска и строка на консоль (`say`)."""

    tool: str
    version: str
    say: Callable[[str], None]

    def start(self, size: int | None) -> DownloadMeter:
        """Начало попытки: строка с размером (или без, если он не известен) и новый счёт хода."""
        if size is None:
            self.say(msg.PROGRESS_TOOL_DOWNLOAD_NO_SIZE.format(tool=self.tool, version=self.version))
        else:
            self.say(msg.PROGRESS_TOOL_DOWNLOAD.format(tool=self.tool, version=self.version, size=self.megabytes(size)))
        return DownloadMeter(self, size)

    def megabytes(self, count: int) -> int:
        """Байты — в целых МБ для людей."""
        return round(count / BYTES_PER_MEGABYTE)


@dataclass(frozen=True)
class GitHubRelease:
    """Обращения к GitHub: номер последнего выпуска и байты файла выпуска. `get` — `requests.get` или подделка;
    `policy`, `rng`, `sleep` — повторы (§11)."""

    get: Callable[..., requests.Response] = requests.get
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    def latest_version(self, url: str) -> str | ToolProblem:
        """Номер последнего выпуска без буквы «v»; ответа нет или в нём нет номера — причина."""
        answer: requests.Response | ToolProblem = self._answer(url, lambda: self._attempt(url))
        if isinstance(answer, ToolProblem):
            return answer
        try:
            payload: object = answer.json()
        except ValueError:
            return ToolProblem.NO_VERSION
        tag: object = payload.get(ReleaseKey.TAG.value) if isinstance(payload, dict) else None
        version: str = tag.strip().lstrip(VERSION_PREFIXES) if isinstance(tag, str) else ""
        return version or ToolProblem.NO_VERSION

    def download(self, url: str, watch: DownloadWatch) -> bytes | ToolProblem:
        """Байты файла выпуска или причина; ход чтения — наблюдателю `watch`."""
        return self._answer(url, lambda: self._read(url, watch))

    def _answer(self, url: str, attempt: Callable[[], T | AttemptFailure]) -> T | ToolProblem:
        """Итог обращения после повторов или причина отказа; отказ — строкой лога с кодом ответа и числом попыток."""
        loop: RetryLoop = RetryLoop(self.policy, self.rng, self.sleep)
        run: RetryRun[T] = loop.run(attempt, lambda step: self._note_retry(url, step))
        if run.failure is None:
            return run.value
        problem: ToolProblem = ToolProblem(run.failure.reason)
        failed: LogEvent = LogEvent.of(ReleaseEvent.REQUEST_FAILED, url=url, problem=problem, **run.failure.log_fields)
        failed.extended(attempts=run.attempts).emit(LOGGER, logging.WARNING)
        return problem

    def _read(self, url: str, watch: DownloadWatch) -> bytes | AttemptFailure:
        """Одна попытка загрузки: ответ потоком, файл кусками; обрыв посреди файла — повторяемая неудача."""
        answer: requests.Response | AttemptFailure = self._attempt(url, is_stream=True)
        if isinstance(answer, AttemptFailure):
            return answer
        size_text: str = answer.headers.get(ReleaseKey.CONTENT_LENGTH.value, "")
        meter: DownloadMeter = watch.start(int(size_text) if size_text.isdigit() else None)
        body: bytearray = bytearray()
        try:
            for chunk in answer.iter_content(DOWNLOAD_CHUNK_BYTES):
                body += chunk
                meter.add(len(chunk))
        except STREAM_ERRORS as error:
            return self._failure(True, error_name=type(error).__name__, cause=error)
        return bytes(body)

    def _attempt(self, url: str, is_stream: bool = False) -> requests.Response | AttemptFailure:
        """Одно обращение: ответ 2xx или неудача; 429, 5xx, обрыв и таймаут — повторяемые."""
        try:
            answer: requests.Response = self.get(
                url, headers=GITHUB_HEADERS, timeout=DOWNLOAD_TIMEOUT_SEC, stream=is_stream
            )
        except requests.RequestException as error:
            return self._failure(isinstance(error, RETRYABLE_ERRORS), error_name=type(error).__name__, cause=error)
        if answer.ok:
            return answer
        return self._failure(answer.status_code in RETRYABLE_HTTP_STATUSES, status=answer.status_code)

    def _failure(self, is_retryable: bool, **details: object) -> AttemptFailure:
        """Повторяемая неудача — GitHub не ответил; прочая — отказал."""
        reason: ToolProblem = ToolProblem.NO_ANSWER if is_retryable else ToolProblem.REFUSED
        return AttemptFailure(reason, is_retryable, **details)

    def _note_retry(self, url: str, step: RetryStep) -> None:
        retry: LogEvent = LogEvent.of(ReleaseEvent.REQUEST_RETRY, url=url, **step.failure.log_fields)
        retry.extended(retry=step.retry, delay_sec=round(step.delay_sec, 1)).emit(LOGGER, logging.WARNING)
