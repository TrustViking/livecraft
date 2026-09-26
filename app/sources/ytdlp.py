"""Данные источника через tools\\yt-dlp.exe (CLAUDE.md §2 контур A, §3 шаг 2.4).

Команда: `--dump-single-json --no-warnings --skip-download --no-playlist`, cookies — временной копией (yt-dlp
пишет свой cookie jar обратно в файл `--cookies`, а оригинал трогать нельзя: время его записи — дата экспорта
cookies), `--js-runtimes deno:<путь>`, если рядом лежит deno.exe. Причина отказа называется по подстрокам stderr
(`YtDlpRefusalMarkers`, ресурсы `ytdlp_*_markers.txt`).

stderr целиком пишется только в DEBUG; в итог и в строки INFO/WARNING идёт первая строка, обрезанная.
Повторов нет: yt-dlp повторяет сетевые сбои сам, а отказ по одному источнику не останавливает остальные.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from app.core.errors import DETAIL_MAX_CHARS
from app.core.text_format import SPACE, TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths
from app.resources.loader import TextResource
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
COOKIES_COPY_PREFIX: Final[str] = "livecraft_cookies_"
COOKIES_COPY_SUFFIX: Final[str] = ".txt"
# Подстроки stderr yt-dlp, по которым называется причина отказа, — ресурсы.
PRIVATE_MARKERS_RESOURCE: Final[str] = "ytdlp_private_markers.txt"
UNAVAILABLE_MARKERS_RESOURCE: Final[str] = "ytdlp_unavailable_markers.txt"
EXIT_CODE_DETAIL_TEMPLATE: Final[str] = "exit_code={code}"
TIMEOUT_DETAIL_TEMPLATE: Final[str] = "timeout_sec={seconds:.0f}"


class YtDlpEvent(str, Enum):
    """События вызова yt-dlp в логе."""

    MISSING = "ytdlp_missing"
    COMMAND = "ytdlp_command"
    TIMEOUT = "ytdlp_timeout"
    START_FAILED = "ytdlp_start_failed"
    STDERR = "ytdlp_stderr"
    REFUSED = "ytdlp_refused"
    BAD_OUTPUT = "ytdlp_bad_output"
    COOKIES_COPY_FAILED = "ytdlp_cookies_copy_failed"


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


@dataclass(frozen=True)
class YtDlpFetcher:
    """Получатель данных источника через yt-dlp.exe; реализует `MetadataFetcher`.

    `run` — `subprocess.run` или подделка с той же сигнатурой (в тестах).
    """

    ytdlp_exe: Path
    deno_exe: Path
    cookies_file: Path
    timeout_sec: float = YTDLP_TIMEOUT_SEC
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> YtDlpFetcher:
        return cls(ytdlp_exe=paths.ytdlp_exe, deno_exe=paths.deno_exe, cookies_file=paths.cookies_file)

    def fetch(self, url: str) -> SourceFetch:
        """Данные видео по ссылке; любой отказ — итогом с причиной."""
        if not self.ytdlp_exe.is_file():
            LogEvent.of(YtDlpEvent.MISSING, path=self.ytdlp_exe).emit(LOGGER, logging.ERROR)
            return SourceFetch.failed(url, SourceFailureReason.TOOL_MISSING, self.ytdlp_exe.name)
        outcome: YtDlpResult | SourceFetch = self._call(url)
        if isinstance(outcome, SourceFetch):
            return outcome
        return self._interpret(url, outcome)

    def command(self, url: str, cookies_copy: Path | None) -> list[str]:
        """Команда вызова: базовые ключи, cookies-копия и deno — если есть, ссылка последней."""
        command: list[str] = [str(self.ytdlp_exe), *YTDLP_BASE_ARGS]
        if cookies_copy is not None:
            command += [COOKIES_ARG, str(cookies_copy)]
        if self.deno_exe.is_file():
            command += [JS_RUNTIMES_ARG, DENO_RUNTIME_TEMPLATE.format(path=self.deno_exe)]
        command.append(url)
        return command

    def _call(self, url: str) -> YtDlpResult | SourceFetch:
        """Один вызов yt-dlp с копией cookies; таймаут и незапускаемый exe — итогом-отказом."""
        with self._cookies_copy() as cookies_copy:
            command: list[str] = self.command(url, cookies_copy)
            LogEvent.of(YtDlpEvent.COMMAND, command=SPACE.join(command)).emit(LOGGER, logging.DEBUG)
            try:
                completed: subprocess.CompletedProcess[str] = self.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.timeout_sec,
                    encoding=TEXT_ENCODING,
                    errors=OUTPUT_ERRORS,
                )
            except subprocess.TimeoutExpired:
                detail: str = TIMEOUT_DETAIL_TEMPLATE.format(seconds=self.timeout_sec)
                LogEvent.of(YtDlpEvent.TIMEOUT, url=url, detail=detail).emit(LOGGER, logging.WARNING)
                return SourceFetch.failed(url, SourceFailureReason.TIMEOUT, detail)
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

    @contextmanager
    def _cookies_copy(self) -> Iterator[Path | None]:
        """Временная копия cookies на один вызов; удаляется при любом исходе. Нет cookies — None.

        Копия не сделалась (нет места, файл не читается) — вызов идёт без cookies, причина — в лог.
        """
        copy_path: Path | None = self._make_cookies_copy() if self.cookies_file.is_file() else None
        try:
            yield copy_path
        finally:
            if copy_path is not None:
                copy_path.unlink(missing_ok=True)

    def _make_cookies_copy(self) -> Path | None:
        """Копия cookies во временной папке пользователя; не вышло — None, недоделанная копия удалена."""
        copy_path: Path | None = None
        try:
            handle, temp_name = tempfile.mkstemp(prefix=COOKIES_COPY_PREFIX, suffix=COOKIES_COPY_SUFFIX)
            os.close(handle)
            copy_path = Path(temp_name)
            shutil.copyfile(self.cookies_file, copy_path)
        except OSError as error:
            LogEvent.of(YtDlpEvent.COOKIES_COPY_FAILED, error=type(error).__name__).emit(LOGGER, logging.WARNING)
            if copy_path is not None:
                copy_path.unlink(missing_ok=True)
            return None
        return copy_path
