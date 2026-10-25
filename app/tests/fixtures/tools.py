"""Внешние бинарники tools\\ и GitHub в тестах обновлений (app\\runtime\\ytdlp_updater.py, deno_updater.py).

К настоящим yt-dlp, deno и GitHub тесты не ходят. Бинарник — текстовый файл: его содержимое — то, что он печатает на
`--version`; файл, который начинается с `BROKEN`, не запускается (код 1). `FakeTools.run` — подделка `subprocess.run`:
отвечает за файлы по их содержимому, `-U` переписывает yt-dlp на `self_update_to` (или падает с `self_update_fails`).
`FakeGitHub.get` — подделка `requests.get`: ответы по адресам,
обрыв связи — `requests.ConnectionError`; байты ответа отдаются потоком кусками, поток может оборваться посреди файла.
"""
from __future__ import annotations

import functools
import io
import subprocess
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from app.core.clock import Clock
from app.paths import FileName, LivecraftPaths
from app.runtime.cookies_updater import CookiesCheck
from app.run.progress import SILENT_PROGRESS
from app.runtime.deno_updater import DENO_RELEASE_URL, DenoUpdater
from app.runtime.github_release import GitHubRelease
from app.runtime.ytdlp_updater import SourceTools, YtDlpUpdater
from app.setup.tools_install import ToolsInstall
from app.tests.fixtures.clock import StoppedClock

BROKEN: str = "BROKEN"
NOW: datetime = datetime(2026, 9, 29, 12, 0, tzinfo=timezone(timedelta(hours=3)))
DENO_NOW: str = "deno 2.9.6 (stable, release, x86_64-pc-windows-msvc)\nv8 15.0\ntypescript 6.0.3\n"
YTDLP_NOW: str = "2026.08.19\n"
Say = Callable[[str], None]
DENO_ZIP_URL: str = "https://github.com/denoland/deno/releases/download/v2.9.7/deno-x86_64-pc-windows-msvc.zip"


def clock_at(moment: datetime = NOW) -> Clock:
    return StoppedClock.at(moment)


def write_tool(paths: LivecraftPaths, name: FileName, version_text: str) -> Path:
    """Бинарник в tools\\: файл, который на `--version` печатает `version_text`."""
    path: Path = paths.file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(version_text, encoding="utf-8")
    return path


def deno_zip(exe_text: str, member: str = "deno.exe") -> bytes:
    """Архив выпуска deno для Windows: внутри `member` с текстом `exe_text`."""
    buffer: io.BytesIO = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, exe_text)
    return buffer.getvalue()


@dataclass
class FakeTools:
    """Подделка `subprocess.run` для бинарников; вызовы записываются."""

    self_update_to: str | None = None
    self_update_fails: bool = False
    calls: list[list[str]] = field(default_factory=list)

    def run(self, command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        exe: Path = Path(command[0])
        if command[1:] == ["-U"]:
            return self._self_update(command, exe)
        text: str = exe.read_text(encoding="utf-8")
        if text.startswith(BROKEN):
            return subprocess.CompletedProcess(command, 1, "", "cannot start")
        return subprocess.CompletedProcess(command, 0, text, "")

    @property
    def self_updates(self) -> int:
        return sum(1 for command in self.calls if command[1:] == ["-U"])

    def _self_update(self, command: list[str], exe: Path) -> subprocess.CompletedProcess[str]:
        if self.self_update_fails:
            return subprocess.CompletedProcess(command, 1, "", "ERROR: Unable to obtain version info")
        if self.self_update_to is not None:
            exe.write_text(self.self_update_to, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "Updated yt-dlp\n", "")


class FakeGitHubResponse:
    """Ответ requests: код, тело JSON и байты. Байты отдаются потоком (`iter_content`) кусками по `chunk_size`;
    `sized` — есть ли заголовок Content-Length; `chunk` — свой размер куска вместо запрошенного (несколько кусков
    маленького файла); `breaks` — ошибка, которой поток обрывается после первого куска."""

    def __init__(
        self,
        status_code: int,
        payload: object = None,
        content: bytes = b"",
        sized: bool = True,
        chunk: int | None = None,
        breaks: Exception | None = None,
    ) -> None:
        self.status_code: int = status_code
        self.payload: object = payload
        self.content: bytes = content
        self.headers: dict[str, str] = {"Content-Length": str(len(content))} if sized else {}
        self.chunk: int | None = chunk
        self.breaks: Exception | None = breaks

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> object:
        if self.payload is None:
            raise ValueError("not json")
        return self.payload

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        step: int = self.chunk or chunk_size
        for start in range(0, len(self.content), step):
            yield self.content[start:start + step]
            if self.breaks is not None:
                raise self.breaks


@dataclass
class FakeGitHub:
    """Подделка `requests.get`: ответы по адресу по очереди, последний — на все следующие обращения; адреса нет в
    `answers` — обрыв связи. Запросы и паузы записываются."""

    answers: dict[str, list[FakeGitHubResponse]] = field(default_factory=dict)
    requested: list[str] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)

    @classmethod
    def releasing(cls, tag: str, archive: bytes, zip_url: str = DENO_ZIP_URL) -> FakeGitHub:
        """GitHub, у которого последний выпуск deno — `tag`, а его архив — `archive`."""
        return cls(
            answers={
                DENO_RELEASE_URL: [FakeGitHubResponse(200, {"tag_name": tag})],
                zip_url: [FakeGitHubResponse(200, content=archive)],
            }
        )

    def get(self, url: str, **options: object) -> FakeGitHubResponse:
        self.requested.append(url)
        if url not in self.answers:
            raise requests.ConnectionError("offline")
        replies: list[FakeGitHubResponse] = self.answers[url]
        return replies.pop(0) if len(replies) > 1 else replies[0]

    @property
    def release(self) -> GitHubRelease:
        return GitHubRelease(get=self.get, sleep=self.sleeps.append)


