"""Бот Telegram на подделанном requests.post: ответы Bot API — сохранённым JSON (CLAUDE.md §13 задача 4.1).

К настоящему Telegram тесты не ходят: бот строится только на `FakeTelegram.bot`.
"""
from __future__ import annotations

import logging

import pytest
import requests

from app.config.telegram import ChatTarget
from app.observability.log_event import LogArea
from app.publish.telegram_api import (
    PARSE_MODE_HTML,
    TEXT_CHUNK_CHARS,
    BotChat,
    BotChats,
    BotDelivery,
    BotDocument,
    BotFailure,
    BotMethod,
    ChatKind,
    MessageText,
    TelegramProblem,
)
from app.publish.telegram_bot import SEND_PAUSE_SEC, TelegramBot
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.telegram import BOT_SECRET, BOT_TOKEN, FakeBotResponse, FakeTelegram
from app.ui import messages_ru as msg

GROUP_ID: str = "-4000000001"
SUPERGROUP_ID: str = "-1001000000001"
PRIVATE_ID: str = "111000111"
CHANNEL_ID: str = "-1002000000002"
NETWORK_ATTEMPTS: int = 5                  # первое обращение и четыре повтора RetryPolicy


def _failure(outcome: object) -> BotFailure:
    assert isinstance(outcome, BotFailure)
    return outcome


def _delivery(outcome: object) -> BotDelivery:
    assert isinstance(outcome, BotDelivery)
    return outcome


# --- кто бот, webhook и чаты


def test_me_names_the_bot_and_is_not_paused() -> None:
    fake: FakeTelegram = FakeTelegram.answering("get_me")
    me: BotChat | BotFailure = fake.bot.me()
    assert isinstance(me, BotChat) and me.label == "Livecraft @livecraft_test_bot"
    assert fake.methods == [BotMethod.GET_ME.value] and fake.sleeps == []    # пауза — только перед отправкой
    assert fake.calls[0].url == f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"


def test_the_bot_comes_from_the_vault_token_only() -> None:
    assert TelegramBot.from_vault(None) is None
    assert TelegramBot.from_vault(Vault.empty()) is None
    vault: Vault = Vault.empty().with_field(SecretField.TELEGRAM_BOT_TOKEN, BOT_SECRET, VaultOrigin.OWN)
    bot: TelegramBot | None = TelegramBot.from_vault(vault)
    assert bot is not None and bot.token == BOT_SECRET


def test_the_support_bot_comes_only_from_its_own_field() -> None:
    """Логи носит бот поддержки (§14 решение 58): токен бота объявлений его не заменяет, и наоборот."""
    announce: Vault = Vault.empty().with_field(SecretField.TELEGRAM_BOT_TOKEN, BOT_SECRET, VaultOrigin.OWN)
    assert TelegramBot.from_vault(announce, SecretField.SUPPORT_BOT_TOKEN) is None
    support_secret: SecretValue = SecretValue(field=SecretField.SUPPORT_BOT_TOKEN, value=BOT_TOKEN)
    support: Vault = Vault.empty().with_field(SecretField.SUPPORT_BOT_TOKEN, support_secret, VaultOrigin.OWN)
    assert TelegramBot.from_vault(support) is None
    bot: TelegramBot | None = TelegramBot.from_vault(support, SecretField.SUPPORT_BOT_TOKEN)
    assert bot is not None and bot.token == support_secret


@pytest.mark.parametrize(("name", "url"), [("webhook_none", ""), ("webhook_set", "https://hooks.example.org/telegram")])
def test_the_webhook_url_is_read_as_is(name: str, url: str) -> None:
    assert FakeTelegram.answering(name).bot.webhook_url() == url


def test_a_bot_with_a_webhook_has_no_chats_and_get_updates_is_not_called() -> None:
    fake: FakeTelegram = FakeTelegram.answering("webhook_set")
    failure: BotFailure = _failure(fake.bot.chats())
    assert failure.reason is TelegramProblem.WEBHOOK and failure.human == msg.TELEGRAM_PROBLEMS["webhook"]
    assert fake.methods == [BotMethod.GET_WEBHOOK_INFO.value]


def test_another_poller_is_named_without_retries() -> None:
    fake: FakeTelegram = FakeTelegram.answering("webhook_none", "conflict")
    failure: BotFailure = _failure(fake.bot.chats())
    assert failure.reason is TelegramProblem.OTHER_POLLER and failure.status == 409
    assert "restreamer" in failure.human
    assert fake.methods == [BotMethod.GET_WEBHOOK_INFO.value, BotMethod.GET_UPDATES.value]


