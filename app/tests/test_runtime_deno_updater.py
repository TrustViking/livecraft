from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from app.paths import FileName, LivecraftPaths
from app.runtime.deno_updater import (
    DENO_CHECK_DAYS,
    DENO_RELEASE_URL,
    CheckMark,
    ToolProblem,
    ToolStatus,
    ToolUpdate,
)
from app.tests.fixtures.tools import (
    BROKEN,
    DENO_NOW,
    DENO_ZIP_URL,
    NOW,
    FakeGitHub,
    FakeGitHubResponse,
    FakeTools,
    clock_at,
    deno_updater,
    deno_zip,
    write_tool,
)
from app.ui import messages_ru as msg

DENO_NEW: str = "deno 2.9.7 (stable, release, x86_64-pc-windows-msvc)\n"


def _mark(paths: LivecraftPaths, days_ago: int) -> CheckMark:
    """Отметка проверки deno, поставленная `days_ago` суток назад."""
    mark: CheckMark = CheckMark(paths.file(FileName.DENO_CHECK), clock_at(NOW - timedelta(days=days_ago)))
    mark.write()
    return mark


def _deno_text(paths: LivecraftPaths) -> str:
    return paths.file(FileName.DENO).read_text(encoding="utf-8")


# --- отметка проверки


def test_without_a_mark_the_check_is_due(livecraft_paths: LivecraftPaths) -> None:
    assert CheckMark(livecraft_paths.file(FileName.DENO_CHECK), clock_at()).is_due(DENO_CHECK_DAYS)


def test_a_mark_younger_than_the_interval_is_not_due_and_an_older_one_is(livecraft_paths: LivecraftPaths) -> None:
    path: Path = livecraft_paths.file(FileName.DENO_CHECK)
    _mark(livecraft_paths, DENO_CHECK_DAYS - 1)
    assert not CheckMark(path, clock_at()).is_due(DENO_CHECK_DAYS)
    _mark(livecraft_paths, DENO_CHECK_DAYS)
    assert CheckMark(path, clock_at()).is_due(DENO_CHECK_DAYS)


def test_an_unreadable_mark_counts_as_no_mark(livecraft_paths: LivecraftPaths) -> None:
    path: Path = livecraft_paths.file(FileName.DENO_CHECK)
    for broken in ("не json", json.dumps({"last_check_ts": "вчера"}), json.dumps([1])):
        path.write_text(broken, encoding="utf-8")
        assert CheckMark(path, clock_at()).is_due(DENO_CHECK_DAYS)


def test_the_mark_keeps_the_epoch_seconds_of_now(livecraft_paths: LivecraftPaths) -> None:
    mark: CheckMark = _mark(livecraft_paths, 0)
    assert json.loads(mark.path.read_text(encoding="utf-8")) == {"last_check_ts": int(NOW.timestamp())}


# --- обновление deno


