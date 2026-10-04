"""Вкладка «Логи» на настоящем окне Tk за краем экрана (§8.2 п.11, §13 задача 7.2): место в окне, бот поддержки —
свой, отдельный от бота объявлений (§14 решение 58), подключение чата поддержки тем же видом, что чат объявлений, бот
и чат поддержки из токена доступа и архив в папке logs (§14 решение 46)."""
from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config.files import SettingsFile
from app.config.telegram import ChatTarget, TelegramSettings
from app.paths import DataDir, FileName, LivecraftPaths
from app.publish.telegram_bot import TelegramBot
from app.runtime.log_archive import LOG_ARCHIVE_LIMIT_MEGABYTES
from app.secretsafe.field import SecretField
from app.secretsafe.token import TOKEN_SUFFIX
from app.setup.page import SetupPage
from app.setup.tabs.logs_tab import LogsTab
from app.tests.conftest import CLIENT_SECRET_STUB, REPO_CHANNELS_EXAMPLE
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.tests.fixtures.telegram import BOT_TOKEN, PRIVATE_CHAT_ID, FakeTelegram, connect_private_chat
from app.tests.fixtures.token import FakePicker, network_at
from app.tests.fixtures.vault import save_own_values
from app.ui import messages_ru as msg

GROUP_ID: str = "-4000000001"
SUPPORT_BOT_TOKEN: str = "987654321:AAFsupport-Zy9xWvUtSrQpOnMlKjIhGfEdCbA_987"
ARCHIVE: str = "livecraft_logs_29-09-2026_150000.zip"


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на готовом корне: свой бот и объявления в личный чат, чата поддержки нет."""
    connect_private_chat(ready_paths)
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def _by_id(chat_id: str) -> str:
    """Строка чата поддержки по файлу: называет только чат — как строки объявлений, без «уходят»."""
    return msg.SETUP_TELEGRAM_CHAT_CONNECTED.format(chat=msg.SETUP_TELEGRAM_CHAT_BY_ID.format(chat_id=chat_id))


def test_the_tab_stands_before_advanced_and_says_what_goes(driver: SetupWindowDriver) -> None:
    tab: LogsTab = driver.logs
    assert list(SetupPage)[-2:] == [SetupPage.LOGS, SetupPage.ADVANCED]
    assert [item.page for item in driver.tabs.all][-2:] == [SetupPage.LOGS, SetupPage.ADVANCED]
    texts: list[str] = driver.visible_texts()
    for text in (
        msg.SETUP_TAB_TITLES["logs"], msg.SETUP_LOGS_INTRO, msg.SETUP_LOGS_BOT_TITLE, msg.SETUP_LOGS_BOT_TEXT,
        msg.SETUP_KEY_FIELD_LABELS["support_bot_token"], msg.SETUP_LOGS_CHAT_TITLE, msg.SETUP_LOGS_CHAT_TEXT,
        msg.SETUP_LOGS_SEND_TITLE, msg.SETUP_LOGS_SEND_TEXT.format(limit=LOG_ARCHIVE_LIMIT_MEGABYTES),
        msg.SETUP_LOGS_NO_SUPPORT_BOT,
    ):
        assert text in texts
    assert len(tab.chat.rows) == 1 and tab.chat.rows[0].line.cget("text") == msg.SETUP_TELEGRAM_CHAT_NOT_CONNECTED
    assert tab.route_line.cget("text") == msg.SETUP_LOGS_NO_SUPPORT_BOT
    assert tab.chat.rows[0].button.cget("text") == msg.SETUP_LOGS_BUTTON_CONNECT
    assert tab.send_line.button.cget("text") == msg.SETUP_LOGS_BUTTON_SAVE


def test_connecting_the_support_chat_keeps_the_announcement_chat(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_group", "send_message_group")
    driver.logs_talk_to(fake)
    driver.logs.chat.rows[0].button.invoke()
    telegram: TelegramSettings = SettingsFile.of(ready_paths).load().telegram
    assert telegram == TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_CHAT_ID, GROUP_ID)
    assert fake.calls[-1].body["text"] == msg.SETUP_LOGS_CHAT_CONNECT_TEXT
    destination: str = msg.SETUP_TELEGRAM_DESTINATION_BY_TITLE.format(
        into=msg.SETUP_TELEGRAM_TARGETS_INTO["group"], title="Livecraft group"
    )
    assert driver.logs.chat.status.cget("text") == msg.SETUP_LOGS_CHAT_CONNECTED.format(destination=destination)
    assert driver.logs.send_line.button.cget("text") == msg.SETUP_LOGS_BUTTON_SEND
    assert driver.logs.route_line.cget("text") == msg.SETUP_LOGS_ROUTE_SEND
    announce: str = " ".join(str(row.line.cget("text")) for row in driver.telegram.chat.rows)
    assert PRIVATE_CHAT_ID in announce and GROUP_ID not in announce


def test_the_logs_never_take_the_announcement_bot(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    """Бот объявлений задан, чат поддержки подключён, бота поддержки нет: вкладка не шлёт логи ботом объявлений —
    архив только в logs\\ и строка «Бот поддержки не задан» (§14 решение 58)."""
    file: SettingsFile = SettingsFile.of(ready_paths)
    file.save(file.load().with_telegram(TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_CHAT_ID, GROUP_ID)))
    driver.window.refresh()
    assert driver.telegram.telegram_bot() is not None and driver.logs.telegram_bot() is None
    assert driver.logs.send_line.button.cget("text") == msg.SETUP_LOGS_BUTTON_SAVE
    assert driver.logs.chat.rows[0].line.cget("text") == _by_id(GROUP_ID)
    assert driver.logs.route_line.cget("text") == msg.SETUP_LOGS_NO_SUPPORT_BOT
    driver.logs.chat.rows[0].button.invoke()
    assert driver.logs.chat.status.cget("text") == msg.SETUP_LOGS_BOT_FIRST
    driver.logs.send_line.button.invoke()
    driver.wait_for(driver.logs.send_line)
    assert (ready_paths.dir(DataDir.LOGS) / ARCHIVE).is_file()
    assert msg.SETUP_LOGS_NO_SUPPORT_BOT in driver.logs.send_line.result_text


def test_the_support_bot_token_is_saved_on_the_tab_and_names_the_bot(driver: SetupWindowDriver) -> None:
    """Токен бота поддержки — своё значение сейфа своей строки; после записи вкладка называет бота поддержки, а бот
    вкладки — на этом токене, не на токене бота объявлений."""
    fake: FakeTelegram = FakeTelegram.answering("get_me")
    driver.logs_talk_to(fake)
    driver.accept_key(SecretField.SUPPORT_BOT_TOKEN, SUPPORT_BOT_TOKEN)
    assert driver.logs.bot_key.line.cget("text") == msg.SETUP_TELEGRAM_BOT_READY.format(
        name="Livecraft", username="livecraft_test_bot"
    )
    bot: TelegramBot | None = driver.logs.telegram_bot()
    assert bot is not None and bot.token.reveal() == SUPPORT_BOT_TOKEN       # эталон теста раскрывает сам тест
    assert not any(SUPPORT_BOT_TOKEN in text for text in driver.visible_texts())


def test_without_a_support_chat_the_archive_goes_to_the_logs_folder(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    driver.logs.send_line.button.invoke()
    driver.wait_for(driver.logs.send_line)
    saved: Path = ready_paths.dir(DataDir.LOGS) / ARCHIVE
    assert saved.is_file()
    first: str = driver.logs.send_line.result_text.split("\n")[0]
    assert first.startswith(msg.CHECK_OK_LINE.format(line=msg.SETUP_LOGS_SAVED.format(
        path=ready_paths.shown(saved), files=0, megabytes=0
    ).split(" (")[0]))


def test_a_loaded_token_brings_the_support_chat(
    driver: SetupWindowDriver, tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    """Получатель токена получает бота и чат поддержки без настройки: вкладка показывает их сразу после загрузки."""
    creator: LivecraftPaths = LivecraftPaths(tmp_path / "creator")
    creator.ensure_dirs()
    SettingsFile.of(creator).install_shipped()
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, creator.file(FileName.CHANNELS))
    creator.file(FileName.CLIENT_SECRET).write_text(CLIENT_SECRET_STUB, encoding="utf-8")
    save_own_values(creator, {SecretField.SUPPORT_BOT_TOKEN: SUPPORT_BOT_TOKEN})
    file: SettingsFile = SettingsFile.of(creator)
    file.save(file.load().with_telegram(TelegramSettings(ChatTarget.PRIVATE, "", "", GROUP_ID)))
    for maker in SetupWindowDriver.opened(creator, pytestconfig):
        maker.tokens.create_line.button.invoke()
        maker.wait_for(maker.tokens.create_line)
    token: Path = next(creator.dir(DataDir.TOKENS).glob("*" + TOKEN_SUFFIX))
    driver.tokens_on(network_at(), FakePicker(token))
    driver.tokens.load_line.button.invoke()
    driver.wait_for(driver.tokens.load_line)
    assert driver.logs.chat.rows[0].line.cget("text") == _by_id(GROUP_ID)
    assert driver.logs.send_line.button.cget("text") == msg.SETUP_LOGS_BUTTON_SEND
    assert driver.logs.rows[SecretField.SUPPORT_BOT_TOKEN].status.cget("text").startswith("✓")
