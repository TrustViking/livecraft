"""Вкладка «Логи» без окна: «Отправить логи» (§8.2 п.11, §13 задача 7.2, §14 решения 20, 46). Архив всегда ложится в
папку logs и, если есть бот и чат поддержки, уходит туда документом; бот — на подделанном requests.post."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config.files import SettingsFile
from app.config.telegram import ChatTarget, TelegramSettings
from app.observability.log_event import LogArea
from app.paths import DataDir, LivecraftPaths
from app.publish.telegram_bot import TelegramBot
from app.setup.panels.logs_panel import LogsPanel, LogsRoute, LogsVerdict
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.telegram import BOT_TOKEN, BotCall, FakeTelegram
from app.ui import messages_ru as msg
from app.version import APP_VERSION

GROUP_ID: str = "-4000000001"
SUPERGROUP_ID: str = "-1001000000001"
PRIVATE_ID: str = "111000111"
MOMENT: datetime = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)      # 15:00 по Киеву
ARCHIVE: str = "livecraft_logs_29-09-2026_150000.zip"
LOG_TEXT: bytes = b"run_started version=7.2\n"


@pytest.fixture
def panel(ready_paths: LivecraftPaths) -> LogsPanel:
    """Установка с одним файлом лога, объявления — в личный чат."""
    (ready_paths.dir(DataDir.LOGS) / "29-09-2026_140000_livecraft.log").write_bytes(LOG_TEXT)
    _telegram(ready_paths, "")
    return LogsPanel(paths=ready_paths, clock=StoppedClock.at(MOMENT))


def _telegram(paths: LivecraftPaths, support_chat_id: str) -> None:
    file: SettingsFile = SettingsFile.of(paths)
    file.save(file.load().with_telegram(TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, support_chat_id)))


def _document(call: BotCall) -> tuple[object, ...]:
    files: object = call.options["files"]
    assert isinstance(files, dict)
    return tuple(files["document"])


def _saved(paths: LivecraftPaths) -> Path:
    return paths.dir(DataDir.LOGS) / ARCHIVE


def _saved_line(paths: LivecraftPaths) -> str:
    """Строка записи архива в logs\\: путь — от корня программы, размер — как у записанного файла."""
    saved: Path = _saved(paths)
    line: str = msg.SETUP_LOGS_SAVED.format(
        path=paths.shown(saved), files=1, megabytes=saved.stat().st_size / 1024 / 1024
    )
    return msg.CHECK_OK_LINE.format(line=line)


def test_the_route_says_what_will_be_done(panel: LogsPanel) -> None:
    """Одно правило для кнопки, строки вкладки и отправки: в чат поддержки — только с ботом и чатом поддержки; бота
    нет — строка о боте, даже когда чат подключён; бот без чата — строка о чате."""
    bot: TelegramBot = FakeTelegram.answering().bot
    without_chat: TelegramSettings = TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, "")
    with_chat: TelegramSettings = TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, GROUP_ID)
    assert panel.route(None, with_chat) == LogsRoute(msg.SETUP_LOGS_BUTTON_SAVE, msg.SETUP_LOGS_NO_SUPPORT_BOT)
    assert panel.route(bot, without_chat) == LogsRoute(msg.SETUP_LOGS_BUTTON_SAVE, msg.SETUP_LOGS_CHAT_NOT_CONNECTED)
    assert panel.route(bot, with_chat) == LogsRoute(msg.SETUP_LOGS_BUTTON_SEND, msg.SETUP_LOGS_ROUTE_SEND, GROUP_ID)


def test_the_archive_lies_in_the_logs_folder_and_goes_to_the_support_chat(
    panel: LogsPanel, ready_paths: LivecraftPaths
) -> None:
    _telegram(ready_paths, GROUP_ID)
    fake: FakeTelegram = FakeTelegram.answering("send_document_group")
    with LogCapture.on(LogArea.SETUP) as capture:
        verdict: LogsVerdict = panel.run(fake.bot)
    assert fake.methods == ["sendDocument"]
    call: BotCall = fake.calls[0]
    assert call.body["chat_id"] == GROUP_ID
    assert call.body["caption"] == msg.SETUP_LOGS_CAPTION.format(version=APP_VERSION, moment="29.09.2026 15:00", files=1)
    assert call.body["caption"].startswith("🛠")
    name, data, mime = _document(call)
    assert (name, mime) == (ARCHIVE, "application/zip")
    assert isinstance(data, bytes) and _saved(ready_paths).read_bytes() == data
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == ["diagnostics.txt", "29-09-2026_140000_livecraft.log"]
        assert archive.read("29-09-2026_140000_livecraft.log") == LOG_TEXT
    sent: str = msg.SETUP_LOGS_SENT.format(files=1, megabytes=len(data) / 1024 / 1024)
    assert verdict == LogsVerdict(is_ok=True, lines=(_saved_line(ready_paths), msg.CHECK_OK_LINE.format(line=sent)))
    assert f"logs_sent files=1 skipped=0 bytes={len(data)}" in capture.messages()
    assert not any(BOT_TOKEN in line for line in capture.messages())


def test_a_refused_bot_names_the_reason_and_the_archive_stays_in_the_logs_folder(
    panel: LogsPanel, ready_paths: LivecraftPaths
) -> None:
    _telegram(ready_paths, GROUP_ID)
    with LogCapture.on(LogArea.SETUP) as capture:
        verdict: LogsVerdict = panel.run(FakeTelegram.answering("forbidden").bot)
    assert _saved(ready_paths).is_file()
    refused: str = msg.SETUP_LOGS_NOT_SENT.format(reason=msg.TELEGRAM_PROBLEMS["forbidden"])
    assert verdict.lines == (_saved_line(ready_paths), msg.CHECK_PROBLEM_LINE.format(line=refused))
    assert not verdict.is_ok
    assert "logs_not_sent reason=forbidden" in capture.messages()


def test_without_a_support_bot_the_archive_stays_in_the_logs_folder_and_a_line_says_so(
    panel: LogsPanel, ready_paths: LivecraftPaths
) -> None:
    """Бота поддержки нет — архив только в logs\\, и строка говорит, почему он никуда не ушёл (§14 решение 58)."""
    _telegram(ready_paths, GROUP_ID)
    with LogCapture.on(LogArea.SETUP) as capture:
        verdict: LogsVerdict = panel.run(None)
    assert verdict == LogsVerdict(is_ok=True, lines=(_saved_line(ready_paths), msg.SETUP_LOGS_NO_SUPPORT_BOT))
    with zipfile.ZipFile(_saved(ready_paths)) as archive:
        assert "diagnostics.txt" in archive.namelist()
    assert any(line.startswith("logs_saved path=") for line in capture.messages())


def test_without_a_support_chat_the_archive_is_saved_and_nothing_is_sent(
    panel: LogsPanel, ready_paths: LivecraftPaths
) -> None:
    """Бот поддержки есть, чата поддержки нет — архив только в logs\\, и строка говорит, что чат не подключён."""
    fake: FakeTelegram = FakeTelegram.answering()
    verdict: LogsVerdict = panel.run(fake.bot)
    assert fake.calls == []
    assert verdict == LogsVerdict(is_ok=True, lines=(_saved_line(ready_paths), msg.SETUP_LOGS_CHAT_NOT_CONNECTED))


def test_a_second_archive_leaves_the_first_one_out(panel: LogsPanel, ready_paths: LivecraftPaths) -> None:
    """Прежний архив лежит в той же папке logs, но в новый не входит (§14 решение 46)."""
    earlier: Path = ready_paths.dir(DataDir.LOGS) / "livecraft_logs_28-09-2026_120000.zip"
    earlier.write_bytes(b"PK old archive")
    panel.run(None)
    with zipfile.ZipFile(_saved(ready_paths)) as archive:
        assert archive.namelist() == ["diagnostics.txt", "29-09-2026_140000_livecraft.log"]


def test_a_support_group_that_became_a_supergroup_gets_its_new_id(panel: LogsPanel, ready_paths: LivecraftPaths) -> None:
    """Перенос — тот же `ChatMigration`, что у объявлений: новый id — в livecraft.json, чат объявлений прежний."""
    _telegram(ready_paths, GROUP_ID)
    verdict: LogsVerdict = panel.run(FakeTelegram.answering("migrated", "send_message_supergroup").bot)
    assert verdict.lines[-1] == msg.TELEGRAM_CHAT_MIGRATED.format(old_chat_id=GROUP_ID, new_chat_id=SUPERGROUP_ID)
    telegram: TelegramSettings = SettingsFile.of(ready_paths).load().telegram
    assert telegram == TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, SUPERGROUP_ID)


def test_an_archive_that_does_not_write_is_named_and_nothing_is_sent(panel: LogsPanel, ready_paths: LivecraftPaths) -> None:
    """На месте архива — папка: архив не записан, отправки нет, строка — с причиной ОС."""
    _telegram(ready_paths, GROUP_ID)
    _saved(ready_paths).mkdir()
    fake: FakeTelegram = FakeTelegram.answering()
    verdict: LogsVerdict = panel.run(fake.bot)
    assert not verdict.is_ok and len(verdict.lines) == 1 and fake.calls == []
    assert verdict.lines[0].startswith(msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_LOGS_NOT_SAVED.format(reason="")))