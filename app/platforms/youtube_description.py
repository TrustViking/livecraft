"""Описание ключа потока в Студии YouTube: чей это ключ и для какого эфира (CLAUDE.md §6 инвариант 1).

Метка программы (slot_id) стоит в названии потока; описание объясняет её человеку: канал, ник, дата для людей
(§14 решение 31), время и язык эфира, когда описание записано. Хвост — метка заглушки обложки
(`PlaceholderMark.token`), когда она известна: по ней следующий запуск узнаёт эфир без обложки.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config.channel import ChannelConfig
from app.core.clock import Clock
from app.core.dates import format_human_datetime
from app.platforms.placeholder import PlaceholderMark
from app.slots.slot import SlotKey
from app.ui.messages import msg


@dataclass(frozen=True)
class StreamDescription:
    """Описание ключа: канал, метка потока, часы программы (момент записи и пояс метки) и метка заглушки."""

    channel: ChannelConfig
    marker: str
    clock: Clock
    placeholder: PlaceholderMark | None = None

    @property
    def text(self) -> str:
        """Метка не slot_id — дата описания и есть метка, времени и языка нет."""
        key: SlotKey | None = SlotKey.parse(self.marker, self.clock.zone)
        text: str = msg.STREAM_DESCRIPTION.format(
            account_name=self.channel.account_name,
            handle=self.channel.handle,
            date=self.marker if key is None else key.human_date,
            time="" if key is None else key.time_text,
            language="" if key is None else key.language,
            written_at=format_human_datetime(self.clock.now()),
        )
        if self.placeholder is None:
            return text
        return text + msg.STREAM_DESCRIPTION_PLACEHOLDER.format(token=self.placeholder.token)
