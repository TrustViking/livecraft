"""Окно настройки само ставит недостающие yt-dlp и deno (CLAUDE.md §14 решение 74): модель установки без Tk и строка
над строкой готовности на настоящем окне Tk за краем экрана; процесс и GitHub — подделки."""
from __future__ import annotations

import queue
import time
from collections.abc import Callable, Iterator

import pytest

from app.config.files import ShippedSettings
from app.paths import FileName, LivecraftPaths
from app.runtime.deno_updater import ToolStatus, ToolUpdate
from app.runtime.github_release import ToolProblem
from app.runtime.ytdlp_updater import SourceTools
from app.setup.app import SetupWindow
from app.setup.tabs.check_line import RowState, ResultRow
from app.setup.tools_install import ToolsInstall, ToolsVerdict
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.tests.fixtures.tools import (
    DENO_NOW,
    YTDLP_NOW,
    FakeGitHub,
    FakeGitHubResponse,
    FakeTools,
    deno_zip,
    tools_install,
    write_tool,
)
from app.ui import messages_ru as msg

YTDLP_URL: str = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
YTDLP_FILE_URL: str = "https://github.com/yt-dlp/yt-dlp/releases/download/2026.09.20/yt-dlp.exe"
DENO_NEW: str = "deno 2.9.7 (stable, release, x86_64-pc-windows-msvc)\n"
WAIT_SEC: float = 10.0


def _github() -> FakeGitHub:
    """GitHub с последними выпусками yt-dlp 2026.09.20 и deno 2.9.7."""
    github: FakeGitHub = FakeGitHub.releasing("v2.9.7", deno_zip(DENO_NEW))
    github.answers[YTDLP_URL] = [FakeGitHubResponse(200, {"tag_name": "2026.09.20"})]
    github.answers[YTDLP_FILE_URL] = [FakeGitHubResponse(200, content=b"2026.09.20\n")]
    return github


def _updated(tool: str, version: str) -> ToolUpdate:
    return ToolUpdate(tool, ToolStatus.UPDATED, None, after=version)


# --- модель без окна


def test_both_tools_in_place_need_nothing(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    install: ToolsInstall = ToolsInstall.of(livecraft_paths, ShippedSettings().settings)
    assert (install.missing, install.is_needed) == ((), False)


def test_missing_tools_are_named(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    install: ToolsInstall = ToolsInstall.of(livecraft_paths, ShippedSettings().settings)
    assert (install.missing, install.is_needed) == (("yt-dlp",), True)
    assert install.starting_line == "Нет yt-dlp в папке tools — идёт загрузка, подождите…"


def test_the_work_puts_the_progress_then_the_verdict(livecraft_paths: LivecraftPaths) -> None:
    install: ToolsInstall = tools_install(livecraft_paths, FakeTools(), _github())
    inbox: queue.Queue[ToolsVerdict | str] = queue.Queue()
    install.work(inbox)
    items: list[ToolsVerdict | str] = [inbox.get_nowait() for _ in range(inbox.qsize())]
    assert items[:-1] == ["Скачивание yt-dlp 2026.09.20 с GitHub: 0 МБ…", "Скачивание deno 2.9.7 с GitHub: 0 МБ…"]
    verdict: ToolsVerdict | str = items[-1]
    assert isinstance(verdict, ToolsVerdict) and verdict.text == "✓ Скачаны: yt-dlp 2026.09.20, deno 2.9.7."
    assert livecraft_paths.file(FileName.YTDLP).is_file() and livecraft_paths.file(FileName.DENO).is_file()


def test_a_failed_download_is_named_first_and_left_to_the_run() -> None:
    failed: ToolUpdate = ToolUpdate.failed("yt-dlp", None, ToolProblem.NO_ANSWER)
    verdict: ToolsVerdict = ToolsVerdict((failed, _updated("deno", "2.9.7")))
    assert verdict.text.split("\n") == [
        "✗ yt-dlp не скачан — нет связи с GitHub.", "Его скачает запуск.", "✓ Скачаны: deno 2.9.7.",
    ]
    assert ResultRow(verdict.text).state is RowState.PROBLEM


def test_a_work_that_breaks_still_gives_a_verdict(livecraft_paths: LivecraftPaths) -> None:
    """Ошибка программы в потоке: итог — «прервалась», строка окна не ждёт вечно."""

    def _broken(say: Callable[[str], None]) -> SourceTools:
        raise RuntimeError("broken")

    install: ToolsInstall = ToolsInstall(("yt-dlp",), _broken)
    inbox: queue.Queue[ToolsVerdict | str] = queue.Queue()
    with pytest.raises(RuntimeError):
        install.work(inbox)
    verdict: ToolsVerdict | str = inbox.get_nowait()
    assert isinstance(verdict, ToolsVerdict)
    assert verdict.text == f"✗ {msg.SETUP_TOOLS_INTERRUPTED}"


# --- строка окна


@pytest.fixture
def downloading(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на корне без yt-dlp и deno: установка — на подделках процесса и GitHub."""
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig, tools_install(ready_paths, FakeTools(), _github()))


def test_the_window_downloads_the_missing_tools_with_a_line_above_the_readiness(downloading: SetupWindowDriver) -> None:
    window: SetupWindow = downloading.window
    window.root.update_idletasks()                       # окно открылось: установка пошла (опроса ещё не было)
    assert window.tools.text == "Нет yt-dlp, deno в папке tools — идёт загрузка, подождите…"
    assert window.tools.label.winfo_manager() == "pack"
    slaves: list[str] = [str(widget) for widget in window.root.pack_slaves()]
    assert slaves.index(str(window.readiness_line)) < slaves.index(str(window.tools.label))    # над строкой готовности
    deadline: float = time.monotonic() + WAIT_SEC
    while window.tools.poll.is_running:
        assert time.monotonic() < deadline
        window.root.update()
        time.sleep(0.01)
    assert window.tools.text == "✓ Скачаны: yt-dlp 2026.09.20, deno 2.9.7."
    assert window.paths.file(FileName.YTDLP).is_file()


def test_the_window_with_both_tools_shows_no_line(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> None:
    write_tool(ready_paths, FileName.YTDLP, YTDLP_NOW)
    write_tool(ready_paths, FileName.DENO, DENO_NOW)
    github: FakeGitHub = FakeGitHub()
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig, tools_install(ready_paths, FakeTools(), github)):
        driver.window.root.update()
        assert driver.window.tools.text == "" and not driver.window.tools.poll.is_running
        assert github.requested == []
