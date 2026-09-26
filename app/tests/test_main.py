from __future__ import annotations

import base64
import io
import json
import logging
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config.files import SettingsFile, ShippedSettings
from app.core.clock import Clock
from app.core.text_format import TEXT_ENCODING
from app.intake.intake import IntakeRequest, IntakeResult, IntakeStage, PlanIntake
from app.main import run_cli
from app.paths import ROOT_ENV_VAR, LivecraftPaths
from app.run.exit_code import ExitCode
from app.run.mode import RunPart
from app.runtime.single_instance import InstanceLock, LockEvent, LockOwner
from app.secretsafe.crypto import VaultFileKey
from app.secretsafe.store import VaultStore
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.packages.package import PackageResult
from app.sheets.plan import SheetPlan
from app.sheets.rows import AdmittedRow, PlannedRows
from app.sources.video import PreparedSources, SourceVideo
from app.tests.conftest import FORM_URL, REPO_ROOT, SUPPLIED_VALUES, write_supplied_vault
from app.tests.fixtures.settings import set_form_url
from app.tests.fixtures.slots import build_slots
from app.tests.fixtures.vault import LOCAL_UNREADABLE_WARNING
from app.tests.fixtures.sources import admitted_row, ready_source
from app.ui import messages_ru as msg
from app.ui.console import Console
from app.version import APP_VERSION

LOG_GLOB: str = "*_livecraft.log"
INTAKE_LINK: str = "https://youtu.be/dQw4w9WgXcQ"
INTAKE_START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=timezone(timedelta(hours=3)))
INTAKE_TITLE: str = "Название видео для прогона"


def _ok_intake_result() -> IntakeResult:
    """Итог прогона «всё сделано»: один ряд, годный источник, один слот, записанный пакет."""
    row: AdmittedRow = admitted_row(2, INTAKE_LINK, INTAKE_START)
    video: SourceVideo = ready_source(row, INTAKE_TITLE, "Описание видео", "uk")
    package: PackageResult = PackageResult(
        path=Path("bcast") / "plan.bcast", problem=None, slots=1, previews=0, size_bytes=1
    )
    return IntakeResult(
        rows=PlannedRows(admitted=(row,), skipped=()),
        sources=PreparedSources((video,)),
        build=build_slots((video,), ZoneInfo("Europe/Kyiv")),
        package=package,
    )


@dataclass
class _IntakeStub:
    """Подменённый прогон контура A: к Google и yt-dlp тесты запуска не ходят. Итог задаёт тест."""

    result: IntakeResult = field(default_factory=_ok_intake_result)
    requests: list[IntakeRequest] = field(default_factory=list)


@pytest.fixture(autouse=True)
def intake(monkeypatch: pytest.MonkeyPatch) -> _IntakeStub:
    """Прогон режима А в тестах запуска подменён: запрос записывается, итог — из заглушки."""
    stub: _IntakeStub = _IntakeStub()

    def _run(self: PlanIntake) -> IntakeResult:
        stub.requests.append(self.request)
        return stub.result

    monkeypatch.setattr(PlanIntake, "run", _run)
    return stub


@pytest.fixture(autouse=True)
def window_calls(monkeypatch: pytest.MonkeyPatch) -> list[LivecraftPaths]:
    """Окно настройщика в тестах запуска не открывается: вызовы записываются. Тест может подменить сам."""
    from app.setup.app import SetupApp

    calls: list[LivecraftPaths] = []
    monkeypatch.setattr(SetupApp, "run", lambda self: calls.append(self.paths))
    return calls


@pytest.fixture
def unformed_root(ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch) -> LivecraftPaths:
    """Корень из conftest со всем, кроме ссылки на форму, подставленный запуску через LIVECRAFT_ROOT."""
    monkeypatch.setenv(ROOT_ENV_VAR, str(ready_paths.root))
    return ready_paths


