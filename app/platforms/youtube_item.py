"""Элементы ответов YouTube как значения площадки: канал, эфир, поток, видео (CLAUDE.md §6 инварианты 1, 7).

Эфир без разбираемого времени старта сверять не с чем: вместо эфира — замечание площадки (`PlatformNotice`). Это
служебный эфир «Начать эфир сейчас», который YouTube заводит сам; признак — только отсутствие времени старта. Что о нём
прислала площадка, пишется в лог строкой `broadcast_without_start` — только диагностика.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from app.config.channel import ChannelConfig
from app.observability.log_event import LogArea, Quoted, get_logger
from app.platforms.broadcast import BroadcastFacts, UpcomingBroadcast
from app.platforms.channel_info import ChannelInfo
from app.platforms.notice import PlatformNotice, PlatformNoticeKind
from app.platforms.placeholder import PlaceholderMark
from app.platforms.stream import StreamInfo
from app.platforms.video import AppliedVideo
from app.platforms.youtube_event import YouTubeEvent
from app.platforms.youtube_picture import PictureReader
from app.platforms.youtube_response import YouTubeKey, YouTubeResponse

LOGGER = get_logger(LogArea.PLATFORMS)
AGE_RESTRICTED_RATING: Final[str] = "ytAgeRestricted"


@dataclass(frozen=True)
class ChannelItem:
    """Элемент channels.list(mine=true)."""

    item: YouTubeResponse

    def info(self) -> ChannelInfo:
        snippet: YouTubeResponse = self.item.part(YouTubeKey.SNIPPET)
        return ChannelInfo(
            youtube_channel_id=self.item.text(YouTubeKey.ID),
            title=snippet.text(YouTubeKey.TITLE),
            default_language=self._language(snippet),
            handle_raw=snippet.optional_text(YouTubeKey.CUSTOM_URL),
        )

    def _language(self, snippet: YouTubeResponse) -> str | None:
        """brandingSettings.channel.defaultLanguage, иначе snippet.defaultLanguage, иначе None."""
        branding: YouTubeResponse = self.item.part(YouTubeKey.BRANDING_SETTINGS).part(YouTubeKey.CHANNEL)
        for source in (branding, snippet):
            value: str | None = source.optional_text(YouTubeKey.DEFAULT_LANGUAGE)
            if value is not None and value.strip():
                return value
        return None


@dataclass(frozen=True)
class BroadcastItem:
    """Элемент liveBroadcasts.list."""

    item: YouTubeResponse

    @property
    def thumbnails(self) -> YouTubeResponse:
        return self.item.part(YouTubeKey.SNIPPET).part(YouTubeKey.THUMBNAILS)

    def upcoming(self, channel: ChannelConfig) -> UpcomingBroadcast | PlatformNotice:
        """Эфир со временем старта или замечание об эфире без него."""
        snippet: YouTubeResponse = self.item.part(YouTubeKey.SNIPPET)
        status: YouTubeResponse = self.item.part(YouTubeKey.STATUS)
        details: YouTubeResponse = self.item.part(YouTubeKey.CONTENT_DETAILS)
        broadcast_id: str = self.item.text(YouTubeKey.ID)
        start: datetime | None = snippet.moment(YouTubeKey.SCHEDULED_START_TIME)
        if start is None:
            return self._undated(channel, broadcast_id)
        return UpcomingBroadcast(
            broadcast_id=broadcast_id,
            start_utc=start,
            title=snippet.text(YouTubeKey.TITLE, allow_empty=True),
            description=snippet.text(YouTubeKey.DESCRIPTION, allow_empty=True),
            stream_id=details.optional_text(YouTubeKey.BOUND_STREAM_ID),
            live_chat_id=snippet.optional_text(YouTubeKey.LIVE_CHAT_ID),
            category_id=snippet.optional_text(YouTubeKey.CATEGORY_ID),
            privacy_status=status.optional_text(YouTubeKey.PRIVACY_STATUS),
            auto_start=details.optional_bool(YouTubeKey.ENABLE_AUTO_START),
            auto_stop=details.optional_bool(YouTubeKey.ENABLE_AUTO_STOP),
            latency_preference=details.optional_text(YouTubeKey.LATENCY_PREFERENCE),
            published_utc=snippet.moment(YouTubeKey.PUBLISHED_AT),
        )

    def _undated(self, channel: ChannelConfig, broadcast_id: str) -> PlatformNotice:
        """Замечание владельцу — данными; в лог — что площадка прислала, как есть."""
        snippet: YouTubeResponse = self.item.part(YouTubeKey.SNIPPET)
        status: YouTubeResponse = self.item.part(YouTubeKey.STATUS)
        title: str = snippet.optional_text(YouTubeKey.TITLE) or ""
        YouTubeEvent.BROADCAST_WITHOUT_START.of(
            channel,
            broadcast_id=broadcast_id,
            title=Quoted(title),
            value=snippet.get(YouTubeKey.SCHEDULED_START_TIME),
            is_default=snippet.get(YouTubeKey.IS_DEFAULT_BROADCAST),
            lifecycle=status.get(YouTubeKey.LIFE_CYCLE_STATUS),
            privacy=status.get(YouTubeKey.PRIVACY_STATUS),
            bound_stream_id=self.item.part(YouTubeKey.CONTENT_DETAILS).get(YouTubeKey.BOUND_STREAM_ID),
            published_at=snippet.get(YouTubeKey.PUBLISHED_AT),
        ).emit(LOGGER)
        return PlatformNotice(
            PlatformNoticeKind.UNDATED_BROADCAST, account_name=channel.account_name, title=title, handle=channel.handle
        )


@dataclass(frozen=True)
class BroadcastPage:
    """Эфиры одной страницы списка с отпечатками их картинок и замечания об эфирах, которые сверять не с чем."""

    broadcasts: tuple[UpcomingBroadcast, ...]
    notices: tuple[PlatformNotice, ...]

    @classmethod
    def read(cls, page: YouTubeResponse, channel: ChannelConfig, pictures: PictureReader) -> BroadcastPage:
        broadcasts: list[UpcomingBroadcast] = []
        notices: list[PlatformNotice] = []
        for item in (BroadcastItem(raw) for raw in page.items()):
            found: UpcomingBroadcast | PlatformNotice = item.upcoming(channel)
            if isinstance(found, PlatformNotice):
                notices.append(found)
                continue
            mark: PlaceholderMark | None = pictures.mark(item.thumbnails)
            broadcasts.append(replace(found, thumbnail_sha=None if mark is None else mark.sha))
        return cls(tuple(broadcasts), tuple(notices))


@dataclass(frozen=True)
class StreamItem:
    """Элемент liveStreams.list или ответ liveStreams.insert."""

    item: YouTubeResponse

    def info(self, allow_empty: bool) -> StreamInfo:
        """Поток; `allow_empty` — пустые метка, адрес и ключ допустимы (прочитанный поток), иначе — badResponse."""
        snippet: YouTubeResponse = self.item.part(YouTubeKey.SNIPPET)
        ingestion: YouTubeResponse = self.item.part(YouTubeKey.CDN).part(YouTubeKey.INGESTION_INFO)
        return StreamInfo(
            stream_id=self.item.text(YouTubeKey.ID),
            title=snippet.text(YouTubeKey.TITLE, allow_empty=True),
            ingestion_address=ingestion.text(YouTubeKey.INGESTION_ADDRESS, allow_empty=allow_empty),
            stream_name=ingestion.text(YouTubeKey.STREAM_NAME, allow_empty=allow_empty),
            description=snippet.text(YouTubeKey.DESCRIPTION, allow_empty=True),
        )


@dataclass(frozen=True)
class VideoItem:
    """Элемент videos.list или ответ videos.update."""

    item: YouTubeResponse

    def facts(self, broadcast_id: str, broadcast: UpcomingBroadcast | None, stream: StreamInfo | None) -> BroadcastFacts:
        """Язык, аудитория и возраст — у видео; время старта — в liveStreamingDetails; поток и чат — у эфира."""
        snippet: YouTubeResponse = self.item.part(YouTubeKey.SNIPPET)
        status: YouTubeResponse = self.item.part(YouTubeKey.STATUS)
        rating: YouTubeResponse = self.item.part(YouTubeKey.CONTENT_DETAILS).part(YouTubeKey.CONTENT_RATING)
        return BroadcastFacts(
            broadcast_id=broadcast_id,
            title=snippet.text(YouTubeKey.TITLE, allow_empty=True),
            description=snippet.text(YouTubeKey.DESCRIPTION, allow_empty=True),
            start_utc=self.item.part(YouTubeKey.LIVE_STREAMING_DETAILS).moment(YouTubeKey.SCHEDULED_START_TIME),
            privacy_status=status.optional_text(YouTubeKey.PRIVACY_STATUS),
            made_for_kids=status.optional_bool(YouTubeKey.MADE_FOR_KIDS),
            age_restricted=rating.get(YouTubeKey.YT_RATING) == AGE_RESTRICTED_RATING,
            default_language=snippet.optional_text(YouTubeKey.DEFAULT_LANGUAGE),
            default_audio_language=snippet.optional_text(YouTubeKey.DEFAULT_AUDIO_LANGUAGE),
            category_id=snippet.optional_text(YouTubeKey.CATEGORY_ID),
            bound_stream_id=None if broadcast is None else broadcast.stream_id,
            stream_marker=None if stream is None else stream.title,
            live_chat_id=None if broadcast is None else broadcast.live_chat_id,
            thumbnail_url=self._largest_thumbnail(snippet.part(YouTubeKey.THUMBNAILS)),
            auto_start=None if broadcast is None else broadcast.auto_start,
            auto_stop=None if broadcast is None else broadcast.auto_stop,
            latency_preference=None if broadcast is None else broadcast.latency_preference,
        )

    def applied(self) -> AppliedVideo:
        """Что площадка записала на самом деле; пустой ответ — пустой AppliedVideo."""
        snippet: YouTubeResponse = self.item.part(YouTubeKey.SNIPPET)
        status: YouTubeResponse = self.item.part(YouTubeKey.STATUS)
        return AppliedVideo(
            language=snippet.optional_text(YouTubeKey.DEFAULT_LANGUAGE),
            audio_language=snippet.optional_text(YouTubeKey.DEFAULT_AUDIO_LANGUAGE),
            category_id=snippet.optional_text(YouTubeKey.CATEGORY_ID),
            privacy=status.optional_text(YouTubeKey.PRIVACY_STATUS),
            made_for_kids=status.optional_bool(YouTubeKey.MADE_FOR_KIDS),
        )

    def _largest_thumbnail(self, thumbnails: YouTubeResponse) -> str | None:
        """Самое крупное доступное разрешение; поле справочное, в сравнении не участвует."""
        sizes: list[YouTubeResponse] = [YouTubeResponse(size) for size in thumbnails.data.values() if isinstance(size, dict)]
        with_url: list[YouTubeResponse] = [size for size in sizes if size.optional_text(YouTubeKey.URL) is not None]
        if not with_url:
            return None
        widest: YouTubeResponse = max(with_url, key=lambda size: self._width(size))
        return widest.optional_text(YouTubeKey.URL)

    def _width(self, size: YouTubeResponse) -> int:
        width: object = size.get(YouTubeKey.WIDTH)
        return width if isinstance(width, int) else 0
