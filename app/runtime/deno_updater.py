"""Свежий tools\\deno.exe и общее у обновлений внешних бинарников (CLAUDE.md §2: `runtime\\deno_updater.py` restreamer).

deno — среда JavaScript, которой yt-dlp решает задачи YouTube (`--js-runtimes deno:<путь>`, app\\sources\\ytdlp.py):
без свежего deno видео YouTube перестают читаться. Проверка — не чаще раза в `DENO_CHECK_DAYS` суток (отметка
`state\\deno_last_check.json`); файла нет — скачивание сразу, без оглядки на отметку. Последняя версия — ответ GitHub
о последнем выпуске denoland/deno; стоит она — только отметка. Иначе архив выпуска для Windows x64 скачивается в
память, из него берётся deno.exe и кладётся рядом с рабочим временным файлом; на место рабочего он встаёт одним
`os.replace`, только если сам назвал ожидаемую версию (`ToolBinary.replace`): битая или чужая загрузка рабочий файл не
трогает. Сеть — requests с повторами `RetryLoop` (§11) на обрыве, таймауте, 429 и 5xx. Без сети и при любом отказе —
работа на прежнем файле, отметка не ставится: следующий запуск проверит снова.

Общее у обновлений yt-dlp и deno (app\\runtime\\ytdlp_updater.py берёт отсюда): итог проверки `ToolUpdate`, отметка
последней проверки `CheckMark` и сам бинарник `ToolBinary` (номер версии по `--version`, замена целиком или никак).
"""
from __future__ import annotations

import io
import json
import logging
import random
import subprocess
import time
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Final

import requests

from app.core.clock import Clock
from app.core.errors import DETAIL_MAX_CHARS
from app.core.retry import (
    RETRYABLE_ERRORS,
    RETRYABLE_HTTP_STATUSES,
    AttemptFailure,
    RetryLoop,
    RetryPolicy,
    RetryRun,
    RetryStep,
)
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import AtomicFile, FileName, LivecraftPaths, write_text_atomically
from app.ui.console import EncodingErrors
from app.ui.messages import msg
from app.version import APP_NAME

LOGGER = get_logger(LogArea.RUNTIME)

DENO_CHECK_DAYS: Final[int] = 15            # как часто проверять новую версию deno, в сутках
DENO_RELEASE_URL: Final[str] = "https://api.github.com/repos/denoland/deno/releases/latest"
DENO_DOWNLOAD_TEMPLATE: Final[str] = (
    "https://github.com/denoland/deno/releases/download/v{version}/deno-x86_64-pc-windows-msvc.zip"
)
DENO_VERSION_WORD: Final[int] = 1           # «deno 2.9.6 (stable, release, …)» — номер вторым словом
DOWNLOAD_TIMEOUT_SEC: Final[float] = 60.0
VERSION_TIMEOUT_SEC: Final[float] = 10.0
VERSION_PREFIXES: Final[str] = "vV"         # тег выпуска «v2.9.6» — номер без буквы
# Архив выпуска не разбирается: не ZIP, повреждённое сжатие, нет deno.exe внутри.
ARCHIVE_ERRORS: Final[tuple[type[Exception], ...]] = (zipfile.BadZipFile, zlib.error, EOFError, KeyError)


class ToolStatus(str, Enum):
    """Чем кончилась проверка бинарника. Значение — идентификатор для лога."""

    UPDATED = "updated"            # поставлена новая версия (или скачан недостающий файл)
    FRESH = "fresh"                # проверено: последняя версия уже стоит
    NOT_DUE = "not_due"            # проверять ещё рано: отметка свежая
    NOT_CHECKED = "not_checked"    # проверка не состоялась — причина в `problem`
    MISSING = "missing"            # файла нет, а сам себя он не скачает (yt-dlp)


