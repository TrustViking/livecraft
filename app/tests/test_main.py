from __future__ import annotations

import base64
import io
import json
import logging
import os
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config.files import SettingsFile, ShippedSettings
from app.config.folders import FolderSettings
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.text_format import NEWLINE, TEXT_ENCODING
from app.intake.builder import SlotBuild
from app.intake.intake import IntakeRequest, IntakeResult, IntakeStage, PlanIntake
from app.main import run_cli
from app.paths import ROOT_ENV_VAR, DataDir, FileName, LivecraftPaths
from app.run.exit_code import ExitCode
from app.run.mode import Need, NeedGap, RunPart
from app.run.progress import StepCount
from app.runtime.cookies_updater import CookiesState, CookiesStatus
from app.runtime.deno_updater import ToolStatus, ToolUpdate
from app.runtime.single_instance import InstanceLock, LockEvent, LockOwner
from app.runtime.ytdlp_updater import SourceTools, SourceToolsCheck
from app.secretsafe.crypto import VaultFileKey
from app.secretsafe.store import VaultStore
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.readiness import Readiness
from app.form.book import FormBook
from app.platforms.youtube import YouTubePlatform
from app.publish.doc_copy import DocCopy
from app.publish.telegram_bot import TelegramBot
from app.platforms.error import PlatformError
from app.sheets.plan import SheetPlan
from app.slots.slot import StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.sheets.rows import AdmittedRow, PlannedRows
from app.sources.video import PreparedSources, SourceVideo
from app.tests.conftest import FORM_URL, REPO_ROOT, TOKEN_VALUES, write_token_vault
from app.google.docs import DocsClient
from app.google.drive import DOCUMENT_MIME_TYPE, DriveClient
from app.tests.fixtures.broadcasts import form_page
from app.tests.fixtures.docs import FakeDocsService, docs_client, docs_error
from app.tests.fixtures.drive import ROOT_FOLDER_ID, DriveItem, FakeDriveService, drive_client
from app.tests.fixtures.form import SUCCESS_PAGE, FakeForms, FormCall
from app.tests.fixtures.packages import PACKAGE_FORM_URL, manifest, slot_record, write_package
from app.tests.fixtures.platform import FAKE_TOKEN_TEXT, FakePlatform, token_path, written_token
from app.tests.fixtures.settings import (
    lines_on,
    lines_without,
    set_drive_folder,
    set_folders,
    set_form_url,
    set_lines,
)
from app.tests.fixtures.slots import build_slots
from app.tests.fixtures.telegram import BOT_TOKEN, PRIVATE_CHAT_ID, FakeBotResponse, FakeTelegram, connect_private_chat
from app.tests.fixtures.vault import LOCAL_UNREADABLE_WARNING, save_own_values
from app.tests.fixtures.sources import admitted_row, ready_source
from app.ui import messages_ru as msg
from app.ui.console import Console
from app.version import APP_VERSION

LOG_GLOB: str = "*_livecraft.log"
INTAKE_LINK: str = "https://youtu.be/dQw4w9WgXcQ"
INTAKE_START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=timezone(timedelta(hours=3)))
INTAKE_TITLE: str = "Название видео для прогона"
EXAMPLE_HANDLES: tuple[str, ...] = ("@kanal_ua", "@kanal_ru")


def _ok_intake_result() -> IntakeResult:
    """Итог прогона «всё сделано»: один ряд, годный источник, один слот; пакет из него пишет вывод запуска."""
    row: AdmittedRow = admitted_row(2, INTAKE_LINK, INTAKE_START)
    video: SourceVideo = ready_source(row, INTAKE_TITLE, "Описание видео", "uk")
    return IntakeResult(
        rows=PlannedRows(admitted=(row,), skipped=()),
        sources=PreparedSources((video,)),
        build=build_slots((video,), ZoneInfo("Europe/Kyiv")),
    )


@dataclass
class _IntakeStub:
    """Подменённый прогон контура A: к Google и yt-dlp тесты запуска не ходят. Итог задаёт тест."""

    result: IntakeResult
    requests: list[IntakeRequest] = field(default_factory=list)


@pytest.fixture(autouse=True)
def intake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _IntakeStub:
    """Прогон режима А в тестах запуска подменён: запрос записывается, итог — из заглушки (пакет — во временной
    папке теста)."""
    stub: _IntakeStub = _IntakeStub(result=_ok_intake_result())

    def _run(self: PlanIntake) -> IntakeResult:
        stub.requests.append(self.request)
        return stub.result

    monkeypatch.setattr(PlanIntake, "run", _run)
    return stub


@dataclass
class _ToolsStub:
    """Подменённая подготовка yt-dlp: к GitHub и бинарникам тесты запуска не ходят. Итог задаёт тест; при каждом вызове
    записывается, сколько прогонов таблицы уже было."""

    intake: _IntakeStub
    check: SourceToolsCheck = field(
        default_factory=lambda: SourceToolsCheck((), CookiesStatus("secrets\\cookies.txt", CookiesState.ABSENT))
    )
    intakes_before: list[int] = field(default_factory=list)


@pytest.fixture(autouse=True)
def tools(monkeypatch: pytest.MonkeyPatch, intake: _IntakeStub) -> _ToolsStub:
    stub: _ToolsStub = _ToolsStub(intake)

    def _refresh(self: SourceTools) -> SourceToolsCheck:
        stub.intakes_before.append(len(stub.intake.requests))
        return stub.check

    monkeypatch.setattr(SourceTools, "refresh", _refresh)
    return stub


@dataclass
class _GoogleStub:
    """Google Диск и Docs запуска в памяти: часть «документ объявлений» к Google не ходит."""

    drive: FakeDriveService = field(default_factory=FakeDriveService)
    docs: FakeDocsService = field(default_factory=FakeDocsService)


@pytest.fixture(autouse=True)
def google(monkeypatch: pytest.MonkeyPatch) -> _GoogleStub:
    """Клиенты Диска и Docs запуска подменены подделками: вход и сеть не нужны."""
    stub: _GoogleStub = _GoogleStub()
    monkeypatch.setattr(DriveClient, "open", classmethod(lambda cls, login, on_login=None: drive_client(stub.drive)))
    monkeypatch.setattr(DocsClient, "open", classmethod(lambda cls, login, on_login=None: docs_client(stub.docs)))
    return stub


@pytest.fixture(autouse=True)
def telegram(monkeypatch: pytest.MonkeyPatch) -> FakeTelegram:
    """Бот запуска — на подделке Telegram: всё отправляется в личный чат, обращения записываются."""
    fake: FakeTelegram = FakeTelegram.delivering()
    monkeypatch.setattr(TelegramBot, "from_vault", classmethod(lambda cls, vault: fake.bot))
    return fake


@dataclass
class _BroadcastsStub:
    """YouTube и форма ключей части «эфиры» в памяти: к Google запуск не ходит. Каналы примера (kanal_ua — uk,
    kanal_ru — ru) по умолчанию с токенами — входов нет; форма принимает дату слота прогона (16.10.2026)."""

    platform: FakePlatform = field(default_factory=FakePlatform)
    page: str = field(default_factory=lambda: form_page(INTAKE_START.strftime("%d.%m.%Y")))
    has_tokens: bool = True
    forms: list[FakeForms] = field(default_factory=list)
    opened: int = 0

    def youtube(self, paths: LivecraftPaths) -> FakePlatform:
        self.opened += 1
        self.platform.paths = paths
        for handle in EXAMPLE_HANDLES if self.has_tokens else ():
            written_token(paths, handle)
        return self.platform

    def book(self, paths: LivecraftPaths) -> FormBook:
        forms: FakeForms = FakeForms.answering(self.page, SUCCESS_PAGE)
        self.forms.append(forms)
        return forms.book(paths.logs_dir)

    @property
    def posts(self) -> list[FormCall]:
        return [post for forms in self.forms for post in forms.posts]


@pytest.fixture(autouse=True)
def broadcasts(monkeypatch: pytest.MonkeyPatch) -> _BroadcastsStub:
    """Площадка YouTube и формы ключей запуска подменены подделками: вход, сеть и браузер не нужны."""
    stub: _BroadcastsStub = _BroadcastsStub()
    monkeypatch.setattr(YouTubePlatform, "open", classmethod(lambda cls, paths, settings: stub.youtube(paths)))
    monkeypatch.setattr(FormBook, "for_run", classmethod(lambda cls, paths, clock: stub.book(paths)))
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
    """Полностью настроенный корень: заданы ссылка на форму, папка Google Диска, бот и личный чат — готовы все
    реализованные части режима."""
    set_form_url(unformed_root, FORM_URL)
    set_drive_folder(unformed_root)
    connect_private_chat(unformed_root)
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
        ["--auth", "@Kanal.X"],
        ["--auth", "all"],
    ],
)
def test_without_setup_a_service_run_names_its_needs(
    argv: list[str],
    livecraft_root: Path,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """--check, --auth, --status без каналов и client_secret.json не начинаются: строка на каждую нужду и код 2; окна
    и шаблонов нет."""
    assert run_cli(argv) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    channels: str = msg.READINESS_GAP_IN_SETUP.format(
        what=msg.READINESS_GAP_CHANNELS_MISSING, tab=msg.SETUP_TAB_TITLES["broadcasts"]
    )
    client_secret: str = msg.READINESS_GAP_CLIENT_SECRET.format(
        path=LivecraftPaths(livecraft_root).file(FileName.CLIENT_SECRET)
    )
    assert msg.SERVICE_NEED_BLOCKED.format(gap=channels) in out
    assert msg.SERVICE_NEED_BLOCKED.format(gap=client_secret) in out
    assert msg.CONFIG_CHANNELS_TEMPLATE not in out and ShippedSettings().template not in out
    assert window_calls == []


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--dry-run"],
        ["--dry-run", "--debug"],
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
        "docs",
        "image",
        "keystreams",
        "logs",
        "secrets",
        "state",
        "tokens",
        "tools",
    ]


def test_run_started_and_run_finished_land_in_the_log(livecraft_root: Path) -> None:
    assert run_cli(["--dry-run"]) == int(ExitCode.CONFIG)
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert f"run_started version={APP_VERSION} " in text
    assert f"root={livecraft_root}" in text
    assert "mode=run auth=- dry_run=yes debug=no package=- log=" in text
    assert f"run_finished exit_code={int(ExitCode.CONFIG)}" in text


