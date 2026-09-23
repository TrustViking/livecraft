from __future__ import annotations

import base64
import io
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import main as main_module
from app.main import ExitCode, RunRequest, build_parser, run_cli
from app.observability.logging_setup import close_logging
from app.paths import ROOT_ENV_VAR, LivecraftPaths, build_paths, ensure_dirs
from app.runtime.single_instance import (
    EVENT_ACQUIRED,
    EVENT_REJECTED,
    EVENT_RELEASED,
    InstanceLock,
    LockOwner,
)
from app.secretsafe.crypto import KEY_WRAPPED
from app.secretsafe.store import VAULT_FILE_ENCODING, VaultStore
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.tests.conftest import REPO_CHANNELS_EXAMPLE, REPO_ROOT, SUPPLIED_VALUES
from app.ui import messages_ru as msg
from app.version import APP_VERSION

LOG_GLOB: str = "*_livecraft.log"


@pytest.fixture(autouse=True)
def _closed_logging() -> Iterator[None]:
    """Лог запуска закрывается и в тестах: иначе Windows не отдаст tmp_path."""
    yield
    close_logging()


@pytest.fixture
def ready_root(ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch) -> LivecraftPaths:
    """Готовый к запуску корень из conftest, подставленный запуску через LIVECRAFT_ROOT."""
    monkeypatch.setenv(ROOT_ENV_VAR, str(ready_paths.root))
    return ready_paths


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
    """Нет сейфа и конфига — обычный запуск не начинается: код 2, шаблон и строка про --setup (CLAUDE.md §8)."""
    assert run_cli(argv) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert msg.SETUP_REQUIRED in out
    assert msg.CONFIG_CHANNELS_TEMPLATE in out        # загрузчик читает channels.json первым — его шаблон
    assert out.rstrip().endswith(msg.SETUP_REQUIRED)  # что делать — последней строкой


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


def test_a_run_leaves_no_lock_behind(livecraft_root: Path) -> None:
    """Замок снимается на любом исходе: следующий запуск не должен спотыкаться о прошлый."""
    assert run_cli([]) == int(ExitCode.CONFIG)
    assert not build_paths(livecraft_root).lock_file.exists()


def test_the_run_writes_acquire_and_release_into_the_startup_log(livecraft_root: Path) -> None:
    """Замок берётся до настройки логов, поэтому его след — logs\\startup.log (инвариант 12)."""
    assert run_cli([]) == int(ExitCode.CONFIG)
    text: str = build_paths(livecraft_root).startup_log_file.read_text(encoding="utf-8")
    assert EVENT_ACQUIRED in text and EVENT_RELEASED in text


