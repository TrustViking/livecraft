"""Чат объявлений, который Telegram перенёс: группа стала супергруппой (CLAUDE.md §14 решение 19, §13 задача 4.5).

Прежний id такой группы мёртв, отправка ушла на новый (`BotDelivery.migrated_from`). `ChatMigration` сам решает, что
записать в livecraft.json, и сам даёт строку лога и строку для человека — одну на вкладку «Telegram» и на консоль
запуска: о переносе они говорят одно.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from app.config.settings import LivecraftSettings
from app.config.telegram import ChatTarget, TelegramSettings
from app.observability.log_event import LogEvent
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
        telegram: TelegramSettings = fresh.telegram.migrated(self.old_chat_id, self.new_chat_id)
        return fresh.with_telegram(dataclasses.replace(telegram, **{target.chat_key.leaf: self.new_chat_id}))

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(TelegramChatEvent.CHAT_MIGRATED, old_chat_id=self.old_chat_id, new_chat_id=self.new_chat_id)

    @property
    def line(self) -> str:
        return msg.TELEGRAM_CHAT_MIGRATED.format(old_chat_id=self.old_chat_id, new_chat_id=self.new_chat_id)
