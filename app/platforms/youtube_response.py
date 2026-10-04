"""Ответ YouTube Data API — объект над словарём ответа (CLAUDE.md §6 инвариант 9).

Поле не той формы — `PlatformError(badResponse)`: разбирать такой ответ нечем. Ключи JSON — `YouTubeKey`; по ним же
строятся тела запросов. Отсутствующий раздел читается пустым: площадка не присылает пустых разделов.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.platforms.error import PlatformCode, PlatformDetail, PlatformError
from app.platforms.youtube_operation import YouTubeOperation


class YouTubeKey(str, Enum):
    """Поля ответов и тел запросов YouTube Data API v3."""

    ID = "id"
    ITEMS = "items"
    NEXT_PAGE_TOKEN = "nextPageToken"
    SNIPPET = "snippet"
    STATUS = "status"
    CONTENT_DETAILS = "contentDetails"
    CDN = "cdn"
    INGESTION_INFO = "ingestionInfo"
    INGESTION_ADDRESS = "ingestionAddress"
    STREAM_NAME = "streamName"
    INGESTION_TYPE = "ingestionType"
    RESOLUTION = "resolution"
    FRAME_RATE = "frameRate"
    TITLE = "title"
    DESCRIPTION = "description"
    CUSTOM_URL = "customUrl"
    DEFAULT_LANGUAGE = "defaultLanguage"
    DEFAULT_AUDIO_LANGUAGE = "defaultAudioLanguage"
    BRANDING_SETTINGS = "brandingSettings"
    CHANNEL = "channel"
    SCHEDULED_START_TIME = "scheduledStartTime"
    PUBLISHED_AT = "publishedAt"
    CATEGORY_ID = "categoryId"
    LIVE_CHAT_ID = "liveChatId"
    THUMBNAILS = "thumbnails"
    DEFAULT = "default"
    URL = "url"
    WIDTH = "width"
    PRIVACY_STATUS = "privacyStatus"
    SELF_DECLARED_MADE_FOR_KIDS = "selfDeclaredMadeForKids"
    MADE_FOR_KIDS = "madeForKids"
    LIFE_CYCLE_STATUS = "lifeCycleStatus"
    ENABLE_AUTO_START = "enableAutoStart"
    ENABLE_AUTO_STOP = "enableAutoStop"
    LATENCY_PREFERENCE = "latencyPreference"
    BOUND_STREAM_ID = "boundStreamId"
    # флаг постоянного эфира: только факт для строки лога, не основание решения — у служебных эфиров
    # «Начать эфир сейчас» он приходит false (planers, выгрузки 18-09-2026); признак — нет времени старта
    IS_DEFAULT_BROADCAST = "isDefaultBroadcast"
    CONTENT_RATING = "contentRating"
    YT_RATING = "ytRating"
    LIVE_STREAMING_DETAILS = "liveStreamingDetails"


@dataclass(frozen=True)
class YouTubeResponse:
    """Словарь ответа или его раздела."""

    data: Mapping[str, object]

    @classmethod
    def of(cls, operation: YouTubeOperation, answer: object) -> YouTubeResponse:
        """Ответ одной попытки: не объект JSON — badResponse."""
        if not isinstance(answer, dict):
            detail: str = PlatformDetail.NOT_MAPPING.text(operation=operation.value, kind=type(answer).__name__)
            raise PlatformError(PlatformCode.BAD_RESPONSE, detail)
        return cls(answer)

    def items(self) -> tuple[YouTubeResponse, ...]:
        """Элементы списка `items`; нет списка — пусто."""
        value: object = self.data.get(YouTubeKey.ITEMS, [])
        if not isinstance(value, list):
            raise PlatformError(PlatformCode.BAD_RESPONSE, PlatformDetail.NOT_LIST.text(key=YouTubeKey.ITEMS.value))
        return tuple(YouTubeResponse(item) for item in value if isinstance(item, dict))

    def part(self, key: YouTubeKey) -> YouTubeResponse:
        """Раздел ответа; раздела нет — пустой."""
        value: object = self.data.get(key, {})
        if not isinstance(value, dict):
            raise PlatformError(PlatformCode.BAD_RESPONSE, PlatformDetail.NOT_OBJECT.text(key=key.value))
        return YouTubeResponse(value)

    def text(self, key: YouTubeKey, allow_empty: bool = False) -> str:
        """Строка поля; не строка или пусто там, где пусто нельзя, — badResponse."""
        value: object = self.data.get(key, "")
        if not isinstance(value, str) or (not allow_empty and not value):
            raise PlatformError(PlatformCode.BAD_RESPONSE, PlatformDetail.BAD_VALUE.text(key=key.value, value=value))
        return value

    def optional_text(self, key: YouTubeKey) -> str | None:
        """Непустая строка поля или None."""
        value: object = self.data.get(key)
        return value if isinstance(value, str) and value else None

    def optional_bool(self, key: YouTubeKey) -> bool | None:
        value: object = self.data.get(key)
        return value if isinstance(value, bool) else None

    def moment(self, key: YouTubeKey) -> datetime | None:
        """Момент ISO-8601 в UTC; нет поля или не разбирается — None. Без пояса — UTC."""
        text: str | None = self.optional_text(key)
        if text is None:
            return None
        try:
            parsed: datetime = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)

    def get(self, key: YouTubeKey) -> object:
        """Значение поля как пришло — для сравнения и строки лога; нет — None."""
        return self.data.get(key)

    def copy(self) -> dict[str, object]:
        """Раздел целиком для записи: read-modify-write не теряет полей, которые программа не задаёт."""
        return dict(self.data)