def deno_updater(
    paths: LivecraftPaths, tools: FakeTools, github: FakeGitHub, clock: Clock, say: Say = SILENT_PROGRESS.tool_note
) -> DenoUpdater:
    """Обновление deno на подделках процесса и GitHub; строки хода — в `say`."""
    built: DenoUpdater = DenoUpdater.of(paths, clock, say)
    return replace(built, binary=replace(built.binary, run=tools.run), github=github.release)


def ytdlp_updater(
    paths: LivecraftPaths, tools: FakeTools, clock: Clock, github: FakeGitHub | None = None,
    say: Say = SILENT_PROGRESS.tool_note,
) -> YtDlpUpdater:
    """Обновление yt-dlp на подделках процесса и GitHub (нет его — к GitHub не ходит); строки хода — в `say`."""
    built: YtDlpUpdater = YtDlpUpdater.of(paths, clock, say)
    built = replace(built, binary=replace(built.binary, run=tools.run))
    return built if github is None else replace(built, github=github.release)


REMIND_DAYS: int = 7      # срок напоминания о cookies — как в поставке


def cookies_check(paths: LivecraftPaths, clock: Clock, remind_days: int = REMIND_DAYS) -> CookiesCheck:
    """Проверка cookies установки `paths`; срок напоминания — `remind_days`."""
    return CookiesCheck.of(paths, clock, remind_days)


def source_tools(
    paths: LivecraftPaths, tools: FakeTools, github: FakeGitHub, clock: Clock, say: Say = SILENT_PROGRESS.tool_note
) -> SourceTools:
    """yt-dlp, deno и cookies запуска на подделках процесса и GitHub; строки хода — в `say`."""
    return SourceTools(
        ytdlp_updater(paths, tools, clock, github, say),
        deno_updater(paths, tools, github, clock, say),
        cookies_check(paths, clock),
    )


def installed_tools(paths: LivecraftPaths) -> ToolsInstall:
    """Установка окна, которой ставить нечего: yt-dlp и deno будто на месте — окно к GitHub не ходит."""
    return ToolsInstall((), functools.partial(SourceTools.of, paths, clock_at(), remind_days=REMIND_DAYS))


def tools_install(paths: LivecraftPaths, tools: FakeTools, github: FakeGitHub) -> ToolsInstall:
    """Установка окна на подделках процесса и GitHub: ставит то, чего нет в tools\\ установки `paths`."""
    build = functools.partial(source_tools, paths, tools, github, clock_at())
    missing: tuple[str, ...] = build().missing
    return ToolsInstall(missing, build)
