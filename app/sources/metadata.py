"""Данные одного видео-источника, как их отдал yt-dlp (CLAUDE.md §2 контур A: `ingest\\youtube_metadata.py`).

`SourceMetadata.from_ytdlp` — правило донора `YtDlpYouTubeMetadataFetcher._build_metadata` (restreamer):
название чистится от хвоста хештегов, пустая обложка заменяется запасной `hqdefault.jpg` по id видео,
языки аудио берутся из форматов со звуком, языки субтитров — ключами словарей. Язык источника здесь
не решается (задача 3.4): объект несёт только сырые поля yt-dlp.

В отличие от донора, объект без названия не выбрасывается исключением: он строится, а `problem` называет
причину — дальше по конвейеру такой источник не идёт (§0).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from app.core.sheet_text import YOUTUBE_ID_CHARS, YOUTUBE_ID_LENGTH, extract_youtube_video_id
from app.observability.logging_setup import get_logger
from app.texts.source_title import sanitize_source_video_title
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "sources"
LOGGER = get_logger(LOGGER_NAME)

FALLBACK_THUMBNAIL_TEMPLATE: Final[str] = "https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
NO_AUDIO_CODEC: Final[str] = "none"      # yt-dlp пишет так acodec у формата без звука
VIDEO_ID_PATTERN: Final[re.Pattern[str]] = re.compile(f"{YOUTUBE_ID_CHARS}{{{YOUTUBE_ID_LENGTH}}}")


def _text(value: Any) -> str:
    """Поле ответа yt-dlp строкой без краёв; None и пустое — пустая строка (как `str(x or "")` донора)."""
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text: str = _text(value)
    return text or None


def _keys(value: Any) -> tuple[str, ...]:
    """Ключи словаря языков субтитров; не словарь — пусто."""
    return tuple(str(key) for key in value) if isinstance(value, dict) else ()


@dataclass(frozen=True)
class SourceMetadata:
    """Что yt-dlp сказал о видео. `url` — ссылка, по которой спрашивали (нормализованная ссылка ряда)."""

    url: str
    video_id: str
    title: str
    description: str
    thumbnail_url: str                       # пусто — ни yt-dlp, ни id видео не дали адреса обложки
    youtube_language: str | None
    channel_language: str | None
    duration_seconds: int | None
    audio_languages: tuple[str, ...]
    subtitle_languages: tuple[str, ...]
    auto_caption_languages: tuple[str, ...]

    @classmethod
    def from_ytdlp(cls, url: str, info: dict[str, Any]) -> SourceMetadata:
        """Объект из JSON `--dump-single-json`; правила донора, без исключений на пустых полях."""
        video_id: str = _text(info.get("id"))
        metadata: SourceMetadata = cls(
            url=url,
            video_id=video_id,
            title=sanitize_source_video_title(_text(info.get("title"))),
            description=_text(info.get("description")),
            thumbnail_url=_text(info.get("thumbnail")) or cls._fallback_thumbnail(url, video_id),
            youtube_language=_optional_text(info.get("language")),
            channel_language=_optional_text(info.get("channel_language")),
            duration_seconds=cls._duration(info.get("duration")),
            audio_languages=cls._audio_languages(info.get("formats")),
            subtitle_languages=_keys(info.get("subtitles")),
            auto_caption_languages=_keys(info.get("automatic_captions")),
        )
        metadata._log_built(has_own_thumbnail=bool(_text(info.get("thumbnail"))))
        return metadata

    @staticmethod
    def _fallback_thumbnail(url: str, video_id: str) -> str:
        """Запасная обложка по id видео: сначала id из ответа, затем из ссылки; id нет — пусто."""
        if VIDEO_ID_PATTERN.fullmatch(video_id):
            return FALLBACK_THUMBNAIL_TEMPLATE.format(video_id=video_id)
        fallback_id: str | None = extract_youtube_video_id(url)
        return FALLBACK_THUMBNAIL_TEMPLATE.format(video_id=fallback_id) if fallback_id else ""

    @staticmethod
    def _duration(value: Any) -> int | None:
        """Длительность в целых секундах; не число или не больше нуля — None. bool — не число."""
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return None
        return int(value)

    @staticmethod
    def _audio_languages(formats: Any) -> tuple[str, ...]:
        """Языки форматов со звуком в порядке первого появления, без повторов."""
        languages: list[str] = []
        for item in formats if isinstance(formats, list) else ():
            if not isinstance(item, dict):
                continue
            codec: str = _text(item.get("acodec"))
            language: str = _text(item.get("language"))
            if codec and codec != NO_AUDIO_CODEC and language and language not in languages:
                languages.append(language)
        return tuple(languages)

    @property
    def problem(self) -> str | None:
        """Почему источник дальше не идёт; None — годен. Пустое описание — не проблема."""
        if not self.title:
            return msg.SOURCE_NO_TITLE
        return None

    @property
    def log_line(self) -> str:
        """Сводка key=value без названия и описания: они длинные и уходят в лог только на DEBUG."""
        duration: str = str(self.duration_seconds) if self.duration_seconds is not None else "-"
        return (
            f"id={self.video_id or '-'} duration_sec={duration} language={self.youtube_language or '-'} "
            f"channel_language={self.channel_language or '-'} audio={','.join(self.audio_languages) or '-'} "
            f"subtitles={len(self.subtitle_languages)} auto_captions={len(self.auto_caption_languages)}"
        )

    def _log_built(self, has_own_thumbnail: bool) -> None:
        LOGGER.debug("source_metadata url=%s %s title=%r", self.url, self.log_line, self.title)
        if not has_own_thumbnail:
            LOGGER.warning(
                "source_thumbnail_fallback url=%s thumbnail=%s", self.url, self.thumbnail_url or "-"
            )
        if not self.description:
            LOGGER.warning("source_description_empty url=%s id=%s", self.url, self.video_id or "-")
        if self.problem is not None:
            LOGGER.warning("source_title_empty url=%s id=%s", self.url, self.video_id or "-")
