"""Свежий tools\\deno.exe и общее у обновлений внешних бинарников (CLAUDE.md §2: `runtime\\deno_updater.py` restreamer).

deno — среда JavaScript, которой yt-dlp решает задачи YouTube (`--js-runtimes deno:<путь>`, app\\sources\\ytdlp.py):
без свежего deno видео YouTube перестают читаться. Проверка — не чаще раза в `DENO_CHECK_DAYS` суток (отметка
`state\\deno_last_check.json`); файла нет — скачивание сразу, без оглядки на отметку. Последняя версия — ответ GitHub
о последнем выпуске denoland/deno; стоит она — только отметка. Иначе архив выпуска для Windows x64 читается потоком в
память — по ходу консоль получает строку начала с размером и строки на 25, 50 и 75 % (`DownloadWatch`,
app\\runtime\\github_release.py), — из него берётся deno.exe и кладётся рядом с рабочим временным файлом; на место
рабочего он встаёт одним `os.replace`, только если сам назвал ожидаемую версию (`ToolBinary.replace`): битая или чужая
загрузка рабочий файл не трогает. Сеть — `GitHubRelease` с повторами `RetryLoop` (§11) на обрыве (и посреди файла),
таймауте, 429 и 5xx. Без сети и при любом отказе — работа на прежнем файле, отметка не ставится: следующий запуск
проверит снова.

Общее у обновлений yt-dlp и deno (app\\runtime\\ytdlp_updater.py берёт отсюда): итог проверки `ToolUpdate`, отметка
последней проверки `CheckMark`, сам бинарник `ToolBinary` (номер версии по `--version`, замена целиком или никак) и
откуда он берёт выпуск — `ReleaseSource` (последний выпуск на GitHub → файл на месте рабочего, ход загрузки — строками
на консоль). Установщик бинарников не несёт (§14 решение 65): недостающий файл программа скачивает сама по тому же
правилу.
"""
from __future__ import annotations

import io
import json
import logging
import subprocess
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Final

from app.core.clock import Clock
from app.core.errors import DETAIL_MAX_CHARS
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import AtomicFile, FileName, LivecraftPaths, write_text_atomically
from app.runtime.github_release import VERSION_PREFIXES, DownloadWatch, GitHubRelease, ToolProblem
from app.ui.console import EncodingErrors
from app.ui.messages import msg

LOGGER = get_logger(LogArea.RUNTIME)

DENO_CHECK_DAYS: Final[int] = 15            # как часто проверять новую версию deno, в сутках
DENO_RELEASE_URL: Final[str] = "https://api.github.com/repos/denoland/deno/releases/latest"
DENO_DOWNLOAD_TEMPLATE: Final[str] = (
    "https://github.com/denoland/deno/releases/download/v{version}/deno-x86_64-pc-windows-msvc.zip"
)
DENO_VERSION_WORD: Final[int] = 1           # «deno 2.9.6 (stable, release, …)» — номер вторым словом
VERSION_TIMEOUT_SEC: Final[float] = 10.0
# Архив выпуска не разбирается: не ZIP, повреждённое сжатие, нет deno.exe внутри.
ARCHIVE_ERRORS: Final[tuple[type[Exception], ...]] = (zipfile.BadZipFile, zlib.error, EOFError, KeyError)


class ToolStatus(str, Enum):
    """Чем кончилась проверка бинарника. Значение — идентификатор для лога."""

    UPDATED = "updated"            # поставлена новая версия (или скачан недостающий файл)
    FRESH = "fresh"                # проверено: последняя версия уже стоит
    NOT_DUE = "not_due"            # проверять ещё рано: отметка свежая
    NOT_CHECKED = "not_checked"    # проверка не состоялась — причина в `problem`


class ToolEvent(str, Enum):
    """События обновления бинарников в логе."""

    CHECKED = "tool_update"
    VERSION_FAILED = "tool_version_failed"