def test_the_log_quotes_the_channel_handle(livecraft_root: Path) -> None:
    """Имя канала в логе — в кавычках (CLAUDE.md §11)."""
    assert run_cli(["--auth", "@Kanal.X"]) == int(ExitCode.CONFIG)
    [log_file] = list((livecraft_root / "logs").glob(LOG_GLOB))
    assert 'auth="@Kanal.X"' in log_file.read_text(encoding="utf-8")


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
    assert not LivecraftPaths(livecraft_root).file(FileName.LOCK).exists()


def test_the_run_writes_acquire_and_release_into_the_startup_log(livecraft_root: Path) -> None:
    """Замок берётся до настройки логов, поэтому его след — logs\\startup.log (инвариант 12)."""
    assert run_cli([]) == int(ExitCode.CONFIG)
    text: str = LivecraftPaths(livecraft_root).file(FileName.STARTUP_LOG).read_text(encoding="utf-8")
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
        path=paths.file(FileName.LOCK),
        startup_log=paths.file(FileName.STARTUP_LOG),
        clock=Clock.utc(),
        pid=live_foreign_process.pid,
    ).acquire()
    held: bytes = paths.file(FileName.LOCK).read_bytes()
    owner: LockOwner | None = LockOwner.parse(held.decode("utf-8"))
    assert owner is not None
    assert run_cli([]) == int(ExitCode.ERRORS)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert msg.LOCK_REJECTED.format(pid=owner.pid, started_at=owner.started_at) in captured.err
    assert captured.out == ""                                    # отказ идёт в stderr, не в stdout
    assert list(paths.logs_dir.glob(LOG_GLOB)) == []              # логи этого запуска не настраивались
    assert LockEvent.REJECTED.value in paths.file(FileName.STARTUP_LOG).read_text(encoding="utf-8")
    assert paths.file(FileName.LOCK).read_bytes() == held                   # чужой замок не тронут


def test_a_stale_lock_does_not_stop_the_run(livecraft_root: Path, dead_pid: int) -> None:
    """Замок мёртвого процесса — застарелый: запуск идёт своим ходом и снимает его за собой."""
    paths: LivecraftPaths = LivecraftPaths(livecraft_root)
    paths.ensure_dirs()
    InstanceLock(
        path=paths.file(FileName.LOCK), startup_log=paths.file(FileName.STARTUP_LOG), clock=Clock.utc(), pid=dead_pid
    ).acquire()
    assert run_cli([]) == int(ExitCode.CONFIG)
    assert not paths.file(FileName.LOCK).exists()


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
    data: dict[str, object] = json.loads(ready_root.file(FileName.CONFIG).read_text(encoding="utf-8"))
    data["keep_days"] = 7
    ready_root.file(FileName.CONFIG).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before: bytes = ready_root.file(FileName.CONFIG).read_bytes()
    mtime: int = ready_root.file(FileName.CONFIG).stat().st_mtime_ns
    for _ in range(2):
        assert run_cli([]) == int(ExitCode.OK)
        assert msg.SETTINGS_FILE_CREATED.split("{", 1)[0] not in capsys.readouterr().out
    assert ready_root.file(FileName.CONFIG).read_bytes() == before
    assert ready_root.file(FileName.CONFIG).stat().st_mtime_ns == mtime


