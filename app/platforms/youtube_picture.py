"""Картинка эфира для сверки обложки: размер default с i.ytimg.com (CLAUDE.md §6 инвариант 1).

CDN картинок — не YouTube API: скачивание квоту не тратит, паузы между обращениями к API перед ним нет, и отсчёт
паузы оно не сдвигает. Картинка не скачалась — отпечатка нет (None): это не отказ площадки и не сбой канала.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Final

import requests

from app.observability.log_event import LogArea, LogEvent, get_logger
from app.platforms.placeholder import PlaceholderMark
from app.platforms.youtube_event import YouTubeEvent
from app.platforms.youtube_response import YouTubeKey, YouTubeResponse

LOGGER = get_logger(LogArea.PLATFORMS)
PICTURE_TIMEOUT_SEC: Final[int] = 15


@dataclass
class PictureReader:
    """Скачивает картинки эфиров без авторизации; `session` — requests.Session или подделка с тем же `get`."""

    session: requests.Session = field(default_factory=requests.Session)

    def mark(self, thumbnails: YouTubeResponse) -> PlaceholderMark | None:
        """Отпечаток картинки размера default из раздела `snippet.thumbnails`; адреса нет или не скачалась — None."""
        url: str | None = thumbnails.part(YouTubeKey.DEFAULT).optional_text(YouTubeKey.URL)
        if url is None:
            return None
        try:
            response: requests.Response = self.session.get(url, timeout=PICTURE_TIMEOUT_SEC)
        except requests.RequestException as error:
            LogEvent.of(YouTubeEvent.PICTURE_UNAVAILABLE, url=url, status=None, error=type(error).__name__).emit(LOGGER)
            return None
        if response.status_code != HTTPStatus.OK or not response.content:
            LogEvent.of(YouTubeEvent.PICTURE_UNAVAILABLE, url=url, status=response.status_code).emit(LOGGER)
            return None
        return PlaceholderMark.of(response.content)
