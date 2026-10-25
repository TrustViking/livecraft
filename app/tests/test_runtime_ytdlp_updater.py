from __future__ import annotations

import os
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from app.paths import FileName, LivecraftPaths
from app.run.progress import SILENT_PROGRESS
from app.runtime.cookies_updater import CookiesState
from app.runtime.deno_updater import CheckMark, ToolBinary, ToolStatus, ToolUpdate
from app.runtime.github_release import ToolProblem
from app.runtime.ytdlp_updater import (
    YTDLP_CHECK_DAYS,
    YTDLP_RELEASE_URL,
    YTDLP_VERSION_WORD,
    SourceTools,
    SourceToolsCheck,
    YtDlpUpdater,
)
from app.tests.fixtures.tools import (
    DENO_NOW,
    NOW,
    YTDLP_NOW,
    FakeGitHub,
    FakeGitHubResponse,
    FakeTools,
    clock_at,
    deno_zip,
    source_tools,
    write_tool,
    ytdlp_updater,
)
from app.ui import messages_ru as msg

DENO_NEW: str = "deno 2.9.7 (stable, release, x86_64-pc-windows-msvc)\n"
YTDLP_FILE_URL: str = "https://github.com/yt-dlp/yt-dlp/releases/download/2026.09.20/yt-dlp.exe"


def _mark(paths: LivecraftPaths, name: FileName, days_ago: int) -> None:
    CheckMark(paths.file(name), clock_at(NOW - timedelta(days=days_ago))).write()


def _downloading(paths: LivecraftPaths, github: FakeGitHub) -> YtDlpUpdater:
    """Обновление yt-dlp на подделках процесса и GitHub."""
    binary: ToolBinary = ToolBinary(paths.file(FileName.YTDLP), YTDLP_VERSION_WORD, FakeTools().run)
    mark: CheckMark = CheckMark(paths.file(FileName.YTDLP_CHECK), clock_at())
    return YtDlpUpdater(binary, mark, SILENT_PROGRESS.tool_note, github.release)


def _releasing(exe_text: str) -> FakeGitHub:
    """GitHub, у которого последний выпуск yt-dlp — 2026.09.20, а его файл печатает `exe_text`."""
    return FakeGitHub(
        answers={
            YTDLP_RELEASE_URL: [FakeGitHubResponse(200, {"tag_name": "2026.09.20"})],
            YTDLP_FILE_URL: [FakeGitHubResponse(200, content=exe_text.encode())],
        }
    )


def test_a_missing_ytdlp_is_downloaded_and_marked(livecraft_paths: LivecraftPaths) -> None:
    """Установщик yt-dlp не несёт (решение 65): недостающий файл программа скачивает сама."""
    _mark(livecraft_paths, FileName.YTDLP_CHECK, 1)
    github: FakeGitHub = _releasing("2026.09.20\n")
    update: ToolUpdate = _downloading(livecraft_paths, github).update()
    assert (update.status, update.before, update.after) == (ToolStatus.UPDATED, None, "2026.09.20")
    assert update.console_lines == (msg.TOOL_DOWNLOADED.format(tool="yt-dlp", after="2026.09.20"),)
    assert livecraft_paths.file(FileName.YTDLP).read_text(encoding="utf-8") == "2026.09.20\n"
    assert github.requested == [YTDLP_RELEASE_URL, YTDLP_FILE_URL]
    assert not CheckMark(livecraft_paths.file(FileName.YTDLP_CHECK), clock_at()).is_due(YTDLP_CHECK_DAYS)


def test_a_missing_ytdlp_without_network_says_the_next_run_tries_again(livecraft_paths: LivecraftPaths) -> None:
    update: ToolUpdate = _downloading(livecraft_paths, FakeGitHub()).update()
    assert (update.status, update.problem) == (ToolStatus.NOT_CHECKED, ToolProblem.NO_ANSWER)
    assert update.console_lines == (msg.TOOL_UNUSABLE.format(tool="yt-dlp", reason=msg.TOOL_PROBLEMS["no_answer"]),)
    assert not livecraft_paths.file(FileName.YTDLP).exists()
    assert not livecraft_paths.file(FileName.YTDLP_CHECK).exists()


def test_a_downloaded_ytdlp_that_names_another_version_is_thrown_away(livecraft_paths: LivecraftPaths) -> None:
    update: ToolUpdate = _downloading(livecraft_paths, _releasing("2026.08.19\n")).update()
    assert (update.status, update.problem, update.detail) == (
        ToolStatus.NOT_CHECKED, ToolProblem.BROKEN_DOWNLOAD, "2026.09.20",
    )
    assert list(livecraft_paths.file(FileName.YTDLP).parent.iterdir()) == []
    assert not livecraft_paths.file(FileName.YTDLP_CHECK).exists()