def test_a_settings_file_missing_a_field_names_it_and_logs_its_template(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Сломанный файл программа не перезаписывает: называет поле и где исправить; шаблон — только в лог (§5)."""
    data: dict[str, object] = json.loads(ready_root.file(FileName.CONFIG).read_text(encoding="utf-8"))
    del data["keep_days"]
    ready_root.file(FileName.CONFIG).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert run_cli([]) == int(ExitCode.CONFIG)          # без настроек таблицу не прочитать — не готово ничего
    out: str = capsys.readouterr().out
    assert ShippedSettings().template not in out
    assert "keep_days" in out and msg.SETUP_TAB_TITLES["advanced"] in out
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
    for field, value in TOKEN_VALUES.items():
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
    """§16: личный сейф не прочитан — громкая строка, работа на поставочных значениях, код как у готового (линии без
    Telegram и Google Диска: токен бота и папка Диска — в личном сейфе, без них им не уйти)."""
    own: Vault = Vault.empty().with_field(
        SecretField.SHEETS_ID, SecretValue(field=SecretField.SHEETS_ID, value="1own-table-0123456789"), VaultOrigin.OWN
    )
    VaultStore.open(ready_root).save_local(own)
    data: dict[str, object] = json.loads(ready_root.file(FileName.VAULT_LOCAL).read_text(encoding=TEXT_ENCODING))
    wrapped: bytes = base64.b64decode(str(data[VaultFileKey.WRAPPED_KEY.value]), validate=True)
    data[VaultFileKey.WRAPPED_KEY.value] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    ready_root.file(FileName.VAULT_LOCAL).write_text(json.dumps(data), encoding=TEXT_ENCODING)
    set_lines(ready_root, lines_without(RunPart.DOC, RunPart.DOC_COPY, RunPart.ANNOUNCE, RunPart.DRIVE_PREVIEWS))
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert LOCAL_UNREADABLE_WARNING in out
    assert msg.READINESS_FIELD_LINE.format(
        label=SecretField.SHEETS_ID.human_label, origin=msg.VAULT_ORIGIN_TOKEN
    ) in out


def test_a_broken_own_vault_file_opens_the_setup_window_with_code_2(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Повреждённый vault.local.dat — не «файла нет» и не тупик: код 2 без отката на поставку (§16)
    и окно настройщика, где первое сохранение заменит файл (D9)."""
    ready_root.file(FileName.VAULT_LOCAL).write_bytes(b"\xff\xfe\x00vault\x80\x81")
    assert run_cli([]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert ready_root.file(FileName.VAULT_LOCAL).name in out
    assert msg.SETUP_OPENING in out
    assert window_calls == [ready_root]
    assert LOCAL_UNREADABLE_WARNING not in out
    assert "ВНИМАНИЕ" not in out


def test_a_broken_token_vault_file_opens_the_window_with_code_2(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Повреждённый файл значений из токена заменит загрузка токена в окне: строка с этим действием, окно и код 2."""
    ready_root.file(FileName.VAULT_TOKEN).write_bytes(b"\xff\xfe\x00vault\x80\x81")
    assert run_cli([]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert ready_root.file(FileName.VAULT_TOKEN).name in out
    assert msg.VAULT_FILE_ADVICE_TOKEN in out
    assert msg.SETUP_OPENING in out
    assert window_calls == [ready_root]


def test_a_broken_vault_file_goes_to_the_log_with_reason_and_detail(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Английская подробность — только в лог, строкой vault_error с причиной (D4); в консоли её нет."""
    ready_root.file(FileName.VAULT_TOKEN).write_text("{", encoding=TEXT_ENCODING)
    run_cli([])
    out: str = capsys.readouterr().out
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "vault_error file=vault.token.dat source=token reason=damaged detail=vault file is not valid JSON" in text
    assert "JSON" not in out


def test_the_secret_filter_works_during_a_normal_run(
    ready_root: LivecraftPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Чужая библиотека пишет в лог URL с id таблицы посреди запуска — в файл уходит ярлык, а не значение.

    Подмены логики нет: консоль запуска поддельная — к боевой печати строк добавлена запись от имени googleapiclient,
    как это бывает, когда клиент Sheets ходит в сеть. Чистит её боевой фильтр, поставленный самим запуском.
    """
    sheets_id: str = TOKEN_VALUES[SecretField.SHEETS_ID]

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
    assert "readiness settings=ok channels=2 local=read vault=" in text      # личный сейф — с токеном бота
    for value in (*TOKEN_VALUES.values(), BOT_TOKEN):
        assert value not in text


# --- готовность по частям режима (задача 3.8, §10, §14 решения 17, 18)


def _line_of(part: RunPart, out: str) -> str:
    """Строка нужды части в консоли: «Не готово — …» с именем части для людей."""
    lead: str = msg.RUN_NEED_BLOCKED.split("{", 1)[0]
    [line] = [line for line in out.splitlines() if line.startswith(lead) and part.human_label in line]
    return line


def _announcements_only(paths: LivecraftPaths) -> None:
    """Линии без эфиров и ключей в форму: таблица, нейросеть, превью, пакет, документ и копия, Telegram."""
    set_lines(paths, lines_without(RunPart.BROADCAST, RunPart.KEYS))


def _broadcasts_only(paths: LivecraftPaths) -> None:
    """Линии без документа, его копии и Telegram: таблица, нейросеть, превью, пакет, эфиры и ключи."""
    set_lines(paths, lines_without(RunPart.DOC, RunPart.DOC_COPY, RunPart.ANNOUNCE))


def _packages_only(paths: LivecraftPaths) -> None:
    """Таблица выключена: эфиры и ключи в форму — из пакетов (режим Б)."""
    set_lines(paths, lines_on(RunPart.BROADCAST, RunPart.KEYS))


def test_without_channels_the_settings_are_read_and_the_table_run_goes_on(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
    intake: _IntakeStub,
) -> None:
    """Боевой случай 24-09-2026: нет channels.json — настройки всё равно прочитаны, сводка есть, шаблона каналов
    в консоли нет; эфиры не готовы — одна строка «задайте каналы», код 1; прогон таблицы и объявления идут, окно не
    открывается, к YouTube не обращаемся."""
    ready_root.file(FileName.CHANNELS).unlink()
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    assert msg.READINESS_SUMMARY_TITLE in out
    assert msg.READINESS_GAP_CHANNELS_MISSING in _line_of(RunPart.BROADCAST, out)
    assert msg.CONFIG_CHANNELS_TEMPLATE not in out
    assert msg.SETUP_REQUIRED not in out and msg.SETUP_OPENING not in out
    assert window_calls == []
    assert len(intake.requests) == 1


def test_without_channels_the_announce_mode_is_code_0(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Объявлениям каналы не нужны: без channels.json объявления уходят, код 0; строки нужды нет."""
    ready_root.file(FileName.CHANNELS).unlink()
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0) in out
    assert msg.RUN_NEED_BLOCKED.split("{", 1)[0] not in out


def test_the_broadcast_mode_without_channels_runs_the_table_and_says_what_to_set(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    intake: _IntakeStub,
    broadcasts: _BroadcastsStub,
) -> None:
    ready_root.file(FileName.CHANNELS).unlink()
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    assert msg.READINESS_GAP_CHANNELS_MISSING in _line_of(RunPart.BROADCAST, out)
    assert len(intake.requests) == 1 and broadcasts.opened == 0


def _package_of_the_run(folder: Path, name: str = "plan_16-10-2026.bcast") -> Path:
    """Пакет с одним слотом прогона — 16.10.2026 19:00 uk — и формой ключей пакета."""
    return write_package(folder, manifest(slot_record("16-10-2026")), name)


def test_mode_b_sets_up_the_broadcasts_of_a_package_with_the_form_of_the_package(
    unformed_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
    intake: _IntakeStub,
    broadcasts: _BroadcastsStub,
) -> None:
    """Режим Б: ни таблицы, ни ключа OpenAI, ни ссылки на форму в настройках — эфир слота пакета создан, ключ ушёл в
    форму из пакета, keys.txt и отчёт с разделом «Пакеты» записаны; код 0."""
    _drop_token_vault(unformed_root)
    _package_of_the_run(unformed_root.bcast_dir)
    _packages_only(unformed_root)
    assert run_cli([]) == int(ExitCode.OK)
    lines: list[str] = capsys.readouterr().out.splitlines()
    assert msg.PROGRESS_PACKAGES_READ.format(packages=1, slots_total=1, slots_mine=1) in lines
    assert [call.marker for call in broadcasts.platform.created] == ["16-10-2026_1900_uk"]
    [forms] = broadcasts.forms
    assert [call.url for call in forms.gets] == [PACKAGE_FORM_URL] and len(forms.posts) == 1
    assert "fake-0001-0000-0000-0000" in unformed_root.file(FileName.KEYS).read_text(encoding=TEXT_ENCODING)
    [report] = list(unformed_root.logs_dir.glob("*_report.md"))
    text: str = report.read_text(encoding=TEXT_ENCODING)
    assert msg.REPORT_SECTION_PACKAGES in text
    assert "plan_16-10-2026.bcast — принят, слотов 1, из них языков каналов 1" in text
    assert window_calls == [] and intake.requests == []


def test_mode_b_with_an_empty_bcast_is_code_3_without_the_channels(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    _packages_only(ready_root)
    assert run_cli([]) == int(ExitCode.NO_FUTURE_SLOTS)
    out: str = capsys.readouterr().out
    assert msg.BCAST_EMPTY.format(path=ready_root.shown(ready_root.bcast_dir)) in out
    assert broadcasts.opened == 0 and broadcasts.platform.describe_calls == []


def test_mode_b_without_future_slots_is_code_3_and_names_the_broken_packages(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    write_package(ready_root.bcast_dir, manifest(slot_record("15-03-2025")), "old.bcast")
    (ready_root.bcast_dir / "broken.bcast").write_bytes(b"not a zip")
    _packages_only(ready_root)
    assert run_cli([]) == int(ExitCode.NO_FUTURE_SLOTS)
    out: str = capsys.readouterr().out
    assert msg.BCAST_NO_FUTURE_SLOTS.format(path=ready_root.shown(ready_root.bcast_dir)) in out
    assert "  пакет: broken.bcast — пакет повреждён: не ZIP-архив" in out
    assert broadcasts.opened == 0


def test_mode_b_with_a_broken_package_next_to_a_good_one_is_code_1(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    """Повреждённый пакет не мешает годному: эфир создан, пакет — строкой ВНИМАНИЕ и в отчёте, код 1."""
    _package_of_the_run(ready_root.bcast_dir)
    (ready_root.bcast_dir / "broken.bcast").write_bytes(b"not a zip")
    _packages_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    assert len(broadcasts.platform.created) == 1
    assert "  пакет: broken.bcast — пакет повреждён: не ZIP-архив" in out
    assert msg.EXIT_REASON_TEXT["packages"].format(count=1) in out
    [report] = list(ready_root.logs_dir.glob("*_report.md"))
    assert "broken.bcast — пакет повреждён" in report.read_text(encoding=TEXT_ENCODING)


def test_mode_b_dry_run_changes_nothing_outside(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    _package_of_the_run(ready_root.bcast_dir)
    _packages_only(ready_root)
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    platform: FakePlatform = broadcasts.platform
    assert platform.created == [] and platform.updated == [] and broadcasts.posts == []
    assert not ready_root.file(FileName.KEYS).exists()
    assert len(list(ready_root.logs_dir.glob("*_report.md"))) == 1
    assert platform.list_calls == ["kanal_ua", "kanal_ru"]


def test_mode_b_without_channels_reads_no_packages(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    """Эфиры не готовы — пакеты читать незачем: строка «задайте каналы», код 1, к YouTube не обращаемся."""
    ready_root.file(FileName.CHANNELS).unlink()
    _package_of_the_run(ready_root.bcast_dir)
    _packages_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    assert msg.READINESS_GAP_CHANNELS_MISSING in _line_of(RunPart.BROADCAST, out)
    assert msg.PROGRESS_PACKAGES_READ.split("{", 1)[0] not in out and broadcasts.opened == 0


def test_a_bcast_file_from_the_explorer_is_copied_and_the_run_goes_by_the_lines(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub, tmp_path: Path
) -> None:
    """Пакет из проводника (§14 решение 37): копия в папку пакетов, затем обычный запуск по включённым линиям — здесь
    таблица выключена, и эфиры идут по слотам пакетов."""
    _packages_only(ready_root)
    source: Path = _package_of_the_run(tmp_path / "downloads")
    assert run_cli([str(source)]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    target: Path = ready_root.bcast_dir / source.name
    assert target.read_bytes() == source.read_bytes()
    assert msg.PACKAGE_DROP_COPIED.format(path=ready_root.shown(target)) in out
    assert [call.marker for call in broadcasts.platform.created] == ["16-10-2026_1900_uk"]


def test_a_file_that_is_not_a_package_is_code_2(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub, tmp_path: Path
) -> None:
    source: Path = tmp_path / "plan.zip"
    source.write_bytes(b"PK")
    assert run_cli([str(source)]) == int(ExitCode.CONFIG)
    assert msg.PACKAGE_DROP_PROBLEMS["not_package"].format(path=source) in capsys.readouterr().out
    assert broadcasts.opened == 0 and not any(ready_root.bcast_dir.glob("*"))


# --- служебные запуски по каналам: --status, --check, --auth (поведение planers)


def test_status_writes_the_keys_and_the_report_of_the_program_broadcasts(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    """--status: эфир, поставленный прошлым запуском, — в keys.txt (форма — из памяти) и в отчёт; к форме не ходит."""
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    ready_root.file(FileName.KEYS).unlink()
    capsys.readouterr()
    assert run_cli(["--status"]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    keys: str = ready_root.file(FileName.KEYS).read_text(encoding=TEXT_ENCODING)
    assert "fake-0001-0000-0000-0000" in keys and msg.KEY_FORM_SENT_LEAD in keys
    assert msg.SUMMARY_BROADCASTS_STATUS.format(total=1, matched=1, errors=0) in out
    report: Path = max(ready_root.logs_dir.glob("*_report.md"), key=lambda path: path.stat().st_mtime_ns)
    assert msg.REPORT_SECTION_SCHEDULED.format(count=1) in report.read_text(encoding=TEXT_ENCODING)
    assert len(broadcasts.posts) == 1 and len(broadcasts.forms) == 2 and broadcasts.forms[1].gets == []


def test_status_needs_no_vault_and_no_form(
    unformed_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    _drop_token_vault(unformed_root)
    assert run_cli(["--status"]) == int(ExitCode.OK)
    assert unformed_root.file(FileName.KEYS).exists()
    assert broadcasts.platform.list_calls == ["kanal_ua", "kanal_ru"]


def test_check_names_every_channel(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    assert run_cli(["--check"]) == int(ExitCode.OK)
    lines: list[str] = capsys.readouterr().out.splitlines()
    assert msg.CHECK_HEADER.format(path=ready_root.file(FileName.CHANNELS)) in lines
    for name, handle, language in (("Канал UA", "@kanal_ua", "uk"), ("Канал RU", "@kanal_ru", "ru")):
        assert msg.CHECK_CHANNEL_OK.format(
            account_name=name,
            handle=handle,
            title=name,
            youtube_handle=handle,
            youtube_channel_id=f"UCfake{handle[1:]}",
            channel_language=msg.CHECK_CHANNEL_LANGUAGE_UNSET,
            languages=language,
            upcoming=0,
        ) in lines
    assert lines[-2:] == [msg.CHECK_CHANNEL_LANGUAGE_NOTE, msg.CHECK_ALL_OK]


def test_check_is_code_1_when_a_channel_fails(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    error: PlatformError = PlatformError("liveStreamingNotEnabled", "выключены")
    broadcasts.platform.fail_list["kanal_ua"] = error
    assert run_cli(["--check"]) == int(ExitCode.ERRORS)
    lines: list[str] = capsys.readouterr().out.splitlines()
    assert msg.CHECK_CHANNEL_FAILED.format(account_name="Канал UA", handle="@kanal_ua", reason=error.human) in lines
    assert lines[-1] == msg.CHECK_HAS_PROBLEMS


def test_auth_all_logs_in_every_channel_again(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    assert run_cli(["--auth", "all"]) == int(ExitCode.OK)
    assert broadcasts.platform.logins == ["kanal_ua", "kanal_ru"]
    assert token_path(ready_root, "@kanal_ua").read_text(encoding="utf-8") == FAKE_TOKEN_TEXT


def test_auth_of_an_unknown_handle_lists_the_handles(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    assert run_cli(["--auth", "@nobody"]) == int(ExitCode.ERRORS)
    known: str = msg.LIST_JOINER.join(
        msg.CHANNEL_LISTED.format(handle=handle, account_name=name)
        for handle, name in (("@kanal_ua", "Канал UA"), ("@kanal_ru", "Канал RU"))
    )
    expected: str = msg.AUTH_UNKNOWN_CHANNEL.format(
        path=ready_root.file(FileName.CHANNELS), handle="@nobody", known=known
    )
    assert expected in capsys.readouterr().out and broadcasts.platform.logins == []


def test_a_failed_auth_keeps_the_previous_token(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    """Прежний токен заменяется только подтверждённым входом: вход не удался — файл токена прежний, код 1."""
    broadcasts.platform.fail_login["kanal_ua"] = PlatformError("flow_failed", "browser closed")
    assert run_cli(["--auth", "@kanal_ua"]) == int(ExitCode.ERRORS)
    assert broadcasts.platform.logins == ["kanal_ua"]
    assert token_path(ready_root, "@kanal_ua").read_text(encoding="utf-8") == "token"


def _drop_token_vault(paths: LivecraftPaths) -> None:
    """Токена не загружали: ни таблицы, ни ключа OpenAI."""
    paths.file(FileName.VAULT_TOKEN).unlink()


def test_a_fully_configured_root_runs_every_built_part(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    intake: _IntakeStub,
) -> None:
    """Всё настроено: режим «всё» печатает сводку и строки прогона, затем объявления и последними — эфиры; нейросеть
    готова — о ней строки готовности нет, прогон идёт с merge; код — код прогона."""
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    lines: list[str] = out.splitlines()
    assert msg.READINESS_SUMMARY_TITLE in out
    assert [request.scope.runs(RunPart.MERGE) for request in intake.requests] == [True]
    announce: int = lines.index(msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0))
    for line in intake.result.console_lines:
        assert lines.index(line) < announce
    summary: int = next(index for index, line in enumerate(lines) if line.startswith("Итог по эфирам"))
    assert announce < summary
    assert "Не готово" not in out and "Пока нет" not in out
    assert INTAKE_TITLE not in NEWLINE.join(lines[:summary]) and FORM_URL not in out   # название — только в блоках эфиров


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (IntakeResult(rows=PlannedRows(admitted=(), skipped=()), stopped_at=IntakeStage.TABLE), ExitCode.NO_FUTURE_SLOTS),
        (IntakeResult(plan=SheetPlan.from_values("План", 0, [["шапка"]]), stopped_at=IntakeStage.TABLE), ExitCode.ERRORS),
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


def test_the_run_request_carries_an_aware_now_in_the_program_zone(ready_root: LivecraftPaths, intake: _IntakeStub) -> None:
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    assert run_cli([]) == int(ExitCode.OK)
    first, _second = intake.requests
    assert first.now.utcoffset() is not None
    assert str(first.now.tzinfo) == SettingsFile(ready_root.file(FileName.CONFIG)).load().timezone
    assert first.paths.root == ready_root.root


def test_each_run_writes_its_own_package_from_the_slots_of_the_table(ready_root: LivecraftPaths) -> None:
    """Вход «Таблица» с нейросетью: пакет пишет вывод запуска — из слотов прогона с формой настроек; у каждого запуска
    свой id пакета (§14 решение 51)."""
    set_lines(ready_root, lines_without(RunPart.DOC, RunPart.DOC_COPY, RunPart.ANNOUNCE, RunPart.BROADCAST, RunPart.KEYS))
    ids: list[str] = []
    for _ in range(2):
        for path in ready_root.bcast_dir.glob("*.bcast"):
            path.unlink()
        assert run_cli([]) == int(ExitCode.OK)
        [package] = ready_root.bcast_dir.glob("*.bcast")
        manifest_data: dict[str, object] = json.loads(zipfile.ZipFile(package).read("manifest.json"))
        assert manifest_data["form"] == SettingsFile.of(ready_root).load().form.to_data()
        ids.append(str(manifest_data["package_id"]))
    assert ids[0] != ids[1]


def test_without_the_openai_key_the_run_goes_on_with_the_video_texts(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    intake: _IntakeStub,
) -> None:
    """Без ключа OpenAI прогон идёт без merge (слоты, которым merge нужен, — «по номерам», §14 решение 32): строка
    «Не готово — название и описание эфиров нейросетью: …» и код 1. Режима без нейросети нет."""
    write_token_vault(ready_root, {k: v for k, v in TOKEN_VALUES.items() if k is not SecretField.OPENAI_API_KEY})
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    gap: NeedGap | None = Readiness.check(ready_root).gap(Need.OPENAI_VAULT)
    assert gap is not None and SecretField.OPENAI_API_KEY.human_label in gap.text
    assert _line_of(RunPart.MERGE, out) == msg.RUN_NEED_BLOCKED.format(parts=RunPart.MERGE.human_label, gap=gap.text)
    assert [request.scope.runs(RunPart.MERGE) for request in intake.requests] == [False]


def test_the_run_request_goes_with_merge_only_when_the_merge_part_is_ready(
    ready_root: LivecraftPaths,
    intake: _IntakeStub,
) -> None:
    """Ключ OpenAI в сейфе — прогон идёт с merge."""
    assert run_cli([]) == int(ExitCode.OK)
    assert [request.scope.runs(RunPart.MERGE) for request in intake.requests] == [True]


def test_the_run_request_goes_with_materials_only_when_the_drive_folder_is_set(
    ready_root: LivecraftPaths,
    intake: _IntakeStub,
) -> None:
    """Папка материалов задана — прогон кладёт превью на Диск; без неё — только в image\\ (решение 27)."""
    assert run_cli([]) == int(ExitCode.OK)
    set_drive_folder(ready_root, "")
    assert run_cli([]) == int(ExitCode.ERRORS)
    assert [request.scope.runs(RunPart.DRIVE_PREVIEWS) for request in intake.requests] == [True, False]


def test_the_run_request_carries_the_dry_run_flag(
    ready_root: LivecraftPaths,
    intake: _IntakeStub,
) -> None:
    """--dry-run доходит до прогона: этап превью ничего не отправляет наружу (§10)."""
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    assert run_cli([]) == int(ExitCode.OK)
    assert [request.scope.dry_run for request in intake.requests] == [True, False]


def test_without_the_table_nothing_is_ready_and_the_window_opens(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
) -> None:
    """Без чтения таблицы режим А не делает ничего, даже если форма и каналы на месте: окно и код 2."""
    ready_root.file(FileName.CLIENT_SECRET).unlink()
    assert run_cli([]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert "client_secret.json" in _line_of(RunPart.PLAN, out)
    assert msg.SETUP_OPENING in out
    assert window_calls == [ready_root]


def test_without_the_drive_folder_the_previews_part_names_it_and_the_code_is_1(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    google: _GoogleStub,
) -> None:
    """§10: части «превью на Google Диске» и «документ объявлений» не готовы — остальное делается, одна строка с
    действием на обе, код 1; документ не создаётся."""
    set_drive_folder(ready_root, "")
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    gap: str = msg.READINESS_GAP_IN_SETUP.format(
        what=msg.VAULT_FIELD_DRIVE_FOLDER, tab=msg.SETUP_TAB_TITLES["previews"]
    )
    parts: str = msg.LIST_JOINER.join((RunPart.DRIVE_PREVIEWS.human_label, RunPart.DOC.human_label))
    assert msg.RUN_NEED_BLOCKED.format(parts=parts, gap=gap) in out
    assert google.drive.calls == [] and google.docs.calls == []


def test_the_mode_readiness_lands_in_the_log(ready_root: LivecraftPaths) -> None:
    ready_root.file(FileName.CHANNELS).unlink()
    assert run_cli([]) == int(ExitCode.ERRORS)
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    ready: str = "ready=plan,local_previews,drive_previews,merge,package,doc,doc_copy,announce,keys"
    runs: str = "runs=plan,local_previews,drive_previews,merge,package,doc,doc_copy,announce"
    assert f"mode_readiness {ready} blocked=broadcast {runs} no_support=-" in text
    assert "run_started version=" in text and "mode=run " in text


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
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert msg.RUN_CRASHED.format(log=log_file) in captured.err     # отказ запуска — в stderr, как отказ замка
    assert msg.RUN_CRASHED.format(log=log_file) not in captured.out
    assert f"run_crashed log={log_file}" in text and "RuntimeError: disk exploded" in text
    assert f"run_finished exit_code={int(ExitCode.ERRORS)}" in text
    assert not ready_root.file(FileName.LOCK).exists()


def test_a_crash_in_a_windowed_process_shows_a_message_window(
    ready_root: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """livecraftw.exe: консоли нет — аварийная остановка показывается окном-сообщением с путём лога, а не теряется."""
    from tkinter import messagebox

    def _crash(self: PlanIntake) -> IntakeResult:
        raise RuntimeError("disk exploded")

    shown: list[str] = []
    monkeypatch.setattr(PlanIntake, "run", _crash)
    monkeypatch.setattr(messagebox, "showerror", lambda title, text: shown.append(text))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert run_cli([]) == int(ExitCode.ERRORS)
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    assert shown == [msg.RUN_CRASHED.format(log=log_file)]
    assert "RuntimeError: disk exploded" in log_file.read_text(encoding="utf-8")


def test_the_setup_window_gets_the_log_of_its_run(livecraft_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Окно пишет ошибки своих действий в лог того запуска, который его открыл."""
    from app.setup.app import SetupApp

    logs: list[Path] = []
    monkeypatch.setattr(SetupApp, "run", lambda self: logs.append(self.log))
    assert run_cli(["--setup"]) == int(ExitCode.OK)
    assert logs == list((livecraft_root / "logs").glob(LOG_GLOB))


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


# --- Telegram (§13 задача 4.1): раздел настроек дописывается сам, токен бота необязателен и не вытекает


def test_a_settings_file_without_the_telegram_section_gets_it_and_says_so(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Файл прежней версии: раздел дописан из шаблона до чтения готовности, строка консоли его называет; второй
    запуск файл не трогает. В шаблоне чата нет — линия Telegram выключена."""
    _broadcasts_only(ready_root)
    data: dict[str, object] = json.loads(ready_root.file(FileName.CONFIG).read_text(encoding="utf-8"))
    del data["telegram"]
    ready_root.file(FileName.CONFIG).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.SETTINGS_SECTIONS_ADDED.format(sections="telegram") in out
    assert SettingsFile.of(ready_root).load().telegram == ShippedSettings().settings.telegram
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    assert "settings_sections_added path=" in log_file.read_text(encoding="utf-8")
    before: bytes = ready_root.file(FileName.CONFIG).read_bytes()
    assert run_cli([]) == int(ExitCode.OK)
    assert msg.SETTINGS_SECTIONS_ADDED.split("{", 1)[0] not in capsys.readouterr().out
    assert ready_root.file(FileName.CONFIG).read_bytes() == before


@pytest.mark.parametrize("argv", [["--check"], ["--status"]])
def test_without_the_vault_the_service_runs_are_not_refused(
    argv: list[str],
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Служебным запускам по каналам сейф не нужен: ни токен бота, ни ключ OpenAI, ни таблица."""
    ready_root.file(FileName.VAULT_LOCAL).unlink()
    _drop_token_vault(ready_root)
    assert run_cli(argv) == int(ExitCode.OK)
    assert msg.SETUP_REQUIRED not in capsys.readouterr().out


def test_the_announce_mode_sends_the_announcements_after_the_document(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    google: _GoogleStub,
    telegram: FakeTelegram,
) -> None:
    """Часть ANNOUNCE реализована: за документом даты — объявления в личный чат (в шапке — ссылка на документ даты),
    последним — пакет документом; строки консоли — после строки документа; код 0."""
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    lines: list[str] = capsys.readouterr().out.splitlines()
    [document] = _documents(google)
    url: str = f"https://docs.google.com/document/d/{document.item_id}/edit"
    copy: str = str(Path("docs", "16-10-2026", DocCopy("16-10-2026", document.name).file_name))
    doc_line: str = msg.DOC_LINE.format(date="16.10.2026", url=url, placed=1, total=1) + msg.DOC_COPY_SAVED.format(
        path=copy
    )
    day_line: str = msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0)
    [package] = ready_root.bcast_dir.glob("*.bcast")
    package_line: str = msg.ANNOUNCE_PACKAGE_LINE.format(name=package.name)
    assert lines.index(doc_line) < lines.index(day_line) < lines.index(package_line)
    assert {call.body["chat_id"] for call in telegram.calls} == {PRIVATE_CHAT_ID}
    assert telegram.methods[-1] == "sendDocument" and set(telegram.methods[:-1]) == {"sendMessage"}
    assert url in str(telegram.calls[1].body["text"])


def test_the_announce_mode_without_the_chat_names_the_need_and_still_makes_the_document(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    google: _GoogleStub,
    telegram: FakeTelegram,
) -> None:
    """Чат не подключён: строка нужды Telegram, документ создаётся, к Telegram ни одного обращения, код 1."""
    file: SettingsFile = SettingsFile.of(ready_root)
    file.save(file.load().with_telegram(ShippedSettings().settings.telegram))
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    gap: str = msg.READINESS_GAP_IN_SETUP.format(what=msg.READINESS_GAP_TELEGRAM, tab=msg.SETUP_TAB_TITLES["telegram"])
    assert msg.RUN_NEED_BLOCKED.format(parts=RunPart.ANNOUNCE.human_label, gap=gap) in out
    assert len(_documents(google)) == 1
    assert telegram.calls == []


def test_a_failed_announcement_is_code_1(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    telegram: FakeTelegram,
) -> None:
    """Отказ бота — ошибка запуска: строка с причиной, пакет не отправлен, код 1."""
    telegram.outcomes.append(FakeBotResponse.saved("forbidden"))
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    reason: str = msg.TELEGRAM_PROBLEMS["forbidden"]
    assert msg.ANNOUNCE_FAILED_LINE.format(date="16.10.2026", reason=reason) in out
    assert "sendDocument" not in telegram.methods


def test_the_bot_token_never_reaches_the_log_or_the_console(
    ready_root: LivecraftPaths,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """urllib3 пишет путь запроса Bot API с токеном — в файл уходит ярлык с отпечатком, в консоль — ничего."""
    save_own_values(ready_root, {SecretField.TELEGRAM_BOT_TOKEN: BOT_TOKEN})

    @dataclass(frozen=True)
    class _NoisyConsole(Console):
        """Консоль запуска, посреди печати которой urllib3 пишет в лог строку запроса к Bot API."""

        def say_lines(self, lines: Iterable[str]) -> None:
            logging.getLogger("urllib3.connectionpool").warning(
                'https://api.telegram.org:443 "POST /bot%s/sendMessage HTTP/1.1" 200 None', BOT_TOKEN
            )
            super().say_lines(lines)

    monkeypatch.setattr(Console, "system", classmethod(lambda cls: _NoisyConsole(out=sys.stdout, err=sys.stderr)))
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    assert "sendMessage" in text and BOT_TOKEN not in text
    assert SecretValue(field=SecretField.TELEGRAM_BOT_TOKEN, value=BOT_TOKEN).log_label in text
    assert BOT_TOKEN not in out
    assert msg.READINESS_FIELD_LINE.format(label=msg.VAULT_FIELD_TELEGRAM_BOT_TOKEN, origin=msg.VAULT_ORIGIN_OWN) in out


# --- документ объявлений (часть DOC, §13 задача 4.4)


def _documents(google: _GoogleStub) -> list[DriveItem]:
    return [item for item in google.drive.items.values() if item.mime_type == DOCUMENT_MIME_TYPE]


def test_the_announce_mode_with_a_ready_doc_part_creates_the_document(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    google: _GoogleStub,
    intake: _IntakeStub,
) -> None:
    """Часть «документ объявлений» готова: за прогоном таблицы — документ даты слота в папке материалов, открытый по
    ссылке на правку (поставочный docs.access), и строка со ссылкой после строк прогона; код 0."""
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    lines: list[str] = capsys.readouterr().out.splitlines()
    [document] = _documents(google)
    assert document.parent == ROOT_FOLDER_ID and document.name.startswith("16-10-2026_")
    assert google.drive.shared[document.item_id] == {"type": "anyone", "role": "writer"}
    url: str = f"https://docs.google.com/document/d/{document.item_id}/edit"
    copy: str = str(Path("docs", "16-10-2026", DocCopy("16-10-2026", document.name).file_name))
    line: str = msg.DOC_LINE.format(date="16.10.2026", url=url, placed=1, total=1) + msg.DOC_COPY_SAVED.format(path=copy)
    assert lines.index(line) > lines.index(intake.result.console_lines[-1])


def test_the_drive_folder_of_the_vault_reaches_the_drive_but_no_output(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    google: _GoogleStub,
    intake: _IntakeStub,
) -> None:
    """§14 решение 39, §7.4: id папки — только в обращении к Диску (документ лёг в неё); ни в livecraft.json, ни в
    консоли, ни в логе, ни в отчёте его нет — в логе ярлык с отпечатком."""
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    [document] = _documents(google)
    assert document.parent == ROOT_FOLDER_ID
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    [report] = list(ready_root.logs_dir.glob("*_report.md"))
    for text in (out, log_file.read_text(encoding="utf-8"), report.read_text(encoding="utf-8")):
        assert ROOT_FOLDER_ID not in text
    assert ROOT_FOLDER_ID not in ready_root.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert SecretValue(field=SecretField.DRIVE_FOLDER, value=ROOT_FOLDER_ID).log_label in log_file.read_text(
        encoding="utf-8"
    )


def test_a_settings_file_with_the_old_folder_link_is_moved_at_the_start_of_the_run(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Прежний livecraft.json с drive.folder_url: запуск сам переносит папку в сейф до чтения настроек, строка — в
    консоль, ключ уходит из файла; второй запуск молчит."""
    set_drive_folder(ready_root, "")
    _broadcasts_only(ready_root)
    config: Path = ready_root.file(FileName.CONFIG)
    data: dict[str, dict[str, object]] = json.loads(config.read_text(encoding="utf-8"))
    data["drive"] = {"folder_url": f"https://drive.google.com/drive/folders/{ROOT_FOLDER_ID}", **data["drive"]}
    config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.DRIVE_FOLDER_MIGRATED in out and ROOT_FOLDER_ID not in out
    assert "folder_url" not in config.read_text(encoding="utf-8")
    assert msg.READINESS_FIELD_LINE.format(label=msg.VAULT_FIELD_DRIVE_FOLDER, origin=msg.VAULT_ORIGIN_OWN) in out
    assert run_cli([]) == int(ExitCode.OK)
    assert msg.DRIVE_FOLDER_MIGRATED not in capsys.readouterr().out


def test_the_announce_mode_without_the_drive_folder_names_the_need_and_creates_no_document(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    google: _GoogleStub,
) -> None:
    set_drive_folder(ready_root, "")
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    gap: str = msg.READINESS_GAP_IN_SETUP.format(
        what=msg.VAULT_FIELD_DRIVE_FOLDER, tab=msg.SETUP_TAB_TITLES["previews"]
    )
    parts: str = msg.LIST_JOINER.join((RunPart.DRIVE_PREVIEWS.human_label, RunPart.DOC.human_label))
    assert msg.RUN_NEED_BLOCKED.format(parts=parts, gap=gap) in out
    assert google.drive.calls == [] and google.docs.calls == []


def test_a_dry_run_creates_no_document_and_sends_nothing(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    google: _GoogleStub,
    telegram: FakeTelegram,
) -> None:
    _announcements_only(ready_root)
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.DOC_DRY_RUN_LINE in out and msg.ANNOUNCE_DRY_RUN_LINE in out
    assert google.drive.calls == [] and google.docs.calls == []
    assert telegram.calls == []


def test_without_slots_no_document_is_made(ready_root: LivecraftPaths, intake: _IntakeStub, google: _GoogleStub) -> None:
    """Будущих рядов нет — документа нет: к Google часть не обращается, код — «нечего делать»."""
    intake.result = IntakeResult(rows=PlannedRows(admitted=(), skipped=()), stopped_at=IntakeStage.TABLE)
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.NO_FUTURE_SLOTS)
    assert google.drive.calls == []


def test_a_failed_document_is_code_1(ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], google: _GoogleStub) -> None:
    """Отказ Docs — ошибка запуска: строка с причиной, код 1."""
    google.docs.failures.append(docs_error(403))
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    reason: str = msg.DOCS_FAILED.format(
        reason=msg.DOCS_REASON_TEXT["no_access"], status=msg.DOCS_FAILED_STATUS.format(status=403)
    )
    assert msg.DOC_FAILED_LINE.format(date="16.10.2026", reason=reason) in capsys.readouterr().out


# --- эфиры (§13 задача 5.7): часть «эфиры» в режимах «эфиры» и «всё»


def _two_language_intake() -> IntakeResult:
    """Итог прогона с двумя слотами на одну минуту: uk (канал kanal_ua) и ru (канал kanal_ru)."""
    uk_row: AdmittedRow = admitted_row(2, INTAKE_LINK, INTAKE_START)
    ru_row: AdmittedRow = admitted_row(3, "https://youtu.be/abcdefghijk", INTAKE_START)
    videos: tuple[SourceVideo, ...] = (
        ready_source(uk_row, INTAKE_TITLE, "Описание видео", "uk"),
        ready_source(ru_row, "Название ru", "Описание ru", "ru"),
    )
    return IntakeResult(
        rows=PlannedRows(admitted=(uk_row, ru_row), skipped=()),
        sources=PreparedSources(videos),
        build=build_slots(videos, ZoneInfo("Europe/Kyiv")),
    )


def test_the_broadcast_mode_runs_the_whole_broadcast_part(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], intake: _IntakeStub, broadcasts: _BroadcastsStub
) -> None:
    """Шапка → прогон таблицы → строки по ходу работы → пустая строка → «Итог», блоки, расход; эфир создан, ключ в
    форме, keys.txt и отчёт записаны; последним — подвал путей: ключи, отчёт, лог."""
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    lines: list[str] = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("Livecraft ")
    table: int = lines.index(intake.result.console_lines[0])
    create: int = next(index for index, line in enumerate(lines) if "создание эфира 16.10.2026 19:00 uk" in line)
    report: int = lines.index(msg.PROGRESS_REPORT)
    assert table < create < report and lines[report + 1] == "" and lines[report + 2].startswith("Итог по эфирам")
    assert [call.marker for call in broadcasts.platform.created] == ["16-10-2026_1900_uk"]
    assert len(broadcasts.posts) == 1
    keys: str = ready_root.file(FileName.KEYS).read_text(encoding=TEXT_ENCODING)
    assert "fake-0001-0000-0000-0000" in keys
    [report_file] = list(ready_root.logs_dir.glob("*_report.md"))
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    assert lines[-4:] == [
        "",
        f"  ключи   {ready_root.shown(ready_root.file(FileName.KEYS))}",
        f"  отчёт   {ready_root.shown(report_file)}",
        f"  лог     {ready_root.shown(log_file)}",
    ]
    assert lines[-5] == broadcasts.platform.gateway.usage.line
    assert sum(1 for line in lines if line.startswith("  отчёт ")) == 1
    assert msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0) not in lines   # линия выключена


def test_the_all_mode_publishes_first_and_broadcasts_last(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    assert run_cli([]) == int(ExitCode.OK)
    lines: list[str] = capsys.readouterr().out.splitlines()
    announce: int = lines.index(msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0))
    first_read: int = next(index for index, line in enumerate(lines) if "запрос запланированных эфиров" in line)
    assert announce < first_read
    assert len(broadcasts.platform.created) == 1 and len(broadcasts.posts) == 1


def test_a_youtube_failure_does_not_hold_back_the_announcements(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub, telegram: FakeTelegram
) -> None:
    """Сбой YouTube — код 1, но объявления уже ушли: эфиры идут последними."""
    broadcasts.platform.fail_create["16-10-2026_1900_uk"] = PlatformError("liveStreamingNotEnabled", "выключены")
    assert run_cli([]) == int(ExitCode.ERRORS)
    out: str = capsys.readouterr().out
    assert msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0) in out
    assert broadcasts.posts == []


def test_the_dry_run_changes_nothing_outside_but_writes_the_report(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    _broadcasts_only(ready_root)
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    platform: FakePlatform = broadcasts.platform
    assert platform.created == [] and platform.updated == [] and platform.attached == []
    assert platform.settings_writes == [] and platform.thumbnail_attempts == [] and platform.markers_set == []
    assert broadcasts.posts == []
    assert not ready_root.file(FileName.KEYS).exists() and not ready_root.file(FileName.RECORDS).exists()
    assert len(list(ready_root.logs_dir.glob("*_report.md"))) == 1
    assert "Итог по эфирам" in out and platform.list_calls == ["kanal_ua", "kanal_ru"]


def test_channels_without_a_token_log_in_before_the_first_channel_read(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    broadcasts.has_tokens = False
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    lines: list[str] = capsys.readouterr().out.splitlines()
    assert broadcasts.platform.logins == ["kanal_ua"]           # вход — только каналу с эфирами
    login: int = next(index for index, line in enumerate(lines) if "@kanal_ua" in line and "браузер" in line)
    first_read: int = next(index for index, line in enumerate(lines) if "запрос запланированных эфиров" in line)
    assert login < first_read
    assert len(broadcasts.platform.created) == 1


def test_a_refusing_channel_fails_only_its_own_broadcasts(
    ready_root: LivecraftPaths, intake: _IntakeStub, broadcasts: _BroadcastsStub, tmp_path: Path
) -> None:
    intake.result = _two_language_intake()
    broadcasts.platform.fail_list["kanal_ua"] = PlatformError("liveStreamingNotEnabled", "выключены")
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    assert [call.channel_id for call in broadcasts.platform.created] == ["kanal_ru"]
    assert len(broadcasts.posts) == 1


def test_the_memory_is_closed_after_a_crash_of_the_broadcast_part(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    broadcasts.platform.fail_create["16-10-2026_1900_uk"] = RuntimeError("platform exploded")  # type: ignore[assignment]
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    assert "run_crashed" in next(ready_root.logs_dir.glob(LOG_GLOB)).read_text(encoding="utf-8")
    ready_root.file(FileName.RECORDS).unlink()                 # открытый файл Windows удалить не даст


def test_the_memory_is_closed_after_an_interrupt_of_the_broadcast_part(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    broadcasts.platform.fail_create["16-10-2026_1900_uk"] = KeyboardInterrupt()  # type: ignore[assignment]
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)
    assert msg.RUN_INTERRUPTED in capsys.readouterr().out
    ready_root.file(FileName.RECORDS).unlink()


def test_no_youtube_slot_means_no_youtube(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], intake: _IntakeStub, broadcasts: _BroadcastsStub
) -> None:
    """Слот «по номерам» на YouTube не идёт: площадка не открывается, строка об этом."""
    single: IntakeResult = intake.result
    [slot] = single.slots
    numbered: StreamSlot = StreamSlot(slot.key, SlotTexts("1) Видео", "", SlotTextOrigin.NUMBERED), (), slot.sources)
    intake.result = IntakeResult(rows=single.rows, sources=single.sources, build=SlotBuild.of([numbered], True))
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.ERRORS)       # слот «по номерам» — код 1 прогона (решение 32)
    assert msg.BROADCASTS_NO_SLOTS in capsys.readouterr().out
    assert broadcasts.platform.describe_calls == [] and broadcasts.platform.list_calls == []


# --- линии работы и папки ролей (§14 решения 37, 38)


def test_with_the_table_on_a_bcast_file_is_copied_and_the_table_runs(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], intake: _IntakeStub, tmp_path: Path
) -> None:
    """Все линии включены: пакет из проводника только копируется, слоты — из таблицы (смешанной линии нет)."""
    source: Path = _package_of_the_run(tmp_path / "downloads")
    assert run_cli([str(source)]) == int(ExitCode.OK)
    assert (ready_root.bcast_dir / source.name).is_file() and len(intake.requests) == 1


def test_a_bcast_file_goes_into_the_package_folder_of_the_settings(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub, tmp_path: Path
) -> None:
    """Папка пакетов из настроек — абсолютная: пакет копируется туда, режим Б читает его оттуда."""
    chosen: Path = tmp_path / "chosen" / "packages"
    set_folders(ready_root, FolderSettings(packages=str(chosen), docs="docs", images="image"))
    _packages_only(ready_root)
    source: Path = _package_of_the_run(tmp_path / "downloads")
    assert run_cli([str(source)]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert (chosen / source.name).read_bytes() == source.read_bytes()
    assert msg.PACKAGE_DROP_COPIED.format(path=chosen / source.name) in out
    assert not (ready_root.bcast_dir / source.name).exists()
    assert [call.marker for call in broadcasts.platform.created] == ["16-10-2026_1900_uk"]


def test_the_packages_are_read_from_a_relative_package_folder(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    """Относительная папка пакетов — от корня программы; стандартная bcast\\ не читается."""
    set_folders(ready_root, FolderSettings(packages="shared/packages", docs="docs", images="image"))
    _packages_only(ready_root)
    _package_of_the_run(ready_root.root / "shared" / "packages")
    assert run_cli([]) == int(ExitCode.OK)
    assert [call.marker for call in broadcasts.platform.created] == ["16-10-2026_1900_uk"]


def test_a_bcast_file_with_unreadable_settings_is_not_copied_and_the_code_is_2(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], window_calls: list[LivecraftPaths], tmp_path: Path
) -> None:
    ready_root.file(FileName.CONFIG).write_bytes(b"{ broken")
    source: Path = _package_of_the_run(tmp_path / "downloads")
    assert run_cli([str(source)]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert msg.PACKAGE_DROP_NO_SETTINGS.format(file=source.name) in out
    assert not any(ready_root.bcast_dir.glob("*.bcast"))


def test_the_table_the_merge_and_the_package_only(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    intake: _IntakeStub,
    google: _GoogleStub,
    telegram: FakeTelegram,
    broadcasts: _BroadcastsStub,
) -> None:
    """Только таблица, нейросеть и пакет: прогон с merge и пакетом; ни Диска, ни документа, ни Telegram, ни YouTube."""
    set_lines(ready_root, lines_on(RunPart.PLAN, RunPart.MERGE, RunPart.PACKAGE))
    assert run_cli([]) == int(ExitCode.OK)
    [request] = intake.requests
    assert request.scope.parts == {RunPart.PLAN, RunPart.MERGE, RunPart.PACKAGE}
    assert google.drive.calls == [] and google.docs.calls == [] and telegram.calls == []
    assert broadcasts.opened == 0 and broadcasts.forms == []


def test_everything_but_telegram_sends_nothing_to_telegram(
    ready_root: LivecraftPaths, google: _GoogleStub, telegram: FakeTelegram, broadcasts: _BroadcastsStub
) -> None:
    set_lines(ready_root, lines_without(RunPart.ANNOUNCE))
    assert run_cli([]) == int(ExitCode.OK)
    assert telegram.calls == []
    assert len(_documents(google)) == 1 and len(broadcasts.platform.created) == 1 and len(broadcasts.posts) == 1


def test_the_document_without_its_copy(ready_root: LivecraftPaths, google: _GoogleStub) -> None:
    set_lines(ready_root, lines_without(RunPart.DOC_COPY, RunPart.BROADCAST, RunPart.KEYS))
    assert run_cli([]) == int(ExitCode.OK)
    assert len(_documents(google)) == 1 and google.drive.exports == []
    assert not any(ready_root.dir(DataDir.DOCS).rglob("*.docx"))


def test_the_broadcasts_without_the_keys_line_leave_the_key_in_the_keys_file(
    ready_root: LivecraftPaths, broadcasts: _BroadcastsStub
) -> None:
    """Эфиры без линии «Ключи в форму»: эфир создан, форма не читалась, ключ — в keys.txt со строкой
    «не отправлялся»."""
    set_lines(ready_root, lines_without(RunPart.KEYS, RunPart.DOC, RunPart.DOC_COPY, RunPart.ANNOUNCE))
    assert run_cli([]) == int(ExitCode.OK)
    assert len(broadcasts.platform.created) == 1
    assert [forms.gets for forms in broadcasts.forms] == [[]] and broadcasts.posts == []
    keys: str = ready_root.file(FileName.KEYS).read_text(encoding=TEXT_ENCODING)
    assert "fake-0001-0000-0000-0000" in keys and "не отправлялся: линия «Ключи в форму» выключена" in keys


def test_a_line_without_its_support_is_a_summary_line_and_code_0(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], intake: _IntakeStub
) -> None:
    """Копия документа без документа — не ошибка (§14 решение 37): строка сводки «Не работают без …», код 0; таблица
    идёт."""
    set_lines(ready_root, lines_on(RunPart.PLAN, RunPart.DOC_COPY))
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.LINES_NO_SUPPORT.format(support="Google-документ", lines="Копия документа") in out
    assert len(intake.requests) == 1


def test_no_line_on_is_one_line_the_window_and_code_2(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    window_calls: list[LivecraftPaths],
    intake: _IntakeStub,
) -> None:
    set_lines(ready_root, lines_on())
    assert run_cli([]) == int(ExitCode.CONFIG)
    out: str = capsys.readouterr().out
    assert msg.LINES_NONE_WORKING in out and msg.SETUP_OPENING in out
    assert window_calls == [ready_root] and intake.requests == []


def test_a_settings_file_without_the_lines_and_the_folders_gets_them_from_the_template(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    data: dict[str, object] = json.loads(ready_root.file(FileName.CONFIG).read_text(encoding=TEXT_ENCODING))
    del data["lines"], data["folders"]
    ready_root.file(FileName.CONFIG).write_text(json.dumps(data, ensure_ascii=False), encoding=TEXT_ENCODING)
    assert run_cli([]) == int(ExitCode.OK)
    assert msg.SETTINGS_SECTIONS_ADDED.format(sections="lines, folders") in capsys.readouterr().out
    shipped: LivecraftSettings = ShippedSettings().settings
    loaded: LivecraftSettings = SettingsFile.of(ready_root).load()
    assert (loaded.lines, loaded.folders) == (shipped.lines, shipped.folders)


def test_the_summary_names_the_lines(ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> None:
    set_lines(ready_root, lines_without(RunPart.ANNOUNCE, RunPart.DOC_COPY))
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.READINESS_LINES_OFF.format(lines="Копия документа, Telegram") in out
    assert "  линии работы: Таблица плана, Нейросеть," in out


def test_the_snapshot_of_the_run_is_in_the_log_without_a_value_of_the_vault(ready_root: LivecraftPaths) -> None:
    """Снимок запуска (§14 решение 38): настройки целиком, линии, папки, каналы, сейф — ярлыками с отпечатками."""
    assert run_cli([]) == int(ExitCode.OK)
    [log_file] = list(ready_root.logs_dir.glob(LOG_GLOB))
    text: str = log_file.read_text(encoding="utf-8")
    for event in ("run_snapshot_settings settings=", "run_snapshot_lines plan=on=yes;state=works;ready=yes",
                  "run_snapshot_folders packages=", "run_snapshot_channels channels=", "run_snapshot_vault vault="):
        assert event in text
    for value in (*TOKEN_VALUES.values(), BOT_TOKEN):
        assert value not in text


# --- отчёт запуска по частям (§3 шаг 12, задача 6.3)


def _report_text(paths: LivecraftPaths) -> str:
    """Текст единственного отчёта запуска в logs\\."""
    [report] = list(paths.logs_dir.glob("*_report.md"))
    return report.read_text(encoding=TEXT_ENCODING)


def _part_titles(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("## ")]


def test_the_report_of_a_run_has_the_run_the_table_and_the_broadcasts(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], intake: _IntakeStub, broadcasts: _BroadcastsStub
) -> None:
    """Части — в порядке работы; «Запуск» — строки, которые запуск сказал до частей; разделы частей — уровнем «###»."""
    _broadcasts_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    out: list[str] = capsys.readouterr().out.splitlines()
    said: list[str] = out[1:out.index(intake.result.console_lines[0])]
    text: str = _report_text(ready_root)
    assert text.startswith(f"# Livecraft {APP_VERSION} — отчёт ")
    assert _part_titles(text) == ["## Запуск", "## Таблица плана и тексты", "## Пакет", "## Эфиры YouTube"]
    lines: list[str] = text.splitlines()
    start: int = lines.index("## Запуск") + 2
    assert said and lines[start:start + len(said)] == said
    assert all(line in lines for line in intake.result.console_lines)
    assert "### Слоты (1)" in lines and "### Видео (1)" in lines and "### Создано (1)" in lines
    assert text.index("## Таблица плана и тексты") < text.index("### Слоты (1)") < text.index("## Эфиры YouTube")


def test_a_run_without_the_broadcasts_line_writes_the_report_too(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], google: _GoogleStub, telegram: FakeTelegram
) -> None:
    """Запуск без эфиров отчёт тоже пишет: таблица, пакет, документ и Telegram; подвал — отчёт и лог, без ключей."""
    _announcements_only(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    text: str = _report_text(ready_root)
    assert _part_titles(text) == [
        "## Запуск", "## Таблица плана и тексты", "## Пакет", "## Google-документ", "## Telegram"
    ]
    assert msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0) in text.splitlines()
    lines: list[str] = capsys.readouterr().out.splitlines()
    assert lines[-3] == "" and lines[-2].startswith("  " + msg.CONSOLE_LABEL_REPORT + " ")
    assert lines[-1].startswith("  " + msg.CONSOLE_LABEL_LOG + " ")


def test_a_package_run_without_packages_writes_the_report_with_code_3(
    ready_root: LivecraftPaths, broadcasts: _BroadcastsStub
) -> None:
    """Режим Б, в папке пакетов пусто: код 3, в отчёте — «Пакеты» со строкой полки; эфиров нет."""
    _packages_only(ready_root)
    assert run_cli([]) == int(ExitCode.NO_FUTURE_SLOTS)
    text: str = _report_text(ready_root)
    assert _part_titles(text) == ["## Запуск", "## Пакеты"]
    assert msg.BCAST_EMPTY.format(path=ready_root.shown(ready_root.bcast_dir)) in text.splitlines()


def test_a_dry_run_report_is_marked(ready_root: LivecraftPaths, broadcasts: _BroadcastsStub) -> None:
    _broadcasts_only(ready_root)
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    assert _report_text(ready_root).splitlines()[0].endswith(msg.REPORT_TITLE_DRY_RUN)


def test_a_run_refused_before_the_work_writes_no_report(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], window_calls: list[LivecraftPaths]
) -> None:
    """Не готова основа — окно настройки и код 2: до работы запуск не дошёл, отчёта и подвала нет."""
    ready_root.file(FileName.CLIENT_SECRET).unlink()
    assert run_cli([]) == int(ExitCode.CONFIG)
    assert not list(ready_root.logs_dir.glob("*_report.md"))
    assert "  " + msg.CONSOLE_LABEL_REPORT + " " not in capsys.readouterr().out


def test_status_writes_the_report_and_the_footer_is_the_last_output(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub
) -> None:
    """--status: отчёт из одной части эфиров (запуск до неё ничего не сказал), подвал — ключи, отчёт, лог."""
    assert run_cli(["--status"]) == int(ExitCode.OK)
    assert _part_titles(_report_text(ready_root)) == ["## Эфиры YouTube"]
    lines: list[str] = capsys.readouterr().out.splitlines()
    assert lines[-4] == ""
    assert [line.split()[0] for line in lines[-3:]] == [
        msg.CONSOLE_LABEL_KEYS, msg.CONSOLE_LABEL_REPORT, msg.CONSOLE_LABEL_LOG
    ]


def test_check_writes_no_report(ready_root: LivecraftPaths, broadcasts: _BroadcastsStub) -> None:
    assert run_cli(["--check"]) == int(ExitCode.OK)
    assert not list(ready_root.logs_dir.glob("*_report.md"))


# --- чистка старья по keep_days (§3 шаг 12): только полный запуск по линиям


def _old_log(paths: LivecraftPaths) -> Path:
    """Файл в logs\\, изменённый 40 дней назад: старше поставочного срока (30 дней)."""
    path: Path = paths.logs_dir / "01-01-2026_120000_livecraft.log"
    path.write_text("old", encoding=TEXT_ENCODING)
    moment: float = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    os.utime(path, (moment, moment))
    return path


def test_a_full_run_removes_old_files_and_says_so_in_the_launch_part(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    old: Path = _old_log(ready_root)
    assert run_cli([]) == int(ExitCode.OK)
    line: str = msg.RETENTION_REMOVED.format(days=30, count=1)
    assert not old.exists()
    assert line in capsys.readouterr().out.splitlines()
    assert line in _report_text(ready_root)


def test_a_run_without_old_files_says_nothing_about_them(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli([]) == int(ExitCode.OK)
    assert msg.RETENTION_REMOVED.split("(")[0] not in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--dry-run"], ["--status"], ["--check"]])
def test_dry_and_service_runs_remove_nothing(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub, argv: list[str]
) -> None:
    old: Path = _old_log(ready_root)
    run_cli(argv)
    assert old.exists()
    assert msg.RETENTION_REMOVED.split("(")[0] not in capsys.readouterr().out


def test_the_table_run_refreshes_yt_dlp_before_the_sources_and_says_what_was_updated(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], tools: _ToolsStub, intake: _IntakeStub
) -> None:
    """Обновление yt-dlp — до прогона таблицы, строкой раздела «Запуск» (в консоли и в отчёте); код не меняется."""
    updated: ToolUpdate = ToolUpdate("yt-dlp", ToolStatus.UPDATED, "2026.08.19", "2026.09.20")
    tools.check = SourceToolsCheck((updated,), tools.check.cookies)
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    line: str = msg.TOOL_UPDATED.format(tool="yt-dlp", before="2026.08.19", after="2026.09.20")
    assert line in capsys.readouterr().out.splitlines()
    assert tools.intakes_before == [0] and len(intake.requests) == 1
    [report] = list(ready_root.logs_dir.glob("*_report.md"))
    text: str = report.read_text(encoding=TEXT_ENCODING)
    assert text.index(msg.REPORT_PART_RUN) < text.index(line)


def test_a_cookies_file_of_the_wrong_form_is_code_2_before_the_sources(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], tools: _ToolsStub, intake: _IntakeStub
) -> None:
    tools.check = SourceToolsCheck((), CookiesStatus("secrets\\cookies.txt", CookiesState.BAD_FORMAT))
    assert run_cli([]) == int(ExitCode.CONFIG)
    assert msg.COOKIES_REEXPORT.format(path="secrets\\cookies.txt") in capsys.readouterr().out
    assert intake.requests == []


def test_packages_and_service_runs_do_not_refresh_yt_dlp(
    ready_root: LivecraftPaths, tools: _ToolsStub
) -> None:
    """Эфиры из пакетов, --status и окно настройки видео не читают — обновлений там нет."""
    _broadcasts_only(ready_root)
    run_cli([])
    _packages_only(ready_root)
    run_cli([])
    run_cli(["--status"])
    run_cli(["--setup"])
    assert tools.intakes_before == [0]


def test_a_live_lock_in_a_windowed_process_shows_a_message_window(
    livecraft_root: Path,
    live_foreign_process: subprocess.Popen[bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """livecraftw.exe (ярлык настройки): консоли нет — отказ второго экземпляра показывается окном-сообщением."""
    from tkinter import messagebox

    paths: LivecraftPaths = LivecraftPaths(livecraft_root)
    paths.ensure_dirs()
    InstanceLock(
        path=paths.file(FileName.LOCK),
        startup_log=paths.file(FileName.STARTUP_LOG),
        clock=Clock.utc(),
        pid=live_foreign_process.pid,
    ).acquire()
    owner: LockOwner | None = LockOwner.parse(paths.file(FileName.LOCK).read_text(encoding="utf-8"))
    assert owner is not None
    shown: list[str] = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, text: shown.append(text))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert run_cli(["--setup"]) == int(ExitCode.ERRORS)
    assert shown == [msg.LOCK_REJECTED.format(pid=owner.pid, started_at=owner.started_at)]


# --- вывод и эфиры от любого входа, тексты по линиям (§14 решения 49, 50, 51)

OTHER_FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-other-form/viewform"


def _run_packages(folder: Path) -> list[Path]:
    """Пакеты, которые записал запуск (не пакеты полки, которые положил тест: у тех имена без «plan_…_gen»)."""
    return sorted(path for path in folder.glob("plan_*_gen*.bcast"))


def _manifest_of(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        data: dict[str, Any] = json.loads(archive.read("manifest.json"))
    return data


def test_the_table_without_the_ai_gives_people_their_output_and_youtube_nothing(
    ready_root: LivecraftPaths,
    capsys: pytest.CaptureFixture[str],
    google: _GoogleStub,
    telegram: FakeTelegram,
    broadcasts: _BroadcastsStub,
) -> None:
    """Таблица без нейросети (§14 решение 50): документ и Telegram идут, пакета, эфиров и ключей нет — сводка называет
    причину; это не ошибка — код 0."""
    set_lines(ready_root, lines_without(RunPart.MERGE))
    assert run_cli([]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert len(_documents(google)) == 1 and "sendMessage" in telegram.methods
    assert "sendDocument" not in telegram.methods                  # пакета нет — и в Telegram его нет
    assert _run_packages(ready_root.bcast_dir) == [] and broadcasts.opened == 0
    assert "  не работают без «Нейросеть»: Пакет, Эфиры YouTube, Ключи в форму — " in out
    assert msg.READINESS_FIELD_LINE.format(label=msg.READINESS_TEXTS_LABEL, origin=msg.RUN_TEXT_SOURCES["videos"]) in out


def test_the_packages_give_only_a_fresh_package_per_form(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], broadcasts: _BroadcastsStub, google: _GoogleStub
) -> None:
    """«Пакеты → Пакет» — актуализация (§14 решение 51): прошедшие слоты отпали, из повторов остался слот новейшего
    пакета, по пакету на форму — со своей формой; ни Google, ни YouTube."""
    older: dict[str, Any] = slot_record("16-10-2026", title="Старое название")
    newer: dict[str, Any] = slot_record("16-10-2026", title="Новое название")
    past: dict[str, Any] = slot_record("15-03-2025", language="en")
    other: dict[str, Any] = slot_record("17-10-2026", language="ru", title="Другая форма")
    write_package(ready_root.bcast_dir, manifest(older, past, generated_at="01-09-2026 10:00"), "a_old.bcast")
    write_package(ready_root.bcast_dir, manifest(newer, generated_at="20-09-2026 10:00"), "b_new.bcast")
    write_package(ready_root.bcast_dir, manifest(other, form_url=OTHER_FORM_URL), "c_other.bcast")
    set_lines(ready_root, lines_on(RunPart.PACKAGE))
    assert run_cli([]) == int(ExitCode.OK)
    first, second = (_manifest_of(path) for path in _run_packages(ready_root.bcast_dir))
    by_form: dict[str, dict[str, Any]] = {data["form"]["url"]: data for data in (first, second)}
    assert [slot["title"] for slot in by_form[PACKAGE_FORM_URL]["slots"]] == ["Новое название"]
    assert [slot["slot_id"] for slot in by_form[OTHER_FORM_URL]["slots"]] == ["17-10-2026_1900_ru"]
    assert first["package_id"] != second["package_id"]
    assert google.drive.calls == [] and broadcasts.opened == 0
    out: str = capsys.readouterr().out
    texts: str = msg.READINESS_FIELD_LINE.format(label=msg.READINESS_TEXTS_LABEL, origin=msg.RUN_TEXT_SOURCES["packages"])
    assert texts in out


def test_the_packages_give_a_document_and_an_announcement_per_form_of_a_date(
    ready_root: LivecraftPaths, google: _GoogleStub, telegram: FakeTelegram, broadcasts: _BroadcastsStub
) -> None:
    """«Пакеты → документ и Telegram» (§14 решение 51): две формы на одну дату — два документа и два объявления, в
    каждом — форма своего пакета; таблица и форма настроек не нужны."""
    write_package(ready_root.bcast_dir, manifest(slot_record("16-10-2026")), "a.bcast")
    other: dict[str, Any] = manifest(slot_record("16-10-2026", "20:00", "en"), form_url=OTHER_FORM_URL)
    write_package(ready_root.bcast_dir, other, "b.bcast")
    set_lines(ready_root, lines_on(RunPart.DOC, RunPart.ANNOUNCE))
    assert run_cli([]) == int(ExitCode.OK)
    documents: list[DriveItem] = _documents(google)
    assert [item.name.endswith("_2") for item in documents] == [False, True]
    texts: list[str] = [str(call.body["text"]) for call in telegram.calls if call.method == "sendMessage"]
    headers: list[str] = [text for text in texts if PACKAGE_FORM_URL in text or OTHER_FORM_URL in text]
    assert any(PACKAGE_FORM_URL in text and OTHER_FORM_URL not in text for text in headers)
    assert any(OTHER_FORM_URL in text and PACKAGE_FORM_URL not in text for text in headers)
    assert texts.count(texts[0]) == 2                                  # начало дня — у каждого из двух объявлений
    assert broadcasts.opened == 0 and _run_packages(ready_root.bcast_dir) == []


def test_the_packages_copy_the_previews_under_the_cover_names_of_the_slot(ready_root: LivecraftPaths) -> None:
    """Превью слотов пакетов — в папке превью по шаблону, под именами обложек слота (§14 решение 51)."""
    record: dict[str, Any] = slot_record("16-10-2026", previews=["previews/a.jpg"])
    write_package(ready_root.bcast_dir, manifest(record), "a.bcast")
    set_lines(ready_root, lines_on(RunPart.LOCAL_PREVIEWS))
    assert run_cli([]) == int(ExitCode.OK)
    [copy] = ready_root.dir(DataDir.IMAGE).rglob("*.jpg")
    assert copy.name == "16-10-2026_1900_uk_1.jpg" and copy.parent.name == "uk"


def test_the_launch_drops_the_former_text_source_key_before_reading_the_settings(ready_root: LivecraftPaths) -> None:
    """livecraft.json с ключом broadcasts.text_source (до §14 решения 50): запуск убирает его сам и работает дальше."""
    config: Path = ready_root.file(FileName.CONFIG)
    data: dict[str, Any] = json.loads(config.read_text(encoding=TEXT_ENCODING))
    data["broadcasts"] = {"text_source": "package", **data["broadcasts"]}
    config.write_text(json.dumps(data, ensure_ascii=False), encoding=TEXT_ENCODING)
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    assert json.loads(config.read_text(encoding=TEXT_ENCODING))["broadcasts"] == {"resend_keys": False}


# --- строки хода в консоли (CLAUDE.md §13 задача 9.5)


def test_the_run_says_the_document_the_announcements_and_the_package_as_it_goes(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """Полный запуск: перед документом, объявлениями и пакетом — строка хода; итоговая строка части идёт после неё.
    В отчёт .md строки хода не попадают."""
    assert run_cli([]) == int(ExitCode.OK)
    lines: list[str] = capsys.readouterr().out.splitlines()
    [package] = ready_root.bcast_dir.glob("*.bcast")
    doc: int = lines.index(msg.PROGRESS_DOC.format(place=1, total=1, date="16.10.2026"))
    announce: int = lines.index(msg.PROGRESS_ANNOUNCE.format(place=1, total=1, date="16.10.2026"))
    sending: int = lines.index(msg.PROGRESS_ANNOUNCE_PACKAGE.format(name=package.name))
    doc_done: int = next(index for index, line in enumerate(lines) if line.startswith("Документ объявлений на "))
    day_done: int = lines.index(msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0))
    assert doc < doc_done < announce < sending < day_done
    [report] = list(ready_root.logs_dir.glob("*_report.md"))
    text: str = report.read_text(encoding=TEXT_ENCODING)
    assert msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=0) in text
    for started in (lines[doc], lines[announce], lines[sending]):
        assert started not in text
    assert "Создание документа" not in text and "Отправка" not in text and "Чтение видео" not in text


def test_the_table_run_gets_the_progress_of_the_launch_console(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str], intake: _IntakeStub
) -> None:
    """Прогон таблицы получает прогресс с консолью запуска: его строка хода уходит в тот же stdout."""
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    capsys.readouterr()
    [request] = intake.requests
    request.progress.video_started(StepCount(1, 1), INTAKE_LINK)
    assert capsys.readouterr().out.splitlines() == [msg.PROGRESS_VIDEO.format(place=1, total=1, link=INTAKE_LINK)]


def test_a_dry_run_has_no_progress_lines_of_the_parts_that_do_not_go(
    ready_root: LivecraftPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """Пробный запуск документ не создаёт и в Telegram не шлёт — строк хода этих частей нет."""
    assert run_cli(["--dry-run"]) == int(ExitCode.OK)
    out: str = capsys.readouterr().out
    assert msg.DOC_DRY_RUN_LINE in out and msg.ANNOUNCE_DRY_RUN_LINE in out
    assert "Создание документа" not in out and "Отправка" not in out
