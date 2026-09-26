"""Данные одного видео-источника, как их отдал yt-dlp (CLAUDE.md §2 контур A, §3 шаг 2.4).

`YtDlpInfo` — ответ yt-dlp как есть (объект JSON `--dump-single-json`) и правила чтения его полей: текст без краёв,
ключи словарей, длительность, языки звука из форматов со звуком, запасная обложка `hqdefault.jpg` по id видео.
`SourceMetadata` — значение, которое из ответа получается: название без хвоста хештегов, описание, обложка, сырые
языки. Язык источника здесь не решается (app\\sources\\language.py): объект несёт только поля yt-dlp.

Объект без названия не выбрасывается исключением: он строится, а `problem` называет причину — дальше по конвейеру
такой источник не идёт (§0).
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from app.core.sequence import unique_in_order
from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.texts.source_title import sanitize_source_video_title
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.SOURCES)

FALLBACK_THUMBNAIL_TEMPLATE: Final[str] = "https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


class SourceFailureReason(str, Enum):
    """Почему данных источника нет или они не годятся."""

    TOOL_MISSING = "tool_missing"    # нет tools\yt-dlp.exe — yt-dlp не вызывался
    PRIVATE = "private"              # приватное видео или нужен вход через cookies
    UNAVAILABLE = "unavailable"      # удалено или заблокировано
    TIMEOUT = "timeout"              # yt-dlp не уложился в своё время
    BAD_OUTPUT = "bad_output"        # ответ yt-dlp — не объект JSON
    NO_TITLE = "no_title"            # ответ разобран, но названия нет
    FAILED = "failed"                # прочий отказ yt-dlp
    NO_LANGUAGE = "no_language"      # язык видео не определился; yt-dlp эту причину не выдаёт — её ставит SourceFacts

    @property
    def human(self) -> str:
        """Русская строка причины; текст — в messages_ru (§11)."""
        return msg.SOURCE_FAILURE_REASONS[self.value]


class YtDlpKey(str, Enum):
    """Поля ответа yt-dlp, которые читает программа: видео целиком и один его формат."""

    ID = "id"
    TITLE = "title"
    DESCRIPTION = "description"
    THUMBNAIL = "thumbnail"
    LANGUAGE = "language"                    # язык видео, а у формата — язык его звука
    CHANNEL_LANGUAGE = "channel_language"
    DURATION = "duration"
    FORMATS = "formats"
    SUBTITLES = "subtitles"
    AUTOMATIC_CAPTIONS = "automatic_captions"
    AUDIO_CODEC = "acodec"


class AudioCodec(str, Enum):
    """Значения поля `acodec` формата yt-dlp, которые что-то значат для языка звука."""

    NONE = "none"      # так yt-dlp пишет acodec у формата без звука


class MetadataEvent(str, Enum):
    """События данных видео в логе."""

    BUILT = "source_metadata"
    THUMBNAIL_FALLBACK = "source_thumbnail_fallback"
    DESCRIPTION_EMPTY = "source_description_empty"
    TITLE_EMPTY = "source_title_empty"


@dataclass(frozen=True)
class YtDlpInfo:
    """Объект JSON ответа yt-dlp — видео целиком или один его формат — и правила чтения полей."""

    data: dict[str, Any]

    def text(self, key: YtDlpKey) -> str:
        """Поле строкой без краёв; None и пустое — пустая строка."""
        return str(self.data.get(key.value) or "").strip()

    def optional_text(self, key: YtDlpKey) -> str | None:
        return self.text(key) or None

    def keys(self, key: YtDlpKey) -> tuple[str, ...]:
        """Ключи поля-словаря (языки субтитров); не словарь — пусто."""
        value: Any = self.data.get(key.value)
        return tuple(str(name) for name in value) if isinstance(value, dict) else ()

    @property
    def duration(self) -> int | None:
        """Длительность в целых секундах; не число или не больше нуля — None. bool — не число."""
        value: Any = self.data.get(YtDlpKey.DURATION.value)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return None
        return int(value)

    @property
    def has_audio(self) -> bool:
        """Формат со звуком: кодек звука назван и это не «none»."""
        codec: str = self.text(YtDlpKey.AUDIO_CODEC)
        return bool(codec) and codec != AudioCodec.NONE

    @property
    def formats(self) -> tuple[YtDlpInfo, ...]:
        """Форматы видео объектами ответа; поле не список — пусто, элемент не объект — пропускается."""
        formats: Any = self.data.get(YtDlpKey.FORMATS.value)
        if not isinstance(formats, list):
            return ()
        return tuple(YtDlpInfo(item) for item in formats if isinstance(item, dict))

    @property
    def audio_languages(self) -> tuple[str, ...]:
        """Языки форматов со звуком в порядке первого появления, без повторов и пустых."""
        languages: tuple[str, ...] = tuple(item.text(YtDlpKey.LANGUAGE) for item in self.formats if item.has_audio)
        return unique_in_order(language for language in languages if language)

    def thumbnail_url(self, url: str) -> str:
        """Обложка из ответа; нет — запасная по id видео (сначала id ответа, затем ссылки); id нет — пусто."""
        own: str = self.text(YtDlpKey.THUMBNAIL)
        if own:
            return own
        video: YouTubeVideoId | None = YouTubeVideoId.of(self.text(YtDlpKey.ID)) or YouTubeVideoId.of(url)
        return FALLBACK_THUMBNAIL_TEMPLATE.format(video_id=video.value) if video is not None else ""

    def metadata(self, url: str) -> SourceMetadata:
        """Значение данных видео; `url` — ссылка, по которой спрашивали."""
        return SourceMetadata(
            url=url,
            video_id=self.text(YtDlpKey.ID),
            title=sanitize_source_video_title(self.text(YtDlpKey.TITLE)),
            description=self.text(YtDlpKey.DESCRIPTION),
            thumbnail_url=self.thumbnail_url(url),
            youtube_language=self.optional_text(YtDlpKey.LANGUAGE),
            channel_language=self.optional_text(YtDlpKey.CHANNEL_LANGUAGE),
            duration_seconds=self.duration,
            audio_languages=self.audio_languages,
            subtitle_languages=self.keys(YtDlpKey.SUBTITLES),
            auto_caption_languages=self.keys(YtDlpKey.AUTOMATIC_CAPTIONS),
        )


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
        """Значение из JSON `--dump-single-json`, без исключений на пустых полях; что не так — строками лога."""
        answer: YtDlpInfo = YtDlpInfo(info)
        metadata: SourceMetadata = answer.metadata(url)
        metadata._log_built(has_own_thumbnail=bool(answer.text(YtDlpKey.THUMBNAIL)))
        return metadata

    @property
    def problem(self) -> SourceFailureReason | None:
        """Почему источник дальше не идёт; None — годен. Пустое описание — не проблема."""
        return SourceFailureReason.NO_TITLE if not self.title else None

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Сводка без названия и описания: они длинные и уходят в лог только на DEBUG."""
        return dict(
            id=self.video_id,
            duration_sec=self.duration_seconds,
            language=self.youtube_language,
            channel_language=self.channel_language,
            audio=self.audio_languages,
            subtitles=len(self.subtitle_languages),
            auto_captions=len(self.auto_caption_languages),
        )

    def _log_built(self, has_own_thumbnail: bool) -> None:
        """Строки лога о построенном значении: сводка на DEBUG, запасная обложка, пустые описание и название."""
        LogEvent.of(MetadataEvent.BUILT, url=self.url, **self.log_fields, title=self.title).emit(LOGGER, logging.DEBUG)
        if not has_own_thumbnail:
            fallback: LogEvent = LogEvent.of(MetadataEvent.THUMBNAIL_FALLBACK, url=self.url)
            fallback.extended(thumbnail=self.thumbnail_url).emit(LOGGER, logging.WARNING)
        if not self.description:
            LogEvent.of(MetadataEvent.DESCRIPTION_EMPTY, url=self.url, id=self.video_id).emit(LOGGER, logging.WARNING)
        if self.problem is not None:
            LogEvent.of(MetadataEvent.TITLE_EMPTY, url=self.url, id=self.video_id).emit(LOGGER, logging.WARNING)
