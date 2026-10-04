"""Данные источника через tools\\yt-dlp.exe (CLAUDE.md §2 контур A, §3 шаг 2.4).

Команда: `--dump-single-json --no-warnings --skip-download --no-playlist`, cookies — копией на один вызов,
`--js-runtimes deno:<путь>`, если рядом лежит deno.exe; кэш yt-dlp и deno и копия cookies — в папке программы
(`YtDlpLaunch`, §14 решение 56). Причина отказа называется по подстрокам stderr (`YtDlpRefusalMarkers`, ресурсы
`ytdlp_*_markers.txt`).

stderr целиком пишется только в DEBUG; в итог и в строки INFO/WARNING идёт первая строка, обрезанная.
Повтор — только после таймаута: один, сразу, с таймаутом вдвое (`TimeoutLadder`): на нагруженной машине первый вызов
запуска не укладывается в 30 с, а следующий идёт за секунды (прогоны 30-09-2026 теряли по таймауту до 10 видео из 15).
Прочие отказы не повторяются: yt-dlp повторяет сетевые сбои сам, а отказ по одному источнику не останавливает остальные.
"""
from __future__ import annotations

import json
import logging
import random
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final

from app.core.errors import DETAIL_MAX_CHARS
from app.core.retry import AttemptFailure, RetryLoop, RetryPolicy, RetryRun
from app.core.text_format import SPACE, TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import FileName, LivecraftPaths
from app.resources.loader import TextResource
from app.runtime.ytdlp_launch import YtDlpLaunch
from app.sources.fetcher import SourceFetch
from app.sources.metadata import SourceFailureReason, SourceMetadata

LOGGER = get_logger(LogArea.SOURCES_YTDLP)

YTDLP_TIMEOUT_SEC: Final[float] = 30.0
YTDLP_BASE_ARGS: Final[tuple[str, ...]] = (
    "--dump-single-json",
    "--no-warnings",
    "--skip-download",
    "--no-playlist",
)
COOKIES_ARG: Final[str] = "--cookies"
JS_RUNTIMES_ARG: Final[str] = "--js-runtimes"
DENO_RUNTIME_TEMPLATE: Final[str] = "deno:{path}"
OUTPUT_ERRORS: Final[str] = "replace"
# Подстроки stderr yt-dlp, по которым называется причина отказа, — ресурсы.
PRIVATE_MARKERS_RESOURCE: Final[str] = "ytdlp_private_markers.txt"
UNAVAILABLE_MARKERS_RESOURCE: Final[str] = "ytdlp_unavailable_markers.txt"
EXIT_CODE_DETAIL_TEMPLATE: Final[str] = "exit_code={code}"
TIMEOUT_DETAIL_TEMPLATE: Final[str] = "timeout_sec={seconds:.0f}"
TIMEOUT_GROWTH: Final[int] = 2      # попытка после таймаута ждёт вдвое дольше прежней
# После таймаута — ещё одна попытка, сразу: машина была занята, а не видео недоступно.
TIMEOUT_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(max_retries=1, base_delay_sec=0.0, jitter_max_sec=0.0)


class YtDlpEvent(str, Enum):
    """События вызова yt-dlp в логе."""

    MISSING = "ytdlp_missing"
    COMMAND = "ytdlp_command"
    TIMEOUT = "ytdlp_timeout"
    TIMEOUT_RETRY = "ytdlp_timeout_retry"
    START_FAILED = "ytdlp_start_failed"
    STDERR = "ytdlp_stderr"
    REFUSED = "ytdlp_refused"
    BAD_OUTPUT = "ytdlp_bad_output"


def first_line(text: str, limit: int = DETAIL_MAX_CHARS) -> str:
    """Первая непустая строка текста, обрезанная до `limit` символов; пусто — пустая строка."""
    for line in text.splitlines():
        stripped: str = line.strip()
        if stripped:
            return stripped[:limit]
    return ""


