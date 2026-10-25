from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.runtime.cookies_file import NETSCAPE_HEADER
from app.runtime.cookies_updater import CookiesCheck, CookiesLogin, CookiesLoginProbe, CookiesState, CookiesStatus
from app.runtime.ytdlp_launch import YtDlpLaunch
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.tools import NOW, REMIND_DAYS, clock_at, cookies_check

LOGIN_EXPIRES: datetime = NOW + timedelta(days=400)
COOKIES_TEXT: str = (
    NETSCAPE_HEADER + "\n"
    ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n"
    f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t{int(LOGIN_EXPIRES.timestamp())}\t__Secure-3PAPISID\tvalue\n"
    f".youtube.com\tTRUE\t/\tTRUE\t{int((NOW + timedelta(days=30)).timestamp())}\tSAPISID\tvalue\n"
)
NO_LOGIN_TEXT: str = NETSCAPE_HEADER + "\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n.google.com\tTRUE\t/\tTRUE\t0\tSAPISID\tv\n"
SHOWN: str = "secrets\\cookies.txt"
WIDTH: int = 90       # строки окна — не шире (§14 решение 63)


def _cookies(paths: LivecraftPaths, text: str = COOKIES_TEXT, days_ago: int = 1) -> Path:
    """Файл cookies, выгруженный `days_ago` суток назад (время записи файла)."""
    path: Path = paths.file(FileName.COOKIES)
    path.write_text(text, encoding="utf-8")
    stamp: float = (NOW - timedelta(days=days_ago)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def _status(paths: LivecraftPaths, remind_days: int = REMIND_DAYS) -> CookiesStatus:
    return cookies_check(paths, clock_at(), remind_days).status()


def _expired_text() -> str:
    gone: int = int((NOW - timedelta(days=2)).timestamp())
    return NETSCAPE_HEADER + f"\n.youtube.com\tTRUE\t/\tTRUE\t{gone}\tSAPISID\tvalue\n"


def _checked_line(status: CookiesStatus) -> tuple[int, str]:
    """Строка лога `cookies_checked` проверки `status`: уровень и текст."""
    with LogCapture.on(LogArea.RUNTIME) as log:
        status.log()
    return log.records[0].levelno, log.records[0].getMessage()


def test_the_check_holds_only_the_file_the_clock_the_path_and_the_reminder(livecraft_paths: LivecraftPaths) -> None:
    """Проба входа ушла (решение 73, поправка 18-10-2026): проверке не нужен ни yt-dlp, ни отметка в state\\."""
    check: CookiesCheck = cookies_check(livecraft_paths, clock_at())
    assert (check.file.path, check.shown, check.remind_days) == (
        livecraft_paths.file(FileName.COOKIES), SHOWN, REMIND_DAYS
    )
    assert set(CookiesCheck.__dataclass_fields__) == {"file", "clock", "shown", "remind_days"}


def test_no_cookies_file_is_fine_and_silent(livecraft_paths: LivecraftPaths) -> None:
    status: CookiesStatus = _status(livecraft_paths)
    assert status.state is CookiesState.ABSENT
    assert status.window_lines == (f"✗ Файла cookies нет ({SHOWN}) — загрузите его кнопкой «Загрузить файл…».",)
    assert _checked_line(status)[0] == logging.INFO


def test_a_file_of_the_wrong_form_goes_to_the_log_only(livecraft_paths: LivecraftPaths) -> None:
    """Не тот вид: человеку запуск ничего не говорит, причина — предупреждением в логе; окно называет вид."""
    _cookies(livecraft_paths, "\n\n.youtube.com\tTRUE\t/\n")
    status: CookiesStatus = _status(livecraft_paths)
    assert (status.state, status.is_ok) == (CookiesState.BAD_FORMAT, False)
    assert status.window_lines == (
        f"✓ Файл cookies: {SHOWN}",
        f"✗ Не тот вид: первой строкой должно быть «{NETSCAPE_HEADER}»",
    )
    level, line = _checked_line(status)
    assert level == logging.WARNING and line.startswith("cookies_checked state=bad_format")


def test_a_bom_and_blank_lines_before_the_header_are_fine(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths)
    livecraft_paths.file(FileName.COOKIES).write_bytes(b"\xef\xbb\xbf\n" + COOKIES_TEXT.encode())
    assert _status(livecraft_paths).state is CookiesState.READY


def test_a_file_without_login_cookies_goes_to_the_log_only(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths, NO_LOGIN_TEXT)
    status: CookiesStatus = _status(livecraft_paths)
    assert status.state is CookiesState.NO_LOGIN
    assert status.window_lines[-1] == "✗ Cookies входа в аккаунт YouTube: нет — выгрузите их после входа в YouTube"
    level, line = _checked_line(status)
    assert level == logging.WARNING and line.startswith("cookies_checked state=no_login")


def test_expired_login_cookies_go_to_the_log_only_and_the_window_names_the_date(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths, _expired_text())
    status: CookiesStatus = _status(livecraft_paths)
    assert status.state is CookiesState.EXPIRED
    assert status.window_lines[-1] == "✗ Cookies входа в аккаунт YouTube: срок истёк 27.09.2026"
    assert _checked_line(status)[0] == logging.WARNING


def test_fresh_cookies_with_a_login_are_silent_and_have_no_sign_in_line(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths, days_ago=REMIND_DAYS)
    status: CookiesStatus = _status(livecraft_paths)
    assert (status.age_days, status.is_ok) == (REMIND_DAYS, True)
    assert status.login_expires == LOGIN_EXPIRES.replace(microsecond=0)      # самый поздний срок cookies входа
    assert status.window_lines == (
        f"✓ Файл cookies: {SHOWN}",
        "✓ Вид: Netscape",
        "✓ Выгружены 22.09.2026, 7 сут. назад; срок напоминания — 7 сут.",
        "✓ Cookies входа в аккаунт YouTube: есть, действуют до 03.11.2027",
    )
    assert _checked_line(status)[0] == logging.INFO


def test_a_finished_reminder_is_a_window_line_and_a_log_warning(livecraft_paths: LivecraftPaths) -> None:
    """Срок напоминания — из настроек (`cookies.remind_days`); закончился — в окне «✗» с датой и действием, в логе —
    предупреждение; запуск о cookies не пишет (§14 решение 80)."""
    _cookies(livecraft_paths, days_ago=4)
    status: CookiesStatus = _status(livecraft_paths, remind_days=3)
    assert status.is_stale
    assert status.window_lines[2] == (
        "✗ Выгружены 25.09.2026 (4 сут.): срок напоминания 3 сут. закончился — выгрузите новые"
    )
    assert not status.is_ok and _checked_line(status)[0] == logging.WARNING
    assert not _status(livecraft_paths, remind_days=4).is_stale


def test_every_window_line_fits_the_width() -> None:
    """Строки окна не шире 90 знаков — при всех исходах, со строкой входа (§14 решение 63)."""
    statuses: list[CookiesStatus] = [CookiesStatus(SHOWN, state, 30, NOW, 365, NOW) for state in CookiesState]
    statuses += [CookiesStatus(SHOWN, state, 30) for state in CookiesState]
    lines: list[str] = [line for status in statuses for line in status.window_lines]
    lines += [line for login in CookiesLogin for line in login.window_line.split("\n")]
    assert lines and max(len(line) for line in lines) <= WIDTH


# --- вход в YouTube по cookies — только по кнопке окна (§14 решение 80)


class _Run:
    """Подделка subprocess.run для проверки входа: ответ yt-dlp или исключение; команды и копия cookies запоминаются."""

    def __init__(self, returncode: int = 0, stderr: str = "", error: BaseException | None = None) -> None:
        self.returncode: int = returncode
        self.stderr: str = stderr
        self.error: BaseException | None = error
        self.commands: list[list[str]] = []
        self.copies: list[Path] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        self.copies.append(Path(command[command.index("--cookies") + 1]))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(command, self.returncode, stdout="", stderr=self.stderr)


def _probe(paths: LivecraftPaths, run: _Run, with_ytdlp: bool = True) -> CookiesLoginProbe:
    if with_ytdlp:
        paths.file(FileName.YTDLP).write_bytes(b"")
    return CookiesLoginProbe(YtDlpLaunch.of(paths), run)


@pytest.mark.parametrize(
    ("run", "login"),
    [
        (_Run(0), CookiesLogin.LOGGED_IN),
        (_Run(0, "WARNING: [youtube] The provided YouTube account cookies are no longer valid."), CookiesLogin.NO_LOGIN),
        (_Run(1, "ERROR: [youtube:history] :ythistory: Login details are needed to download"), CookiesLogin.NO_LOGIN),
        (_Run(1, "ERROR: Unable to download webpage: HTTP Error 500"), CookiesLogin.UNKNOWN),
        (_Run(error=subprocess.TimeoutExpired(["yt-dlp"], 30)), CookiesLogin.UNKNOWN),
    ],
)
def test_the_login_is_asked_of_youtube_with_a_copy_of_the_cookies(
    livecraft_paths: LivecraftPaths, run: _Run, login: CookiesLogin
) -> None:
    """Годные cookies входа — yt-dlp открывает ленту вошедшего `:ythistory` с копией cookies; копия удаляется."""
    _cookies(livecraft_paths)
    assert _probe(livecraft_paths, run).login(_status(livecraft_paths)) is login
    [command] = run.commands
    assert command[-6:] == ["--flat-playlist", "--playlist-items", "1", "--print", "id", ":ythistory"]
    assert run.copies[0].parent == livecraft_paths.file(FileName.COOKIES).parent and not run.copies[0].exists()


@pytest.mark.parametrize("text", [None, "\n.youtube.com\tTRUE\t/\n", NO_LOGIN_TEXT])
def test_without_usable_login_cookies_there_is_no_login_and_youtube_is_not_asked(
    livecraft_paths: LivecraftPaths, text: str | None
) -> None:
    """Файла нет, не тот вид, нет cookies входа — входа нет без вызова yt-dlp."""
    if text is not None:
        _cookies(livecraft_paths, text)
    run: _Run = _Run(0)
    assert _probe(livecraft_paths, run).login(_status(livecraft_paths)) is CookiesLogin.NO_LOGIN
    assert run.commands == []


def test_without_ytdlp_the_login_could_not_be_checked(livecraft_paths: LivecraftPaths) -> None:
    _cookies(livecraft_paths)
    run: _Run = _Run(0)
    assert _probe(livecraft_paths, run, with_ytdlp=False).login(_status(livecraft_paths)) is CookiesLogin.UNKNOWN
    assert run.commands == []


def test_the_login_lines_say_the_program_works_either_way() -> None:
    assert CookiesLogin.LOGGED_IN.window_line == "Вход в YouTube есть: yt-dlp прочтёт и описания видео 18+."
    assert CookiesLogin.NO_LOGIN.window_line == (
        "Входа в YouTube нет — работе программы это не мешает:\nбез входа недоступны только описания видео 18+."
    )
    assert "не мешает" in CookiesLogin.UNKNOWN.window_line