def test_no_updates_give_no_chats() -> None:
    chats: BotChats | BotFailure = FakeTelegram.answering("webhook_none", "updates_empty").bot.chats()
    assert chats == BotChats(chats=())


def test_chats_come_once_per_id_private_first_and_the_later_title_wins() -> None:
    """Личный чат пришёл дважды (сообщение и его правка) — один чат с поздним именем; неизвестное обновление
    (callback_query) не даёт чата; личный — первым, затем группы в порядке прихода."""
    chats: BotChats | BotFailure = FakeTelegram.answering("webhook_none", "updates").bot.chats()
    assert isinstance(chats, BotChats)
    assert [(chat.chat_id, chat.kind) for chat in chats.chats] == [
        (PRIVATE_ID, ChatKind.PRIVATE),
        (GROUP_ID, ChatKind.GROUP),
        (SUPERGROUP_ID, ChatKind.SUPERGROUP),
        (CHANNEL_ID, ChatKind.CHANNEL),
    ]
    assert [chat.label for chat in chats.chats] == [
        "Test User @test_user", "Livecraft group", "Livecraft super", "Livecraft news @livecraft_news"
    ]
    assert [(chat.title, chat.username) for chat in chats.chats][0] == ("Test User", "test_user")
    assert [chat.target for chat in chats.chats] == [ChatTarget.PRIVATE, ChatTarget.GROUP, ChatTarget.GROUP,
                                                     ChatTarget.GROUP]


def test_chats_of_one_kind_are_only_the_chats_fit_for_it() -> None:
    """Кнопка группы ищет среди групп (группа, супергруппа, канал), кнопка личного чата — среди личных; порядок
    прежний."""
    chats: BotChats | BotFailure = FakeTelegram.answering("webhook_none", "updates").bot.chats()
    assert isinstance(chats, BotChats)
    groups: BotChats = chats.of_targets((ChatTarget.GROUP,))
    assert [chat.chat_id for chat in groups.chats] == [GROUP_ID, SUPERGROUP_ID, CHANNEL_ID]
    assert [chat.chat_id for chat in chats.of_targets((ChatTarget.PRIVATE,)).chats] == [PRIVATE_ID]
    assert chats.of_targets(tuple(ChatTarget)) == chats


def test_a_chat_option_names_kind_title_and_id() -> None:
    chat: BotChat = BotChat(chat_id=GROUP_ID, kind=ChatKind.GROUP, title="Livecraft group")
    assert chat.option == msg.SETUP_TELEGRAM_CHAT_OPTION.format(
        kind=msg.TELEGRAM_CHAT_KINDS["group"], title="Livecraft group", chat_id=GROUP_ID
    )


def test_the_bot_username_comes_apart_from_its_name() -> None:
    """@имя бота — отдельным полем: по нему окно открывает бота по ссылке t.me; в подписи — имя и @имя."""
    me: BotChat | BotFailure = FakeTelegram.answering("get_me").bot.me()
    assert isinstance(me, BotChat)
    assert (me.title, me.username, me.label) == ("Livecraft", "livecraft_test_bot", "Livecraft @livecraft_test_bot")


def test_a_chat_without_name_and_username_is_named_by_its_id() -> None:
    assert BotChat(chat_id=GROUP_ID, kind=ChatKind.GROUP, title="").label == GROUP_ID


# --- отправка текста


def test_send_text_posts_html_after_a_pause() -> None:
    fake: FakeTelegram = FakeTelegram.answering("send_message_group")
    delivery: BotDelivery = _delivery(fake.bot.send_text(GROUP_ID, "<b>Эфир</b>"))
    assert delivery.chat.chat_id == GROUP_ID and delivery.chat.label == "Livecraft group"
    assert not delivery.is_migrated
    assert fake.calls[0].options["json"] == {"chat_id": GROUP_ID, "text": "<b>Эфир</b>", "parse_mode": PARSE_MODE_HTML}
    assert fake.sleeps == [SEND_PAUSE_SEC]


def test_a_long_text_is_cut_at_line_breaks_and_every_piece_is_paused() -> None:
    line: str = "x" * 999 + "\n"
    text: str = line * 8                                      # 8000 знаков: три куска
    fake: FakeTelegram = FakeTelegram.answering("send_message_group", "send_message_group", "send_message_group")
    _delivery(fake.bot.send_text(GROUP_ID, text))
    pieces: list[object] = [call.body["text"] for call in fake.calls]
    assert "".join(str(piece) for piece in pieces) == text
    assert all(isinstance(piece, str) and len(piece) <= TEXT_CHUNK_CHARS and piece.endswith("\n") for piece in pieces)
    assert len(pieces) == 3 and fake.sleeps == [SEND_PAUSE_SEC] * 3


