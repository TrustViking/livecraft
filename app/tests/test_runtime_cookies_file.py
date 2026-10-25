from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.paths import FileName, LivecraftPaths
from app.runtime.cookies_file import NETSCAPE_HEADER, CookiesFile, CookiesPlaceProblem, NetscapeCookie
from app.ui import messages_ru as msg

ZONE: timezone = timezone(timedelta(hours=3))
EXPORTED: datetime = datetime(2026, 10, 10, 9, 30, tzinfo=ZONE)
LATEST: datetime = datetime(2027, 11, 3, 12, 0, tzinfo=ZONE)
LOGIN_TEXT: str = (
    NETSCAPE_HEADER + "\n# комментарий\n\n"
    ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tv\n"
    f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t{int(LATEST.timestamp())}\t__Secure-1PAPISID\tv\n"
    f".youtube.com\tTRUE\t/\tTRUE\t{int((LATEST - timedelta(days=9)).timestamp())}\tSAPISID\tv\n"
    f".google.com\tTRUE\t/\tTRUE\t{int((LATEST + timedelta(days=9)).timestamp())}\tSAPISID\tv\n"
)


def _write(path: Path, text: str, moment: datetime = EXPORTED) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (moment.timestamp(), moment.timestamp()))
    return path


def _file(paths: LivecraftPaths) -> CookiesFile:
    return CookiesFile(paths.file(FileName.COOKIES), ZONE)


def test_the_header_line_decides_the_form(livecraft_paths: LivecraftPaths) -> None:
    file: CookiesFile = _file(livecraft_paths)
    _write(file.path, "\n\n" + LOGIN_TEXT)
    assert file.exists and file.is_netscape
    _write(file.path, ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tv\n" + NETSCAPE_HEADER)
    assert not file.is_netscape


def test_the_export_date_is_the_file_time_in_the_program_zone(livecraft_paths: LivecraftPaths) -> None:
    file: CookiesFile = _file(livecraft_paths)
    _write(file.path, LOGIN_TEXT)
    assert file.exported == EXPORTED and file.exported.utcoffset() == timedelta(hours=3)


def test_login_cookies_are_youtube_cookies_by_name_and_give_the_latest_term(livecraft_paths: LivecraftPaths) -> None:
    """Cookies входа — youtube.com с именами ресурса (и для HTTP с `#HttpOnly_`); чужой домен и SID не входят."""
    file: CookiesFile = _file(livecraft_paths)
    _write(file.path, LOGIN_TEXT)
    assert [cookie.name for cookie in file.login_cookies] == ["__Secure-1PAPISID", "SAPISID"]
    assert file.login_expires == LATEST


def test_no_login_cookies_or_only_session_ones_give_no_term(livecraft_paths: LivecraftPaths) -> None:
    file: CookiesFile = _file(livecraft_paths)
    _write(file.path, NETSCAPE_HEADER + "\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tv\n")
    assert (file.login_cookies, file.login_expires) == ((), None)
    _write(file.path, NETSCAPE_HEADER + "\n.youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PAPISID\tv\n")
    assert (len(file.login_cookies), file.login_expires) == (1, None)


@pytest.mark.parametrize("line", ["", "# comment", ".youtube.com\tTRUE\t/", ".youtube.com\tTRUE\t/\tTRUE\tsoon\tSAPISID\tv"])
def test_a_comment_or_broken_line_is_no_cookie(line: str) -> None:
    assert NetscapeCookie.of_line(line) is None


def test_loading_copies_the_file_with_its_export_time(livecraft_paths: LivecraftPaths, tmp_path: Path) -> None:
    source: Path = _write(tmp_path / "Downloads" / "www.youtube.com_cookies.txt", LOGIN_TEXT)
    file: CookiesFile = _file(livecraft_paths)
    assert file.place_from(source) is None
    assert file.path.read_text(encoding="utf-8") == LOGIN_TEXT and file.exported == EXPORTED
    assert source.is_file()


def test_a_file_of_another_form_is_not_loaded_and_the_old_one_stays(
    livecraft_paths: LivecraftPaths, tmp_path: Path
) -> None:
    file: CookiesFile = _file(livecraft_paths)
    _write(file.path, LOGIN_TEXT)
    source: Path = _write(tmp_path / "cookies.json", '[{"name": "SAPISID"}]')
    assert file.place_from(source) is CookiesPlaceProblem.NOT_NETSCAPE
    assert file.path.read_text(encoding="utf-8") == LOGIN_TEXT


def test_an_unreadable_source_is_named(livecraft_paths: LivecraftPaths, tmp_path: Path) -> None:
    assert _file(livecraft_paths).place_from(tmp_path / "missing.txt") is CookiesPlaceProblem.UNREADABLE


def test_loading_the_file_itself_copies_nothing(livecraft_paths: LivecraftPaths) -> None:
    file: CookiesFile = _file(livecraft_paths)
    _write(file.path, LOGIN_TEXT)
    assert file.place_from(file.path) is None
    assert file.exported == EXPORTED
    assert [path.name for path in file.path.parent.iterdir()] == [file.path.name]


def test_every_load_problem_has_words() -> None:
    assert set(msg.COOKIES_PLACE_PROBLEMS) == {problem.value for problem in CookiesPlaceProblem}
