from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.runtime.ytdlp_launch import YtDlpLaunch
from app.tests.fixtures.logs import LogCapture

COOKIES_TEXT: bytes = b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n"


def _with_cookies(paths: LivecraftPaths) -> YtDlpLaunch:
    paths.file(FileName.COOKIES).write_bytes(COOKIES_TEXT)
    return YtDlpLaunch.of(paths)


def _copies(paths: LivecraftPaths) -> list[Path]:
    return list(paths.file(FileName.COOKIES).parent.glob("livecraft_cookies_*"))


def test_the_launch_takes_the_exe_the_cookies_and_both_caches_of_the_root(livecraft_paths: LivecraftPaths) -> None:
    """Кэш yt-dlp и deno — в state\\: удаление программы уносит их вместе с ней (§14 решение 56)."""
    launch: YtDlpLaunch = YtDlpLaunch.of(livecraft_paths)
    assert launch == YtDlpLaunch(
        exe=livecraft_paths.root / "tools" / "yt-dlp.exe",
        cookies=livecraft_paths.root / "secrets" / "cookies.txt",
        cache_dir=livecraft_paths.root / "state" / "yt-dlp-cache",
        deno_dir=livecraft_paths.root / "state" / "deno-cache",
    )


def test_the_command_puts_the_cache_folder_right_after_the_exe(livecraft_paths: LivecraftPaths) -> None:
    launch: YtDlpLaunch = YtDlpLaunch.of(livecraft_paths)
    assert launch.command(("--flat-playlist", "URL")) == [
        str(livecraft_paths.file(FileName.YTDLP)), "--cache-dir", str(livecraft_paths.file(FileName.YTDLP_CACHE)),
        "--flat-playlist", "URL",
    ]


def test_the_environment_is_the_process_one_plus_the_deno_folder(livecraft_paths: LivecraftPaths) -> None:
    env: dict[str, str] = YtDlpLaunch.of(livecraft_paths).env
    assert env["DENO_DIR"] == str(livecraft_paths.file(FileName.DENO_CACHE))
    assert {key: value for key, value in env.items() if key != "DENO_DIR"} == {
        key: value for key, value in os.environ.items() if key != "DENO_DIR"
    }


def test_the_cookies_copy_lies_in_secrets_and_is_gone_after_the_call(livecraft_paths: LivecraftPaths) -> None:
    launch: YtDlpLaunch = _with_cookies(livecraft_paths)
    with launch.cookies_copy() as copy:
        assert copy is not None
        assert copy.parent == livecraft_paths.file(FileName.COOKIES).parent
        assert copy != launch.cookies
        assert copy.read_bytes() == COOKIES_TEXT
    assert not copy.exists()
    assert _copies(livecraft_paths) == []


def test_the_cookies_copy_is_gone_after_a_failed_call(livecraft_paths: LivecraftPaths) -> None:
    launch: YtDlpLaunch = _with_cookies(livecraft_paths)
    with pytest.raises(RuntimeError):
        with launch.cookies_copy() as copy:
            assert copy is not None
            raise RuntimeError("yt-dlp interrupted")
    assert _copies(livecraft_paths) == []
    assert launch.cookies.read_bytes() == COOKIES_TEXT


def test_without_cookies_there_is_no_copy(livecraft_paths: LivecraftPaths) -> None:
    with YtDlpLaunch.of(livecraft_paths).cookies_copy() as copy:
        assert copy is None


def test_a_copy_that_fails_is_none_and_a_log_line(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нет места или файл занят — вызов идёт без cookies, недоделанной копии не остаётся, причина — в лог."""
    launch: YtDlpLaunch = _with_cookies(livecraft_paths)

    def _deny(source: Path, target: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr("app.runtime.ytdlp_launch.shutil.copyfile", _deny)
    with LogCapture.on(LogArea.RUNTIME) as log:
        with launch.cookies_copy() as copy:
            assert copy is None
    assert log.messages(logging.WARNING) == ["ytdlp_cookies_copy_failed error=PermissionError"]
    assert _copies(livecraft_paths) == []