def test_a_line_longer_than_the_limit_is_cut_at_the_limit() -> None:
    assert MessageText("abcdefgh", limit=3).chunks == ("abc", "def", "gh")
    assert MessageText("ab\ncdef\ng", limit=4).chunks == ("ab\n", "cdef", "\ng")
    assert MessageText("short").chunks == ("short",)


# --- 429, сбои сети и сервера, отказы без повторов


def test_too_many_requests_waits_retry_after_and_sends_again() -> None:
    fake: FakeTelegram = FakeTelegram.answering("too_many_requests", "send_message_group")
    _delivery(fake.bot.send_text(GROUP_ID, "text"))
    assert fake.sleeps == [SEND_PAUSE_SEC, 7.0, SEND_PAUSE_SEC]


def test_too_many_requests_without_retry_after_waits_five_seconds() -> None:
    fake: FakeTelegram = FakeTelegram.answering("too_many_requests_no_wait", "send_message_group")
    _delivery(fake.bot.send_text(GROUP_ID, "text"))
    assert fake.sleeps == [SEND_PAUSE_SEC, 5.0, SEND_PAUSE_SEC]


def test_too_many_requests_gives_up_after_three_attempts() -> None:
    fake: FakeTelegram = FakeTelegram.answering("too_many_requests", "too_many_requests", "too_many_requests")
    failure: BotFailure = _failure(fake.bot.send_text(GROUP_ID, "text"))
    assert failure.reason is TelegramProblem.RATE_LIMITED and len(fake.calls) == 3
    assert fake.sleeps == [SEND_PAUSE_SEC, 7.0, SEND_PAUSE_SEC, 7.0, SEND_PAUSE_SEC]


def test_a_network_failure_is_retried_by_the_retry_loop() -> None:
    fake: FakeTelegram = FakeTelegram.answering(requests.ConnectionError("down"), "send_message_group")
    _delivery(fake.bot.send_text(GROUP_ID, "text"))
    assert len(fake.calls) == 2 and len(fake.sleeps) == 3        # пауза, повтор RetryLoop, пауза


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [(requests.Timeout("slow"), TelegramProblem.NETWORK), (FakeBotResponse(None, 502), TelegramProblem.SERVER)],
)
def test_network_and_server_failures_end_after_the_retries(outcome: object, reason: TelegramProblem) -> None:
    fake: FakeTelegram = FakeTelegram([outcome] * NETWORK_ATTEMPTS)          # type: ignore[list-item]
    failure: BotFailure = _failure(fake.bot.me())
    assert failure.reason is reason and len(fake.calls) == NETWORK_ATTEMPTS


def test_a_server_error_then_an_answer_is_an_answer() -> None:
    fake: FakeTelegram = FakeTelegram.answering(FakeBotResponse(None, 503), "get_me")
    assert isinstance(fake.bot.me(), BotChat)


@pytest.mark.parametrize(
    ("name", "reason", "status"),
    [
        ("unauthorized", TelegramProblem.BAD_TOKEN, 401),
        ("forbidden", TelegramProblem.FORBIDDEN, 403),
        ("chat_not_found", TelegramProblem.CHAT_NOT_FOUND, 400),
        ("text_is_empty", TelegramProblem.REJECTED, 400),
    ],
)
def test_refusals_are_named_without_retries(name: str, reason: TelegramProblem, status: int) -> None:
    fake: FakeTelegram = FakeTelegram.answering(name)
    failure: BotFailure = _failure(fake.bot.send_text(GROUP_ID, "text"))
    assert (failure.reason, failure.status, failure.method) == (reason, status, BotMethod.SEND_MESSAGE)
    assert len(fake.calls) == 1 and fake.sleeps == [SEND_PAUSE_SEC]
    assert failure.human == msg.TELEGRAM_PROBLEMS[reason.value].format(description=failure.description)


def test_another_refusal_carries_the_telegram_description() -> None:
    failure: BotFailure = _failure(FakeTelegram.answering("text_is_empty").bot.send_text(GROUP_ID, ""))
    assert failure.human == msg.TELEGRAM_PROBLEMS["rejected"].format(description="Bad Request: message text is empty")


def test_an_answer_that_is_not_json_is_a_refusal_with_its_status() -> None:
    failure: BotFailure = _failure(FakeTelegram.answering(FakeBotResponse(None, 404)).bot.me())
    assert failure.reason is TelegramProblem.REJECTED and failure.description == "HTTP 404"


# --- группа стала супергруппой


