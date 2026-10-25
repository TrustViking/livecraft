"""Ссылки источников в тексте описания после чистки (CLAUDE.md §3 шаг 5, санация после LLM).

`SourceLink` — ссылка из текста или из данных видео, какой она уходит в описание: сам адрес — без обрамления, точки
или запятой после него и меток слежения, полный (оборванная многоточием ссылка в описание не идёт), ссылка YouTube —
короткой `https://youtu.be/<id>`, прочая — без `/` в конце пути (`WebLink.published`, §14 решение 81). Ссылка
YouTube, из которой id не извлёкся, в описание не идёт: объект сам пишет об этом строку лога.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.web_link import WebLink
from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogArea, LogEvent, get_logger

LOGGER = get_logger(LogArea.TEXTS)

YOUTUBE_DROP_REASON: Final[str] = "youtube_normalization_failed"


class SourceLinkEvent(str, Enum):
    """События лога ссылок источников."""

    YOUTUBE_DROPPED = "non_authoritative_youtube_tail_url_dropped"   # ссылка YouTube без id не идёт в описание


@dataclass(frozen=True)
class SourceLink:
    """Ссылка после чистки: `url` None — не ссылка, неполная (в том числе оборванная) или YouTube без id
    (`dropped_youtube`)."""

    raw: str
    url: str | None
    dropped_youtube: bool = False

    @classmethod
    def of(cls, raw: str) -> SourceLink:
        """Ссылка из текста: проверка полноты, затем адрес без обрамления и хвостовой пунктуации — в виде для описания
        эфира (`WebLink.published`) или короткой ссылкой YouTube."""
        link: WebLink = WebLink.of(raw)
        if not link.is_complete:
            return cls(raw=raw, url=None)
        address: WebLink = WebLink(link.unwrapped.published)
        if not address.is_youtube:
            return cls(raw=raw, url=address.text)
        video: YouTubeVideoId | None = YouTubeVideoId.of(address.text)
        if video is not None:
            return cls(raw=raw, url=video.short_url)
        dropped: SourceLink = cls(raw=address.text, url=None, dropped_youtube=True)
        LogEvent.of(SourceLinkEvent.YOUTUBE_DROPPED, reason=YOUTUBE_DROP_REASON, raw=dropped.raw).emit(LOGGER)
        return dropped

    @property
    def is_youtube(self) -> bool:
        return self.url is not None and WebLink.of(self.url).unwrapped.is_youtube
