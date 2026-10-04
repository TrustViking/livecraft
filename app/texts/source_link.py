"""Ссылки источников в тексте описания после чистки (CLAUDE.md §3 шаг 5, санация после LLM).

`SourceLink` — ссылка из текста или из данных видео, какой она уходит в описание: без меток слежения, полная,
ссылка YouTube — короткой `https://youtu.be/<id>`. Ссылка YouTube, из которой id не извлёкся, в описание не идёт:
объект сам пишет об этом строку лога. `LinkedText` — текст, в котором каждая ссылка почищена, и какие ссылки
чистка изменила.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.web_link import URL_PATTERN, WebLink
from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogArea, LogEvent, get_logger

LOGGER = get_logger(LogArea.TEXTS)

YOUTUBE_DROP_REASON: Final[str] = "youtube_normalization_failed"


class SourceLinkEvent(str, Enum):
    """События лога ссылок источников."""

    YOUTUBE_DROPPED = "non_authoritative_youtube_tail_url_dropped"   # ссылка YouTube без id не идёт в описание


@dataclass(frozen=True)
class SourceLink:
    """Ссылка после чистки: `url` None — не ссылка, неполная или YouTube без id (`dropped_youtube`)."""

    raw: str
    url: str | None
    dropped_youtube: bool = False

    @classmethod
    def of(cls, raw: str) -> SourceLink:
        """Ссылка из текста: сначала чистка (метки слежения, корень без `/`), затем проверка полноты и YouTube."""
        sanitized: str = WebLink.of(raw).sanitized.strip()
        link: WebLink = WebLink.of(sanitized)
        if not link.is_complete:
            return cls(raw=raw, url=None)
        if not link.unwrapped.is_youtube:
            return cls(raw=raw, url=sanitized)
        video: YouTubeVideoId | None = YouTubeVideoId.of(sanitized)
        if video is not None:
            return cls(raw=raw, url=video.short_url)
        dropped: SourceLink = cls(raw=sanitized, url=None, dropped_youtube=True)
        LogEvent.of(SourceLinkEvent.YOUTUBE_DROPPED, reason=YOUTUBE_DROP_REASON, raw=dropped.raw).emit(LOGGER)
        return dropped

    @property
    def is_youtube(self) -> bool:
        return self.url is not None and WebLink.of(self.url).unwrapped.is_youtube


@dataclass(frozen=True)
class LinkedText:
    """Текст, в котором каждая ссылка почищена (`WebLink.sanitized`), и ссылки, которые чистка изменила."""

    text: str
    changed_links: tuple[str, ...] = ()

    @classmethod
    def of(cls, text: str) -> LinkedText:
        pieces: list[str] = []
        changed: list[str] = []
        whole: str = text or ""
        position: int = 0
        for match in URL_PATTERN.finditer(whole):
            raw: str = match.group(0)
            sanitized: str = WebLink.of(raw).sanitized
            if sanitized != raw:
                changed.append(raw)
            pieces.extend((whole[position : match.start()], sanitized))
            position = match.end()
        pieces.append(whole[position:])
        return cls(text="".join(pieces), changed_links=tuple(changed))

    @property
    def change_count(self) -> int:
        return len(self.changed_links)