class ToolProblem(str, Enum):
    """Почему проверка не состоялась. Значение — ключ `msg.TOOL_PROBLEMS`."""

    NO_ANSWER = "no_answer"                  # нет сети, обрыв, таймаут; 429 и 5xx — и после повторов
    REFUSED = "refused"                      # прочий отказ GitHub
    NO_VERSION = "no_version"                # ответ GitHub без номера последней версии
    BROKEN_DOWNLOAD = "broken_download"      # скачанное — не архив, или файл из него не назвал ожидаемую версию
    NOT_WRITTEN = "not_written"              # новый файл не встал на место рабочего: сбой диска, файл занят
    SELF_UPDATE_FAILED = "self_update_failed"    # yt-dlp -U не справился: код не 0, таймаут, не запустился

    @property
    def human(self) -> str:
        return msg.TOOL_PROBLEMS[self.value]


class ToolEvent(str, Enum):
    """События обновления бинарников в логе."""

    CHECKED = "tool_update"
    VERSION_FAILED = "tool_version_failed"
    REQUEST_RETRY = "tool_request_retry"
    REQUEST_FAILED = "tool_request_failed"


class ToolArg(str, Enum):
    """Ключи командной строки бинарника."""

    VERSION = "--version"


class ReleaseKey(str, Enum):
    """Поля ответа GitHub о выпуске и заголовки запроса к нему."""

    TAG = "tag_name"
    USER_AGENT = "User-Agent"      # без него API GitHub отказывает


GITHUB_HEADERS: Final[dict[str, str]] = {ReleaseKey.USER_AGENT.value: APP_NAME}


class MarkKey(str, Enum):
    """Поле отметки последней проверки: секунды эпохи."""

    LAST_CHECK = "last_check_ts"


class BrokenDownload(Exception):
    """Скачанный файл не назвал ожидаемую версию: на место рабочего он не встаёт. До человека не доходит —
    `ToolBinary.replace` превращает его в `ToolProblem.BROKEN_DOWNLOAD`."""


