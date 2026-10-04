from __future__ import annotations

from datetime import timedelta

from app.paths import FileName, LivecraftPaths
from app.runtime.deno_updater import CheckMark, ToolProblem, ToolStatus, ToolUpdate
from app.runtime.ytdlp_updater import YTDLP_CHECK_DAYS, SourceToolsCheck
from app.tests.fixtures.tools import (
    DENO_NOW,
    NOW,
    YTDLP_NOW,
    FakeGitHub,
    FakeTools,
    clock_at,
    source_tools,
    write_tool,
    ytdlp_updater,
)
from app.ui import messages_ru as msg


def _mark(paths: LivecraftPaths, name: FileName, days_ago: int) -> None:
    CheckMark(paths.file(name), clock_at(NOW - timedelta(days=days_ago))).write()


def test_a_missing_ytdlp_names_what_to_do_and_is_not_started(livecraft_paths: LivecraftPaths) -> None:
    tools: FakeTools = FakeTools()
    update: ToolUpdate = ytdlp_updater(livecraft_paths, tools, clock_at()).update()
    assert update.status is ToolStatus.MISSING
    assert update.console_lines == (msg.TOOL_MISSING.format(tool="yt-dlp"),)
    assert tools.calls == []


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
    check: SourceToolsCheck = source_tools(livecraft_paths, tools, FakeGitHub(), clock_at()).refresh()
    assert [update.status for update in check.updates] == [ToolStatus.UPDATED, ToolStatus.NOT_DUE]
    assert check.console_lines == (msg.TOOL_UPDATED.format(tool="yt-dlp", before="2026.08.19", after="2026.09.20"),)
    assert not check.stops


def test_source_tools_stop_on_a_cookies_file_of_the_wrong_form(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    for name in (FileName.YTDLP_CHECK, FileName.DENO_CHECK):
        _mark(livecraft_paths, name, 1)
    livecraft_paths.file(FileName.COOKIES).write_text("youtube.com\tTRUE\t/\n", encoding="utf-8")
    check: SourceToolsCheck = source_tools(livecraft_paths, FakeTools(), FakeGitHub(), clock_at()).refresh()
    assert check.stops
    assert check.console_lines[0].startswith("Файл cookies secrets\\cookies.txt — не того вида")
