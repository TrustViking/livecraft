from __future__ import annotations

import os
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from app.paths import FileName, LivecraftPaths
from app.runtime.deno_updater import CheckMark
from app.runtime.cookies_updater import (
    COOKIES_PROBE_DAYS,
    COOKIES_WARN_DAYS,
    NETSCAPE_HEADER,
    CookiesCheck,
    CookiesLogin,
    CookiesState,
    CookiesStatus,
    LoginProbe,
)
from app.tests.fixtures.tools import NOW, YTDLP_NOW, FakeTools, clock_at, cookies_check, write_tool
from app.ui import messages_ru as msg

COOKIES_TEXT: str = NETSCAPE_HEADER + "\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n"
SHOWN: str = "secrets\\cookies.txt"


def _cookies(paths: LivecraftPaths, text: str = COOKIES_TEXT, days_ago: int = 1) -> Path:
    """Файл cookies, выгруженный `days_ago` суток назад (время записи файла)."""
    path: Path = paths.file(FileName.COOKIES)
    path.write_text(text, encoding="utf-8")
    stamp: float = (NOW - timedelta(days=days_ago)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def _status(paths: LivecraftPaths, tools: FakeTools) -> CookiesStatus:
    return cookies_check(paths, tools, clock_at()).status()


def test_no_cookies_file_is_fine_and_silent(livecraft_paths: LivecraftPaths) -> None:
    status: CookiesStatus = _status(livecraft_paths, FakeTools())
    assert (status.state, status.stops, status.console_lines) == (CookiesState.ABSENT, False, ())


def test_a_file_of_the_wrong_form_stops_and_says_how_to_export_again(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths, "\n\n.youtube.com\tTRUE\t/\n")
    tools: FakeTools = FakeTools()
    status: CookiesStatus = _status(livecraft_paths, tools)
    assert (status.state, status.stops) == (CookiesState.BAD_FORMAT, True)
    assert status.console_lines == (
        msg.COOKIES_BAD_FORMAT.format(path=SHOWN, header=NETSCAPE_HEADER),
        msg.COOKIES_REEXPORT.format(path=SHOWN),
    )
    assert tools.calls == []


def test_a_bom_and_blank_lines_before_the_header_are_fine(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths)
    livecraft_paths.file(FileName.COOKIES).write_bytes(b"\xef\xbb\xbf\n" + COOKIES_TEXT.encode())
    assert _status(livecraft_paths, FakeTools()).state is CookiesState.READY


def test_fresh_cookies_with_a_login_are_silent(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths, days_ago=COOKIES_WARN_DAYS)
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    tools: FakeTools = FakeTools()
    status: CookiesStatus = _status(livecraft_paths, tools)
    assert (status.age_days, status.probe.login, status.console_lines) == (
        COOKIES_WARN_DAYS, CookiesLogin.LOGGED_IN, ()
    )
    probe: list[str] = tools.calls[0]
    copy: Path = Path(probe[probe.index("--cookies") + 1])
    assert probe[-1] == ":ythistory" and copy != livecraft_paths.file(FileName.COOKIES)
    assert not copy.exists()        # копия cookies убрана


def test_stale_cookies_name_the_export_date_and_the_limit(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths, days_ago=COOKIES_WARN_DAYS + 1)
    status: CookiesStatus = _status(livecraft_paths, FakeTools())
    assert status.probe.login is CookiesLogin.NOT_CHECKED      # yt-dlp нет — вход не проверяется
    assert status.console_lines == (
        msg.COOKIES_STALE.format(date="13.09.2026", days=COOKIES_WARN_DAYS + 1, limit=COOKIES_WARN_DAYS),
        msg.COOKIES_REEXPORT.format(path=SHOWN),
    )


def test_a_failed_login_says_why_and_how_to_export_again(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths)
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    stderr: str = "ERROR: [youtube] The provided YouTube account cookies are no longer valid."
    status: CookiesStatus = _status(livecraft_paths, FakeTools(probe_code=1, probe_stderr=stderr))
    assert status.console_lines == (
        msg.COOKIES_LOGIN_FAILED.format(reason=msg.COOKIES_LOGIN_FAILURES["invalid"]),
        msg.COOKIES_REEXPORT.format(path=SHOWN),
    )
    assert not status.stops


@pytest.mark.parametrize(
    ("code", "stderr", "login"),
    [
        (0, "", CookiesLogin.LOGGED_IN),
        (0, "WARNING: [youtube:tab] The provided YouTube account cookies are no longer valid", CookiesLogin.INVALID),
        (1, "ERROR: The provided YouTube account cookies are no longer valid", CookiesLogin.INVALID),
        (1, "ERROR: This feed is only available when logged in. Login details are needed", CookiesLogin.NO_AUTH),
        (1, "ERROR: Unable to download webpage", CookiesLogin.UNKNOWN),
        (1, "", CookiesLogin.UNKNOWN),
    ],
)
def test_the_login_probe_reads_the_markers_then_the_code(code: int, stderr: str, login: CookiesLogin) -> None:
    probe: LoginProbe = LoginProbe.of(code, stderr)
    assert (probe.login, probe.exit_code) == (login, code)


def test_only_a_refused_login_needs_a_person() -> None:
    assert {login for login in CookiesLogin if login.is_failed} == {CookiesLogin.INVALID, CookiesLogin.NO_AUTH}
    assert set(msg.COOKIES_LOGIN_FAILURES) == {CookiesLogin.INVALID.value, CookiesLogin.NO_AUTH.value}


def _recording_check(paths: LivecraftPaths, tools: FakeTools, seen: list[dict[str, object]]) -> CookiesCheck:
    """Проверка cookies, чей запуск процесса записывает ключи вызова в `seen` и отвечает как `tools`."""

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        seen.append(options)
        return tools.run(command, **options)

    built: CookiesCheck = CookiesCheck.of(paths, clock_at())
    return CookiesCheck(built.launch, built.clock, built.shown, built.mark, run=run)


def test_the_probe_keeps_the_cache_and_the_cookies_copy_in_the_program_folder(livecraft_paths: LivecraftPaths) -> None:
    """Кэш yt-dlp и deno — в state\\, копия cookies — в secrets\\: удаление программы уносит их (§14 решение 56)."""
    _cookies(livecraft_paths)
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    tools: FakeTools = FakeTools()
    seen: list[dict[str, object]] = []
    assert _recording_check(livecraft_paths, tools, seen).status().probe.login is CookiesLogin.LOGGED_IN
    probe: list[str] = tools.calls[0]
    cookies: Path = livecraft_paths.file(FileName.COOKIES)
    cache: str = str(livecraft_paths.file(FileName.YTDLP_CACHE))
    assert probe[:3] == [str(livecraft_paths.file(FileName.YTDLP)), "--cache-dir", cache]
    assert Path(probe[probe.index("--cookies") + 1]).parent == cookies.parent
    assert list(cookies.parent.glob("livecraft_cookies_*")) == []
    env: object = seen[0]["env"]
    assert isinstance(env, dict) and env["DENO_DIR"] == str(livecraft_paths.file(FileName.DENO_CACHE))


def test_a_cookies_copy_that_fails_is_an_unclear_login_without_a_call_or_a_mark(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Копия не сделалась — вход не проверен, отметки нет: следующий запуск проверит снова."""
    _cookies(livecraft_paths)
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)

    def _deny(source: Path, target: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr("app.runtime.ytdlp_launch.shutil.copyfile", _deny)
    tools: FakeTools = FakeTools()
    status: CookiesStatus = _status(livecraft_paths, tools)
    assert (status.probe.login, status.probe.detail) == (CookiesLogin.UNKNOWN, "ytdlp_cookies_copy_failed")
    assert tools.calls == []
    assert not livecraft_paths.file(FileName.COOKIES_CHECK).exists()


# --- когда проверять вход


def _probe_mark(paths: LivecraftPaths, hours_ago: int) -> CheckMark:
    mark: CheckMark = CheckMark(paths.file(FileName.COOKIES_CHECK), clock_at(NOW - timedelta(hours=hours_ago)))
    mark.write()
    return mark


def _exported(paths: LivecraftPaths, hours_ago: int) -> None:
    """Файл cookies, выгруженный `hours_ago` часов назад."""
    _cookies(paths)
    stamp: float = (NOW - timedelta(hours=hours_ago)).timestamp()
    os.utime(paths.file(FileName.COOKIES), (stamp, stamp))


def test_a_fresh_login_mark_over_older_cookies_means_no_probe(livecraft_paths: LivecraftPaths) -> None:
    """Вход по тем же cookies уже подтверждён меньше суток назад — yt-dlp не зовётся (под нагрузкой — до 30 с)."""
    _exported(livecraft_paths, hours_ago=30)
    _probe_mark(livecraft_paths, hours_ago=COOKIES_PROBE_DAYS * 24 - 1)
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    tools: FakeTools = FakeTools()
    status: CookiesStatus = _status(livecraft_paths, tools)
    assert (status.probe.login, status.console_lines, tools.calls) == (CookiesLogin.NOT_CHECKED, (), [])


def test_cookies_exported_after_the_mark_are_probed(livecraft_paths: LivecraftPaths) -> None:
    _probe_mark(livecraft_paths, hours_ago=3)
    _exported(livecraft_paths, hours_ago=1)
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    tools: FakeTools = FakeTools()
    assert _status(livecraft_paths, tools).probe.login is CookiesLogin.LOGGED_IN
    assert len(tools.calls) == 1


def test_a_day_old_mark_is_probed_again(livecraft_paths: LivecraftPaths) -> None:
    _exported(livecraft_paths, hours_ago=30)
    _probe_mark(livecraft_paths, hours_ago=COOKIES_PROBE_DAYS * 24)
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    assert _status(livecraft_paths, FakeTools()).probe.login is CookiesLogin.LOGGED_IN


@pytest.mark.parametrize(
    ("code", "stderr", "marked"),
    [
        (0, "", True),
        (0, "WARNING: The provided YouTube account cookies are no longer valid", False),
        (1, "ERROR: Unable to download webpage", False),
    ],
)
def test_only_a_login_leaves_the_mark(livecraft_paths: LivecraftPaths, code: int, stderr: str, marked: bool) -> None:
    """Отказ и неясный итог отметки не ставят: следующий запуск проверит вход снова."""
    _cookies(livecraft_paths)
    write_tool(livecraft_paths, FileName.YTDLP, YTDLP_NOW)
    _status(livecraft_paths, FakeTools(probe_code=code, probe_stderr=stderr))
    assert livecraft_paths.file(FileName.COOKIES_CHECK).is_file() is marked
