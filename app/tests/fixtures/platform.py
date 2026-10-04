"""Площадка в памяти и каналы для тестов контура B (CLAUDE.md §11): в поставку не идёт.

`FakePlatform` хранит эфиры по ключу канала (каждый канал — отдельный канал YouTube); тест называет канал ником или
ключом — `fake_key` приводит их к одному ключу. Вход в канал имитируется так же, как у YouTube: у канала из
`tokens_missing` токена нет — любое обращение без входа даёт loginRequired; вход — только
`describe_channel(allow_login=True)` после `drop_login`. Ответ входа — очередной из `login_answers` (иначе
`channel_info` или «тот же канал»), сбой входа — `fail_login`. Учётные данные нового входа «в памяти», пока
`keep_login` их не «запишет» (файл — если задан `paths`). Идентификаторы детерминированные (счётчик); ключи — 5 групп
по 4 символа [a-z0-9], как у YouTube; id эфира — 11 знаков, как у видео YouTube.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from app.config.channel import ChannelConfig, ChannelHandle, ConfiguredChannels, Platform, Privacy
from app.config.files import ChannelsFile
from app.core.clock import Clock
from app.core.youtube_video import YouTubeVideoId
from app.paths import LivecraftPaths
from app.platforms.broadcast import BroadcastFacts, CreatedBroadcast, UpcomingBroadcast
from app.platforms.channel_info import ChannelInfo
from app.platforms.channel_sync import ChannelSync
from app.platforms.error import PlatformCode, PlatformError
from app.platforms.limits import PlatformLimits
from app.platforms.notice import PlatformNotice, PlatformNoticeKind
from app.platforms.placeholder import PlaceholderMark
from app.platforms.spec import BroadcastSpec
from app.platforms.stream import StreamInfo
from app.platforms.video import AppliedVideo, VideoFixes, VideoSettings
from app.platforms.youtube_usage import YouTubeUsage
from app.slots.texts import SlotTexts
from app.tests.fixtures.clock import StoppedClock

FAKE_STREAM_URL: Final[str] = "rtmp://a.rtmp.youtube.com/live2"
FAKE_BROADCAST_ID_TEMPLATE: Final[str] = "fakebc{number:05d}"
FAKE_STREAM_ID_TEMPLATE: Final[str] = "fakestream{number:04d}"
FAKE_STREAM_KEY_TEMPLATE: Final[str] = "fake-{number:04d}-0000-0000-0000"
FAKE_CHANNEL_ID_TEMPLATE: Final[str] = "UCfake{key}"   # по ключу канала: у каналов с одним названием id разные
NOT_FOUND_CODE: Final[str] = "broadcastNotFound"
FAKE_TOKEN_TEXT: Final[str] = '{"token": "fake"}'
FAKE_AUTO_STOP: Final[bool] = True
FAKE_LATENCY_PREFERENCE: Final[str] = "normal"
# Посеянный эфир по умолчанию выглядит так, как его поставила бы программа с поставочными настройками.
SEED_PRIVACY: Final[str] = "public"
SEED_AUTO_START: Final[bool] = True
SEED_CATEGORY_ID: Final[str] = "22"
# Эфир «уже на канале» создан давно — раньше любой памяти программы в тестах.
SEED_PUBLISHED_UTC: Final[datetime] = datetime(2026, 1, 1, tzinfo=timezone.utc)
# Отказы загрузки обложки, после которых площадка до конца запуска обложки канала не грузит (как YouTube).
THUMBNAIL_CHANNEL_REFUSALS: Final[frozenset[str]] = frozenset({"uploadRateLimitExceeded", "forbidden"})
# Момент проверки каналов в тестах: отметка паспорта — «16-03-2027 12:00».
KYIV: Final[ZoneInfo] = ZoneInfo("Europe/Kyiv")
CHECKED_AT: Final[datetime] = datetime(2027, 3, 16, 12, 0, tzinfo=KYIV)
CHECK_CLOCK: Final[StoppedClock] = StoppedClock.at(CHECKED_AT)


def fake_key(name: str) -> str:
    """Ник («@yt_ua») или ключ («yt_ua») → ключ канала: тесты называют канал как удобнее."""
    return ChannelHandle.of(name).key


def channel_of(
    handle: str = "@yt_ua", account_name: str = "yt_ua", language: str = "uk", google_account: str = "owner@gmail.com"
) -> ChannelConfig:
    """Канал channels.json: ник, название, почта аккаунта, один язык (§14 решение 21), видимость — для всех."""
    return ChannelConfig(
        platform=Platform.YOUTUBE,
        account_name=account_name,
        handle=handle,
        google_account=google_account,
        languages=(language,),
        privacy=Privacy.PUBLIC,
    )


def two_channels() -> tuple[ChannelConfig, ChannelConfig]:
    """Два канала: yt_ua (uk) и yt_ru (ru)."""
    return channel_of(), channel_of("@yt_ru", "yt_ru", "ru")


def written_channels(paths: LivecraftPaths, *channels: ChannelConfig) -> ConfiguredChannels:
    """channels.json с этими каналами — тем же объектом файла, что у программы."""
    configured: ConfiguredChannels = ConfiguredChannels(channels)
    ChannelsFile.of(paths).save(configured)
    return configured


def token_path(paths: LivecraftPaths, handle: str) -> Path:
    """Файл токена канала с этим ником."""
    return paths.token_file(ChannelHandle.of(handle).token_file_stem)


def written_token(paths: LivecraftPaths, handle: str, content: str = "token") -> Path:
    path: Path = token_path(paths, handle)
    path.write_text(content, encoding="utf-8")
    return path


def channel_sync(platform: FakePlatform, paths: LivecraftPaths, clock: Clock = CHECK_CLOCK) -> ChannelSync:
    """Сверка каналов на подделке площадки; вход подделки пишет файл токена в корень `paths`."""
    platform.paths = paths
    return ChannelSync(platform, paths, clock)


def changed_channel(channel: ChannelConfig, **changes: object) -> ChannelConfig:
    """Тот же канал с другими значениями полей."""
    return dataclasses.replace(channel, **changes)


def channel_info(channel: ChannelConfig, **changes: object) -> ChannelInfo:
    """Что ответит YouTube на токен канала по умолчанию («тот же канал»), с другими значениями полей."""
    return dataclasses.replace(FakePlatform.default_channel_info(channel), **changes)


@dataclass(frozen=True)
class FakeCall:
    channel_id: str      # ключ канала
    broadcast_id: str
    marker: str
    preview: bytes | None


@dataclass
class FakeGateway:
    """Шлюз подделки — как у `YouTubePlatform.gateway`: только расход за запуск."""

    usage: YouTubeUsage = field(default_factory=YouTubeUsage)


class FakePlatform:
    def __init__(self) -> None:
        self.gateway: FakeGateway = FakeGateway()
        self._broadcasts: dict[str, dict[str, UpcomingBroadcast]] = {}
        self._streams: dict[str, dict[str, StreamInfo]] = {}
        self._counter: int = 0
        self.created: list[FakeCall] = []
        self.updated: list[FakeCall] = []
        self.list_calls: list[str] = []
        self.stream_calls: list[tuple[str, str]] = []
        self.fail_list: dict[str, PlatformError] = {}      # ключ канала → ошибка list_upcoming
        self.fail_create: dict[str, PlatformError] = {}    # slot_id → ошибка create_broadcast
        self.fail_describe: dict[str, PlatformError] = {}  # ключ канала → ошибка describe_channel
        self.fail_update: dict[str, PlatformError] = {}    # broadcast_id → ошибка update_broadcast
        self.fail_attach: dict[str, PlatformError] = {}    # broadcast_id → ошибка attach_stream
        self.fail_settings: dict[str, PlatformError] = {}  # broadcast_id → ошибка apply_video_settings
        self.fail_thumbnail: dict[str, PlatformError] = {}  # broadcast_id → ошибка set_thumbnail
        self.fail_facts: dict[str, PlatformError] = {}      # broadcast_id → ошибка read_facts
        self.fail_marker: dict[str, PlatformError] = {}     # stream_id → ошибка set_stream_marker
        self.made_for_kids: dict[str, bool] = {}           # broadcast_id → как стоит на площадке
        self.age_restricted: set[str] = set()              # broadcast_id с ytAgeRestricted
        self.settings_calls: list[str] = []      # обращения к ресурсу видео на чтение
        self.settings_writes: list[str] = []     # и на запись
        self.categories: dict[str, str] = {}     # broadcast_id → категория на площадке
        self.live_chat_ids: dict[str, str] = {}  # broadcast_id → id чата, если он заведён
        self.facts_calls: list[str] = []
        self.facts_override: dict[str, BroadcastFacts] = {}  # broadcast_id → готовый ответ read_facts
        self.thumbnails: list[FakeCall] = []
        self.attached: list[FakeCall] = []
        self.markers_set: list[FakeCall] = []                 # set_stream_marker: канал, поток, метка
        self._notices: list[PlatformNotice] = []             # замечания площадки: seed_undated_broadcast
        self.languages: dict[str, str] = {}                # broadcast_id → записанный язык
        self.channel_info: dict[str, ChannelInfo] = {}     # ключ канала → ответ describe_channel
        self.describe_calls: list[str] = []                # ключ канала каждого describe_channel
        self.describe_without_login: list[str] = []        # ключ канала каждого describe_channel(allow_login=False)
        self.tokens_missing: set[str] = set()              # ключи каналов без токена: без входа — отказ
        self.login_answers: dict[str, list[ChannelInfo]] = {}   # ключ канала → ответы входов по порядку
        self.fail_login: dict[str, PlatformError] = {}     # ключ канала → сбой входа (браузер закрыт)
        self.fail_keep: dict[str, PlatformError] = {}      # ключ канала → токен нового входа не записался
        self.logins: list[str] = []                        # ключ канала каждого входа в браузере
        self.kept_logins: list[str] = []                   # keep_login после нового входа
        self.dropped_logins: list[str] = []                # drop_login
        self.paths: LivecraftPaths | None = None           # задан — keep_login пишет файл токена
        self._fresh: set[str] = set()                      # после drop_login: следующий describe — вход
        self._new_logins: dict[str, ChannelInfo] = {}      # вход был, токен ещё не записан
        self.pictures: dict[str, str] = {}   # broadcast_id → отпечаток текущей картинки эфира
        self.thumbnail_refusals: dict[str, PlatformError] = {}   # ключ канала → запомненный отказ обложек
        self.thumbnail_attempts: list[str] = []   # broadcast_id каждого вызова set_thumbnail
        self.picture_lags: bool = False           # True — картинка после set_thumbnail ещё прежняя
        self.published_utc: datetime | None = SEED_PUBLISHED_UTC   # snippet.publishedAt эфиров из create_broadcast

    def seed_broadcast(
        self,
        channel_id: str,
        start_utc: datetime,
        title: str,
        description: str,
        marker: str | None = None,
        stream_key: str | None = None,
        *,
        privacy: str = SEED_PRIVACY,
        auto_start: bool = SEED_AUTO_START,
        auto_stop: bool = FAKE_AUTO_STOP,
        latency_preference: str = FAKE_LATENCY_PREFERENCE,
        category_id: str = SEED_CATEGORY_ID,
        picture: str | None = None,
        stream_description: str = "",
        published_utc: datetime | None = SEED_PUBLISHED_UTC,
    ) -> UpcomingBroadcast:
        """Эфир «уже на канале» channel_id (ник или ключ). marker — название потока; без marker — эфир без потока.

        Категория, как у YouTube, лежит только у ресурса видео: в списке эфиров её нет. picture — отпечаток картинки
        эфира (None — картинка не скачалась, обложка не сверяется); stream_description — описание потока, в нём может
        быть метка заглушки.
        """
        number: int = self._next_number()
        stream_id: str | None = None
        if marker is not None:
            stream_id = FAKE_STREAM_ID_TEMPLATE.format(number=number)
            self._streams.setdefault(fake_key(channel_id), {})[stream_id] = StreamInfo(
                stream_id=stream_id,
                title=marker,
                ingestion_address=FAKE_STREAM_URL,
                stream_name=stream_key or FAKE_STREAM_KEY_TEMPLATE.format(number=number),
                description=stream_description,
            )
        broadcast: UpcomingBroadcast = UpcomingBroadcast(
            broadcast_id=FAKE_BROADCAST_ID_TEMPLATE.format(number=number),
            start_utc=start_utc.astimezone(timezone.utc),
            title=title,
            description=description,
            stream_id=stream_id,
            privacy_status=privacy,
            auto_start=auto_start,
            auto_stop=auto_stop,
            latency_preference=latency_preference,
            published_utc=published_utc,
        )
        self._broadcasts.setdefault(fake_key(channel_id), {})[broadcast.broadcast_id] = broadcast
        self.categories[broadcast.broadcast_id] = category_id
        if picture is not None:
            self.pictures[broadcast.broadcast_id] = picture
        return broadcast

    def placeholder_of(self, channel_id: str) -> str:
        """Заглушка обложки канала в подделке (канал — ник или ключ): своя у каждого канала, как у YouTube."""
        return PlaceholderMark.of(fake_key(channel_id).encode("utf-8")).sha

    def seed_undated_broadcast(self, account_name: str, title: str, handle: str = "") -> PlatformNotice:
        """Эфир без времени старта на канале: площадка его не отдаёт, а замечание копит до take_notices."""
        notice: PlatformNotice = PlatformNotice(PlatformNoticeKind.UNDATED_BROADCAST, account_name, title, handle=handle)
        self._notices.append(notice)
        return notice

    def take_notices(self) -> tuple[PlatformNotice, ...]:
        taken: tuple[PlatformNotice, ...] = tuple(self._notices)
        self._notices.clear()
        return taken

    def remove_broadcast(self, channel_id: str, broadcast_id: str) -> None:
        """Владелец удалил эфир руками."""
        self._broadcasts.get(fake_key(channel_id), {}).pop(broadcast_id, None)

    def move_broadcast(self, channel_id: str, broadcast_id: str, start_utc: datetime) -> None:
        """Владелец перенёс эфир в Студии на другое время: поток и метка прежние."""
        broadcasts: dict[str, UpcomingBroadcast] = self._broadcasts[fake_key(channel_id)]
        broadcasts[broadcast_id] = dataclasses.replace(
            broadcasts[broadcast_id], start_utc=start_utc.astimezone(timezone.utc)
        )

    @property
    def limits(self) -> PlatformLimits:
        """Те же пределы, что у YouTube: тесты должны ловить настоящее поведение обрезки."""
        return PlatformLimits(
            title_max_chars=SlotTexts.TITLE_MAX_CHARS,
            description_max_chars=SlotTexts.DESCRIPTION_MAX_CHARS,
            auto_stop=FAKE_AUTO_STOP,
            latency_preference=FAKE_LATENCY_PREFERENCE,
        )

    def describe_channel(self, channel: ChannelConfig, *, allow_login: bool = True) -> ChannelInfo:
        """По умолчанию — ответ «канал тот же»: id по ключу, название и ник как в channels.json; тест может задать свой."""
        self.describe_calls.append(channel.key)
        if not allow_login:
            self.describe_without_login.append(channel.key)
        if self._needs_login(channel):
            if not allow_login:
                raise PlatformError(PlatformCode.LOGIN_REQUIRED, f"login required for {channel.handle}")
            return self._log_in(channel)
        if channel.key in self._new_logins:
            return self._new_logins[channel.key]
        if channel.key in self.fail_describe:
            raise self.fail_describe[channel.key]
        return self.channel_info.get(channel.key, self.default_channel_info(channel))

    def keep_login(self, channel: ChannelConfig) -> None:
        if channel.key in self.fail_keep:
            raise self.fail_keep[channel.key]
        if self._new_logins.pop(channel.key, None) is None:
            return
        self.tokens_missing.discard(channel.key)
        self.kept_logins.append(channel.key)
        if self.paths is not None:
            token_file = self.paths.token_file(ChannelHandle.of(channel.handle).token_file_stem)
            token_file.write_text(FAKE_TOKEN_TEXT, encoding="utf-8")

    def drop_login(self, channel: ChannelConfig) -> None:
        self._new_logins.pop(channel.key, None)
        self._fresh.add(channel.key)
        self.dropped_logins.append(channel.key)

    @classmethod
    def default_channel_info(cls, channel: ChannelConfig) -> ChannelInfo:
        return ChannelInfo(
            youtube_channel_id=FAKE_CHANNEL_ID_TEMPLATE.format(key=channel.key),
            title=channel.account_name,
            default_language=None,
            handle_raw=channel.handle,
        )

    def list_upcoming(self, channel: ChannelConfig) -> list[UpcomingBroadcast]:
        self.list_calls.append(channel.key)
        if self._needs_login(channel):
            raise PlatformError(PlatformCode.LOGIN_REQUIRED, f"login required for {channel.handle}")
        if channel.key in self.fail_list:
            raise self.fail_list[channel.key]
        broadcasts: list[UpcomingBroadcast] = [
            dataclasses.replace(broadcast, thumbnail_sha=self.pictures.get(broadcast.broadcast_id))
            for broadcast in self._broadcasts.get(channel.key, {}).values()
        ]
        return sorted(broadcasts, key=lambda broadcast: (broadcast.start_utc, broadcast.broadcast_id))

    def get_stream(self, channel: ChannelConfig, stream_id: str) -> StreamInfo | None:
        self.stream_calls.append((channel.key, stream_id))
        return self._streams.get(channel.key, {}).get(stream_id)

    def create_broadcast(self, channel: ChannelConfig, spec: BroadcastSpec) -> CreatedBroadcast:
        if spec.marker in self.fail_create:
            raise self.fail_create[spec.marker]
        number: int = self._next_number()
        # как у площадки: обложки ещё нет, картинка — заглушка канала, её метка — в описании потока
        placeholder: str = self.placeholder_of(channel.key)
        stream: StreamInfo = StreamInfo(
            stream_id=FAKE_STREAM_ID_TEMPLATE.format(number=number),
            title=spec.marker,
            ingestion_address=FAKE_STREAM_URL,
            stream_name=FAKE_STREAM_KEY_TEMPLATE.format(number=number),
            description=PlaceholderMark(placeholder).token,
        )
        broadcast: UpcomingBroadcast = UpcomingBroadcast(
            broadcast_id=FAKE_BROADCAST_ID_TEMPLATE.format(number=number),
            start_utc=spec.start_minute,
            title=spec.title,
            description=spec.description,
            stream_id=stream.stream_id,
            privacy_status=spec.privacy,
            auto_start=spec.auto_start,
            auto_stop=spec.auto_stop,
            latency_preference=spec.latency_preference,
            published_utc=self.published_utc,
        )
        self._streams.setdefault(channel.key, {})[stream.stream_id] = stream
        self._broadcasts.setdefault(channel.key, {})[broadcast.broadcast_id] = broadcast
        self.pictures[broadcast.broadcast_id] = placeholder
        self.created.append(FakeCall(channel.key, broadcast.broadcast_id, spec.marker, None))
        return self._created(broadcast.broadcast_id, stream)

    def update_broadcast(self, channel: ChannelConfig, broadcast_id: str, spec: BroadcastSpec) -> None:
        if broadcast_id in self.fail_update:
            raise self.fail_update[broadcast_id]
        current: UpcomingBroadcast = self._broadcast(channel, broadcast_id)
        self._broadcasts[channel.key][broadcast_id] = dataclasses.replace(
            current, title=spec.title, description=spec.description
        )
        self.updated.append(FakeCall(channel.key, broadcast_id, spec.marker, None))

    def attach_stream(self, channel: ChannelConfig, broadcast_id: str, spec: BroadcastSpec) -> CreatedBroadcast:
        if broadcast_id in self.fail_attach:
            raise self.fail_attach[broadcast_id]
        current: UpcomingBroadcast = self._broadcast(channel, broadcast_id)
        number: int = self._next_number()
        stream: StreamInfo = StreamInfo(
            stream_id=FAKE_STREAM_ID_TEMPLATE.format(number=number),
            title=spec.marker,
            ingestion_address=FAKE_STREAM_URL,
            stream_name=FAKE_STREAM_KEY_TEMPLATE.format(number=number),
        )
        self._streams.setdefault(channel.key, {})[stream.stream_id] = stream
        self._broadcasts[channel.key][broadcast_id] = dataclasses.replace(current, stream_id=stream.stream_id)
        self.attached.append(FakeCall(channel.key, broadcast_id, spec.marker, None))
        return self._created(broadcast_id, stream)

    def apply_video_settings(self, channel: ChannelConfig, broadcast_id: str, settings: VideoSettings) -> VideoFixes:
        self.settings_calls.append(broadcast_id)
        if broadcast_id in self.fail_settings:
            raise self.fail_settings[broadcast_id]
        current: UpcomingBroadcast | None = self._broadcasts.get(channel.key, {}).get(broadcast_id)
        fixes: VideoFixes = VideoFixes(
            language_set=self.languages.get(broadcast_id) != settings.language,
            category_set=self.categories.get(broadcast_id) != settings.category_id,
            audience_cleared=self.made_for_kids.get(broadcast_id, False),
            privacy_set=current is not None and current.privacy_status != settings.privacy,
        )
        if not fixes.any_fix:
            return fixes
        self.languages[broadcast_id] = settings.language
        self.categories[broadcast_id] = settings.category_id
        self.made_for_kids[broadcast_id] = False
        if current is not None:
            self._broadcasts[channel.key][broadcast_id] = dataclasses.replace(current, privacy_status=settings.privacy)
        self.settings_writes.append(broadcast_id)
        # как настоящая площадка: ответ записи говорит, что записано (VideoFixes.apply_to_facts)
        applied: AppliedVideo = AppliedVideo(
            language=settings.language,
            audio_language=settings.language,
            category_id=settings.category_id,
            privacy=settings.privacy,
            made_for_kids=False,
        )
        return dataclasses.replace(fixes, applied=applied)

    def set_stream_marker(self, channel: ChannelConfig, stream_id: str, marker: str) -> None:
        if stream_id in self.fail_marker:
            raise self.fail_marker[stream_id]
        stream: StreamInfo | None = self._streams.get(channel.key, {}).get(stream_id)
        if stream is None:
            raise PlatformError(NOT_FOUND_CODE, f"stream {stream_id} not found on {channel.account_name}")
        self._streams[channel.key][stream_id] = dataclasses.replace(stream, title=marker)
        self.markers_set.append(FakeCall(channel.key, stream_id, marker, None))

    def set_thumbnail(self, channel: ChannelConfig, broadcast_id: str, preview: bytes) -> None:
        self.thumbnail_attempts.append(broadcast_id)
        refused: PlatformError | None = self.thumbnail_refusals.get(channel.key)
        if refused is not None:
            raise refused
        if broadcast_id in self.fail_thumbnail:
            error: PlatformError = self.fail_thumbnail[broadcast_id]
            if error.code in THUMBNAIL_CHANNEL_REFUSALS:
                self.thumbnail_refusals[channel.key] = error
            raise error
        if not self.picture_lags:
            self.pictures[broadcast_id] = PlaceholderMark.of(preview).sha
        self.thumbnails.append(FakeCall(channel.key, broadcast_id, "", preview))

    def thumbnail_refusal(self, channel: ChannelConfig) -> PlatformError | None:
        return self.thumbnail_refusals.get(channel.key)

    def read_facts(self, channel: ChannelConfig, broadcast_id: str) -> BroadcastFacts:
        self.facts_calls.append(broadcast_id)
        if broadcast_id in self.fail_facts:
            raise self.fail_facts[broadcast_id]
        override: BroadcastFacts | None = self.facts_override.get(broadcast_id)
        if override is not None:
            return override
        broadcast: UpcomingBroadcast = self._broadcast(channel, broadcast_id)
        stream: StreamInfo | None = (
            self._streams.get(channel.key, {}).get(broadcast.stream_id) if broadcast.stream_id else None
        )
        return BroadcastFacts(
            broadcast_id=broadcast_id,
            title=broadcast.title,
            description=broadcast.description,
            start_utc=broadcast.start_utc,
            privacy_status=broadcast.privacy_status,
            made_for_kids=self.made_for_kids.get(broadcast_id, False),
            age_restricted=broadcast_id in self.age_restricted,
            default_language=self.languages.get(broadcast_id),
            default_audio_language=self.languages.get(broadcast_id),
            category_id=self.categories.get(broadcast_id, broadcast.category_id),
            bound_stream_id=broadcast.stream_id,
            stream_marker=stream.title if stream is not None else None,
            live_chat_id=self.live_chat_ids.get(broadcast_id),
            auto_start=broadcast.auto_start,
            auto_stop=broadcast.auto_stop,
            latency_preference=broadcast.latency_preference,
        )

    def _needs_login(self, channel: ChannelConfig) -> bool:
        if channel.key in self._new_logins:
            return False
        return channel.key in self._fresh or channel.key in self.tokens_missing

    def _log_in(self, channel: ChannelConfig) -> ChannelInfo:
        """Вход в «браузере»: ответ — очередной из login_answers, иначе как у describe без входа."""
        self._fresh.discard(channel.key)
        self.logins.append(channel.key)
        if channel.key in self.fail_login:
            raise self.fail_login[channel.key]
        answers: list[ChannelInfo] = self.login_answers.get(channel.key, [])
        info: ChannelInfo = (
            answers.pop(0) if answers else self.channel_info.get(channel.key, self.default_channel_info(channel))
        )
        self._new_logins[channel.key] = info
        return info

    def _broadcast(self, channel: ChannelConfig, broadcast_id: str) -> UpcomingBroadcast:
        current: UpcomingBroadcast | None = self._broadcasts.get(channel.key, {}).get(broadcast_id)
        if current is None:
            raise PlatformError(NOT_FOUND_CODE, f"broadcast {broadcast_id} not found on {channel.account_name}")
        return current

    def _created(self, broadcast_id: str, stream: StreamInfo) -> CreatedBroadcast:
        return CreatedBroadcast(
            broadcast_id=broadcast_id,
            broadcast_url=YouTubeVideoId(broadcast_id).watch_url,
            stream_id=stream.stream_id,
            stream_url=stream.ingestion_address,
            stream_key=stream.stream_name,
        )

    def _next_number(self) -> int:
        self._counter += 1
        return self._counter
