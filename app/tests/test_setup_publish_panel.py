"""Вкладка «Telegram» без окна: кто бот, кнопки подключения чата с ботом и группы с ботом (каждая ищет только чаты
своего вида), подсказка группы, выбор «куда слать» и строка назначения, пробное сообщение, названия чатов этого окна,
запись только раздела telegram поверх свежего файла (CLAUDE.md §8.2 п.7, §14 решения 19, 20, 57, 58). Бот — на
подделанном requests.post: к настоящему Telegram тесты не ходят.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.config.files import SettingsFile, ShippedSettings
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings
from app.config.telegram import ChatRole, ChatSearch, ChatTarget, TelegramSettings
from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.publish.telegram_api import BotChat, BotChats, BotMethod, ChatKind
from app.setup.panels.publish_panel import BotCard, ChatConnection, ChatDestination, PublishPanel
from app.setup.panels.settings_panel import SettingsPanel
from app.tests.fixtures.drafts import draft_with
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.telegram import BOT_TOKEN, FakeBotResponse, FakeTelegram
from app.ui import messages_ru as msg

GROUP_ID: str = "-4000000001"
SUPERGROUP_ID: str = "-1001000000001"
PRIVATE_ID: str = "111000111"
OTHER_PRIVATE_ID: str = "222000222"
GROUP: BotChat = BotChat(chat_id=GROUP_ID, kind=ChatKind.GROUP, title="Livecraft group")
# getMe другого бота: другой id — названия чатов прежнего бота уже неверны.
OTHER_BOT: FakeBotResponse = FakeBotResponse({"ok": True, "result": {
    "id": 999000999, "is_bot": True, "first_name": "Other", "username": "other_test_bot",
}}, 200)
PRIVATE: BotChat = BotChat(chat_id=PRIVATE_ID, kind=ChatKind.PRIVATE, title="Test User", username="test_user")
BOT_READY: str = msg.SETUP_TELEGRAM_BOT_READY.format(name="Livecraft", username="livecraft_test_bot")
PRIVATE_SEARCH: ChatSearch = ChatTarget.PRIVATE.search
GROUP_SEARCH: ChatSearch = ChatTarget.GROUP.search
# getUpdates: боту написали из двух личных чатов.
TWO_PRIVATE_UPDATES: FakeBotResponse = FakeBotResponse({"ok": True, "result": [
    {"update_id": 1, "message": {"chat": {"id": int(PRIVATE_ID), "first_name": "Test", "type": "private"}}},
    {"update_id": 2, "message": {"chat": {"id": int(OTHER_PRIVATE_ID), "first_name": "Other", "type": "private"}}},
]}, 200)


def _panel(paths: LivecraftPaths) -> PublishPanel:
    """Вкладка объявлений на livecraft.json установки."""
    return PublishPanel.from_file(SettingsFile.of(paths))


def _telegram_on_disk(paths: LivecraftPaths) -> TelegramSettings:
    return SettingsFile.of(paths).load().telegram


def _save_telegram(paths: LivecraftPaths, telegram: TelegramSettings) -> None:
    file: SettingsFile = SettingsFile.of(paths)
    file.save(file.load().with_telegram(telegram))


def _into(target: ChatTarget) -> str:
    return msg.SETUP_TELEGRAM_TARGETS_INTO[target.value]


def _connected_line(target: ChatTarget, title: str) -> str:
    destination: str = msg.SETUP_TELEGRAM_DESTINATION_BY_TITLE.format(into=_into(target), title=title)
    return msg.SETUP_TELEGRAM_CONNECTED.format(destination=destination)


def _connected_to_group(paths: LivecraftPaths) -> PublishPanel:
    """Группа подключена: раздел telegram записан, пробное сообщение ушло."""
    return _panel(paths).connect(FakeTelegram.answering("send_message_group").bot, GROUP)


# --- открытие


def test_the_tab_opens_on_the_file_without_a_chat(ready_paths: LivecraftPaths) -> None:
    panel: PublishPanel = _panel(ready_paths)
    assert panel.settings.telegram == TelegramSettings(ChatTarget.PRIVATE, "", "", "")
    assert (panel.notices, panel.status, panel.bot, panel.chats) == ((), (), BotCard(), BotChats(chats=()))
    for search in (PRIVATE_SEARCH, GROUP_SEARCH):
        assert panel.destination_of(search) is None
        assert panel.line_of(search) == msg.SETUP_TELEGRAM_CHAT_NOT_CONNECTED
    assert panel.destination_line == msg.SETUP_TELEGRAM_DESTINATION_NONE


def test_the_announcement_chats_are_the_private_chat_and_the_group_in_this_order() -> None:
    assert ChatRole.ANNOUNCE.searches == (PRIVATE_SEARCH, GROUP_SEARCH)
    assert (PRIVATE_SEARCH.targets, GROUP_SEARCH.targets) == ((ChatTarget.PRIVATE,), (ChatTarget.GROUP,))
    assert (PRIVATE_SEARCH.words.title, GROUP_SEARCH.words.title) == ("Чат с ботом", "Группа с ботом")


def test_an_unreadable_file_opens_the_tab_on_the_template_and_says_why(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.CONFIG).write_bytes(b"{ not json")
    panel: PublishPanel = _panel(ready_paths)
    error: ConfigError | None = SettingsFile.of(ready_paths).read().error
    assert error is not None
    assert panel.notices == (msg.SETUP_TELEGRAM_NOTICE_UNREADABLE.format(key=error.key_path, problem=error.problem),)


def test_the_chats_by_the_file_are_named_by_their_ids(ready_paths: LivecraftPaths) -> None:
    _save_telegram(ready_paths, TelegramSettings(ChatTarget.GROUP, GROUP_ID, PRIVATE_ID, ""))
    panel: PublishPanel = _panel(ready_paths)
    assert panel.destination_of(GROUP_SEARCH) == ChatDestination(ChatTarget.GROUP, GROUP_ID)
    assert panel.destination_of(PRIVATE_SEARCH) == ChatDestination(ChatTarget.PRIVATE, PRIVATE_ID)
    assert panel.line_of(GROUP_SEARCH) == "подключён: id -4000000001"
    assert panel.line_of(PRIVATE_SEARCH) == "подключён: id 111000111"
    assert ChatDestination(ChatTarget.GROUP, GROUP_ID).text == msg.SETUP_TELEGRAM_DESTINATION_BY_ID.format(
        into=_into(ChatTarget.GROUP), chat_id=GROUP_ID
    )


# --- шаг 1 и шаг 2: кто бот


def test_describe_bot_names_the_bot_and_its_address(ready_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.answering("get_me")
    panel: PublishPanel = _panel(ready_paths).describe_bot(fake.bot)
    assert panel.bot.status == BOT_READY
    assert panel.bot.url == "https://t.me/livecraft_test_bot"
    assert fake.methods == [BotMethod.GET_ME.value] and panel.status == ()


def test_without_a_token_the_bot_is_not_named_and_step_one_comes_first(ready_paths: LivecraftPaths) -> None:
    named: PublishPanel = _panel(ready_paths).describe_bot(FakeTelegram.answering("get_me").bot)
    unnamed: PublishPanel = named.describe_bot(None)
    assert unnamed.bot == BotCard() and unnamed.bot.url is None
    assert unnamed.status == (msg.SETUP_TELEGRAM_STEP_1_FIRST,)


def test_a_refused_get_me_is_the_step_status_and_a_log_line_without_the_token(ready_paths: LivecraftPaths) -> None:
    with LogCapture.on(LogArea.SETUP) as capture:
        panel: PublishPanel = _panel(ready_paths).describe_bot(
            FakeTelegram.answering("unauthorized").bot
        )
    assert panel.bot == BotCard(status=msg.TELEGRAM_PROBLEMS["bad_token"]) and panel.bot.url is None
    assert any(line.startswith("telegram_failed method=getMe reason=bad_token") for line in capture.messages())
    assert not any(BOT_TOKEN in line for line in capture.messages())


# --- шаг 3: кнопки подключения чата с ботом и группы с ботом


def _announce_to_private(paths: LivecraftPaths) -> None:
    _save_telegram(paths, TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, ""))


def test_without_a_token_the_buttons_ask_for_step_one(ready_paths: LivecraftPaths) -> None:
    panel: PublishPanel = _panel(ready_paths)
    for done in (panel.find_chats(None, PRIVATE_SEARCH), panel.find_chats(None, GROUP_SEARCH), panel.connect(None, GROUP)):
        assert done.status == (msg.SETUP_TELEGRAM_STEP_1_FIRST,)
    assert _telegram_on_disk(ready_paths) == panel.settings.telegram


def test_one_private_chat_is_connected_at_once(ready_paths: LivecraftPaths) -> None:
    """Боту написали из одного личного чата: он сразу адрес объявлений, в файле — личный чат и его id."""
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_private", "send_message_private")
    panel: PublishPanel = _panel(ready_paths).find_chats(fake.bot, PRIVATE_SEARCH)
    assert fake.methods == ["getMe", "getWebhookInfo", "getUpdates", "sendMessage"]
    assert fake.calls[-1].body["chat_id"] == PRIVATE_ID
    assert fake.calls[-1].body["text"] == msg.SETUP_TELEGRAM_CONNECT_TEXT
    telegram: TelegramSettings = _telegram_on_disk(ready_paths)
    assert (telegram.target, telegram.private_chat_id, telegram.group_chat_id) == (ChatTarget.PRIVATE, PRIVATE_ID, "")
    assert panel.status == (_connected_line(ChatTarget.PRIVATE, "Test User @test_user"),)
    assert panel.line_of(PRIVATE_SEARCH) == "подключён: Test User @test_user"
    assert panel.line_of(GROUP_SEARCH) == msg.SETUP_TELEGRAM_CHAT_NOT_CONNECTED
    assert panel.bot.status == BOT_READY and panel.chats == BotChats(chats=())


def test_a_group_connected_while_the_chat_with_the_bot_is_the_target_leaves_the_target(
    ready_paths: LivecraftPaths,
) -> None:
    """Объявления уходят в подключённый чат с ботом: подключение группы пишет её id, а назначение не трогает — его
    меняет только выбор «Куда слать объявления» (§14 решение 58, прогон 0.1.6 04-10-2026 00:59)."""
    _announce_to_private(ready_paths)
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_group", "send_message_group")
    panel: PublishPanel = _panel(ready_paths).find_chats(fake.bot, GROUP_SEARCH)
    assert _telegram_on_disk(ready_paths) == TelegramSettings(ChatTarget.PRIVATE, GROUP_ID, PRIVATE_ID, "")
    assert panel.status == (_connected_line(ChatTarget.GROUP, "Livecraft group"),)
    assert panel.line_of(GROUP_SEARCH) == "подключён: Livecraft group"
    assert panel.line_of(PRIVATE_SEARCH) == "подключён: id 111000111"
    assert panel.destination_line == msg.SETUP_TELEGRAM_DESTINATION_NOW.format(
        destination=msg.SETUP_TELEGRAM_DESTINATION_BY_ID.format(into=_into(ChatTarget.PRIVATE), chat_id=PRIVATE_ID)
    )
    telegram: TelegramSettings = panel.settings.telegram
    assert telegram.is_connected(ChatTarget.PRIVATE) and telegram.is_connected(ChatTarget.GROUP)


def test_the_first_connected_chat_becomes_the_target(ready_paths: LivecraftPaths) -> None:
    """У назначения ещё нет чата (по умолчанию — чат с ботом): подключённая группа становится назначением, и строка
    назначения называет её."""
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_group", "send_message_group")
    panel: PublishPanel = _panel(ready_paths).find_chats(fake.bot, GROUP_SEARCH)
    assert _telegram_on_disk(ready_paths) == TelegramSettings(ChatTarget.GROUP, GROUP_ID, "", "")
    assert panel.destination_line == msg.SETUP_TELEGRAM_DESTINATION_NOW.format(
        destination=msg.SETUP_TELEGRAM_DESTINATION_BY_TITLE.format(into=_into(ChatTarget.GROUP), title="Livecraft group")
    )


def test_reconnecting_the_chat_with_the_bot_after_the_group_leaves_the_group_the_target(
    ready_paths: LivecraftPaths,
) -> None:
    """Боевой случай 04-10-2026 00:58: группа — назначение, повторное подключение чата с ботом её не сменяет."""
    _save_telegram(ready_paths, TelegramSettings(ChatTarget.GROUP, GROUP_ID, PRIVATE_ID, ""))
    _panel(ready_paths).connect(FakeTelegram.answering("send_message_private").bot, PRIVATE)
    assert _telegram_on_disk(ready_paths) == TelegramSettings(ChatTarget.GROUP, GROUP_ID, PRIVATE_ID, "")


def test_the_announcement_role_moves_the_target_only_to_a_target_without_a_chat() -> None:
    connected: TelegramSettings = TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, "")
    empty: TelegramSettings = TelegramSettings(ChatTarget.PRIVATE, GROUP_ID, "", "")
    assert ChatRole.ANNOUNCE.connected(connected, ChatTarget.GROUP, GROUP_ID).target is ChatTarget.PRIVATE
    assert ChatRole.ANNOUNCE.connected(empty, ChatTarget.GROUP, SUPERGROUP_ID) == TelegramSettings(
        ChatTarget.GROUP, SUPERGROUP_ID, "", ""
    )


def test_two_chats_connected_in_a_row_both_keep_their_names(ready_paths: LivecraftPaths) -> None:
    """Названия знает только Telegram: окно помнит все чаты, подключённые в нём, а не только последний."""
    private: PublishPanel = _panel(ready_paths).find_chats(
        FakeTelegram.answering("get_me", "webhook_none", "updates_private", "send_message_private").bot, PRIVATE_SEARCH
    )
    both: PublishPanel = private.find_chats(
        FakeTelegram.answering("get_me", "webhook_none", "updates_group", "send_message_group").bot, GROUP_SEARCH
    )
    assert both.line_of(PRIVATE_SEARCH) == "подключён: Test User @test_user"
    assert both.line_of(GROUP_SEARCH) == "подключён: Livecraft group"


def test_another_bot_forgets_the_names_of_the_chats_of_the_former_one(ready_paths: LivecraftPaths) -> None:
    """Бот сменился (сохранён другой токен, токен убран): чаты, подключённые прежним ботом, — строкой по файлу."""
    connected: PublishPanel = _panel(ready_paths).find_chats(
        FakeTelegram.answering("get_me", "webhook_none", "updates_group", "send_message_group").bot, GROUP_SEARCH
    )
    same: PublishPanel = connected.describe_bot(FakeTelegram.answering("get_me").bot)
    assert same.line_of(GROUP_SEARCH) == "подключён: Livecraft group"
    other: PublishPanel = connected.describe_bot(FakeTelegram.answering(OTHER_BOT).bot)
    removed: PublishPanel = connected.describe_bot(None)
    for panel in (other, removed):
        assert panel.line_of(GROUP_SEARCH) == "подключён: id -4000000001"


def test_rereading_takes_the_chats_from_the_disk_and_keeps_the_names(ready_paths: LivecraftPaths) -> None:
    """Чат поддержки подключён на «Логах»: модель «Telegram» перечитывает файл и не забывает своих названий."""
    connected: PublishPanel = _panel(ready_paths).find_chats(
        FakeTelegram.answering("get_me", "webhook_none", "updates_group", "send_message_group").bot, GROUP_SEARCH
    )
    _save_telegram(ready_paths, TelegramSettings(ChatTarget.GROUP, GROUP_ID, PRIVATE_ID, SUPERGROUP_ID))
    reread: PublishPanel = connected.reread()
    assert reread.settings.telegram.private_chat_id == PRIVATE_ID
    assert reread.line_of(GROUP_SEARCH) == "подключён: Livecraft group"
    assert (reread.bot, reread.status) == (connected.bot, connected.status)


def test_the_group_hint_says_what_to_do_first_naming_the_bot(ready_paths: LivecraftPaths) -> None:
    """Пока группа не подключена — подсказка над её кнопкой: с @именем бота, когда бот назван; подключена — пусто. У
    чата с ботом подсказки нет: её даёт шаг 2."""
    telegram: TelegramSettings = _panel(ready_paths).settings.telegram
    assert GROUP_SEARCH.hint(telegram, None) == msg.SETUP_TELEGRAM_TARGET_HINTS_UNNAMED["group"]
    assert GROUP_SEARCH.hint(telegram, "livecraft_test_bot") == (
        "Сначала добавьте бота @livecraft_test_bot в группу и отправьте в ней /start@livecraft_test_bot, затем нажмите "
        "«Подключить группу с ботом»."
    )
    assert PRIVATE_SEARCH.hint(telegram, "livecraft_test_bot") == ""
    connected: TelegramSettings = TelegramSettings(ChatTarget.GROUP, GROUP_ID, "", "")
    assert GROUP_SEARCH.hint(connected, "livecraft_test_bot") == ""
    named: PublishPanel = _panel(ready_paths).describe_bot(FakeTelegram.answering("get_me").bot)
    assert named.bot.username == "livecraft_test_bot"


def test_the_group_button_does_not_take_a_private_chat(ready_paths: LivecraftPaths) -> None:
    """Боту писали только из личного чата: кнопка группы его не подключает, а говорит, как подключить группу."""
    before: bytes = ready_paths.file(FileName.CONFIG).read_bytes()
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_private")
    panel: PublishPanel = _panel(ready_paths).find_chats(fake.bot, GROUP_SEARCH)
    assert panel.status == (
        "Бот @livecraft_test_bot пока не видит ни одной группы: добавьте его в группу, отправьте в ней "
        "/start@livecraft_test_bot, затем ещё раз «Подключить группу с ботом».",
    )
    assert ready_paths.file(FileName.CONFIG).read_bytes() == before and "sendMessage" not in fake.methods


def test_the_private_button_does_not_take_a_group(ready_paths: LivecraftPaths) -> None:
    before: bytes = ready_paths.file(FileName.CONFIG).read_bytes()
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_group")
    panel: PublishPanel = _panel(ready_paths).find_chats(fake.bot, PRIVATE_SEARCH)
    assert panel.status == (
        msg.SETUP_TELEGRAM_TARGET_NO_CHATS["private"].format(
            username="livecraft_test_bot", button=msg.SETUP_TELEGRAM_TARGET_CONNECT["private"]
        ),
    )
    assert ready_paths.file(FileName.CONFIG).read_bytes() == before and "sendMessage" not in fake.methods


def test_several_groups_are_offered_for_choice_without_the_private_chat(ready_paths: LivecraftPaths) -> None:
    """Бот видит личный чат, группу, супергруппу и канал: кнопка группы предлагает только три чата для группы."""
    before: bytes = ready_paths.file(FileName.CONFIG).read_bytes()
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates")
    panel: PublishPanel = _panel(ready_paths).find_chats(fake.bot, GROUP_SEARCH)
    assert [chat.chat_id for chat in panel.chats.chats] == [GROUP_ID, SUPERGROUP_ID, "-1002000000002"]
    assert panel.status == ("Бот видит несколько групп — нажмите в списке на нужную.",)
    assert ready_paths.file(FileName.CONFIG).read_bytes() == before
    assert "sendMessage" not in fake.methods


def test_the_private_button_takes_the_only_private_chat_among_groups(ready_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates", "send_message_private")
    _panel(ready_paths).find_chats(fake.bot, PRIVATE_SEARCH)
    assert _telegram_on_disk(ready_paths) == TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, "")


def test_several_private_chats_are_offered_for_choice(ready_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", TWO_PRIVATE_UPDATES)
    panel: PublishPanel = _panel(ready_paths).find_chats(fake.bot, PRIVATE_SEARCH)
    assert [chat.chat_id for chat in panel.chats.chats] == [PRIVATE_ID, OTHER_PRIVATE_ID]
    assert panel.status == ("Бот видит несколько чатов с ботом — нажмите в списке на свой.",)


def test_choosing_from_the_list_connects_the_chat_and_hides_the_list(ready_paths: LivecraftPaths) -> None:
    listed: PublishPanel = _panel(ready_paths).find_chats(
        FakeTelegram.answering("get_me", "webhook_none", "updates").bot, GROUP_SEARCH
    )
    chosen: PublishPanel = listed.connect(FakeTelegram.answering("send_message_group").bot, listed.chats.chats[0])
    assert _telegram_on_disk(ready_paths).group_chat_id == GROUP_ID
    assert chosen.chats == BotChats(chats=()) and chosen.status == (_connected_line(ChatTarget.GROUP, "Livecraft group"),)


def test_nobody_wrote_to_the_bot_says_what_to_do_naming_the_bot(ready_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_empty")
    panel: PublishPanel = _panel(ready_paths).find_chats(fake.bot, PRIVATE_SEARCH)
    assert panel.status == (
        msg.SETUP_TELEGRAM_TARGET_NO_CHATS["private"].format(
            username="livecraft_test_bot", button=msg.SETUP_TELEGRAM_TARGET_CONNECT["private"]
        ),
    )
    assert "@livecraft_test_bot" in panel.status[0]


def test_nobody_wrote_to_a_connected_bot_names_the_button_it_has_now(ready_paths: LivecraftPaths) -> None:
    """Группа уже подключена: её кнопка — «Подключить другую (новую) группу с ботом», и подсказка называет её."""
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_empty")
    panel: PublishPanel = _connected_to_group(ready_paths).find_chats(fake.bot, GROUP_SEARCH)
    assert panel.status == (
        msg.SETUP_TELEGRAM_TARGET_NO_CHATS["group"].format(
            username="livecraft_test_bot", button="Подключить другую (новую) группу с ботом"
        ),
    )


# --- надпись кнопки подключения


def test_the_button_connects_a_chat_until_one_of_its_kind_is_connected(ready_paths: LivecraftPaths) -> None:
    """До подключения — «Подключить группу с ботом»; после — «Подключить другую (новую) группу с ботом»: пробное
    сообщение уже ушло, кнопка нужна только для смены чата. Чат из файла, открытого заново, — тоже подключённый; кнопка
    чата с ботом — своя."""
    assert GROUP_SEARCH.button(_panel(ready_paths).settings.telegram) == "Подключить группу с ботом"
    connected: TelegramSettings = _connected_to_group(ready_paths).settings.telegram
    assert GROUP_SEARCH.button(connected) == "Подключить другую (новую) группу с ботом"
    assert GROUP_SEARCH.button(_panel(ready_paths).settings.telegram) == "Подключить другую (новую) группу с ботом"
    assert PRIVATE_SEARCH.button(connected) == "Подключить чат с ботом"
    private: TelegramSettings = TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, "")
    assert PRIVATE_SEARCH.button(private) == "Подключить другой чат с ботом"


def test_a_chat_that_was_not_saved_leaves_the_button_as_it_was(ready_paths: LivecraftPaths) -> None:
    """Токена уже нет — файл не тронут, чат не подключён: кнопка по-прежнему «Подключить группу с ботом»."""
    panel: PublishPanel = _panel(ready_paths).connect(None, GROUP)
    assert GROUP_SEARCH.button(panel.settings.telegram) == "Подключить группу с ботом"


# --- «Куда слать объявления»


def test_choosing_the_target_changes_only_the_target(ready_paths: LivecraftPaths) -> None:
    _save_telegram(ready_paths, TelegramSettings(ChatTarget.GROUP, GROUP_ID, PRIVATE_ID, ""))
    panel: PublishPanel = _panel(ready_paths).choose_target(ChatTarget.PRIVATE)
    assert _telegram_on_disk(ready_paths) == TelegramSettings(ChatTarget.PRIVATE, GROUP_ID, PRIVATE_ID, "")
    assert panel.settings.telegram.target is ChatTarget.PRIVATE and panel.status == ()
    assert panel.choose_target(ChatTarget.GROUP).settings.telegram.chat_id == GROUP_ID


def test_choosing_the_target_keeps_what_the_settings_tab_saved(ready_paths: LivecraftPaths) -> None:
    _save_telegram(ready_paths, TelegramSettings(ChatTarget.GROUP, GROUP_ID, PRIVATE_ID, ""))
    publish: PublishPanel = _panel(ready_paths)                             # открыта до сохранения настроек
    settings: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    settings.apply(draft_with(settings.draft, keep_days="7")).panel.save()
    publish.choose_target(ChatTarget.PRIVATE)
    saved: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert saved.keep_days == 7 and saved.telegram.target is ChatTarget.PRIVATE


def test_a_kind_that_is_not_connected_cannot_be_the_target(ready_paths: LivecraftPaths) -> None:
    _announce_to_private(ready_paths)
    telegram: TelegramSettings = _panel(ready_paths).settings.telegram
    assert telegram.is_connected(ChatTarget.PRIVATE) and not telegram.is_connected(ChatTarget.GROUP)


def test_a_webhook_and_another_poller_are_named(ready_paths: LivecraftPaths) -> None:
    panel: PublishPanel = _panel(ready_paths)
    webhook: PublishPanel = panel.find_chats(FakeTelegram.answering("get_me", "webhook_set").bot, GROUP_SEARCH)
    poller: PublishPanel = panel.find_chats(FakeTelegram.answering("get_me", "webhook_none", "conflict").bot, GROUP_SEARCH)
    assert webhook.status == (msg.TELEGRAM_PROBLEMS["webhook"],)
    assert poller.status == (msg.TELEGRAM_PROBLEMS["other_poller"],)


def test_a_bad_token_is_named_and_logged_without_the_token(ready_paths: LivecraftPaths) -> None:
    with LogCapture.on(LogArea.SETUP) as capture:
        panel: PublishPanel = _panel(ready_paths).find_chats(
            FakeTelegram.answering("unauthorized").bot, PRIVATE_SEARCH
        )
    assert panel.status == (msg.TELEGRAM_PROBLEMS["bad_token"],)
    lines: list[str] = capture.messages(logging.WARNING)
    assert any(line.startswith("telegram_failed method=getMe reason=bad_token status=401") for line in lines)
    assert not any(BOT_TOKEN in line for line in capture.messages())


# --- подключение пишет только раздел telegram поверх свежего файла


def test_a_chat_goes_to_the_field_of_its_target() -> None:
    fresh: LivecraftSettings = ShippedSettings().settings
    private: TelegramSettings = ChatConnection(PRIVATE).written(fresh).telegram
    group: TelegramSettings = ChatConnection(GROUP).written(fresh).telegram
    assert (private.target, private.private_chat_id, private.group_chat_id) == (ChatTarget.PRIVATE, PRIVATE_ID, "")
    assert (group.target, group.group_chat_id, group.private_chat_id) == (ChatTarget.GROUP, GROUP_ID, "")


def test_connecting_keeps_what_the_settings_tab_saved(ready_paths: LivecraftPaths) -> None:
    publish: PublishPanel = _panel(ready_paths)            # открыта до сохранения настроек
    settings: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    settings.apply(draft_with(settings.draft, keep_days="7")).panel.save()
    publish.connect(FakeTelegram.answering("send_message_group").bot, GROUP)
    saved: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert saved.keep_days == 7 and saved.telegram.group_chat_id == GROUP_ID


def test_saving_the_settings_tab_keeps_the_connected_chat(ready_paths: LivecraftPaths) -> None:
    settings: SettingsPanel = SettingsPanel.from_paths(ready_paths)         # открыта до подключения чата
    _connected_to_group(ready_paths)
    settings.apply(draft_with(settings.draft, keep_days="9")).panel.save()
    saved: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert saved.keep_days == 9 and saved.telegram.group_chat_id == GROUP_ID


def test_a_refused_test_message_keeps_the_connection_and_names_the_reason(ready_paths: LivecraftPaths) -> None:
    panel: PublishPanel = _panel(ready_paths).connect(FakeTelegram.answering("forbidden").bot, GROUP)
    assert panel.status == (msg.TELEGRAM_PROBLEMS["forbidden"],)
    assert _telegram_on_disk(ready_paths).group_chat_id == GROUP_ID


def test_a_group_that_became_a_supergroup_is_connected_by_its_new_id(ready_paths: LivecraftPaths) -> None:
    """Перенос — тот же `ChatMigration`, что у объявлений в Telegram: строка вкладки и строка лога одни."""
    fake: FakeTelegram = FakeTelegram.answering("migrated", "send_message_supergroup")
    with LogCapture.on(LogArea.SETUP) as capture:
        panel: PublishPanel = _panel(ready_paths).connect(fake.bot, GROUP)
    assert f"telegram_chat_migrated old_chat_id={GROUP_ID} new_chat_id={SUPERGROUP_ID}" in capture.messages()
    assert panel.status == (
        msg.TELEGRAM_CHAT_MIGRATED.format(old_chat_id=GROUP_ID, new_chat_id=SUPERGROUP_ID),
        _connected_line(ChatTarget.GROUP, "Livecraft super"),
    )
    assert _telegram_on_disk(ready_paths).group_chat_id == SUPERGROUP_ID
    assert panel.line_of(GROUP_SEARCH) == "подключён: Livecraft super"


def test_connecting_over_an_unreadable_file_writes_it_anew(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.CONFIG).write_bytes(b"{ broken")
    panel: PublishPanel = _panel(ready_paths).connect(
        FakeTelegram.answering("send_message_group").bot, GROUP
    )
    assert _telegram_on_disk(ready_paths).group_chat_id == GROUP_ID
    assert panel.notices == ()


def test_a_migration_keeps_the_other_fields_of_the_file(ready_paths: LivecraftPaths) -> None:
    """Вкладка открыта до того, как другая записала keep_days: подключение и новый id супергруппы пишутся поверх
    файла, как он на диске."""
    panel: PublishPanel = _panel(ready_paths)
    data: dict[str, Any] = json.loads(ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8"))
    data["keep_days"] = 11
    ready_paths.file(FileName.CONFIG).write_text(json.dumps(data), encoding="utf-8")
    panel.connect(FakeTelegram.answering("migrated", "send_message_supergroup").bot, GROUP)
    saved: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert saved.keep_days == 11 and saved.telegram.group_chat_id == SUPERGROUP_ID


# --- чат поддержки: тот же порядок подключения, роль SUPPORT (§13 задача 7.2)


SUPPORT_SEARCH: ChatSearch = ChatRole.SUPPORT.searches[0]


def _support_panel(paths: LivecraftPaths) -> PublishPanel:
    return PublishPanel.from_file(SettingsFile.of(paths), ChatRole.SUPPORT)


def test_the_support_chat_has_one_search_for_a_chat_of_any_kind() -> None:
    assert ChatRole.SUPPORT.searches == (SUPPORT_SEARCH,)
    assert SUPPORT_SEARCH.targets == (ChatTarget.GROUP, ChatTarget.PRIVATE) and SUPPORT_SEARCH.words.title == ""
    assert SUPPORT_SEARCH.button(TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, "")) == "Подключить чат поддержки"


def test_a_support_chat_goes_only_to_the_support_field() -> None:
    """Чат поддержки любого вида пишет только id поддержки: назначение и чаты объявлений прежние."""
    fresh: LivecraftSettings = ShippedSettings().settings.with_telegram(
        TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, "")
    )
    group: TelegramSettings = ChatConnection(GROUP, ChatRole.SUPPORT).written(fresh).telegram
    private: TelegramSettings = ChatConnection(PRIVATE, ChatRole.SUPPORT).written(fresh).telegram
    assert group == TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, GROUP_ID)
    assert private == TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, PRIVATE_ID)


def test_a_migration_moves_the_support_chat_too() -> None:
    telegram: TelegramSettings = TelegramSettings(ChatTarget.GROUP, GROUP_ID, PRIVATE_ID, GROUP_ID)
    assert telegram.migrated(GROUP_ID, SUPERGROUP_ID) == TelegramSettings(
        ChatTarget.GROUP, SUPERGROUP_ID, PRIVATE_ID, SUPERGROUP_ID
    )


def test_the_support_chat_by_the_file_names_only_the_chat(ready_paths: LivecraftPaths) -> None:
    """Строка чата поддержки — словами строк объявлений: подключён ли и какой чат; уйдут ли туда логи, она не
    говорит — это решает и бот поддержки (строка над кнопкой отправки)."""
    assert _support_panel(ready_paths).line_of(SUPPORT_SEARCH) == msg.SETUP_TELEGRAM_CHAT_NOT_CONNECTED
    _save_telegram(ready_paths, TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, GROUP_ID))
    panel: PublishPanel = _support_panel(ready_paths)
    assert panel.destination_of(SUPPORT_SEARCH) == ChatDestination(ChatTarget.GROUP, GROUP_ID)
    by_id: str = msg.SETUP_TELEGRAM_CHAT_BY_ID.format(chat_id=GROUP_ID)
    assert panel.line_of(SUPPORT_SEARCH) == msg.SETUP_TELEGRAM_CHAT_CONNECTED.format(chat=by_id)


def test_connecting_the_support_chat_keeps_the_announcement_chat(ready_paths: LivecraftPaths) -> None:
    _announce_to_private(ready_paths)
    fake: FakeTelegram = FakeTelegram.answering("get_me", "webhook_none", "updates_group", "send_message_group")
    panel: PublishPanel = _support_panel(ready_paths).find_chats(fake.bot, SUPPORT_SEARCH)
    assert _telegram_on_disk(ready_paths) == TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, GROUP_ID)
    assert fake.calls[-1].body["chat_id"] == GROUP_ID
    assert fake.calls[-1].body["text"] == msg.SETUP_LOGS_CHAT_CONNECT_TEXT
    destination: str = msg.SETUP_TELEGRAM_DESTINATION_BY_TITLE.format(
        into=_into(ChatTarget.GROUP), title="Livecraft group"
    )
    assert panel.status == (msg.SETUP_LOGS_CHAT_CONNECTED.format(destination=destination),)
    assert panel.line_of(SUPPORT_SEARCH) == msg.SETUP_TELEGRAM_CHAT_CONNECTED.format(chat="Livecraft group")
    assert SUPPORT_SEARCH.button(panel.settings.telegram) == msg.SETUP_LOGS_BUTTON_RECONNECT


def test_a_support_group_that_became_a_supergroup_keeps_the_announcement_chat(ready_paths: LivecraftPaths) -> None:
    _announce_to_private(ready_paths)
    panel: PublishPanel = _support_panel(ready_paths).connect(
        FakeTelegram.answering("migrated", "send_message_supergroup").bot, GROUP
    )
    assert _telegram_on_disk(ready_paths) == TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, SUPERGROUP_ID)
    assert panel.status[0] == msg.TELEGRAM_CHAT_MIGRATED.format(old_chat_id=GROUP_ID, new_chat_id=SUPERGROUP_ID)


def test_the_support_chat_asks_for_the_support_bot(ready_paths: LivecraftPaths) -> None:
    panel: PublishPanel = _support_panel(ready_paths)
    assert panel.find_chats(None, SUPPORT_SEARCH).status == (msg.SETUP_LOGS_BOT_FIRST,)
    several: PublishPanel = panel.find_chats(
        FakeTelegram.answering("get_me", "webhook_none", "updates").bot, SUPPORT_SEARCH
    )
    assert several.status == (msg.SETUP_LOGS_CHAT_CHOOSE,) and len(several.chats.chats) == 4
