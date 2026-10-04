"""Внешние бинарники tools\\ и GitHub в тестах обновлений (app\\runtime\\ytdlp_updater.py, deno_updater.py).

К настоящим yt-dlp, deno и GitHub тесты не ходят. Бинарник — текстовый файл: его содержимое — то, что он печатает на
`--version`; файл, который начинается с `BROKEN`, не запускается (код 1). `FakeTools.run` — подделка `subprocess.run`:
отвечает за файлы по их содержимому, `-U` переписывает yt-dlp на `self_update_to` (или падает с `self_update_fails`),
проверку cookies отвечает `probe_stderr` и `probe_code`. `FakeGitHub.get` — подделка `requests.get`: ответы по адресам,
обрыв связи — `requests.ConnectionError`.
"""
from __future__ import annotations

import io
import subprocess
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from app.core.clock import Clock
from app.paths import FileName, LivecraftPaths
from app.runtime.cookies_updater import CookiesCheck
from app.runtime.deno_updater import DENO_RELEASE_URL, DenoUpdater, GitHubRelease
from app.runtime.ytdlp_updater import SourceTools, YtDlpUpdater
from app.tests.fixtures.clock import StoppedClock

BROKEN: str = "BROKEN"
NOW: datetime = datetime(2026, 9, 29, 12, 0, tzinfo=timezone(timedelta(hours=3)))
DENO_NOW: str = "deno 2.9.6 (stable, release, x86_64-pc-windows-msvc)\nv8 15.0\ntypescript 6.0.3\n"
YTDLP_NOW: str = "2026.08.19\n"
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
    """Подделка `subprocess.run` для бинарников и проверки входа по cookies; вызовы записываются."""

    self_update_to: str | None = None
    self_update_fails: bool = False
    probe_code: int = 0
    probe_stderr: str = ""
    calls: list[list[str]] = field(default_factory=list)

    def run(self, command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        exe: Path = Path(command[0])
        if "--cookies" in command:
            return subprocess.CompletedProcess(command, self.probe_code, "", self.probe_stderr)
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
    """Ответ requests: код, тело JSON и байты."""

    def __init__(self, status_code: int, payload: object = None, content: bytes = b"") -> None:
        self.status_code: int = status_code
        self.payload: object = payload
        self.content: bytes = content

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> object:
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


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


def deno_updater(paths: LivecraftPaths, tools: FakeTools, github: FakeGitHub, clock: Clock) -> DenoUpdater:
    """Обновление deno на подделках процесса и GitHub."""
    built: DenoUpdater = DenoUpdater.of(paths, clock)
    return replace(built, binary=replace(built.binary, run=tools.run), github=github.release)


def ytdlp_updater(paths: LivecraftPaths, tools: FakeTools, clock: Clock) -> YtDlpUpdater:
    """Обновление yt-dlp на подделке процесса."""
    built: YtDlpUpdater = YtDlpUpdater.of(paths, clock)
    return replace(built, binary=replace(built.binary, run=tools.run))


def cookies_check(paths: LivecraftPaths, tools: FakeTools, clock: Clock) -> CookiesCheck:
    """Проверка cookies на подделке процесса."""
    return replace(CookiesCheck.of(paths, clock), run=tools.run)


def source_tools(paths: LivecraftPaths, tools: FakeTools, github: FakeGitHub, clock: Clock) -> SourceTools:
    """yt-dlp, deno и cookies запуска на подделках процесса и GitHub."""
    return SourceTools(
        ytdlp_updater(paths, tools, clock), deno_updater(paths, tools, github, clock), cookies_check(paths, tools, clock)
    )