@dataclass(frozen=True)
class YtDlpRefusalMarkers:
    """Подстроки stderr, по которым отказ yt-dlp получает свою причину; прочий отказ — FAILED."""

    private: tuple[str, ...]
    unavailable: tuple[str, ...]

    @classmethod
    def load(cls) -> YtDlpRefusalMarkers:
        return cls(
            private=TextResource(PRIVATE_MARKERS_RESOURCE).lines,
            unavailable=TextResource(UNAVAILABLE_MARKERS_RESOURCE).lines,
        )

    def reason(self, stderr: str) -> SourceFailureReason:
        """Причина по stderr: сначала «приватное», затем «недоступно», иначе прочий отказ."""
        if any(marker in stderr for marker in self.private):
            return SourceFailureReason.PRIVATE
        if any(marker in stderr for marker in self.unavailable):
            return SourceFailureReason.UNAVAILABLE
        return SourceFailureReason.FAILED


@dataclass(frozen=True)
class YtDlpResult:
    """Что вернул один вызов yt-dlp: код, stdout, stderr — и что это значит для источника."""

    returncode: int
    stdout: str
    stderr: str

    @classmethod
    def from_completed(cls, completed: subprocess.CompletedProcess[str]) -> YtDlpResult:
        return cls(returncode=completed.returncode, stdout=completed.stdout or "", stderr=completed.stderr or "")

    @property
    def refusal(self) -> SourceFailureReason | None:
        """Причина по stderr, если yt-dlp завершился с ошибкой; код 0 — None."""
        if self.returncode == 0:
            return None
        return YtDlpRefusalMarkers.load().reason(self.stderr)

    @property
    def detail(self) -> str:
        """Подробность для лога и итога: первая строка stderr или код выхода."""
        return first_line(self.stderr) or EXIT_CODE_DETAIL_TEMPLATE.format(code=self.returncode)

    def info(self) -> dict[str, Any] | None:
        """Объект JSON из stdout; не JSON или не объект — None."""
        try:
            parsed: Any = json.loads(self.stdout)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None


@dataclass
class TimeoutLadder:
    """Таймауты попыток одного видео: первая — базовый, каждая следующая — вдвое дольше прежней; `attempts` — сколько
    попыток начато."""

    base_sec: float
    attempts: int = 0

    @property
    def upcoming_sec(self) -> float:
        """Таймаут следующей попытки."""
        return self.base_sec * TIMEOUT_GROWTH ** self.attempts

    @property
    def last_sec(self) -> float:
        """Таймаут последней начатой попытки."""
        return self.base_sec * TIMEOUT_GROWTH ** (self.attempts - 1)

    def take(self) -> float:
        """Начать попытку: её таймаут."""
        seconds: float = self.upcoming_sec
        self.attempts += 1
        return seconds


