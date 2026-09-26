from __future__ import annotations

import pytest

from app.run.flag import CliFlag
from app.run.mode import RunMode
from app.run.request import RunRequest
from app.ui import messages_ru as msg


@pytest.mark.parametrize(
    "argv",
    [
        ["--setup", "--check"],
        ["--setup", "--status"],
        ["--check", "--status"],
        ["--check", "--auth", "all"],
        ["--status", "--auth", "all"],
        ["--setup", "--auth", "all"],
        ["--announce", "--setup"],
        ["--broadcast", "--setup"],
        ["--from-package", "--setup"],
        ["--announce", "--broadcast"],
        ["--broadcast", "--from-package"],
        ["--announce", "--check"],
        ["--from-package", "--status"],
    ],
)
def test_two_modes_at_once_are_a_parse_error(argv: list[str]) -> None:
    """Режимы и --setup / --check / --auth / --status взаимоисключающие (CLAUDE.md §10)."""
    with pytest.raises(SystemExit) as raised:
        RunRequest.from_argv(argv)
    assert raised.value.code == 2


@pytest.mark.parametrize("argv", [["--publish-announcements"], ["--export-slots"], ["--export-slots", "slots.json"]])
def test_unknown_flags_are_a_parse_error(argv: list[str]) -> None:
    """Выгрузка слотов — это пакет plan_*.bcast (§14 решение 13): ключа --export-slots больше нет, код 2."""
    with pytest.raises(SystemExit) as raised:
        RunRequest.from_argv(argv)
    assert raised.value.code == 2


def test_every_run_flag_is_understood() -> None:
    request: RunRequest = RunRequest.from_argv(["--dry-run", "--no-llm", "--debug"])
    assert request == RunRequest(mode=RunMode.ALL, auth_handle=None, dry_run=True, no_llm=True, debug=True)
    assert not request.mode.is_service


def test_a_request_without_flags_is_the_full_cycle() -> None:
    assert RunRequest.from_argv([]) == RunRequest(
        mode=RunMode.ALL, auth_handle=None, dry_run=False, no_llm=False, debug=False
    )


@pytest.mark.parametrize(
    ("argv", "mode"),
    [
        (["--announce"], RunMode.ANNOUNCE),
        (["--broadcast"], RunMode.BROADCAST),
        (["--from-package"], RunMode.FROM_PACKAGE),
        (["--setup"], RunMode.SETUP),
        (["--check"], RunMode.CHECK),
        (["--status"], RunMode.STATUS),
        (["--auth", "all"], RunMode.AUTH),
        ([], RunMode.ALL),
    ],
)
def test_the_flag_chooses_the_mode(argv: list[str], mode: RunMode) -> None:
    request: RunRequest = RunRequest.from_argv(argv)
    assert request.mode is mode
    assert request.log_fields["mode"] is mode


def test_auth_keeps_the_handle_even_when_it_is_empty() -> None:
    """Ник — значение ключа как есть; пустой ник — всё равно запрос входа, а не режим «всё»."""
    assert RunRequest.from_argv(["--auth", "@Osvald.X"]).auth_handle == "@Osvald.X"
    empty: RunRequest = RunRequest.from_argv(["--auth", ""])
    assert empty.mode is RunMode.AUTH and empty.auth_handle == ""


def test_the_log_fields_quote_the_channel_handle() -> None:
    """Имя канала в логе — в кавычках (CLAUDE.md §11); без ника — пусто."""
    assert RunRequest.from_argv(["--auth", "@Osvald.X"]).log_fields["auth"] == '"@Osvald.X"'
    assert RunRequest.from_argv([]).log_fields["auth"] is None


def test_help_lists_every_flag_with_its_text(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        RunRequest.from_argv(["--help"])
    assert raised.value.code == 0
    out: str = capsys.readouterr().out
    assert out.startswith("usage: livecraft")
    for flag in CliFlag:
        assert flag.value in out
    assert msg.CLI_METAVAR_HANDLE in out


def test_version_prints_the_version_text(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        RunRequest.from_argv(["--version"])
    assert raised.value.code == 0
    assert capsys.readouterr().out.strip().startswith("Livecraft ")


def test_every_flag_has_help_and_the_dest_argparse_gives_it() -> None:
    for flag in CliFlag:
        assert flag.help
        assert flag.dest == flag.value.removeprefix("--").replace("-", "_")
    assert [flag for flag in CliFlag if flag.takes_value] == [CliFlag.AUTH]