def test_a_fresh_mark_means_no_request(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    _mark(livecraft_paths, 1)
    github: FakeGitHub = FakeGitHub()
    tools: FakeTools = FakeTools()
    update: ToolUpdate = deno_updater(livecraft_paths, tools, github, clock_at()).update()
    assert (update.status, update.before, update.console_lines) == (ToolStatus.NOT_DUE, None, ())
    assert github.requested == []
    assert tools.calls == []


def test_the_latest_version_already_installed_is_fresh_and_marked(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    github: FakeGitHub = FakeGitHub.releasing("v2.9.6", b"")
    update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
    assert (update.status, update.after, update.console_lines) == (ToolStatus.FRESH, "2.9.6", ())
    assert github.requested == [DENO_RELEASE_URL]
    assert not CheckMark(livecraft_paths.file(FileName.DENO_CHECK), clock_at()).is_due(DENO_CHECK_DAYS)


def test_a_new_release_replaces_the_binary_and_says_so(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    github: FakeGitHub = FakeGitHub.releasing("v2.9.7", deno_zip(DENO_NEW))
    update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
    assert (update.status, update.before, update.after) == (ToolStatus.UPDATED, "2.9.6", "2.9.7")
    assert _deno_text(livecraft_paths) == DENO_NEW
    assert update.console_lines == (msg.TOOL_UPDATED.format(tool="deno", before="2.9.6", after="2.9.7"),)
    assert sorted(path.name for path in livecraft_paths.file(FileName.DENO).parent.iterdir()) == ["deno.exe"]


def test_a_missing_binary_is_downloaded_despite_a_fresh_mark(livecraft_paths: LivecraftPaths) -> None:
    _mark(livecraft_paths, 1)
    github: FakeGitHub = FakeGitHub.releasing("v2.9.7", deno_zip(DENO_NEW))
    update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
    assert (update.status, update.before, update.after) == (ToolStatus.UPDATED, None, "2.9.7")
    assert update.console_lines == (msg.TOOL_DOWNLOADED.format(tool="deno", after="2.9.7"),)


def test_without_network_the_working_binary_stays_and_the_mark_is_not_set(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    github: FakeGitHub = FakeGitHub()
    update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
    assert (update.status, update.problem, update.before) == (ToolStatus.NOT_CHECKED, ToolProblem.NO_ANSWER, "2.9.6")
    assert update.console_lines == (
        msg.TOOL_NOT_CHECKED.format(tool="deno", reason=msg.TOOL_PROBLEMS["no_answer"], version="2.9.6"),
    )
    assert len(github.requested) == 5 and len(github.sleeps) == 4      # первое обращение и четыре повтора
    assert _deno_text(livecraft_paths) == DENO_NOW
    assert not livecraft_paths.file(FileName.DENO_CHECK).exists()


def test_without_network_and_without_a_binary_the_line_says_the_next_run_tries_again(
    livecraft_paths: LivecraftPaths,
) -> None:
    update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), FakeGitHub(), clock_at()).update()
    assert update.console_lines == (msg.TOOL_UNUSABLE.format(tool="deno", reason=msg.TOOL_PROBLEMS["no_answer"]),)


def test_a_refusal_of_github_is_not_repeated(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    github: FakeGitHub = FakeGitHub({DENO_RELEASE_URL: [FakeGitHubResponse(403)]})
    update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
    assert (update.problem, github.requested, github.sleeps) == (ToolProblem.REFUSED, [DENO_RELEASE_URL], [])


def test_an_answer_without_a_tag_names_no_version(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    for payload in ({"name": "deno"}, {"tag_name": " "}, None):
        github: FakeGitHub = FakeGitHub({DENO_RELEASE_URL: [FakeGitHubResponse(200, payload)]})
        update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
        assert update.problem is ToolProblem.NO_VERSION


def test_a_broken_archive_does_not_touch_the_working_binary(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    for archive in (b"not a zip", deno_zip(DENO_NEW)[:40], deno_zip(DENO_NEW, member="other.exe")):
        github: FakeGitHub = FakeGitHub.releasing("v2.9.7", archive)
        update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
        assert (update.status, update.problem) == (ToolStatus.NOT_CHECKED, ToolProblem.BROKEN_DOWNLOAD)
        assert _deno_text(livecraft_paths) == DENO_NOW
    assert not livecraft_paths.file(FileName.DENO_CHECK).exists()


def test_a_downloaded_binary_that_does_not_name_the_release_is_thrown_away(livecraft_paths: LivecraftPaths) -> None:
    """Битая загрузка: файл из архива не запускается или называет не ту версию — рабочий на месте, временного нет."""
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    for exe_text in (BROKEN, "deno 2.9.5 (stable)\n"):
        github: FakeGitHub = FakeGitHub.releasing("v2.9.7", deno_zip(exe_text))
        update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
        assert update.problem is ToolProblem.BROKEN_DOWNLOAD
        assert _deno_text(livecraft_paths) == DENO_NOW
        assert sorted(path.name for path in livecraft_paths.file(FileName.DENO).parent.iterdir()) == ["deno.exe"]


def test_a_busy_github_is_asked_again(livecraft_paths: LivecraftPaths) -> None:
    write_tool(livecraft_paths, FileName.DENO, DENO_NOW)
    github: FakeGitHub = FakeGitHub.releasing("v2.9.6", b"")
    github.answers[DENO_RELEASE_URL].insert(0, FakeGitHubResponse(503))
    update: ToolUpdate = deno_updater(livecraft_paths, FakeTools(), github, clock_at()).update()
    assert (update.status, github.requested, len(github.sleeps)) == (ToolStatus.FRESH, [DENO_RELEASE_URL] * 2, 1)
    assert DENO_ZIP_URL not in github.requested


def test_every_problem_has_its_words() -> None:
    assert set(msg.TOOL_PROBLEMS) == {problem.value for problem in ToolProblem}