@dataclass(frozen=True)
class ToolUpdate:
    """Итог проверки одного бинарника: имя для людей, чем кончилась, версия до и после, причина и подробность для лога.

    Человеку — строка, только когда что-то обновлено или не проверено; свежий и «ещё рано» — только лог."""

    tool: str
    status: ToolStatus
    before: str | None
    after: str | None = None
    problem: ToolProblem | None = None
    detail: str = ""

    @classmethod
    def failed(cls, tool: str, before: str | None, problem: ToolProblem, detail: str = "") -> ToolUpdate:
        return cls(tool, ToolStatus.NOT_CHECKED, before, problem=problem, detail=detail[:DETAIL_MAX_CHARS])

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Обновлено — с какой версии на какую (или скачан недостающий); не проверено — почему и на чём идёт работа;
        файла нет — что сделать."""
        if self.status is ToolStatus.UPDATED:
            template: str = msg.TOOL_UPDATED if self.before is not None else msg.TOOL_DOWNLOADED
            return (template.format(tool=self.tool, before=self.before, after=self.after),)
        if self.status is ToolStatus.MISSING:
            return (msg.TOOL_MISSING.format(tool=self.tool),)
        if self.problem is None:
            return ()
        template = msg.TOOL_NOT_CHECKED if self.before is not None else msg.TOOL_UNUSABLE
        return (template.format(tool=self.tool, reason=self.problem.human, version=self.before),)

    def log(self) -> None:
        """Строка лога — всегда; не проверено и нет файла — предупреждением."""
        level: int = logging.WARNING if self.status in (ToolStatus.NOT_CHECKED, ToolStatus.MISSING) else logging.INFO
        event: LogEvent = LogEvent.of(ToolEvent.CHECKED, tool=self.tool, status=self.status, before=self.before)
        event.extended(after=self.after, problem=self.problem, detail=self.detail).emit(LOGGER, level)


@dataclass(frozen=True)
class CheckMark:
    """Отметка последней состоявшейся проверки в state\\: файл JSON с секундами эпохи; «сейчас» — часы программы.

    Нет отметки или она не читается — проверять пора."""

    path: Path
    clock: Clock

    def is_due(self, interval_days: int) -> bool:
        """Прошло не меньше `interval_days` полных суток с отметки (или отметки нет)."""
        checked: datetime | None = self._checked_at()
        if checked is None:
            return True
        return (self.clock.now() - checked) // timedelta(days=1) >= interval_days

    def is_before(self, moment: datetime) -> bool:
        """Отметки нет или она раньше `moment`: то, что проверялось, с тех пор сменилось."""
        checked: datetime | None = self._checked_at()
        return checked is None or checked < moment

    def write(self) -> None:
        """Проверка состоялась: отметка — «сейчас»; файл пишется целиком или никак."""
        stamp: dict[str, int] = {MarkKey.LAST_CHECK.value: int(self.clock.now().timestamp())}
        write_text_atomically(self.path, json.dumps(stamp), TEXT_ENCODING)

    def _checked_at(self) -> datetime | None:
        try:
            payload: object = json.loads(self.path.read_text(encoding=TEXT_ENCODING))
        except (FileNotFoundError, ValueError):
            return None
        seconds: object = payload.get(MarkKey.LAST_CHECK.value) if isinstance(payload, dict) else None
        if not isinstance(seconds, int):
            return None
        return datetime.fromtimestamp(seconds, self.clock.zone)


@dataclass(frozen=True)
class ToolBinary:
    """Бинарник в tools\\: путь, какое слово первой строки `--version` — номер версии, и запуск процесса (`run` —
    `subprocess.run` или подделка в тестах)."""

    path: Path
    version_word: int
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run

    @property
    def version(self) -> str | None:
        """Номер версии рабочего файла; нет файла или он не отвечает — None."""
        return self.version_of(self.path)

    def version_of(self, exe: Path) -> str | None:
        """Номер версии, который называет файл `exe` на `--version`; не запустился, упал или молчит — None."""
        if not exe.is_file():
            return None
        command: list[str] = [str(exe), ToolArg.VERSION.value]
        try:
            answer: subprocess.CompletedProcess[str] = self.run(
                command, capture_output=True, check=False, timeout=VERSION_TIMEOUT_SEC,
                encoding=TEXT_ENCODING, errors=EncodingErrors.REPLACE.value,
            )
        except (OSError, subprocess.SubprocessError) as error:
            LogEvent.of(ToolEvent.VERSION_FAILED, path=exe, error=type(error).__name__).emit(LOGGER, logging.WARNING)
            return None
        words: list[str] = (answer.stdout or "").split()
        if answer.returncode != 0 or len(words) <= self.version_word:
            LogEvent.of(ToolEvent.VERSION_FAILED, path=exe, exit_code=answer.returncode).emit(LOGGER, logging.WARNING)
            return None
        return words[self.version_word].lstrip(VERSION_PREFIXES)

    def replace(self, data: bytes, version: str) -> ToolProblem | None:
        """Новый файл — рядом с рабочим; на его место встаёт, только если назвал `version`. Иначе рабочий не тронут."""
        try:
            AtomicFile.at(self.path).write(lambda temp: self._fill(temp, data, version))
        except BrokenDownload:
            return ToolProblem.BROKEN_DOWNLOAD
        except OSError:
            return ToolProblem.NOT_WRITTEN
        return None

    def _fill(self, temp: Path, data: bytes, version: str) -> None:
        temp.write_bytes(data)
        if self.version_of(temp) != version:
            raise BrokenDownload


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
        answer: requests.Response | ToolProblem = self._answer(url)
        if isinstance(answer, ToolProblem):
            return answer
        try:
            payload: object = answer.json()
        except ValueError:
            return ToolProblem.NO_VERSION
        tag: object = payload.get(ReleaseKey.TAG.value) if isinstance(payload, dict) else None
        version: str = tag.strip().lstrip(VERSION_PREFIXES) if isinstance(tag, str) else ""
        return version or ToolProblem.NO_VERSION

    def download(self, url: str) -> bytes | ToolProblem:
        """Байты файла выпуска или причина."""
        answer: requests.Response | ToolProblem = self._answer(url)
        return answer if isinstance(answer, ToolProblem) else bytes(answer.content)

    def _answer(self, url: str) -> requests.Response | ToolProblem:
        """Ответ GitHub после повторов или причина отказа; отказ — строкой лога с кодом ответа и числом попыток."""
        loop: RetryLoop = RetryLoop(self.policy, self.rng, self.sleep)
        run: RetryRun[requests.Response] = loop.run(lambda: self._attempt(url), lambda step: self._note_retry(url, step))
        if run.failure is None:
            return run.value
        problem: ToolProblem = ToolProblem(run.failure.reason)
        failed: LogEvent = LogEvent.of(ToolEvent.REQUEST_FAILED, url=url, problem=problem, **run.failure.log_fields)
        failed.extended(attempts=run.attempts).emit(LOGGER, logging.WARNING)
        return problem

    def _attempt(self, url: str) -> requests.Response | AttemptFailure:
        """Одно обращение: ответ 2xx или неудача; 429, 5xx, обрыв и таймаут — повторяемые."""
        try:
            answer: requests.Response = self.get(url, headers=GITHUB_HEADERS, timeout=DOWNLOAD_TIMEOUT_SEC)
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
        retry: LogEvent = LogEvent.of(ToolEvent.REQUEST_RETRY, url=url, **step.failure.log_fields)
        retry.extended(retry=step.retry, delay_sec=round(step.delay_sec, 1)).emit(LOGGER, logging.WARNING)


@dataclass(frozen=True)
class DenoUpdater:
    """Обновление tools\\deno.exe: бинарник, отметка проверки и GitHub."""

    binary: ToolBinary
    mark: CheckMark
    github: GitHubRelease = field(default_factory=GitHubRelease)

    @classmethod
    def of(cls, paths: LivecraftPaths, clock: Clock) -> DenoUpdater:
        binary: ToolBinary = ToolBinary(paths.file(FileName.DENO), DENO_VERSION_WORD)
        return cls(binary, CheckMark(paths.file(FileName.DENO_CHECK), clock))

    @property
    def tool(self) -> str:
        return self.binary.path.stem

    def update(self) -> ToolUpdate:
        """Пора — сверить с последним выпуском и, если нужно, поставить его; файла нет — скачать сразу. Рано — ничего, и
        бинарник не запускается."""
        if self.binary.path.is_file() and not self.mark.is_due(DENO_CHECK_DAYS):
            return ToolUpdate(self.tool, ToolStatus.NOT_DUE, None)
        before: str | None = self.binary.version
        latest: str | ToolProblem = self.github.latest_version(DENO_RELEASE_URL)
        if isinstance(latest, ToolProblem):
            return ToolUpdate.failed(self.tool, before, latest)
        if latest == before:
            self.mark.write()
            return ToolUpdate(self.tool, ToolStatus.FRESH, before, after=latest)
        problem: ToolProblem | None = self._install(latest)
        if problem is not None:
            return ToolUpdate.failed(self.tool, before, problem, latest)
        self.mark.write()
        return ToolUpdate(self.tool, ToolStatus.UPDATED, before, after=latest)

    def _install(self, version: str) -> ToolProblem | None:
        """Архив выпуска `version` → deno.exe из него → на место рабочего; причина, если не вышло."""
        archive: bytes | ToolProblem = self.github.download(DENO_DOWNLOAD_TEMPLATE.format(version=version))
        if isinstance(archive, ToolProblem):
            return archive
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as unpacked:
                exe: bytes = unpacked.read(self.binary.path.name)
        except ARCHIVE_ERRORS:
            return ToolProblem.BROKEN_DOWNLOAD
        return self.binary.replace(exe, version)