@pytest.fixture
def ready_root(unformed_root: LivecraftPaths) -> LivecraftPaths:
    """Полностью настроенный корень: и ссылка на форму задана — готовы все реализованные части режима."""
    set_form_url(unformed_root, FORM_URL)
    return unformed_root


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
        ["--check"],
        ["--status"],
        ["--auth", "@Osvald.X"],
        ["--auth", "all"],
    ],
)
def test_without_setup_a_service_run_asks_for_setup(
    argv: list[str],
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """--check, --auth, --status без полной настройки не начинаются: код 2 и строка про --setup, без шаблонов."""
    assert run_cli(argv) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert msg.READINESS_CHANNELS_MISSING in out
    assert msg.CONFIG_CHANNELS_TEMPLATE not in out and ShippedSettings().template not in out
    assert out.rstrip().endswith(msg.SETUP_REQUIRED)  # что делать — последней строкой
    assert window_calls == []


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--announce"],
        ["--broadcast"],
        ["--dry-run"],
        ["--no-llm"],
        ["--dry-run", "--no-llm", "--debug"],
    ],
)
def test_without_setup_a_mode_opens_the_setup_window(
    argv: list[str],
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Не готово ничего — программа сама открывает окно настройки, после него код 2; шаблонов в консоли нет."""
    assert run_cli(argv) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert msg.SETUP_OPENING in out
    assert msg.CONFIG_CHANNELS_TEMPLATE not in out and ShippedSettings().template not in out
    assert msg.SETUP_REQUIRED not in out
    assert window_calls == [LivecraftPaths(livecraft_root)]


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
        "bcast",
        "image",
        "keystreams",
        "logs",
        "secrets",
        "state",
        "tools",
    ]


def test_run_started_and_run_finished_land_in_the_log(livecraft_root: Path) -> None:
    assert run_cli(["--dry-run"]) == int(ExitCode.CONFIG)
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert f"run_started version={APP_VERSION} " in text
    assert f"root={livecraft_root}" in text
    assert "mode=all auth=- dry_run=yes no_llm=no debug=no log=" in text
    assert f"run_finished exit_code={int(ExitCode.CONFIG)}" in text


def test_the_log_quotes_the_channel_handle(livecraft_root: Path) -> None:
    """Имя канала в логе — в кавычках (CLAUDE.md §11)."""
    assert run_cli(["--auth", "@Osvald.X"]) == int(ExitCode.CONFIG)
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    assert 'auth="@Osvald.X"' in log_file.read_text(encoding="utf-8")


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


def test_debug_puts_the_log_into_the_terminal(
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli(["--debug"]) == int(ExitCode.CONFIG)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert "run_started version=" in captured.err          # сырой лог — в stderr
    assert msg.SETUP_OPENING in captured.out               # тексты оператора — в stdout


def test_a_run_leaves_no_lock_behind(livecraft_root: Path) -> None:
    """Замок снимается на любом исходе: следующий запуск не должен спотыкаться о прошлый."""
    assert run_cli([]) == int(ExitCode.CONFIG)
    assert not LivecraftPaths(livecraft_root).lock_file.exists()


def test_the_run_writes_acquire_and_release_into_the_startup_log(livecraft_root: Path) -> None:
    """Замок берётся до настройки логов, поэтому его след — logs\\startup.log (инвариант 12)."""
    assert run_cli([]) == int(ExitCode.CONFIG)
    text: str = LivecraftPaths(livecraft_root).startup_log_file.read_text(encoding="utf-8")
    assert LockEvent.ACQUIRED.value in text and LockEvent.RELEASED.value in text


def test_a_live_lock_stops_the_run(
    livecraft_root: Path,
    live_foreign_process: subprocess.Popen[bytes],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Второй экземпляр: русская строка в stderr, код 1, файла лога этого запуска нет (инвариант 12)."""
    paths: LivecraftPaths = LivecraftPaths(livecraft_root)
    paths.ensure_dirs()
    InstanceLock(
        path=paths.lock_file, startup_log=paths.startup_log_file, clock=Clock.utc(), pid=live_foreign_process.pid
    ).acquire()
    held: bytes = paths.lock_file.read_bytes()
    owner: LockOwner | None = LockOwner.parse(held.decode("utf-8"))
    assert owner is not None
    assert run_cli([]) == int(ExitCode.ERRORS)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert msg.LOCK_REJECTED.format(pid=owner.pid, started_at=owner.started_at) in captured.err
    assert captured.out == ""                                    # отказ идёт в stderr, не в stdout
    assert list(paths.logs_dir.glob(LOG_GLOB)) == []              # логи этого запуска не настраивались
    assert LockEvent.REJECTED.value in paths.startup_log_file.read_text(encoding="utf-8")
    assert paths.lock_file.read_bytes() == held                   # чужой замок не тронут


def test_a_stale_lock_does_not_stop_the_run(livecraft_root: Path, dead_pid: int) -> None:
    """Замок мёртвого процесса — застарелый: запуск идёт своим ходом и снимает его за собой."""
    paths: LivecraftPaths = LivecraftPaths(livecraft_root)
    paths.ensure_dirs()
    InstanceLock(path=paths.lock_file, startup_log=paths.startup_log_file, clock=Clock.utc(), pid=dead_pid).acquire()
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
    assert calls == [LivecraftPaths(livecraft_root)]
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
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    assert "setup_window_failed error=no display name" in log_file.read_text(encoding="utf-8")


def test_the_normal_run_does_not_import_the_window() -> None:
    """tkinter тянет только ветка --setup: обычный запуск окна не знает."""
    code: str = "import sys, app.main; print('tkinter' in sys.modules)"
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=REPO_ROOT
    )
    assert result.stdout.strip() == "False"


