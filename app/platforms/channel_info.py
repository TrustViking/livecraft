"""Кто мы на площадке: канал, на который ведёт токен входа (CLAUDE.md §3 шаг 2.2, §6 инвариант 5).

Что прислал YouTube, канал говорит сам: ник в написании channels.json и его ключ (`handle`, `handle_key`), ник для людей
(`handle_text`), название в виде channels.json (`account_name`) и ссылку на канал по id (`channel_url`). Ссылки
на канал по id и по нику — одно место, `ChannelLink`.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum

from app.config.channel import UNICODE_FORM, ChannelHandle
from app.ui.messages import msg


class ChannelLink(str, Enum):
    """Ссылки на канал YouTube: по id — не меняется никогда, по нику — пока ник тот же."""

    CHANNEL = "https://www.youtube.com/channel/{channel_id}"
    HANDLE = "https://www.youtube.com/{handle}"

    def url(self, **values: object) -> str:
        return self.value.format(**values)


@dataclass(frozen=True)
class ChannelInfo:
    """Проверка «токен ведёт на тот канал»: id, название, язык и ник канала на площадке."""

    youtube_channel_id: str
    title: str
    default_language: str | None   # язык канала на площадке; справочный, на решения не влияет
    handle_raw: str | None = None  # ник канала как пришёл (snippet.customUrl); None — ника нет

    @property
    def handle(self) -> ChannelHandle | None:
        """Ник канала в написании channels.json; ника на YouTube нет — None."""
        return ChannelHandle.from_custom_url(self.handle_raw) if self.handle_raw else None

    @property
    def handle_key(self) -> str | None:
        """Ключ ника, который прислал YouTube (`ChannelHandle.key`); ника нет — None."""
        handle: ChannelHandle | None = self.handle
        return None if handle is None else handle.key

    @property
    def handle_text(self) -> str:
        """Ник, который прислал YouTube, — для людей; ника нет — текст «без ника»."""
        handle: ChannelHandle | None = self.handle
        return msg.AUTH_YOUTUBE_HANDLE_MISSING if handle is None else handle.text

    @property
    def account_name(self) -> str:
        """Название канала на YouTube в виде channels.json: форма NFC, края сняты."""
        return unicodedata.normalize(UNICODE_FORM, self.title).strip()

    @property
    def channel_url(self) -> str:
        """Ссылка на канал по id."""
        return ChannelLink.CHANNEL.url(channel_id=self.youtube_channel_id)
