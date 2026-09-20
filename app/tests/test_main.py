from __future__ import annotations

import io
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.main import ExitCode, RunRequest, build_parser, run_cli
from app.observability.logging_setup import close_logging
from app.paths import ROOT_ENV_VAR
from app.ui import messages_ru as msg
from app.version import APP_VERSION

LOG_GLOB: str = "*_livecraft.log"


@pytest.fixture(autouse=True)
def _closed_logging() -> Iterator[None]:
    """Лог запуска закрывается и в тестах: иначе Windows не отдаст tmp_path."""
    yield
    close_logging()


@pytest.fixture
def livecraft_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Корень как после установки без настройки: ни сейфа, ни конфигов (CLAUDE.md §8)."""
    root: Path = tmp_path / "root"
    monkeypatch.setenv(ROOT_ENV_VAR, str(root))
    return root


def test_version_flag_prints_the_single_version_and_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    """--version ничего не читает: ни корня, ни конфигов, ни сети (CLAUDE.md §10)."""
    with pytest.raises(SystemExit) as raised:
        run_cli(["--version"])
    assert raised.value.code == 0
    out: str = capsys.readouterr().out
    assert out.strip() == msg.VERSION_TEXT.format(version=APP_VERSION)
    assert out.startswith("Livecraft ")


def test_version_flag_creates_no_folders(livecraft_root: Path) -> None:
    with pytest.raises(SystemExit):
        run_cli(["--version"])
    assert not livecraft_root.exists()


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--setup"],
        ["--check"],
        ["--status"],
        ["--auth", "@Osvald.X"],
        ["--auth", "all"],
        ["--dry-run"],
        ["--no-llm"],
        ["--dry-run", "--no-llm", "--debug"],
        ["--export-slots", "slots.json"],
    ],
)
def test_without_setup_every_mode_asks_for_setup(
    argv: list[str],
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Нет сейфа и конфига — обычный запуск не начинается: код 2 и строка про --setup (CLAUDE.md §8)."""
    assert run_cli(argv) == int(ExitCode.CONFIG)
    assert msg.SETUP_REQUIRED in capsys.readouterr().out


def test_the_title_is_the_first_line_of_any_run(
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli([]) == int(ExitCode.CONFIG)
    first_line: str = capsys.readouterr().out.splitlines()[0]
    assert first_line.startswith(f"Livecraft {APP_VERSION} — ")


def test_the_root_comes_from_the_environment_variable(livecraft_root: Path) -> None:
    """Так корень подменяют все тесты запуска: папки создаются в нём, а не в репо (CLAUDE.md §5)."""
    assert run_cli([]) == int(ExitCode.CONFIG)
    assert sorted(item.name for item in livecraft_root.iterdir()) == [
        "image",
        "keystreams",
        "logs",
        "secrets",
        "state",
        "tools",
    ]


def test_run_started_and_run_finished_land_in_the_log(livecraft_root: Path) -> None:
    assert run_cli(["--dry-run"]) == int(ExitCode.CONFIG)
    close_logging()
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert f"run_started version={APP_VERSION} " in text
    assert f"root={livecraft_root}" in text
    assert "dry_run=True" in text
    assert f"run_finished exit_code={int(ExitCode.CONFIG)}" in text


def test_the_log_quotes_the_channel_handle(livecraft_root: Path) -> None:
    """Имя канала в логе — в кавычках (CLAUDE.md §11)."""
    assert run_cli(["--auth", "@Osvald.X"]) == int(ExitCode.CONFIG)
    close_logging()
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    assert 'auth="@Osvald.X"' in log_file.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "argv",
    [
        ["--setup", "--check"],
        ["--setup", "--status"],
        ["--check", "--status"],
        ["--check", "--auth", "all"],
        ["--status", "--auth", "all"],
        ["--setup", "--auth", "all"],
    ],
)
def test_two_modes_at_once_are_a_parse_error(argv: list[str]) -> None:
    """--setup / --check / --auth / --status взаимоисключающие (CLAUDE.md §10)."""
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(argv)
    assert raised.value.code == 2


def test_unknown_flag_is_a_parse_error() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--publish-announcements"])


def test_every_flag_of_section_ten_is_understood() -> None:
    request: RunRequest = RunRequest.from_args(
        build_parser().parse_args(["--dry-run", "--no-llm", "--export-slots", "out/slots.json", "--debug"])
    )
    assert request.dry_run and request.no_llm and request.debug
    assert request.export_slots == Path("out/slots.json")
    assert not request.setup and not request.check and not request.status and request.auth is None


def test_help_survives_a_console_that_cannot_encode_russian(monkeypatch: pytest.MonkeyPatch) -> None:
    """Справку печатает сам argparse — значит консоль настраивается до разбора флагов, а не после."""
    buffer: io.BytesIO = io.BytesIO()
    console: io.TextIOWrapper = io.TextIOWrapper(buffer, encoding="cp1251", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    with pytest.raises(SystemExit) as raised:
        run_cli(["--help"])
    assert raised.value.code == 0
    console.flush()
    assert b"usage: livecraft" in buffer.getvalue()


def test_export_slots_without_a_path_is_a_parse_error() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--export-slots"])


def test_request_without_flags_is_the_full_cycle() -> None:
    request: RunRequest = RunRequest.from_args(build_parser().parse_args([]))
    assert not any(
        (request.setup, request.check, request.status, request.dry_run, request.no_llm, request.debug)
    )
    assert request.auth is None and request.export_slots is None


def test_exit_codes_are_the_ones_section_ten_names() -> None:
    assert (ExitCode.OK, ExitCode.ERRORS, ExitCode.CONFIG, ExitCode.NO_FUTURE_SLOTS) == (0, 1, 2, 3)


def test_debug_puts_the_log_into_the_terminal(
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli(["--debug"]) == int(ExitCode.CONFIG)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert "run_started version=" in captured.err          # сырой лог — в stderr
    assert msg.SETUP_REQUIRED in captured.out              # тексты оператора — в stdout