@dataclass(frozen=True)
class YtDlpFetcher:
    """Получатель данных источника через yt-dlp.exe; реализует `MetadataFetcher`.

    `launch` — exe, cookies и папки кэша; `run` — `subprocess.run` или подделка с той же сигнатурой (в тестах);
    `policy`, `rng`, `sleep` — повтор после таймаута (§11).
    """

    launch: YtDlpLaunch
    deno_exe: Path
    timeout_sec: float = YTDLP_TIMEOUT_SEC
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    policy: RetryPolicy = TIMEOUT_RETRY_POLICY
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> YtDlpFetcher:
        return cls(launch=YtDlpLaunch.of(paths), deno_exe=paths.file(FileName.DENO))

    def fetch(self, url: str) -> SourceFetch:
        """Данные видео по ссылке; любой отказ — итогом с причиной."""
        exe: Path = self.launch.exe
        if not exe.is_file():
            LogEvent.of(YtDlpEvent.MISSING, path=exe).emit(LOGGER, logging.ERROR)
            return SourceFetch.failed(url, SourceFailureReason.TOOL_MISSING, exe.name)
        outcome: YtDlpResult | SourceFetch = self._call(url)
        if isinstance(outcome, SourceFetch):
            return outcome
        return self._interpret(url, outcome)

    def command(self, url: str, cookies_copy: Path | None) -> list[str]:
        """Команда вызова (`YtDlpLaunch.command`): базовые ключи, cookies-копия и deno — если есть, ссылка последней."""
        args: list[str] = [*YTDLP_BASE_ARGS]
        if cookies_copy is not None:
            args += [COOKIES_ARG, str(cookies_copy)]
        if self.deno_exe.is_file():
            args += [JS_RUNTIMES_ARG, DENO_RUNTIME_TEMPLATE.format(path=self.deno_exe)]
        args.append(url)
        return self.launch.command(args)

    def _call(self, url: str) -> YtDlpResult | SourceFetch:
        """Вызов yt-dlp; таймаут — ещё одна попытка сразу, с таймаутом вдвое; второй таймаут — итог-отказ TIMEOUT."""
        timeouts: TimeoutLadder = TimeoutLadder(self.timeout_sec)
        loop: RetryLoop = RetryLoop(self.policy, self.rng, self.sleep)
        run: RetryRun[YtDlpResult | SourceFetch] = loop.run(
            lambda: self._attempt(url, timeouts.take()), lambda _step: self._note_retry(url, timeouts)
        )
        if run.value is None:
            detail: str = TIMEOUT_DETAIL_TEMPLATE.format(seconds=timeouts.last_sec)
            return SourceFetch.failed(url, SourceFailureReason.TIMEOUT, detail)
        return run.value

    def _note_retry(self, url: str, timeouts: TimeoutLadder) -> None:
        LogEvent.of(YtDlpEvent.TIMEOUT_RETRY, url=url, timeout_sec=timeouts.upcoming_sec).emit(LOGGER, logging.WARNING)

    def _attempt(self, url: str, timeout_sec: float) -> YtDlpResult | SourceFetch | AttemptFailure:
        """Один вызов yt-dlp с копией cookies; таймаут — повторяемая неудача, незапускаемый exe — итог-отказ."""
        with self.launch.cookies_copy() as cookies_copy:
            command: list[str] = self.command(url, cookies_copy)
            LogEvent.of(YtDlpEvent.COMMAND, command=SPACE.join(command)).emit(LOGGER, logging.DEBUG)
            try:
                completed: subprocess.CompletedProcess[str] = self.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout_sec,
                    encoding=TEXT_ENCODING,
                    errors=OUTPUT_ERRORS,
                    env=self.launch.env,
                )
            except subprocess.TimeoutExpired:
                detail: str = TIMEOUT_DETAIL_TEMPLATE.format(seconds=timeout_sec)
                LogEvent.of(YtDlpEvent.TIMEOUT, url=url, detail=detail).emit(LOGGER, logging.WARNING)
                return AttemptFailure(SourceFailureReason.TIMEOUT, is_retryable=True)
            except OSError as error:
                LogEvent.of(YtDlpEvent.START_FAILED, url=url, error=type(error).__name__).emit(LOGGER, logging.ERROR)
                return SourceFetch.failed(url, SourceFailureReason.FAILED, type(error).__name__)
        return YtDlpResult.from_completed(completed)

    def _interpret(self, url: str, result: YtDlpResult) -> SourceFetch:
        """Ответ yt-dlp → итог: отказ по stderr, неразборчивый stdout или объект метаданных."""
        if result.stderr:
            stderr: LogEvent = LogEvent.of(YtDlpEvent.STDERR, url=url, exit_code=result.returncode)
            stderr.extended(stderr=repr(result.stderr)).emit(LOGGER, logging.DEBUG)   # одной строкой лога
        refusal: SourceFailureReason | None = result.refusal
        if refusal is not None:
            LogEvent.of(YtDlpEvent.REFUSED, url=url, reason=refusal, detail=result.detail).emit(LOGGER, logging.WARNING)
            return SourceFetch.failed(url, refusal, result.detail)
        info: dict[str, Any] | None = result.info()
        if info is None:
            bad: LogEvent = LogEvent.of(YtDlpEvent.BAD_OUTPUT, url=url, stdout_chars=len(result.stdout))
            bad.emit(LOGGER, logging.WARNING)
            return SourceFetch.failed(url, SourceFailureReason.BAD_OUTPUT, first_line(result.stdout))
        return SourceFetch.from_metadata(url, SourceMetadata.from_ytdlp(url, info))
