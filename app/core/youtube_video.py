"""Id видео YouTube: где он в тексте ячейки или ссылки и какие адреса из него строятся (CLAUDE.md §4, §6 инвариант 1).

Id — 11 символов `A-Z a-z 0-9 _ -`. Он берётся только из ссылки YouTube (`youtu.be/<id>`, `youtube.com/watch?v=<id>`,
`/shorts/`, `/embed/`, `/live/`; из нескольких ссылок — самая ранняя по позиции id) или из ячейки, которая целиком —
id. Одиннадцать символов внутри ссылки на чужой сайт — не id. Хосты YouTube — единственный список программы: по нему
же `WebLink` решает, ведёт ли ссылка на YouTube.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

YOUTUBE_HOSTS: Final[frozenset[str]] = frozenset(
    {"youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"}
)
VIDEO_ID_CHARS: Final[str] = r"[A-Za-z0-9_-]"
VIDEO_ID_LENGTH: Final[int] = 11
_ID: Final[str] = rf"({VIDEO_ID_CHARS}{{{VIDEO_ID_LENGTH}}})"
_ID_END: Final[str] = r"(?:[^A-Za-z0-9_-]|$)"
# Ссылки YouTube с id: из всех совпадений берётся самое раннее по позиции id в тексте.
YOUTUBE_LINK_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(rf"(?:https?://)?(?:www\.)?youtu\.be/{_ID}{_ID_END}", flags=re.IGNORECASE),
    re.compile(
        rf"(?:https?://)?(?:www\.)?(?:m\.)?youtube\.com/watch\?(?:[^#\s]*?&)?v={_ID}{_ID_END}",
        flags=re.IGNORECASE,
    ),
    re.compile(
        rf"(?:https?://)?(?:www\.)?(?:m\.)?youtube\.com/(?:shorts|embed|live)/{_ID}{_ID_END}",
        flags=re.IGNORECASE,
    ),
)
VIDEO_ID_PATTERN: Final[re.Pattern[str]] = re.compile(_ID)
SHORT_URL_TEMPLATE: Final[str] = "https://youtu.be/{video_id}"
WATCH_URL_TEMPLATE: Final[str] = "https://www.youtube.com/watch?v={video_id}"
ID_GROUP: Final[int] = 1


@dataclass(frozen=True)
class YouTubeVideoId:
    """Id видео YouTube и адреса, которые из него строятся."""

    value: str

    @classmethod
    def of(cls, text: str) -> YouTubeVideoId | None:
        """Id из ссылки YouTube в тексте (самой ранней) или из текста, который целиком — id; нет — None."""
        cleaned: str = (text or "").strip()
        earliest: re.Match[str] | None = None
        for pattern in YOUTUBE_LINK_PATTERNS:
            for match in pattern.finditer(cleaned):
                if earliest is None or match.start(ID_GROUP) < earliest.start(ID_GROUP):
                    earliest = match
        if earliest is not None:
            return cls(earliest.group(ID_GROUP))
        return cls(cleaned) if VIDEO_ID_PATTERN.fullmatch(cleaned) else None

    @property
    def short_url(self) -> str:
        """`https://youtu.be/<id>` — вид ссылки на видео в описаниях и в плане."""
        return SHORT_URL_TEMPLATE.format(video_id=self.value)

    @property
    def watch_url(self) -> str:
        """`https://www.youtube.com/watch?v=<id>` — вид ссылки источника в записи слота."""
        return WATCH_URL_TEMPLATE.format(video_id=self.value)