def test_a_migrated_group_gets_the_message_on_the_new_id() -> None:
    fake: FakeTelegram = FakeTelegram.answering("migrated", "send_message_supergroup")
    delivery: BotDelivery = _delivery(fake.bot.send_text(GROUP_ID, "text"))
    assert delivery.is_migrated and delivery.migrated_from == GROUP_ID
    assert delivery.chat.chat_id == SUPERGROUP_ID
    assert [call.body["chat_id"] for call in fake.calls] == [GROUP_ID, SUPERGROUP_ID]


def test_after_a_migration_the_other_pieces_go_to_the_new_id() -> None:
    text: str = ("y" * 2999 + "\n") * 2
    fake: FakeTelegram = FakeTelegram.answering("migrated", "send_message_supergroup", "send_message_supergroup")
    delivery: BotDelivery = _delivery(fake.bot.send_text(GROUP_ID, text))
    assert [call.body["chat_id"] for call in fake.calls] == [GROUP_ID, SUPERGROUP_ID, SUPERGROUP_ID]
    assert delivery.migrated_from == GROUP_ID and delivery.chat.chat_id == SUPERGROUP_ID


def test_a_second_migration_in_a_row_is_a_refusal() -> None:
    failure: BotFailure = _failure(FakeTelegram.answering("migrated", "migrated").bot.send_text(GROUP_ID, "text"))
    assert failure.reason is TelegramProblem.REJECTED


# --- документ


def test_a_document_goes_as_multipart_with_its_caption() -> None:
    fake: FakeTelegram = FakeTelegram.answering("send_document_group")
    document: BotDocument = BotDocument(name="plan_test.bcast", data=b"zip", mime="application/zip", caption="plan")
    _delivery(fake.bot.send_document(GROUP_ID, document))
    options: dict[str, object] = fake.calls[0].options
    assert fake.methods == [BotMethod.SEND_DOCUMENT.value] and "json" not in options
    assert options["data"] == {"chat_id": GROUP_ID, "caption": "plan"}
    assert options["files"] == {"document": ("plan_test.bcast", b"zip", "application/zip")}
    assert fake.sleeps == [SEND_PAUSE_SEC]


def test_a_document_without_a_caption_sends_no_caption() -> None:
    fake: FakeTelegram = FakeTelegram.answering("send_document_group")
    _delivery(fake.bot.send_document(GROUP_ID, BotDocument(name="a.txt", data=b"a", mime="text/plain")))
    assert fake.calls[0].body == {"chat_id": GROUP_ID}


# --- токен не выходит наружу (§7.4)


def test_the_token_is_in_no_failure_text_log_line_or_repr() -> None:
    """Текст исключения requests несёт адрес с токеном — отказ берёт только имя исключения."""
    url: str = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    fake: FakeTelegram = FakeTelegram([requests.ConnectionError(f"Max retries exceeded with url: {url}")] * 5)
    failure: BotFailure = _failure(fake.bot.send_text(GROUP_ID, "text"))
    unauthorized: BotFailure = _failure(FakeTelegram.answering("unauthorized").bot.me())
    for text in (failure.human, failure.log_line, repr(failure), unauthorized.human, unauthorized.log_line,
                 repr(TelegramBot(token=BOT_SECRET)), str(TelegramBot(token=BOT_SECRET))):
        assert BOT_TOKEN not in text
    assert "method=sendMessage" in failure.log_line and "reason=network" in failure.log_line


# --- строка обращения в логе (§14 решение 38)


def test_every_call_is_a_log_line_with_the_chat_attempts_and_result() -> None:
    """429 и повтор — одна строка на обращение с попытками всех обменов; нет чата в запросе — «-»."""
    fake: FakeTelegram = FakeTelegram.answering("too_many_requests", "send_message_group", "get_me")
    with LogCapture.on(LogArea.PUBLISH) as capture:
        _delivery(fake.bot.send_text(GROUP_ID, "секретный текст"))
        fake.bot.me()
    assert capture.messages() == [
        f"telegram_call method=sendMessage chat={GROUP_ID} attempts=2 result=ok",
        "telegram_call method=getMe chat=- attempts=1 result=ok",
    ]


def test_a_refused_call_is_a_warning_with_its_reason_and_no_token_or_text() -> None:
    fake: FakeTelegram = FakeTelegram.answering("too_many_requests", "too_many_requests", "too_many_requests")
    with LogCapture.on(LogArea.PUBLISH) as capture:
        _failure(fake.bot.send_text(GROUP_ID, "секретный текст"))
    assert capture.messages(logging.WARNING) == [
        f"telegram_call method=sendMessage chat={GROUP_ID} attempts=3 result=rate_limited"
    ]
    text: str = "\n".join(capture.messages())
    assert BOT_TOKEN not in text and "api.telegram.org" not in text and "секретный" not in text
