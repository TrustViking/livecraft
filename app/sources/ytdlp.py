"""Данные источника через tools\\yt-dlp.exe (CLAUDE.md §2 контур A: `ingest\\youtube_metadata.py`).

Команда и правила — донора `YtDlpYouTubeMetadataFetcher.fetch` (restreamer): `--dump-single-json
--no-warnings --skip-download --no-playlist`, cookies — временной копией (yt-dlp пишет свой cookie jar
обратно в файл `--cookies`, а оригинал трогать нельзя: время его записи — дата экспорта cookies),
`--js-runtimes deno:<путь>`, если рядом лежит deno.exe. Классификация отказа по stderr — правило донора
`batch_planner._classify_shared_preparation_error`.

stderr целиком пишется только в DEBUG; в итог и в строки INFO/WARNING идёт первая строка, обрезанная.
Повторов нет: yt-dlp повторяет сетевые сбои сам, а отказ по одному источнику не останавливает остальные.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.observability.logging_setup import get_logger
from app.paths import LivecraftPaths
from app.sources.fetcher import SourceFailureReason, SourceFetch
from app.sources.metadata import SourceMetadata

LOGGER_NAME: Final[str] = "sources.ytdlp"
LOGGER = get_logger(LOGGER_NAME)

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
OUTPUT_ENCODING: Final[str] = "utf-8"
OUTPUT_ERRORS: Final[str] = "replace"
COOKIES_COPY_PREFIX: Final[str] = "livecraft_cookies_"
COOKIES_COPY_SUFFIX: Final[str] = ".txt"
DETAIL_MAX_CHARS: Final[int] = 200
# Подстроки stderr yt-dlp, по которым донор называл причину отказа.
PRIVATE_MARKERS: Final[tuple[str, ...]] = ("Private video", "Sign in to confirm", "Sign in if you")
UNAVAILABLE_MARKERS: Final[tuple[str, ...]] = ("Video unavailable", "removed by the uploader")


def first_line(text: str, limit: int = DETAIL_MAX_CHARS) -> str:
    """Первая непустая строка текста, обрезанная до `limit` символов; пусто — пустая строка."""
    for line in text.splitlines():
        stripped: str = line.strip()
        if stripped:
            return stripped[:limit]
    return ""


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
        if any(marker in self.stderr for marker in PRIVATE_MARKERS):
            return SourceFailureReason.PRIVATE
        if any(marker in self.stderr for marker in UNAVAILABLE_MARKERS):
            return SourceFailureReason.UNAVAILABLE
        return SourceFailureReason.FAILED

    @property
    def detail(self) -> str:
        """Подробность для лога и итога: первая строка stderr или код выхода."""
        return first_line(self.stderr) or f"exit_code={self.returncode}"

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
            LOGGER.error("ytdlp_missing path=%s", self.ytdlp_exe)
            return SourceFetch.failed(url, SourceFailureReason.TOOL_MISSING, self.ytdlp_exe.name)
        outcome: YtDlpResult | SourceFetch = self._call(url)
        if isinstance(outcome, SourceFetch):
            return outcome
        return self._interpret(url, outcome)

    def command(self, url: str, cookies_copy: Path | None) -> list[str]:
        """Команда вызова: базовые ключи донора, cookies-копия и deno — если есть, ссылка последней."""
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
            LOGGER.debug("ytdlp_command %s", " ".join(command))
            try:
                completed: subprocess.CompletedProcess[str] = self.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.timeout_sec,
                    encoding=OUTPUT_ENCODING,
                    errors=OUTPUT_ERRORS,
                )
            except subprocess.TimeoutExpired:
                LOGGER.warning("ytdlp_timeout url=%s timeout_sec=%.0f", url, self.timeout_sec)
                return SourceFetch.failed(url, SourceFailureReason.TIMEOUT, f"timeout_sec={self.timeout_sec:.0f}")
            except OSError as error:
                LOGGER.error("ytdlp_start_failed url=%s error=%s", url, type(error).__name__)
                return SourceFetch.failed(url, SourceFailureReason.FAILED, type(error).__name__)
        return YtDlpResult.from_completed(completed)

    def _interpret(self, url: str, result: YtDlpResult) -> SourceFetch:
        """Ответ yt-dlp → итог: отказ по stderr, неразборчивый stdout или объект метаданных."""
        if result.stderr:
            LOGGER.debug("ytdlp_stderr url=%s exit_code=%d stderr=%r", url, result.returncode, result.stderr)
        refusal: SourceFailureReason | None = result.refusal
        if refusal is not None:
            LOGGER.warning("ytdlp_refused url=%s reason=%s detail=%r", url, refusal.value, result.detail)
            return SourceFetch.failed(url, refusal, result.detail)
        info: dict[str, Any] | None = result.info()
        if info is None:
            LOGGER.warning("ytdlp_bad_output url=%s stdout_chars=%d", url, len(result.stdout))
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
            LOGGER.warning("ytdlp_cookies_copy_failed error=%s", type(error).__name__)
            if copy_path is not None:
                copy_path.unlink(missing_ok=True)
            return None
        return copy_path