class ToolArg(str, Enum):
    """Ключи командной строки бинарника."""

    VERSION = "--version"


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
        """Обновлено — с какой версии на какую (или скачан недостающий); не проверено — почему и на чём идёт работа
        (или что рабочего файла нет)."""
        if self.status is ToolStatus.UPDATED:
            template: str = msg.TOOL_UPDATED if self.before is not None else msg.TOOL_DOWNLOADED
            return (template.format(tool=self.tool, before=self.before, after=self.after),)
        if self.problem is None:
            return ()
        template = msg.TOOL_NOT_CHECKED if self.before is not None else msg.TOOL_UNUSABLE
        return (template.format(tool=self.tool, reason=self.problem.human, version=self.before),)

    def log(self) -> None:
        """Строка лога — всегда; не проверено — предупреждением."""
        level: int = logging.WARNING if self.status is ToolStatus.NOT_CHECKED else logging.INFO
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
class ReleaseSource:
    """Откуда бинарник берёт выпуск: адрес API последнего выпуска на GitHub, адрес файла выпуска по `{version}` и имя
    exe внутри ZIP (None — файл выпуска и есть exe). Одно правило «последний выпуск → поставить» для yt-dlp и deno."""

    latest_url: str
    file_template: str
    archive_member: str | None = None

    def latest_version(self, github: GitHubRelease) -> str | ToolProblem:
        """Номер последнего выпуска или причина, почему его не узнать."""
        return github.latest_version(self.latest_url)

    def install(
        self, github: GitHubRelease, binary: ToolBinary, version: str, watch: DownloadWatch
    ) -> ToolProblem | None:
        """Файл выпуска `version` → exe (из ZIP или как есть) → на место рабочего; причина, если не вышло. Ход загрузки
        — наблюдателю `watch`."""
        download: bytes | ToolProblem = github.download(self.file_template.format(version=version), watch)
        if isinstance(download, ToolProblem):
            return download
        exe: bytes | ToolProblem = self._exe(download)
        return exe if isinstance(exe, ToolProblem) else binary.replace(exe, version)

    def _exe(self, download: bytes) -> bytes | ToolProblem:
        """Байты exe: из архива выпуска по имени или сам файл выпуска; архив не разбирается — битая загрузка."""
        if self.archive_member is None:
            return download
        try:
            with zipfile.ZipFile(io.BytesIO(download)) as unpacked:
                return unpacked.read(self.archive_member)
        except ARCHIVE_ERRORS:
            return ToolProblem.BROKEN_DOWNLOAD


DENO_RELEASE: Final[ReleaseSource] = ReleaseSource(DENO_RELEASE_URL, DENO_DOWNLOAD_TEMPLATE, FileName.DENO.value)


@dataclass(frozen=True)
class DenoUpdater:
    """Обновление tools\\deno.exe: бинарник, отметка проверки, строка хода на консоль (`say`) и GitHub."""

    binary: ToolBinary
    mark: CheckMark
    say: Callable[[str], None]
    github: GitHubRelease = field(default_factory=GitHubRelease)

    @classmethod
    def of(cls, paths: LivecraftPaths, clock: Clock, say: Callable[[str], None]) -> DenoUpdater:
        binary: ToolBinary = ToolBinary(paths.file(FileName.DENO), DENO_VERSION_WORD)
        return cls(binary, CheckMark(paths.file(FileName.DENO_CHECK), clock), say)

    @property
    def tool(self) -> str:
        return self.binary.path.stem

    @property
    def is_missing(self) -> bool:
        return not self.binary.path.is_file()

    def install_missing(self) -> ToolUpdate | None:
        """Только недостающий файл: нет — поставить последний выпуск; есть — ничего (ни вопроса GitHub, ни запуска)."""
        return self.update() if self.is_missing else None

    def update(self) -> ToolUpdate:
        """Пора — сверить с последним выпуском и, если нужно, поставить его; файла нет — скачать сразу. Рано — ничего, и
        бинарник не запускается."""
        if not self.is_missing and not self.mark.is_due(DENO_CHECK_DAYS):
            return ToolUpdate(self.tool, ToolStatus.NOT_DUE, None)
        before: str | None = self.binary.version
        latest: str | ToolProblem = DENO_RELEASE.latest_version(self.github)
        if isinstance(latest, ToolProblem):
            return ToolUpdate.failed(self.tool, before, latest)
        if latest == before:
            self.mark.write()
            return ToolUpdate(self.tool, ToolStatus.FRESH, before, after=latest)
        watch: DownloadWatch = DownloadWatch(self.tool, latest, self.say)
        problem: ToolProblem | None = DENO_RELEASE.install(self.github, self.binary, latest, watch)
        if problem is not None:
            return ToolUpdate.failed(self.tool, before, problem, latest)
        self.mark.write()
        return ToolUpdate(self.tool, ToolStatus.UPDATED, before, after=latest)