def test_a_fresh_mark_means_the_binary_is_not_started(livecraft_paths: LivecraftPaths) -> None:
    """Рано проверять — ни `-U`, ни `--version`: под нагрузкой один вызов стоил до 10 с впустую."""
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    _mark(livecraft_paths, FileName.YTDLP_CHECK, YTDLP_CHECK_DAYS - 1)
    tools: FakeTools = FakeTools(self_update_to="2026.09.20\n")
    update: ToolUpdate = ytdlp_updater(livecraft_paths, tools, clock_at()).update()
    assert (update.status, update.before, update.console_lines) == (ToolStatus.NOT_DUE, None, ())
    assert tools.calls == []


def test_a_due_check_updates_and_names_both_versions(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    _mark(livecraft_paths, FileName.YTDLP_CHECK, YTDLP_CHECK_DAYS)
    tools: FakeTools = FakeTools(self_update_to="2026.09.20\n")
    update: ToolUpdate = ytdlp_updater(livecraft_paths, tools, clock_at()).update()
    assert (update.status, update.before, update.after) == (ToolStatus.UPDATED, "2026.08.19", "2026.09.20")
    assert update.console_lines == (msg.TOOL_UPDATED.format(tool="yt-dlp", before="2026.08.19", after="2026.09.20"),)
    assert not CheckMark(livecraft_paths.file(FileName.YTDLP_CHECK), clock_at()).is_due(YTDLP_CHECK_DAYS)


def test_the_same_version_after_the_self_update_is_fresh_and_silent(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    tools: FakeTools = FakeTools()
    update: ToolUpdate = ytdlp_updater(livecraft_paths, tools, clock_at()).update()
    assert (update.status, update.console_lines, tools.self_updates) == (ToolStatus.FRESH, (), 1)


def test_a_failed_self_update_keeps_the_version_and_sets_no_mark(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    update: ToolUpdate = ytdlp_updater(livecraft_paths, FakeTools(self_update_fails=True), clock_at()).update()
    assert (update.status, update.problem) == (ToolStatus.NOT_CHECKED, ToolProblem.SELF_UPDATE_FAILED)
    assert update.detail == "ERROR: Unable to obtain version info"
    assert update.console_lines == (
        msg.TOOL_NOT_CHECKED.format(tool="yt-dlp", reason=msg.TOOL_PROBLEMS["self_update_failed"], version="2026.08.19"),
    )
    assert not livecraft_paths.file(FileName.YTDLP_CHECK).exists()


def test_source_tools_update_both_binaries_and_check_the_cookies(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    _mark(livecraft_paths, FileName.DENO_CHECK, 1)
    tools: FakeTools = FakeTools(self_update_to="2026.09.20\n")
    said: list[str] = []
    check: SourceToolsCheck = source_tools(livecraft_paths, tools, FakeGitHub(), clock_at(), said.append).refresh()
    assert [update.status for update in check.updates] == [ToolStatus.UPDATED, ToolStatus.NOT_DUE]
    assert said == ["Проверка обновления yt-dlp…"]        # deno — «ещё рано»: строк нет
    assert check.console_lines == (msg.TOOL_UPDATED.format(tool="yt-dlp", before="2026.08.19", after="2026.09.20"),)


def test_a_cookies_file_of_the_wrong_form_is_silent_and_runs_no_binary(livecraft_paths: LivecraftPaths) -> None:
    """Не тот вид cookies запуск не останавливает и в консоль не идёт (решение 73, поправка 18-10-2026): yt-dlp
    читает видео без cookies; проверка cookies ни одного бинарника не запускает."""
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    for name in (FileName.YTDLP_CHECK, FileName.DENO_CHECK):
        _mark(livecraft_paths, name, 1)
    livecraft_paths.file(FileName.COOKIES).write_text("youtube.com\tTRUE\t/\n", encoding="utf-8")
    tools: FakeTools = FakeTools()
    check: SourceToolsCheck = source_tools(livecraft_paths, tools, FakeGitHub(), clock_at()).refresh()
    assert (check.cookies.state, check.console_lines, tools.calls) == (CookiesState.BAD_FORMAT, (), [])


def test_stale_cookies_are_not_said_at_the_run(livecraft_paths: LivecraftPaths) -> None:
    """Срок напоминания закончился — запуск о cookies человеку не пишет: работа от входа не зависит (решение 80)."""
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    for name in (FileName.YTDLP_CHECK, FileName.DENO_CHECK):
        _mark(livecraft_paths, name, 1)
    cookies: Path = livecraft_paths.file(FileName.COOKIES)
    cookies.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tv\n", encoding="utf-8")
    stamp: float = (clock_at().now() - timedelta(days=100)).timestamp()
    os.utime(cookies, (stamp, stamp))
    check: SourceToolsCheck = source_tools(livecraft_paths, FakeTools(), FakeGitHub(), clock_at()).refresh()
    assert check.cookies.is_stale and check.console_lines == ()


# --- строки хода: загрузка, самообновление, порядок бинарников


def test_a_due_self_update_is_said_before_it_runs_and_a_fresh_mark_says_nothing(
    livecraft_paths: LivecraftPaths,
) -> None:
    """Строка проверки — до `yt-dlp -U` (в момент строки самообновлений ещё 0); рано проверять — строк нет."""
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    tools: FakeTools = FakeTools()
    said: list[tuple[str, int]] = []
    say: Callable[[str], None] = lambda text: said.append((text, tools.self_updates))
    ytdlp_updater(livecraft_paths, tools, clock_at(), say=say).update()
    assert said == [("Проверка обновления yt-dlp…", 0)] and tools.self_updates == 1
    ytdlp_updater(livecraft_paths, tools, clock_at(), say=say).update()
    assert len(said) == 1 and tools.self_updates == 1


def test_source_tools_download_ytdlp_then_deno_and_log_each_right_after_it(
    livecraft_paths: LivecraftPaths, caplog: pytest.LogCaptureFixture
) -> None:
    """Обе загрузки — строками по ходу; итог yt-dlp — в логе до того, как пошла загрузка deno."""
    github: FakeGitHub = _releasing("2026.09.20\n")
    github.answers.update(FakeGitHub.releasing("v2.9.7", deno_zip(DENO_NEW)).answers)
    said: list[tuple[str, int]] = []
    with caplog.at_level("INFO", logger="livecraft"):
        say: Callable[[str], None] = lambda text: said.append((text, _tool_lines(caplog)))
        check: SourceToolsCheck = source_tools(livecraft_paths, FakeTools(), github, clock_at(), say).refresh()
    assert [update.status for update in check.updates] == [ToolStatus.UPDATED, ToolStatus.UPDATED]
    assert said == [("Скачивание yt-dlp 2026.09.20 с GitHub: 0 МБ…", 0), ("Скачивание deno 2.9.7 с GitHub: 0 МБ…", 1)]
    assert _tool_lines(caplog) == 2


def _tool_lines(caplog: pytest.LogCaptureFixture) -> int:
    """Сколько строк итога бинарника уже в логе."""
    return sum(1 for record in caplog.records if record.getMessage().startswith("tool_update "))


# --- окно ставит только недостающие бинарники (§14 решение 74)


def test_install_missing_downloads_both_when_neither_is_there(livecraft_paths: LivecraftPaths) -> None:
    github: FakeGitHub = _releasing("2026.09.20\n")
    github.answers.update(FakeGitHub.releasing("v2.9.7", deno_zip(DENO_NEW)).answers)
    said: list[str] = []
    tools: SourceTools = source_tools(livecraft_paths, FakeTools(), github, clock_at(), said.append)
    assert tools.missing == ("yt-dlp", "deno")
    updates: tuple[ToolUpdate, ...] = tools.install_missing()
    assert [(update.tool, update.status, update.after) for update in updates] == [
        ("yt-dlp", ToolStatus.UPDATED, "2026.09.20"), ("deno", ToolStatus.UPDATED, "2.9.7"),
    ]
    assert said == ["Скачивание yt-dlp 2026.09.20 с GitHub: 0 МБ…", "Скачивание deno 2.9.7 с GitHub: 0 МБ…"]
    assert tools.missing == ()


def test_install_missing_downloads_only_the_missing_one(livecraft_paths: LivecraftPaths) -> None:
    """yt-dlp на месте и проверять его пора — окно его не трогает: ни `-U`, ни GitHub; ставится только deno."""
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    github: FakeGitHub = FakeGitHub.releasing("v2.9.7", deno_zip(DENO_NEW))
    process: FakeTools = FakeTools(self_update_to="2026.09.20\n")
    updates: tuple[ToolUpdate, ...] = source_tools(livecraft_paths, process, github, clock_at()).install_missing()
    assert [update.tool for update in updates] == ["deno"]
    assert process.self_updates == 0 and YTDLP_RELEASE_URL not in github.requested
    assert livecraft_paths.file(FileName.YTDLP).read_text(encoding="utf-8") == YTDLP_NOW


def test_install_missing_with_both_in_place_does_nothing(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    github: FakeGitHub = FakeGitHub()
    process: FakeTools = FakeTools()
    tools: SourceTools = source_tools(livecraft_paths, process, github, clock_at())
    assert (tools.missing, tools.install_missing()) == ((), ())
    assert (process.calls, github.requested) == ([], [])


def test_install_missing_names_a_failed_download(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    [update] = source_tools(livecraft_paths, FakeTools(), FakeGitHub(), clock_at()).install_missing()
    assert (update.tool, update.status, update.problem) == ("yt-dlp", ToolStatus.NOT_CHECKED, ToolProblem.NO_ANSWER)
