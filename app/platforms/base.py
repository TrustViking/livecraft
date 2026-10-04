"""Площадка эфиров — `BroadcastPlatform` (CLAUDE.md §2, §3 шаги 10–11, §6 инварианты 1, 7, 9).

Любой сбой площадки — только `PlatformError`; других исключений площадка не выпускает. Всё, что уходит в эфир,
площадка получает готовой спекой (`BroadcastSpec`): отправляемое и сравниваемое совпадают по построению. Реализация
v1 — YouTube (`app\\platforms\\youtube.py`); подделка для тестов — `app\\tests\\fixtures\\` (задача 5.4).
"""
from __future__ import annotations

from typing import Protocol

from app.config.channel import ChannelConfig
from app.platforms.broadcast import BroadcastFacts, CreatedBroadcast, UpcomingBroadcast
from app.platforms.channel_info import ChannelInfo
from app.platforms.error import PlatformError
from app.platforms.limits import PlatformLimits
from app.platforms.notice import PlatformNotice
from app.platforms.spec import BroadcastSpec
from app.platforms.stream import StreamInfo
from app.platforms.video import VideoFixes, VideoSettings


class BroadcastPlatform(Protocol):
    @property
    def limits(self) -> PlatformLimits:
        """Пределы длины названия и описания и постоянные настройки эфира площадки."""
        ...

    def describe_channel(self, channel: ChannelConfig, *, allow_login: bool = True) -> ChannelInfo:
        """Канал, на который ведёт токен: id, название, ник, язык канала.

        allow_login=False — вход в браузере запрещён: нужен вход — PlatformError(loginRequired), браузер не
        открывается. Браузер открывает только этот вызов с allow_login=True.
        """
        ...

    def keep_login(self, channel: ChannelConfig) -> None:
        """Канал подтверждён: записать токен нового входа. Нового входа не было — ничего не делать."""
        ...

    def drop_login(self, channel: ChannelConfig) -> None:
        """Забыть клиент, вход, ChannelInfo и отказы канала: следующий describe_channel откроет вход заново.

        Файл токена на диске не трогается и следующим входом не читается.
        """
        ...

    def list_upcoming(self, channel: ChannelConfig) -> list[UpcomingBroadcast]:
        """Запланированные эфиры канала."""
        ...

    def get_stream(self, channel: ChannelConfig, stream_id: str) -> StreamInfo | None:
        """Привязанный поток: метка (title) и ключ; None — потока нет."""
        ...

    def create_broadcast(self, channel: ChannelConfig, spec: BroadcastSpec) -> CreatedBroadcast:
        """Эфир → поток с меткой spec.marker → привязка. Оборвалось — доделает следующий запуск."""
        ...

    def update_broadcast(self, channel: ChannelConfig, broadcast_id: str, spec: BroadcastSpec) -> None:
        """Исправление на месте: название, описание, время, категория.

        update заменяет snippet целиком, поэтому время и категория отправляются всегда; категория — из спеки, а не та,
        что стояла у эфира.
        """
        ...

    def attach_stream(self, channel: ChannelConfig, broadcast_id: str, spec: BroadcastSpec) -> CreatedBroadcast:
        """Эфир есть, потока нет: создать поток с меткой и привязать."""
        ...

    def apply_video_settings(self, channel: ChannelConfig, broadcast_id: str, settings: VideoSettings) -> VideoFixes:
        """Язык, категория, видимость и аудитория у ресурса видео — одним чтением и не более чем одной записью.

        Язык и аудиторию у эфира не записать; видимость и категорию ресурс видео держит сам. Совпало всё — записи нет.
        """
        ...

    def set_stream_marker(self, channel: ChannelConfig, stream_id: str, marker: str) -> None:
        """Метка программы на уже существующем потоке: название — slot_id, описание — чей это ключ."""
        ...

    def set_thumbnail(self, channel: ChannelConfig, broadcast_id: str, preview: bytes) -> None:
        """Обложка эфира. Сбой не отменяет эфир — решает вызывающий."""
        ...

    def read_facts(self, channel: ChannelConfig, broadcast_id: str) -> BroadcastFacts:
        """Что лежит на площадке после действий: для разбора расхождений."""
        ...

    def thumbnail_refusal(self, channel: ChannelConfig) -> PlatformError | None:
        """Запомненный за этот запуск отказ загрузки обложек по каналу или по проекту; без обращения к сети."""
        ...

    def take_notices(self) -> tuple[PlatformNotice, ...]:
        """Замечания, накопленные за запуск (эфир без времени старта); отдаёт и очищает накопитель."""
        ...
