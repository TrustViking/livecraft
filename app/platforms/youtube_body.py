"""Тела запросов YouTube: эфир из спеки, поток с меткой программы, настройки видео (CLAUDE.md §6 инварианты 1, 7).

Всё, что уходит в эфир, берётся из спеки (`BroadcastSpec`): там же оно сверяется с площадкой. Настройки видео
пишутся read-modify-write: части snippet и status отправляются целиком — частичная часть затёрла бы непереданные
поля; совпало всё — записи нет (`VideoSettingsEdit.fixes`). Метка потока тоже переписывает snippet целиком.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from enum import Enum
from typing import Final

from app.platforms.spec import BroadcastSpec
from app.platforms.video import VideoFixes, VideoSettings
from app.platforms.youtube_description import StreamDescription
from app.platforms.youtube_response import YouTubeKey, YouTubeResponse

RFC3339_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"   # момент старта в том виде, в каком его ждёт YouTube


class StreamCdn(str, Enum):
    """Настройки приёма потока: RTMP, разрешение и частота кадров — как пришлёт стример."""

    RTMP = "rtmp"
    VARIABLE = "variable"


@dataclass(frozen=True)
class BroadcastBody:
    """Эфир из спеки: создание — snippet, status и contentDetails; правка — только snippet (contentDetails у update
    требует monitorStream), поэтому время и категория уходят при правке всегда."""

    spec: BroadcastSpec

    @property
    def snippet(self) -> dict[str, object]:
        return {
            YouTubeKey.TITLE: self.spec.title,
            YouTubeKey.DESCRIPTION: self.spec.description,
            YouTubeKey.SCHEDULED_START_TIME: self.spec.start_minute.astimezone(timezone.utc).strftime(RFC3339_FORMAT),
            YouTubeKey.CATEGORY_ID: self.spec.category_id,
        }

    @property
    def insert(self) -> dict[str, object]:
        """Новый эфир: аудитория — всегда «не для детей» (инвариант 7)."""
        return {
            YouTubeKey.SNIPPET: self.snippet,
            YouTubeKey.STATUS: {
                YouTubeKey.PRIVACY_STATUS: self.spec.privacy,
                YouTubeKey.SELF_DECLARED_MADE_FOR_KIDS: False,
            },
            YouTubeKey.CONTENT_DETAILS: {
                YouTubeKey.ENABLE_AUTO_START: self.spec.auto_start,
                YouTubeKey.ENABLE_AUTO_STOP: self.spec.auto_stop,
                YouTubeKey.LATENCY_PREFERENCE: self.spec.latency_preference,
            },
        }

    def update(self, broadcast_id: str) -> dict[str, object]:
        return {YouTubeKey.ID: broadcast_id, YouTubeKey.SNIPPET: self.snippet}


@dataclass(frozen=True)
class StreamBody:
    """Поток с меткой программы: название — slot_id, описание — чей это ключ; зрителям они не видны."""

    description: StreamDescription

    @property
    def insert(self) -> dict[str, object]:
        return {
            YouTubeKey.SNIPPET: {
                YouTubeKey.TITLE: self.description.marker,
                YouTubeKey.DESCRIPTION: self.description.text,
            },
            YouTubeKey.CDN: {
                YouTubeKey.INGESTION_TYPE: StreamCdn.RTMP,
                YouTubeKey.RESOLUTION: StreamCdn.VARIABLE,
                YouTubeKey.FRAME_RATE: StreamCdn.VARIABLE,
            },
        }

    def update(self, stream_id: str, snippet: YouTubeResponse) -> dict[str, object]:
        """Прочитанный snippet потока целиком, в нём заменены только название и описание."""
        written: dict[str, object] = snippet.copy()
        written[YouTubeKey.TITLE] = self.description.marker
        written[YouTubeKey.DESCRIPTION] = self.description.text
        return {YouTubeKey.ID: stream_id, YouTubeKey.SNIPPET: written}


@dataclass(frozen=True)
class VideoSettingsEdit:
    """Настройки видео эфира: что разошлось с заданными (`fixes`) и тело одной записи (`body`)."""

    item: YouTubeResponse          # элемент videos.list с частями snippet и status
    settings: VideoSettings

    @property
    def fixes(self) -> VideoFixes:
        """Язык и язык звука, категория, аудитория (своя и заданная на весь канал) и видимость."""
        snippet: YouTubeResponse = self.item.part(YouTubeKey.SNIPPET)
        status: YouTubeResponse = self.item.part(YouTubeKey.STATUS)
        language: str = self.settings.language
        return VideoFixes(
            language_set=snippet.get(YouTubeKey.DEFAULT_LANGUAGE) != language
            or snippet.get(YouTubeKey.DEFAULT_AUDIO_LANGUAGE) != language,
            category_set=snippet.get(YouTubeKey.CATEGORY_ID) != self.settings.category_id,
            audience_cleared=status.get(YouTubeKey.SELF_DECLARED_MADE_FOR_KIDS) is not False
            or status.get(YouTubeKey.MADE_FOR_KIDS) is True,
            privacy_set=status.get(YouTubeKey.PRIVACY_STATUS) != self.settings.privacy,
        )

    def body(self, broadcast_id: str) -> dict[str, object]:
        """snippet и status целиком с заданными значениями."""
        snippet: dict[str, object] = self.item.part(YouTubeKey.SNIPPET).copy()
        status: dict[str, object] = self.item.part(YouTubeKey.STATUS).copy()
        snippet[YouTubeKey.DEFAULT_LANGUAGE] = self.settings.language
        snippet[YouTubeKey.DEFAULT_AUDIO_LANGUAGE] = self.settings.language
        snippet[YouTubeKey.CATEGORY_ID] = self.settings.category_id
        status[YouTubeKey.SELF_DECLARED_MADE_FOR_KIDS] = False
        status[YouTubeKey.PRIVACY_STATUS] = self.settings.privacy
        return {YouTubeKey.ID: broadcast_id, YouTubeKey.SNIPPET: snippet, YouTubeKey.STATUS: status}
