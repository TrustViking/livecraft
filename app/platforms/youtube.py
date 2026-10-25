"""YouTube Data API v3 — площадка эфиров v1 (CLAUDE.md §3 шаги 10–11, §6 инварианты 1, 7, 9).

Чтение: `describe_channel`, `list_upcoming`, `get_stream`, `read_facts`. Планирование: `create_broadcast`,
`update_broadcast`, `attach_stream`, `apply_video_settings`, `set_stream_marker`, `set_thumbnail`. Любой сбой наружу —
только `PlatformError`. Все обращения к API идут через одну точку (`YouTubeGateway`): пауза, повторы, память отказов,
расход. Картинки эфиров (i.ytimg.com) — не API: их читает `PictureReader` без паузы. Ключ потока — только с площадки;
в строках лога — маской. Браузер открывает только `describe_channel(allow_login=True)`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Final

from googleapiclient.http import MediaInMemoryUpload

from app.config.channel import ChannelConfig
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.observability.logging_setup import mask_stream_key
from app.paths import LivecraftPaths
from app.platforms.broadcast import BroadcastFacts, CreatedBroadcast, UpcomingBroadcast
from app.platforms.channel_info import ChannelInfo
from app.platforms.error import PlatformCode, PlatformDetail, PlatformError
from app.platforms.limits import PlatformLimits
from app.platforms.notice import PlatformNotice
from app.platforms.placeholder import PlaceholderMark
from app.platforms.spec import BroadcastSpec
from app.platforms.stream import StreamInfo
from app.platforms.video import AppliedVideo, VideoFixes, VideoSettings
from app.platforms.youtube_body import BroadcastBody, StreamBody, VideoSettingsEdit
from app.platforms.youtube_description import StreamDescription
from app.platforms.youtube_event import YouTubeEvent
from app.platforms.youtube_gateway import YouTubeGateway
from app.platforms.youtube_item import BroadcastItem, BroadcastPage, ChannelItem, StreamItem, VideoItem
from app.platforms.youtube_logins import ChannelLogins
from app.platforms.youtube_operation import YouTubeOperation
from app.platforms.youtube_picture import PictureReader
from app.platforms.youtube_refusal import Refusal
from app.platforms.youtube_response import YouTubeKey, YouTubeResponse
from app.slots.preview import MIME_TYPE
from app.slots.texts import SlotTexts

LOGGER = get_logger(LogArea.PLATFORMS)
BROADCAST_STATUS_UPCOMING: Final[str] = "upcoming"
MAX_RESULTS: Final[int] = 50
CHANNEL_PARTS: Final[str] = "snippet,brandingSettings"
BROADCAST_PARTS: Final[str] = "snippet,contentDetails,status"
STREAM_PARTS: Final[str] = "snippet,cdn"
SNIPPET_PART: Final[str] = "snippet"   # правка потока и эфира: snippet целиком; contentDetails у эфира требует monitorStream
BROADCAST_INSERT_PARTS: Final[str] = "snippet,status,contentDetails"
BIND_PARTS: Final[str] = "id,contentDetails"
VIDEO_SETTINGS_PARTS: Final[str] = "snippet,status"   # один проход: язык, категория, аудитория, видимость
# Без liveStreamingDetails время старта у videos приходит пустым (planers, живой прогон 13-09-2026).
VIDEO_FACTS_PARTS: Final[str] = "snippet,status,contentDetails,liveStreamingDetails"
LATENCY_PREFERENCE: Final[str] = "normal"
ENABLE_AUTO_STOP: Final[bool] = True
# Вид ключа потока YouTube — единственный источник: 5 или 4 группы по 4 строчных знака.
YOUTUBE_STREAM_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]{4}(-[a-z0-9]{4}){3,4}$")


@dataclass
class YouTubePlatform:
    """Площадка YouTube одного запуска. Настройки эфира площадка не хранит: всё, что уходит в эфир, приходит готовой
    спекой. `notices` — замечания за запуск, их забирает `take_notices`."""

    gateway: YouTubeGateway
    pictures: PictureReader = field(default_factory=PictureReader)
    notices: list[PlatformNotice] = field(default_factory=list)

    @classmethod
    def open(cls, paths: LivecraftPaths, settings: LivecraftSettings) -> YouTubePlatform:
        """Площадка с входами владельцев каналов, часами программы и паузой из livecraft.json."""
        return cls(YouTubeGateway(ChannelLogins.of(paths), Clock(settings.zone), settings.youtube_pause_seconds))

    @property
    def limits(self) -> PlatformLimits:
        """Пределы текстов YouTube — те же, что у текстов слота (§14 решение 30)."""
        return PlatformLimits(
            title_max_chars=SlotTexts.TITLE_MAX_CHARS,
            description_max_chars=SlotTexts.DESCRIPTION_MAX_CHARS,
            auto_stop=ENABLE_AUTO_STOP,
            latency_preference=LATENCY_PREFERENCE,
        )

    def describe_channel(self, channel: ChannelConfig, *, allow_login: bool = True) -> ChannelInfo:
        """За запуск канал спрашивается один раз. allow_login=False — без браузера: нужен вход — loginRequired."""
        cached: ChannelInfo | None = self.gateway.logins.infos.get(channel.key)
        if cached is not None:
            return cached
        items: tuple[YouTubeResponse, ...] = self.gateway.call(
            channel,
            YouTubeOperation.CHANNELS_LIST,
            lambda service: service.channels().list(part=CHANNEL_PARTS, mine=True),
            allow_login,
        ).items()
        if not items:
            detail: str = PlatformDetail.CHANNEL_EMPTY.text(channel=channel.account_name)
            raise PlatformError(PlatformCode.CHANNEL_NOT_FOUND, detail)
        info: ChannelInfo = ChannelItem(items[0]).info()
        described: LogEvent = YouTubeEvent.CHANNEL_DESCRIBED.of(
            channel,
            handle_raw=info.handle_raw,
            youtube_channel_id=info.youtube_channel_id,
            youtube_title=Quoted(info.title),
            language=info.default_language,
        )
        described.emit(LOGGER)
        self.gateway.logins.infos[channel.key] = info
        return info

    def keep_login(self, channel: ChannelConfig) -> None:
        """Канал подтверждён: токен нового входа — в файл; нового входа не было — ничего."""
        self.gateway.logins.keep(channel)

    def drop_login(self, channel: ChannelConfig) -> None:
        """Клиент, вход, ChannelInfo и отказы канала забыты; файл токена не трогается и следующим входом не читается."""
        self.gateway.logins.drop(channel)
        self.gateway.refusals.forget_channel(channel.key)

    def list_upcoming(self, channel: ChannelConfig) -> list[UpcomingBroadcast]:
        """Все страницы; пустой список — нормальный ответ. broadcastStatus — без mine: у liveBroadcasts.list фильтры
        id / mine / broadcastStatus взаимоисключающие, broadcastStatus сам означает эфиры вошедшего канала."""
        broadcasts: list[UpcomingBroadcast] = []
        page_token: str | None = None
        while True:
            page: YouTubeResponse = self.gateway.call(
                channel,
                YouTubeOperation.BROADCASTS_LIST,
                lambda service, token=page_token: service.liveBroadcasts().list(
                    part=BROADCAST_PARTS, broadcastStatus=BROADCAST_STATUS_UPCOMING, maxResults=MAX_RESULTS, pageToken=token
                ),
            )
            read: BroadcastPage = BroadcastPage.read(page, channel, self.pictures)
            broadcasts.extend(read.broadcasts)
            self.notices.extend(read.notices)
            page_token = page.optional_text(YouTubeKey.NEXT_PAGE_TOKEN)
            if page_token is None:
                break
        YouTubeEvent.BROADCASTS_LISTED.of(channel, count=len(broadcasts)).emit(LOGGER)
        return broadcasts

    def get_stream(self, channel: ChannelConfig, stream_id: str) -> StreamInfo | None:
        """Поток по id; нет — None. Ключ неожиданного вида не отбрасывается — только предупреждение с маской ключа."""
        found: YouTubeResponse | None = self.gateway.read_by_id(
            channel,
            YouTubeOperation.STREAMS_LIST,
            stream_id,
            lambda service: service.liveStreams().list(part=STREAM_PARTS, id=stream_id),
        )
        if found is None:
            return None
        stream: StreamInfo = StreamItem(found).info(allow_empty=True)
        if stream.stream_name and not YOUTUBE_STREAM_KEY_PATTERN.fullmatch(stream.stream_name):
            unexpected: LogEvent = YouTubeEvent.STREAM_KEY_UNEXPECTED.of(
                channel, stream_id=stream.stream_id, stream_key=mask_stream_key(stream.stream_name)
            )
            unexpected.emit(LOGGER, logging.WARNING)
        return stream

    def create_broadcast(self, channel: ChannelConfig, spec: BroadcastSpec) -> CreatedBroadcast:
        """Эфир → поток → привязка; оборвалось — доделает следующий запуск. Обложки у нового эфира ещё нет: его
        картинка — заглушка канала, её отпечаток уходит в описание потока."""
        inserted: YouTubeResponse = self.gateway.call(
            channel,
            YouTubeOperation.BROADCASTS_INSERT,
            lambda service: service.liveBroadcasts().insert(part=BROADCAST_INSERT_PARTS, body=BroadcastBody(spec).insert),
        )
        broadcast_id: str = inserted.text(YouTubeKey.ID)
        YouTubeEvent.BROADCAST_INSERTED.of(channel, broadcast_id=broadcast_id).emit(LOGGER)
        placeholder: PlaceholderMark | None = self.pictures.mark(BroadcastItem(inserted).thumbnails)
        captured: LogEvent = YouTubeEvent.PLACEHOLDER_CAPTURED.of(
            channel, broadcast_id=broadcast_id, sha=None if placeholder is None else placeholder.sha
        )
        captured.emit(LOGGER)
        return self._attach_new_stream(channel, broadcast_id, spec, placeholder)

    def attach_stream(self, channel: ChannelConfig, broadcast_id: str, spec: BroadcastSpec) -> CreatedBroadcast:
        """Эфир уже есть, потока нет: тот же путь с создания потока. Отпечаток заглушки не снимается: на картинке
        существующего эфира может быть обложка."""
        return self._attach_new_stream(channel, broadcast_id, spec, None)

    def update_broadcast(self, channel: ChannelConfig, broadcast_id: str, spec: BroadcastSpec) -> None:
        """update заменяет snippet целиком: время и категорию из спеки отправляем всегда."""
        self.gateway.call(
            channel,
            YouTubeOperation.BROADCASTS_UPDATE,
            lambda service: service.liveBroadcasts().update(part=SNIPPET_PART, body=BroadcastBody(spec).update(broadcast_id)),
        )
        YouTubeEvent.BROADCAST_UPDATED.of(channel, broadcast_id=broadcast_id).emit(LOGGER)

    def apply_video_settings(self, channel: ChannelConfig, broadcast_id: str, settings: VideoSettings) -> VideoFixes:
        """Одно чтение и не более одной записи: язык и аудиторию у эфира не записать; совпало всё — записи нет."""
        edit: VideoSettingsEdit = VideoSettingsEdit(
            self.gateway.require_by_id(
                channel,
                YouTubeOperation.VIDEOS_LIST,
                broadcast_id,
                lambda service: service.videos().list(part=VIDEO_SETTINGS_PARTS, id=broadcast_id),
            ),
            settings,
        )
        if not edit.fixes.any_fix:
            return edit.fixes
        updated: YouTubeResponse = self.gateway.call(
            channel,
            YouTubeOperation.VIDEOS_UPDATE,
            lambda service: service.videos().update(part=VIDEO_SETTINGS_PARTS, body=edit.body(broadcast_id)),
        )
        fixes: VideoFixes = replace(edit.fixes, applied=VideoItem(updated).applied())
        applied: LogEvent = YouTubeEvent.VIDEO_SETTINGS_APPLIED.of(
            channel, broadcast_id=broadcast_id, language=fixes.language_set, category=fixes.category_set
        )
        applied = applied.extended(audience=fixes.audience_cleared, privacy=fixes.privacy_set)
        written: AppliedVideo = fixes.applied
        applied = applied.extended(applied_language=written.language, applied_category=written.category_id)
        applied.extended(applied_privacy=written.privacy).emit(LOGGER)
        return fixes

    def set_stream_marker(self, channel: ChannelConfig, stream_id: str, marker: str) -> None:
        """snippet потока читается целиком, меняются только название и описание. Метка заглушки из прежнего описания
        сохраняется: по ней следующий запуск узнает эфир без обложки."""
        snippet: YouTubeResponse = self.gateway.require_by_id(
            channel,
            YouTubeOperation.STREAMS_LIST,
            stream_id,
            lambda service: service.liveStreams().list(part=SNIPPET_PART, id=stream_id),
        ).part(YouTubeKey.SNIPPET)
        previous: PlaceholderMark | None = PlaceholderMark.found_in(snippet.text(YouTubeKey.DESCRIPTION, allow_empty=True))
        body: StreamBody = StreamBody(StreamDescription(channel, marker, self.gateway.clock, previous))
        self.gateway.call(
            channel,
            YouTubeOperation.STREAMS_UPDATE,
            lambda service: service.liveStreams().update(part=SNIPPET_PART, body=body.update(stream_id, snippet)),
        )
        YouTubeEvent.STREAM_MARKER_SET.of(channel, stream_id=stream_id, marker=marker).emit(LOGGER)

    def set_thumbnail(self, channel: ChannelConfig, broadcast_id: str, preview: bytes) -> None:
        """Обложка не критична: сбой поднимается как PlatformError, решает вызывающий."""
        media: MediaInMemoryUpload = MediaInMemoryUpload(preview, mimetype=MIME_TYPE)
        self.gateway.call(
            channel,
            YouTubeOperation.THUMBNAILS_SET,
            lambda service: service.thumbnails().set(videoId=broadcast_id, media_body=media),
        )
        YouTubeEvent.THUMBNAIL_SET.of(channel, broadcast_id=broadcast_id).emit(LOGGER)

    def read_facts(self, channel: ChannelConfig, broadcast_id: str) -> BroadcastFacts:
        """Язык, аудитория и возраст видны только у видео; поток и чат — у самого эфира. Картинки не скачиваются."""
        video: YouTubeResponse = self.gateway.require_by_id(
            channel,
            YouTubeOperation.VIDEOS_LIST,
            broadcast_id,
            lambda service: service.videos().list(part=VIDEO_FACTS_PARTS, id=broadcast_id),
        )
        found: YouTubeResponse | None = self.gateway.read_by_id(
            channel,
            YouTubeOperation.BROADCASTS_LIST,
            broadcast_id,
            lambda service: service.liveBroadcasts().list(part=BROADCAST_PARTS, id=broadcast_id),
        )
        read: UpcomingBroadcast | PlatformNotice | None = None if found is None else BroadcastItem(found).upcoming(channel)
        broadcast: UpcomingBroadcast | None = read if isinstance(read, UpcomingBroadcast) else None
        stream_id: str | None = None if broadcast is None else broadcast.stream_id
        stream: StreamInfo | None = None if stream_id is None else self.get_stream(channel, stream_id)
        return VideoItem(video).facts(broadcast_id, broadcast, stream)

    def thumbnail_refusal(self, channel: ChannelConfig) -> PlatformError | None:
        """Отказ загрузки обложек, запомненный в этом запуске (канал, операция или весь проект); сети нет."""
        found: Refusal | None = self.gateway.refusals.find(channel.key, YouTubeOperation.THUMBNAILS_SET)
        return None if found is None else found.error

    def take_notices(self) -> tuple[PlatformNotice, ...]:
        """Отдать накопленные замечания и очистить накопитель."""
        taken: tuple[PlatformNotice, ...] = tuple(self.notices)
        self.notices.clear()
        return taken

    def _attach_new_stream(
        self, channel: ChannelConfig, broadcast_id: str, spec: BroadcastSpec, placeholder: PlaceholderMark | None
    ) -> CreatedBroadcast:
        """Поток с меткой → проверка ключа → привязка. Один поток на эфир; ключ не того вида — эфир не засчитан."""
        body: StreamBody = StreamBody(StreamDescription(channel, spec.marker, self.gateway.clock, placeholder))
        stream: StreamInfo = StreamItem(
            self.gateway.call(
                channel,
                YouTubeOperation.STREAMS_INSERT,
                lambda service: service.liveStreams().insert(part=STREAM_PARTS, body=body.insert),
            )
        ).info(allow_empty=False)
        masked: str = mask_stream_key(stream.stream_name)
        if not YOUTUBE_STREAM_KEY_PATTERN.fullmatch(stream.stream_name):
            rejected: LogEvent = YouTubeEvent.STREAM_KEY_REJECTED.of(channel, stream_id=stream.stream_id, stream_key=masked)
            rejected.emit(LOGGER, logging.ERROR)
            raise PlatformError(PlatformCode.UNEXPECTED_STREAM_KEY, masked)
        self.gateway.call(
            channel,
            YouTubeOperation.BROADCASTS_BIND,
            lambda service: service.liveBroadcasts().bind(part=BIND_PARTS, id=broadcast_id, streamId=stream.stream_id),
        )
        bound: LogEvent = YouTubeEvent.STREAM_BOUND.of(channel, broadcast_id=broadcast_id, stream_id=stream.stream_id)
        bound.extended(stream_key=masked).emit(LOGGER)
        url: str = YouTubeVideoId(broadcast_id).watch_url
        return CreatedBroadcast(broadcast_id, url, stream.stream_id, stream.ingestion_address, stream.stream_name)
