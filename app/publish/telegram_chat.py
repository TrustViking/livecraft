"""Чат объявлений словами для человека и его перенос в супергруппу (CLAUDE.md §14 решения 19, 57, 63, §13 задачи 4.5,
9.13).

`ChatDestination` — подключённый чат: вид, id и название; его слова («группу с ботом «X»») — одни на вкладку «Telegram»
и на консоль запуска: строка части «объявления» называет чат, куда они ушли.

Группа стала супергруппой: прежний id такой группы мёртв, отправка ушла на новый (`BotDelivery.migrated_from`).
`ChatMigration` сам решает, что записать в livecraft.json, и сам даёт строку лога и строку для человека — одну на
вкладку «Telegram» и на консоль запуска: о переносе они говорят одно.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from app.config.settings import LivecraftSettings
from app.config.telegram import ChatTarget, TelegramSettings
from app.observability.log_event import LogEvent
from app.publish.telegram_api import BotChat
from app.ui.messages import msg


class TelegramChatEvent(str, Enum):
    """События чата объявлений в логе."""

    CHAT_MIGRATED = "telegram_chat_migrated"


@dataclass(frozen=True)
class ChatMigration:
    """Группа стала супергруппой: прежний id мёртв, отправка ушла на новый."""

    old_chat_id: str
    new_chat_id: str

    def written(self, fresh: LivecraftSettings, target: ChatTarget) -> LivecraftSettings:
        """Что записать в файл: его id, равные прежнему, — новым, и новый id — в поле назначения, куда ушло
        сообщение."""
        migrated: TelegramSettings = fresh.telegram.migrated(self.old_chat_id, self.new_chat_id)
        telegram: TelegramSettings = dataclasses.replace(migrated, **{target.chat_key.leaf: self.new_chat_id})
        return dataclasses.replace(fresh, telegram=telegram)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(TelegramChatEvent.CHAT_MIGRATED, old_chat_id=self.old_chat_id, new_chat_id=self.new_chat_id)

    @property
    def line(self) -> str:
        return msg.TELEGRAM_CHAT_MIGRATED.format(old_chat_id=self.old_chat_id, new_chat_id=self.new_chat_id)


@dataclass(frozen=True)
class ChatDestination:
    """Подключённый чат: вид, id и название (`title`; пусто — известен только id из livecraft.json: название знает
    лишь ответ бота — чат, который окно назвало по getChat или проверило, или чат, куда ушло объявление запуска)."""

    target: ChatTarget
    chat_id: str
    title: str = ""

    @classmethod
    def of_chat(cls, chat: BotChat) -> ChatDestination:
        """Чат из ответа бота — с названием."""
        return cls(target=chat.target, chat_id=chat.chat_id, title=chat.label)

    @property
    def text(self) -> str:
        """В винительном падеже, после «уходят в»: «группу с ботом «Livecraft group»», по файлу — «чат с ботом (id
        111000111)»."""
        into: str = msg.SETUP_TELEGRAM_TARGETS_INTO[self.target.value]
        if self.title:
            return msg.SETUP_TELEGRAM_DESTINATION_BY_TITLE.format(into=into, title=self.title)
        return msg.SETUP_TELEGRAM_DESTINATION_BY_ID.format(into=into, chat_id=self.chat_id)

    @property
    def shown(self) -> str:
        """Сам чат, без вида: название, а по файлу — «id 111000111»."""
        return self.title or msg.SETUP_TELEGRAM_CHAT_BY_ID.format(chat_id=self.chat_id)

    @property
    def line(self) -> str:
        """Строка подключённого чата на вкладке «Telegram»: «подключён: <чат>»."""
        return msg.SETUP_TELEGRAM_CHAT_CONNECTED.format(chat=self.shown)