def test_a_live_lock_stops_the_run(
    livecraft_root: Path,
    live_foreign_process: subprocess.Popen[bytes],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Второй экземпляр: русская строка в stderr, код 1, файла лога этого запуска нет (инвариант 12)."""
    paths: LivecraftPaths = build_paths(livecraft_root)
    ensure_dirs(paths)
    InstanceLock(
        path=paths.lock_file, startup_log=paths.startup_log_file, pid=live_foreign_process.pid
    ).acquire()
    held: bytes = paths.lock_file.read_bytes()
    owner: LockOwner | None = LockOwner.parse(held.decode("utf-8"))
    assert owner is not None
    assert run_cli([]) == int(ExitCode.ERRORS)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert msg.LOCK_REJECTED.format(pid=owner.pid, started_at=owner.started_at) in captured.err
    assert captured.out == ""                                    # отказ идёт в stderr, не в stdout
    assert list(paths.logs_dir.glob(LOG_GLOB)) == []              # логи этого запуска не настраивались
    assert EVENT_REJECTED in paths.startup_log_file.read_text(encoding="utf-8")
    assert paths.lock_file.read_bytes() == held                   # чужой замок не тронут


def test_a_stale_lock_does_not_stop_the_run(livecraft_root: Path, dead_pid: int) -> None:
    """Замок мёртвого процесса — застарелый: запуск идёт своим ходом и снимает его за собой."""
    paths: LivecraftPaths = build_paths(livecraft_root)
    ensure_dirs(paths)
    InstanceLock(path=paths.lock_file, startup_log=paths.startup_log_file, pid=dead_pid).acquire()
    assert run_cli([]) == int(ExitCode.CONFIG)
    assert not paths.lock_file.exists()


def test_version_flag_takes_no_lock(livecraft_root: Path) -> None:
    """--version ничего не читает и ничего не занимает: argparse выходит внутри parse_args."""
    with pytest.raises(SystemExit):
        run_cli(["--version"])
    assert not livecraft_root.exists()


# --- готовность к запуску (задача 1.5): сейф и конфиги читаются при каждом запуске


def test_setup_opens_the_window_once_and_exits_0(
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--setup проверка не останавливает: настройщик и есть способ всё починить — открывается окно (§8.2)."""
    from app.setup.app import SetupApp

    calls: list[LivecraftPaths] = []
    monkeypatch.setattr(SetupApp, "run", lambda self: calls.append(self.paths))
    assert run_cli(["--setup"]) == int(ExitCode.OK)
    assert calls == [build_paths(livecraft_root)]
    out: str = capsys.readouterr().out
    assert msg.SETUP_REQUIRED not in out
    assert msg.CONFIG_CHANNELS_TEMPLATE not in out      # что не так, показывает окно, а не консоль


def test_a_window_that_cannot_open_gives_code_1(
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Нет Tk или рабочего стола — русская строка в консоль, setup_window_failed в лог, код 1."""
    from tkinter import TclError

    from app.setup.app import SetupApp

    def _fail(self: SetupApp) -> None:
        raise TclError("no display name")

    monkeypatch.setattr(SetupApp, "run", _fail)
    assert run_cli(["--setup"]) == int(ExitCode.ERRORS)
    assert msg.SETUP_WINDOW_FAILED.format(error="no display name") in capsys.readouterr().out
    close_logging()
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    assert "setup_window_failed error=no display name" in log_file.read_text(encoding="utf-8")


def test_the_normal_run_does_not_import_the_window() -> None:
    """tkinter тянет только ветка --setup: обычный запуск окна не знает."""
    code: str = "import sys, app.main; print('tkinter' in sys.modules)"
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=REPO_ROOT
    )
    assert result.stdout.strip() == "False"


def test_a_missing_settings_file_prints_its_template(
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (livecraft_root / "secrets").mkdir(parents=True)
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_root / "secrets" / "channels.json")
    assert run_cli([]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert msg.CONFIG_SETTINGS_TEMPLATE in out and msg.SETUP_REQUIRED in out


def test_a_ready_root_prints_the_summary_and_exits_0(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.READINESS_SUMMARY_TITLE in out
    assert msg.READINESS_CHANNELS_LINE.format(count=2, languages="en, ru, uk") in out
    assert msg.SETUP_REQUIRED not in out


def test_the_ready_run_prints_no_value_and_no_mask(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """В консоль уходит, откуда значение, но не само значение и не его маска (§7.4)."""
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    for field, value in SUPPLIED_VALUES.items():
        secret: SecretValue = SecretValue(field=field, value=value)
        assert value not in out and secret.masked not in out


def test_config_errors_land_in_the_log(livecraft_root: Path) -> None:
    assert run_cli([]) == int(ExitCode.CONFIG)
    close_logging()
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "config_error path=" in text and "kind=file_missing" in text
    assert "readiness config=error" in text


def test_an_unreadable_own_vault_is_announced_and_the_run_goes_on(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§16: личный сейф не прочитан — громкая строка, работа на поставочных значениях, код как у готового."""
    own: Vault = Vault.empty().with_field(
        SecretField.SHEETS_ID, SecretValue(field=SecretField.SHEETS_ID, value="1own-table-0123456789"), VaultOrigin.OWN
    )
    VaultStore.open(ready_root).save_local(own)
    data: dict[str, object] = json.loads(ready_root.vault_local_file.read_text(encoding=VAULT_FILE_ENCODING))
    wrapped: bytes = base64.b64decode(str(data[KEY_WRAPPED]), validate=True)
    data[KEY_WRAPPED] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    ready_root.vault_local_file.write_text(json.dumps(data), encoding=VAULT_FILE_ENCODING)
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.VAULT_LOCAL_UNREADABLE in out
    assert msg.READINESS_FIELD_LINE.format(
        label=SecretField.SHEETS_ID.human_label, origin=msg.VAULT_ORIGIN_SUPPLIED
    ) in out


def test_a_broken_own_vault_file_stops_the_run_with_code_2(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Повреждённый vault.local.dat — не «файла нет»: отказ с именем файла, без отката на поставку (§16)."""
    ready_root.vault_local_file.write_bytes(b"\xff\xfe\x00vault\x80\x81")
    assert run_cli([]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert ready_root.vault_local_file.name in out
    assert msg.SETUP_REQUIRED in out
    assert msg.VAULT_LOCAL_UNREADABLE not in out
    assert "ВНИМАНИЕ" not in out


def test_the_secret_filter_works_during_a_normal_run(
    ready_root: LivecraftPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Чужая библиотека пишет в лог URL с id таблицы посреди запуска — в файл уходит ярлык, а не значение.

    Подмены логики нет: к боевой печати сводки добавлена запись от имени googleapiclient, как это случится
    на этапе 3, когда клиент Sheets начнёт ходить в сеть. Чистит её боевой фильтр, поставленный самим main.
    """
    sheets_id: str = SUPPLIED_VALUES[SecretField.SHEETS_ID]
    say_lines = main_module._say_lines

    def _say_lines_with_library_noise(lines: tuple[str, ...]) -> None:
        logging.getLogger("googleapiclient.discovery").warning(
            "URL being requested: GET https://sheets.googleapis.com/v4/spreadsheets/%s/values/A:F", sheets_id
        )
        say_lines(lines)

    monkeypatch.setattr(main_module, "_say_lines", _say_lines_with_library_noise)
    assert run_cli([]) == int(ExitCode.OK)
    close_logging()
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "URL being requested" in text                      # запись дошла до файла…
    assert sheets_id not in text                              # …без значения
    assert SecretValue(field=SecretField.SHEETS_ID, value=sheets_id).log_label in text


def test_the_readiness_line_in_the_log_carries_no_value(ready_root: LivecraftPaths) -> None:
    assert run_cli([]) == int(ExitCode.OK)
    close_logging()
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "readiness config=ok channels=2 local=absent vault=" in text
    for value in SUPPLIED_VALUES.values():
        assert value not in text