def test_a_missing_settings_file_is_created_from_the_template(
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """livecraft.json в git нет (§5): программа кладёт поставочный вид сама, восстанавливать руками нечего."""
    config_file: Path = livecraft_root / "secrets" / "livecraft.json"
    run_cli([])
    out: str = capsys.readouterr().out
    assert msg.SETTINGS_FILE_CREATED.format(path=config_file) in out
    assert config_file.read_text(encoding="utf-8") == ShippedSettings().template
    assert ShippedSettings().template not in out                  # шаблон не печатается: файл уже есть
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    assert "settings_file_created path=" in log_file.read_text(encoding="utf-8")


def test_an_existing_settings_file_is_left_alone(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data: dict[str, object] = json.loads(ready_root.config_file.read_text(encoding="utf-8"))
    data["keep_days"] = 7
    ready_root.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before: bytes = ready_root.config_file.read_bytes()
    mtime: int = ready_root.config_file.stat().st_mtime_ns
    for _ in range(2):
        assert run_cli([]) == int(ExitCode.OK)
        assert msg.SETTINGS_FILE_CREATED.split("{", 1)[0] not in capsys.readouterr().out
    assert ready_root.config_file.read_bytes() == before
    assert ready_root.config_file.stat().st_mtime_ns == mtime


def test_a_settings_file_missing_a_field_names_it_and_logs_its_template(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Сломанный файл программа не перезаписывает: называет поле и где исправить; шаблон — только в лог (§5)."""
    data: dict[str, object] = json.loads(ready_root.config_file.read_text(encoding="utf-8"))
    del data["keep_days"]
    ready_root.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert run_cli([]) == int(ExitCode.CONFIG)          # без настроек таблицу не прочитать — не готово ничего
    out: str = capsys.readouterr().out
    assert ShippedSettings().template not in out
    assert "keep_days" in out and msg.SETUP_TAB_SETTINGS in out
    assert window_calls == [ready_root]
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    assert "config_template " in log_file.read_text(encoding="utf-8")


def test_a_ready_root_prints_the_summary_and_exits_0(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.READINESS_SUMMARY_TITLE in out
    assert msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk") in out
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
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "config_missing path=" in text                   # нет файла — не ошибка, а «ещё не настроено»
    assert "kind=file_missing" not in text
    assert "readiness settings=ok channels=- " in text      # настройки прочитаны и без каналов


def test_an_unreadable_own_vault_is_announced_and_the_run_goes_on(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§16: личный сейф не прочитан — громкая строка, работа на поставочных значениях, код как у готового."""
    own: Vault = Vault.empty().with_field(
        SecretField.SHEETS_ID, SecretValue(field=SecretField.SHEETS_ID, value="1own-table-0123456789"), VaultOrigin.OWN
    )
    VaultStore.open(ready_root).save_local(own)
    data: dict[str, object] = json.loads(ready_root.vault_local_file.read_text(encoding=TEXT_ENCODING))
    wrapped: bytes = base64.b64decode(str(data[VaultFileKey.WRAPPED_KEY.value]), validate=True)
    data[VaultFileKey.WRAPPED_KEY.value] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    ready_root.vault_local_file.write_text(json.dumps(data), encoding=TEXT_ENCODING)
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert LOCAL_UNREADABLE_WARNING in out
    assert msg.READINESS_FIELD_LINE.format(
        label=SecretField.SHEETS_ID.human_label, origin=msg.VAULT_ORIGIN_SUPPLIED
    ) in out


def test_a_broken_own_vault_file_opens_the_setup_window_with_code_2(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Повреждённый vault.local.dat — не «файла нет» и не тупик: код 2 без отката на поставку (§16)
    и окно настройщика, где первое сохранение заменит файл (D9)."""
    ready_root.vault_local_file.write_bytes(b"\xff\xfe\x00vault\x80\x81")
    assert run_cli([]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert ready_root.vault_local_file.name in out
    assert msg.SETUP_OPENING in out
    assert window_calls == [ready_root]
    assert LOCAL_UNREADABLE_WARNING not in out
    assert "ВНИМАНИЕ" not in out


def test_a_broken_supplied_vault_file_stops_the_run_with_code_2_and_no_window(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Повреждённый vault.dat окно не заменит: строки с одним действием — переустановить — и код 2."""
    ready_root.vault_file.write_bytes(b"\xff\xfe\x00vault\x80\x81")
    assert run_cli([]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert ready_root.vault_file.name in out
    assert msg.VAULT_FILE_ADVICE_SUPPLIED in out
    assert msg.SETUP_OPENING not in out
    assert window_calls == []


def test_a_broken_vault_file_goes_to_the_log_with_reason_and_detail(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Английская подробность — только в лог, строкой vault_error с причиной (D4); в консоли её нет."""
    ready_root.vault_file.write_text("{", encoding=TEXT_ENCODING)
    run_cli([])
    out: str = capsys.readouterr().out
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "vault_error file=vault.dat source=supplied reason=damaged detail=vault file is not valid JSON" in text
    assert "JSON" not in out


def test_the_secret_filter_works_during_a_normal_run(
    ready_root: LivecraftPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Чужая библиотека пишет в лог URL с id таблицы посреди запуска — в файл уходит ярлык, а не значение.

    Подмены логики нет: консоль запуска поддельная — к боевой печати строк добавлена запись от имени googleapiclient,
    как это бывает, когда клиент Sheets ходит в сеть. Чистит её боевой фильтр, поставленный самим запуском.
    """
    sheets_id: str = SUPPLIED_VALUES[SecretField.SHEETS_ID]

    @dataclass(frozen=True)
    class _NoisyConsole(Console):
        """Консоль запуска, посреди печати которой чужая библиотека пишет в лог URL с id таблицы."""

        def say_lines(self, lines: Iterable[str]) -> None:
            logging.getLogger("googleapiclient.discovery").warning(
                "URL being requested: GET https://sheets.googleapis.com/v4/spreadsheets/%s/values/A:F", sheets_id
            )
            super().say_lines(lines)

    monkeypatch.setattr(Console, "system", classmethod(lambda cls: _NoisyConsole(out=sys.stdout, err=sys.stderr)))
    assert run_cli([]) == int(ExitCode.OK)
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "URL being requested" in text                      # запись дошла до файла…
    assert sheets_id not in text                              # …без значения
    assert SecretValue(field=SecretField.SHEETS_ID, value=sheets_id).log_label in text


def test_the_readiness_line_in_the_log_carries_no_value(ready_root: LivecraftPaths) -> None:
    assert run_cli([]) == int(ExitCode.OK)
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "readiness settings=ok channels=2 local=absent vault=" in text
    for value in SUPPLIED_VALUES.values():
        assert value not in text


# --- ссылка на форму из сейфа — один раз в livecraft.json (§14 решение 15)

OWN_FORM_URL: str = "https://forms.gle/OwnFormCode12345"


def _save_own_form_url(paths: LivecraftPaths, value: str) -> None:
    own: Vault = Vault.empty().with_field(
        SecretField.KEY_FORM_URL, SecretValue(field=SecretField.KEY_FORM_URL, value=value), VaultOrigin.OWN
    )
    VaultStore.open(paths).save_local(own)


def test_the_form_url_moves_from_the_own_vault_to_the_settings(
    unformed_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _save_own_form_url(unformed_root, OWN_FORM_URL)
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.FORM_URL_MIGRATED in out
    assert out.index(msg.FORM_URL_MIGRATED) < out.index(msg.READINESS_SUMMARY_TITLE)
    assert OWN_FORM_URL not in out
    assert SettingsFile(unformed_root.config_file).load().form.url == OWN_FORM_URL
    assert VaultStore.open(unformed_root).load().vault.get(SecretField.KEY_FORM_URL) is None
    [log_file] = list(unformed_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "form_url_migrated outcome=moved source=own" in text
    assert OWN_FORM_URL not in text
    assert run_cli([]) == int(ExitCode.OK)                     # второй запуск — переносить уже нечего
    assert msg.FORM_URL_MIGRATED not in capsys.readouterr().out


def test_a_bad_form_url_in_the_vault_is_announced_and_the_run_goes_on(
    unformed_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _save_own_form_url(unformed_root, "http://example.com/secret-form")
    assert run_cli([]) == int(ExitCode.ERRORS)                 # без формы пакет и эфиры не готовы, таблица — да
    out: str = capsys.readouterr().out
    assert msg.FORM_URL_MIGRATION_FAILED.format(reason=msg.CONFIG_PROBLEM_FORM_URL) in out
    assert "http://example.com/secret-form" not in out
    assert SettingsFile(unformed_root.config_file).load().form.url == ""


# --- готовность по частям режима (задача 3.8, §10, §14 решения 17, 18)


def _line_of(part: RunPart, out: str) -> str:
    """Строка части в консоли: по имени части для людей."""
    [line] = [line for line in out.splitlines() if part.human_label in line]
    return line


def test_without_channels_the_settings_are_read_and_the_table_run_goes_on(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
    intake: _IntakeStub,
) -> None:
    """Боевой случай 24-09-2026: нет channels.json — настройки всё равно прочитаны, сводка есть, шаблона каналов
    в консоли нет; эфиров в этой версии нет — строка «пока нет», прогон таблицы идёт, окно не открывается."""
    ready_root.channels_file.unlink()
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.READINESS_SUMMARY_TITLE in out
    assert _line_of(RunPart.BROADCAST, out) == RunPart.BROADCAST.not_built_line
    assert msg.READINESS_GAP_CHANNELS_MISSING not in out
    assert msg.CONFIG_CHANNELS_TEMPLATE not in out
    assert msg.SETUP_REQUIRED not in out and msg.SETUP_OPENING not in out
    assert window_calls == []
    assert len(intake.requests) == 1


def test_without_channels_the_announce_mode_is_code_0(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Объявлениям каналы не нужны; их самих в этой версии нет — это «появится позже», а не ошибка."""
    ready_root.channels_file.unlink()
    assert run_cli(["--announce"]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert RunPart.ANNOUNCE.not_built_line in out
    assert RunPart.BROADCAST.human_label not in out


def test_the_broadcast_mode_says_broadcasts_come_later_and_runs_the_table(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    intake: _IntakeStub,
) -> None:
    ready_root.channels_file.unlink()
    assert run_cli(["--broadcast"]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert _line_of(RunPart.BROADCAST, out) == RunPart.BROADCAST.not_built_line
    assert len(intake.requests) == 1


def test_the_from_package_mode_says_its_reading_comes_later(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
    intake: _IntakeStub,
) -> None:
    """Режим Б: чтения пакетов и эфиров в этой версии нет — строки «появится позже», код 0; таблица и ключ
    OpenAI не нужны, окно не открывается, прогона таблицы нет."""
    _drop_supplied_vault(ready_root)
    assert run_cli(["--from-package"]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert RunPart.PACKAGES_IN.not_built_line in out
    assert RunPart.BROADCAST.not_built_line in out
    assert window_calls == []
    assert intake.requests == []


def _drop_supplied_vault(paths: LivecraftPaths) -> None:
    """Поставочного сейфа нет: ни таблицы, ни ключа OpenAI."""
    paths.vault_file.unlink()


def test_a_fully_configured_root_runs_every_built_part(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    intake: _IntakeStub,
) -> None:
    """Всё настроено: режим «всё» печатает сводку, одну строку «нейросети пока нет», строки «появится позже»
    и строки прогона; код — код прогона."""
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    lines: list[str] = out.splitlines()
    assert msg.READINESS_SUMMARY_TITLE in out
    assert lines.count(RunPart.MERGE.not_built_line) == 1
    assert RunPart.ANNOUNCE.not_built_line in out and RunPart.BROADCAST.not_built_line in out
    for line in intake.result.console_lines:
        assert line in lines
    assert lines.index(RunPart.BROADCAST.not_built_line) < lines.index(intake.result.console_lines[0])
    assert "Не готово" not in out
    assert INTAKE_TITLE not in out and FORM_URL not in out


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (IntakeResult(rows=PlannedRows(admitted=(), skipped=()), stopped_at=IntakeStage.TABLE), ExitCode.NO_FUTURE_SLOTS),
        (IntakeResult(plan=SheetPlan.from_values([["шапка"]]), stopped_at=IntakeStage.TABLE), ExitCode.ERRORS),
    ],
)
def test_the_run_code_is_the_code_of_the_table_run(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    intake: _IntakeStub,
    result: IntakeResult,
    code: ExitCode,
) -> None:
    intake.result = result
    assert run_cli([]) == int(code)
    out: str = capsys.readouterr().out
    for line in result.console_lines:
        assert line in out


def test_a_blocked_part_and_no_future_rows_give_code_3(
    unformed_root: LivecraftPaths,
    intake: _IntakeStub,
) -> None:
    """Пакет не готов (нет формы) — это 1, но будущих рядов нет — 3 важнее (§10)."""
    intake.result = IntakeResult(rows=PlannedRows(admitted=(), skipped=()), stopped_at=IntakeStage.TABLE)
    assert run_cli([]) == int(ExitCode.NO_FUTURE_SLOTS)


def test_a_blocked_part_and_a_clean_run_give_code_1(unformed_root: LivecraftPaths) -> None:
    """Прогон прошёл чисто, но пакет не готов (нет формы) — код 1."""
    assert run_cli([]) == int(ExitCode.ERRORS)


def test_the_run_request_carries_an_aware_now_in_the_program_zone_and_a_new_package_id(
    ready_root: LivecraftPaths,
    intake: _IntakeStub,
) -> None:
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    assert run_cli([]) == int(ExitCode.OK)
    first, second = intake.requests
    assert first.now.utcoffset() is not None
    assert str(first.now.tzinfo) == SettingsFile(ready_root.config_file).load().timezone
    assert first.package_id != second.package_id
    assert first.paths.root == ready_root.root


def test_without_the_openai_key_the_run_goes_on_with_the_video_texts(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Нейросети в этой версии нет: ключ OpenAI не нужен ни с --no-llm, ни без него; без флага — одна строка
    «нейросети пока нет», с флагом — ни одной."""
    write_supplied_vault(ready_root, {k: v for k, v in SUPPLIED_VALUES.items() if k is not SecretField.OPENAI_API_KEY})
    assert run_cli(["--no-llm"]) == int(ExitCode.OK)
    assert RunPart.MERGE.not_built_line not in capsys.readouterr().out
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert out.splitlines().count(RunPart.MERGE.not_built_line) == 1
    assert "Не готово" not in out


def test_without_the_table_nothing_is_ready_and_the_window_opens(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Без чтения таблицы режим А не делает ничего, даже если форма и каналы на месте: окно и код 2."""
    ready_root.client_secret_file.unlink()
    assert run_cli(["--broadcast"]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert "client_secret.json" in _line_of(RunPart.PLAN, out)
    assert msg.SETUP_OPENING in out
    assert window_calls == [ready_root]


def test_the_mode_readiness_lands_in_the_log(ready_root: LivecraftPaths) -> None:
    ready_root.channels_file.unlink()
    assert run_cli([]) == int(ExitCode.OK)
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "mode_readiness mode=all ready=plan,package blocked=- not_built=merge,announce,broadcast" in text
    assert "run_started version=" in text and "mode=all " in text


# --- падение и обрыв: единственный перехват Exception (Launch.run)


def test_a_crash_is_code_1_with_the_trace_in_the_log_and_a_line_in_the_console(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка программы не пропадает: трассировка — в лог, короткая строка с путём лога — в консоль, код 1."""

    def _crash(self: PlanIntake) -> IntakeResult:
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(PlanIntake, "run", _crash)
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert msg.RUN_CRASHED.format(log=log_file) in out
    assert f"run_crashed log={log_file}" in text and "RuntimeError: disk exploded" in text
    assert f"run_finished exit_code={int(ExitCode.ERRORS)}" in text
    assert not ready_root.lock_file.exists()


def test_an_interrupt_is_code_1_with_a_line_in_the_console(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _interrupt(self: PlanIntake) -> IntakeResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(PlanIntake, "run", _interrupt)
    assert run_cli([]) == int(ExitCode.ERRORS)
    assert msg.RUN_INTERRUPTED in capsys.readouterr().out
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    assert "run_interrupted" in log_file.read_text(encoding="utf-8")
