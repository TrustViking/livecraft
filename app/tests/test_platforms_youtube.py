from __future__ import annotations

import http.client
import json
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import requests
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from app.config.channel import ChannelConfig, Platform, Privacy
from app.core.retry import RetryPolicy
from app.google.auth import YOUTUBE_SCOPE, AuthError, AuthErrorReason, GoogleLogin
from app.observability.log_event import LogArea
from app.paths import DataDir, LivecraftPaths
from app.platforms.broadcast import BroadcastFacts, CreatedBroadcast, UpcomingBroadcast
from app.platforms.channel_info import ChannelInfo, ChannelLink
from app.platforms.error import PlatformCode, PlatformError
from app.platforms.notice import PlatformNotice, PlatformNoticeKind
from app.platforms.placeholder import PlaceholderMark
from app.platforms.spec import BroadcastSpec
from app.platforms.stream import StreamInfo
from app.platforms.video import VideoFixes, VideoSettings
from app.platforms.youtube import VIDEO_FACTS_PARTS, YOUTUBE_STREAM_KEY_PATTERN, YouTubePlatform
from app.platforms.youtube_event import YouTubeEvent
from app.platforms.youtube_failure import YouTubeFailure
from app.platforms.youtube_gateway import YouTubeGateway
from app.platforms.youtube_logins import ChannelLogins
from app.platforms.youtube_operation import QUOTA_UNITS, ErrorBehavior, YouTubeOperation
from app.platforms.youtube_picture import PictureReader
from app.platforms.youtube_usage import OperationUsage
from app.tests.fixtures.clock import RunningClock
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
START: datetime = datetime(2027, 3, 16, 12, 0, tzinfo=KYIV)


def channel(account_name: str = "Канал UA", handle: str = "@KanalUA", google_account: str = "owner@gmail.com") -> ChannelConfig:
    return ChannelConfig(
        platform=Platform.YOUTUBE,
        account_name=account_name,
        handle=handle,
        google_account=google_account,
        languages=("uk",),
        privacy=Privacy.PUBLIC,
    )


CHANNEL: ChannelConfig = channel()
OTHER_CHANNEL: ChannelConfig = channel("Канал RU", "@KanalRU", "ru@gmail.com")
GOOD_KEY: str = "abcd-1234-efgh-5678-ijkl"
RNG_SEED: int = 7
POLICY: RetryPolicy = RetryPolicy()
MARKER: str = "17-03-2027_1900_uk"
DESCRIPTION_HEAD: str = "Ключ Livecraft: канал «Канал UA» @KanalUA, эфир 17.03.2027 19:00, язык uk"
SETTINGS: VideoSettings = VideoSettings(language="uk", category_id="22", privacy="unlisted")


def expected_delays(count: int) -> list[float]:
    """Паузы повторов 1..count по RetryPolicy с тем же фиксированным rng, что у площадки в тестах."""
    rng: random.Random = random.Random(RNG_SEED)
    return [POLICY.delay_sec(number, rng) for number in range(1, count + 1)]


class FakeRequest:
    def __init__(self, response: Any) -> None:
        self.response: Any = response

    def execute(self) -> Any:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeResource:
    """Ресурс googleapiclient: `.list(**kwargs)`, `.insert`, `.bind`, `.update`, `.set` → объект с `.execute()`."""

    def __init__(self, service: FakeService, name: str, responses: list[Any]) -> None:
        self.service: FakeService = service
        self.name: str = name
        self.responses: list[Any] = responses

    def __getattr__(self, method: str) -> Callable[..., FakeRequest]:
        if method.startswith("_"):
            raise AttributeError(method)
        return lambda **kwargs: self.call(method, **kwargs)

    def call(self, method: str, **kwargs: Any) -> FakeRequest:
        self.service.calls.append({"resource": self.name, "method": method, "at": self.service.clock.seconds, **kwargs})
        if not self.responses:
            raise AssertionError(f"неожиданный вызов {self.name}.{method}")
        return FakeRequest(self.responses.pop(0))


class FakeService:
    """Клиент YouTube API с очередью ответов на ресурс; каждый вызов запоминается с моментом по часам теста."""

    def __init__(self, clock: RunningClock, **responses: list[Any]) -> None:
        self.clock: RunningClock = clock
        self.calls: list[dict[str, Any]] = []
        self.resources: dict[str, FakeResource] = {
            name: FakeResource(self, name, list(items)) for name, items in responses.items()
        }

    def resource(self, name: str) -> FakeResource:
        return self.resources.setdefault(name, FakeResource(self, name, []))

    def channels(self) -> FakeResource:
        return self.resource("channels")

    def liveBroadcasts(self) -> FakeResource:  # noqa: N802 — имя как у googleapiclient
        return self.resource("liveBroadcasts")

    def liveStreams(self) -> FakeResource:  # noqa: N802 — имя как у googleapiclient
        return self.resource("liveStreams")

    def videos(self) -> FakeResource:
        return self.resource("videos")

    def thumbnails(self) -> FakeResource:
        return self.resource("thumbnails")


class FakeCredentials:
    def to_json(self) -> str:
        return '{"token": "new"}'


@dataclass
class FakeLogin:
    """Вход канала без браузера и без сети — те же `credentials`, `save` и `token_file`, что у GoogleLogin."""

    logins: FakeLogins
    token_file: Path

    def credentials(self, allow_login: bool = True, force_reauth: bool = False, on_login: Any = None) -> object:
        self.logins.calls.append((self.token_file.name, allow_login, force_reauth))
        if self.logins.error is not None:
            raise self.logins.error
        if not (self.logins.needs_browser or force_reauth):
            return FakeCredentials()
        if not allow_login:
            raise AuthError(AuthErrorReason.LOGIN_REQUIRED, self.token_file.name)
        on_login()
        return FakeCredentials()

    def save(self, credentials: FakeCredentials) -> None:
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")


@dataclass
class FakeLogins:
    """Входы каналов: токен — файл «<ник>.token.json» в `root`; `needs_browser` — токена нет, нужен браузер."""

    root: Path
    needs_browser: bool = False
    error: AuthError | None = None
    calls: list[tuple[str, bool, bool]] = field(default_factory=list)

    def __call__(self, channel: ChannelConfig) -> FakeLogin:
        return FakeLogin(self, self.root / f"{channel.handle}.token.json")


def build_platform(
    service: FakeService, logins: FakeLogins, pause: float = 0, session: Any = None
) -> YouTubePlatform:
    """Площадка на поддельных клиенте, входе и картинках; сон — часы теста, rng — фиксированный."""
    gateway: YouTubeGateway = YouTubeGateway(
        logins=ChannelLogins(login=logins, client=lambda credentials: service),
        clock=service.clock,
        pause_sec=pause,
        sleep=service.clock.sleep,
        rng=random.Random(RNG_SEED),
    )
    return YouTubePlatform(gateway=gateway, pictures=PictureReader(session=session or FakeSession({})))


@pytest.fixture
def clock() -> RunningClock:
    return RunningClock.at(START)


@pytest.fixture
def logins(tmp_path: Path) -> FakeLogins:
    return FakeLogins(tmp_path)


def platform_of(clock: RunningClock, logins: FakeLogins, **responses: list[Any]) -> tuple[YouTubePlatform, FakeService]:
    service: FakeService = FakeService(clock, **responses)
    return build_platform(service, logins), service


def http_error(status: int, reason: str, message: str) -> HttpError:
    content: bytes = json.dumps(
        {"error": {"code": status, "message": message, "errors": [{"reason": reason, "message": message}]}}
    ).encode("utf-8")
    return HttpError(resp=type("Resp", (), {"status": status, "reason": message})(), content=content)


def broadcast_item(broadcast_id: str, start: str, stream_id: str | None = "S1") -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": broadcast_id,
        "snippet": {"title": f"Эфир {broadcast_id}", "description": "Описание", "scheduledStartTime": start},
        "contentDetails": {},
    }
    if stream_id is not None:
        item["contentDetails"]["boundStreamId"] = stream_id
    return item


def spec(**changes: Any) -> BroadcastSpec:
    values: dict[str, Any] = {
        "start_minute": datetime(2027, 3, 17, 17, 0, tzinfo=timezone.utc),
        "marker": MARKER,
        "title": "Эфир",
        "description": "Описание",
        "privacy": "public",
        "category_id": "22",
        "auto_start": True,
        "auto_stop": True,
        "latency_preference": "normal",
    }
    return BroadcastSpec(**{**values, **changes})


def stream_response(key: str = GOOD_KEY) -> dict[str, Any]:
    return {
        "id": "S1",
        "cdn": {"ingestionInfo": {"ingestionAddress": "rtmp://a.rtmp.youtube.com/live2", "streamName": key}},
    }


def stream_list(stream_id: str = "S1") -> dict[str, Any]:
    return {"items": [{"id": stream_id, "snippet": {"title": "m"}, "cdn": {"ingestionInfo": {}}}]}


def empties() -> list[Any]:
    return [{"items": []} for _ in range(POLICY.max_attempts)]


# --- канал


def test_channel_info_says_what_youtube_sent() -> None:
    """Ник — в написании channels.json, сравнение — по ключу; название — NFC без краёв; ссылка — по id."""
    info: ChannelInfo = ChannelInfo("UC1", " Канал UA ", None, handle_raw=" KanalUA ")
    assert info.handle is not None and (info.handle.text, info.handle_key, info.handle_text) == (
        "@KanalUA", "kanalua", "@KanalUA"
    )
    assert info.account_name == "Канал UA"
    assert info.channel_url == "https://www.youtube.com/channel/UC1"
    assert ChannelLink.HANDLE.url(handle="@KanalUA") == "https://www.youtube.com/@KanalUA"


def test_channel_without_handle_says_so() -> None:
    info: ChannelInfo = ChannelInfo("UC1", "Канал UA", None)
    assert (info.handle, info.handle_key, info.handle_text) == (None, None, msg.AUTH_YOUTUBE_HANDLE_MISSING)


def test_login_refusal_carries_the_reason_of_the_login() -> None:
    """Причина отказа входа — полем: по ней решают таймаут, человек читает её текст, лог — подробность."""
    timeout: AuthError = AuthError(AuthErrorReason.LOGIN_TIMEOUT, "no answer")
    error: PlatformError = PlatformError.of_login(timeout, PlatformCode.AUTH_FAILED)
    assert (error.code, error.login_reason) == ("authFailed", AuthErrorReason.LOGIN_TIMEOUT)
    assert error.message == "login_timeout: no answer"
    assert str(error) == error.human == AuthErrorReason.LOGIN_TIMEOUT.human
    assert PlatformError("authFailed", "x").login_reason is None


def test_describe_channel_reads_id_title_and_language(clock: RunningClock, logins: FakeLogins) -> None:
    item: dict[str, Any] = {
        "id": "UC123",
        "snippet": {"title": "Мой канал", "defaultLanguage": "ru"},
        "brandingSettings": {"channel": {"defaultLanguage": "uk"}},
    }
    platform, service = platform_of(clock, logins, channels=[{"items": [item]}])
    info: ChannelInfo = platform.describe_channel(CHANNEL)
    assert info == ChannelInfo(youtube_channel_id="UC123", title="Мой канал", default_language="uk")
    assert service.calls[0]["mine"] is True
    assert platform.describe_channel(CHANNEL) is info            # за запуск канал спрашивается один раз
    assert len(service.calls) == 1


def test_describe_channel_falls_back_to_snippet_language(clock: RunningClock, logins: FakeLogins) -> None:
    item: dict[str, Any] = {"id": "UC1", "snippet": {"title": "X", "defaultLanguage": "ru"}}
    platform, _ = platform_of(clock, logins, channels=[{"items": [item]}])
    assert platform.describe_channel(CHANNEL).default_language == "ru"


def test_describe_channel_without_language_gives_none(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(clock, logins, channels=[{"items": [{"id": "UC1", "snippet": {"title": "X"}}]}])
    assert platform.describe_channel(CHANNEL).default_language is None


def test_empty_channels_list_is_channel_not_found_without_retry(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, channels=[{"items": []}])
    with pytest.raises(PlatformError) as raised:
        platform.describe_channel(CHANNEL)
    assert raised.value.code == "channelNotFound"
    assert len(service.calls) == 1 and clock.sleeps == []


# --- список эфиров


def test_list_upcoming_walks_all_pages(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(
        clock,
        logins,
        liveBroadcasts=[
            {"items": [broadcast_item("B1", "2027-03-17T17:00:00Z")], "nextPageToken": "page2"},
            {"items": [broadcast_item("B2", "2027-03-18T17:00:00Z")]},
        ],
    )
    broadcasts: list[UpcomingBroadcast] = platform.list_upcoming(CHANNEL)
    assert [item.broadcast_id for item in broadcasts] == ["B1", "B2"]
    assert broadcasts[0].start_utc == datetime(2027, 3, 17, 17, 0, tzinfo=timezone.utc)
    assert [call.get("pageToken") for call in service.calls] == [None, "page2"]
    # фильтры id / mine / broadcastStatus взаимоисключающие: mine отправлять нельзя (400)
    assert all("mine" not in call for call in service.calls)
    assert all(call["broadcastStatus"] == "upcoming" for call in service.calls)


def test_empty_upcoming_list_is_normal_and_not_retried(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"items": []}])
    assert platform.list_upcoming(CHANNEL) == []
    assert len(service.calls) == 1 and clock.sleeps == []


def test_broadcast_without_bound_stream_has_none(clock: RunningClock, logins: FakeLogins) -> None:
    item: dict[str, Any] = broadcast_item("B1", "2027-03-17T17:00:00Z", stream_id=None)
    platform, _ = platform_of(clock, logins, liveBroadcasts=[{"items": [item]}])
    [broadcast] = platform.list_upcoming(CHANNEL)
    assert broadcast.stream_id is None
    assert broadcast.description == "Описание"


def test_broadcast_with_offset_start_is_converted_to_utc(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(
        clock, logins, liveBroadcasts=[{"items": [broadcast_item("B1", "2027-03-17T19:00:00+02:00")]}]
    )
    [broadcast] = platform.list_upcoming(CHANNEL)
    assert broadcast.start_utc == datetime(2027, 3, 17, 17, 0, tzinfo=timezone.utc)


def test_undated_broadcast_is_a_notice_taken_once(clock: RunningClock, logins: FakeLogins) -> None:
    """Эфир без scheduledStartTime выпадает из списка и даёт одно замечание."""
    undated: dict[str, Any] = broadcast_item("B1", "2027-03-17T17:00:00Z")
    undated["snippet"].pop("scheduledStartTime")
    platform, _ = platform_of(
        clock, logins, liveBroadcasts=[{"items": [undated, broadcast_item("B2", "2027-03-17T17:00:00Z")]}]
    )
    assert [broadcast.broadcast_id for broadcast in platform.list_upcoming(CHANNEL)] == ["B2"]
    assert platform.take_notices() == (
        PlatformNotice(PlatformNoticeKind.UNDATED_BROADCAST, account_name="Канал UA", title="Эфир B1", handle="@KanalUA"),
    )
    assert platform.take_notices() == ()                 # накопитель очищен


def test_undated_broadcast_logs_what_the_platform_sent(clock: RunningClock, logins: FakeLogins) -> None:
    """Флага isDefaultBroadcast нет — в строке видно, что именно прислала площадка; строка — только INFO."""
    item: dict[str, Any] = broadcast_item("B1", "2027-03-17T17:00:00Z")
    item["snippet"].pop("scheduledStartTime")
    item["snippet"]["publishedAt"] = "2026-05-01T10:00:00Z"
    item["status"] = {"lifeCycleStatus": "ready", "privacyStatus": "unlisted"}
    item["contentDetails"] = {"boundStreamId": "S9"}
    platform, _ = platform_of(clock, logins, liveBroadcasts=[{"items": [item]}])
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        assert platform.list_upcoming(CHANNEL) == []
    [record] = [record for record in capture.records if record.getMessage().startswith("broadcast_without_start")]
    assert record.levelno == logging.INFO and '"Эфир B1"' in record.getMessage()
    assert record.getMessage().endswith(
        "is_default=- lifecycle=ready privacy=unlisted bound_stream_id=S9 published_at=2026-05-01T10:00:00Z"
    )


@pytest.mark.parametrize(("is_default", "shown"), [(True, "yes"), (False, "no")])
def test_undated_broadcast_is_a_notice_whatever_the_default_flag(
    clock: RunningClock, logins: FakeLogins, is_default: bool, shown: str
) -> None:
    """Признак служебного эфира — нет времени старта; isDefaultBroadcast только пишется в лог как факт
    (planers, выгрузки 18-09-2026: у служебных эфиров флаг false)."""
    undated: dict[str, Any] = broadcast_item("B1", "2027-03-17T17:00:00Z")
    undated["snippet"].pop("scheduledStartTime")
    undated["snippet"]["isDefaultBroadcast"] = is_default
    platform, _ = platform_of(clock, logins, liveBroadcasts=[{"items": [undated]}])
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        assert platform.list_upcoming(CHANNEL) == []
    assert len(platform.take_notices()) == 1
    [line] = [line for line in capture.messages() if line.startswith("broadcast_without_start")]
    assert f"is_default={shown} lifecycle=- privacy=- bound_stream_id=S1 published_at=-" in line


def test_list_upcoming_reads_privacy_content_details_chat_and_published_at(
    clock: RunningClock, logins: FakeLogins
) -> None:
    """Части status и contentDetails уже запрашиваются: новых вызовов API нет."""
    item: dict[str, Any] = broadcast_item("B1", "2027-03-17T17:00:00Z")
    item["status"] = {"privacyStatus": "private"}
    item["contentDetails"].update({"enableAutoStart": False, "enableAutoStop": True, "latencyPreference": "low"})
    item["snippet"].update({"liveChatId": "CHAT1", "publishedAt": "2026-09-16T12:34:56Z"})
    bare: dict[str, Any] = broadcast_item("B2", "2027-03-18T17:00:00Z")
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"items": [item, bare]}])
    first, second = platform.list_upcoming(CHANNEL)
    assert (first.privacy_status, first.auto_start, first.auto_stop, first.latency_preference) == (
        "private", False, True, "low"
    )
    assert first.live_chat_id == "CHAT1"
    assert first.published_utc == datetime(2026, 9, 16, 12, 34, 56, tzinfo=timezone.utc)
    assert second.published_utc is None
    assert len(service.calls) == 1 and service.calls[0]["part"] == "snippet,contentDetails,status"


def test_items_that_are_not_a_list_are_a_bad_response(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(clock, logins, liveBroadcasts=[{"items": "не список"}])
    with pytest.raises(PlatformError) as raised:
        platform.list_upcoming(CHANNEL)
    assert raised.value.code == "badResponse"


# --- поток


def test_get_stream_reads_marker_key_and_description(clock: RunningClock, logins: FakeLogins) -> None:
    item: dict[str, Any] = {
        "id": "S1",
        "snippet": {"title": MARKER, "description": "Ключ; заглушка обложки thumb0=044eb0835668"},
        "cdn": {"ingestionInfo": {"ingestionAddress": "rtmp://a.rtmp.youtube.com/live2", "streamName": GOOD_KEY}},
    }
    platform, _ = platform_of(clock, logins, liveStreams=[{"items": [item]}])
    stream: StreamInfo | None = platform.get_stream(CHANNEL, "S1")
    assert stream == StreamInfo(
        stream_id="S1",
        title=MARKER,
        ingestion_address="rtmp://a.rtmp.youtube.com/live2",
        stream_name=GOOD_KEY,
        description="Ключ; заглушка обложки thumb0=044eb0835668",
    )
    assert PlaceholderMark.found_in(stream.description) == PlaceholderMark("044eb0835668")


def test_get_stream_without_items_retries_then_gives_none(clock: RunningClock, logins: FakeLogins) -> None:
    """Пустой ответ по id повторяется; пусто на всех попытках — None."""
    platform, service = platform_of(clock, logins, liveStreams=empties())
    assert platform.get_stream(CHANNEL, "S1") is None
    assert len(service.calls) == POLICY.max_attempts
    assert clock.sleeps == expected_delays(POLICY.max_retries)


def test_unexpected_key_format_warns_with_a_mask_but_keeps_stream(clock: RunningClock, logins: FakeLogins) -> None:
    item: dict[str, Any] = {
        "id": "S1",
        "snippet": {"title": "маркер"},
        "cdn": {"ingestionInfo": {"ingestionAddress": "rtmp://x", "streamName": "STRANGE-KEY"}},
    }
    platform, _ = platform_of(clock, logins, liveStreams=[{"items": [item]}])
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        stream: StreamInfo | None = platform.get_stream(CHANNEL, "S1")
    assert stream is not None and stream.stream_name == "STRANGE-KEY"
    [line] = capture.messages(logging.WARNING)
    assert line.startswith("stream_key_unexpected_format") and "stream_key=****--KEY" in line
    assert "STRANGE" not in "".join(capture.messages())          # ключ в логах только замаскированным


def test_stream_key_pattern_matches_youtube_shapes() -> None:
    """5 и 4 группы — ключ YouTube; 3 группы, заглавные и без дефисов — нет."""
    assert YOUTUBE_STREAM_KEY_PATTERN.fullmatch(GOOD_KEY)
    assert YOUTUBE_STREAM_KEY_PATTERN.fullmatch("abcd-1234-efgh-5678")
    assert not YOUTUBE_STREAM_KEY_PATTERN.fullmatch("abcd-1234-efgh")
    assert not YOUTUBE_STREAM_KEY_PATTERN.fullmatch("ABCD-1234-efgh-5678")
    assert not YOUTUBE_STREAM_KEY_PATTERN.fullmatch("abcd1234efgh5678")


# --- отказы, повторы, пауза


@pytest.mark.parametrize(
    ("status", "reason"),
    [(403, "liveStreamingNotEnabled"), (403, "insufficientPermissions"), (403, "quotaExceeded"), (404, "notFound")],
)
def test_http_error_becomes_platform_error_with_google_reason(
    clock: RunningClock, logins: FakeLogins, status: int, reason: str
) -> None:
    platform, _ = platform_of(clock, logins, liveBroadcasts=[http_error(status, reason, "нельзя")])
    with pytest.raises(PlatformError) as raised:
        platform.list_upcoming(CHANNEL)
    assert raised.value.code == reason
    assert str(status) in raised.value.message


def test_platform_error_speaks_to_a_person_and_logs_the_detail() -> None:
    """Контракт ошибок: str(error) — текст для человека; английская подробность — только в строке лога."""
    known: PlatformError = PlatformError("quotaExceeded", "HTTP 403: quota")
    assert str(known) == known.human == msg.YOUTUBE_REASON_TEXT["quotaExceeded"]
    assert known.log_line == 'platform_failed code=quotaExceeded message="HTTP 403: quota"'
    own: PlatformError = PlatformError(PlatformCode.NOT_LISTED, "videos.list is empty")
    assert own.code == "notListed" and str(own) == msg.YOUTUBE_REASON_TEXT["notListed"]
    assert str(PlatformError("somethingNew", "x")) == msg.YOUTUBE_REASON_UNKNOWN.format(code="somethingNew")


def test_every_own_code_has_a_text_for_a_person() -> None:
    assert all(code.value in msg.YOUTUBE_REASON_TEXT for code in PlatformCode)


def test_transport_failure_is_retried_then_refused(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(
        clock, logins, liveBroadcasts=[ConnectionError("нет сети")] * POLICY.max_attempts
    )
    with pytest.raises(PlatformError) as raised:
        platform.list_upcoming(CHANNEL)
    assert raised.value.code == "transportFailed"
    assert len(service.calls) == POLICY.max_attempts == 5
    assert clock.sleeps == expected_delays(4)


def test_server_error_is_retried_by_the_policy_then_refused(clock: RunningClock, logins: FakeLogins) -> None:
    """503: первое обращение и 4 повтора с паузами RetryPolicy (2–3, 4–5, 8–9, 16–17 с), затем отказ."""
    platform, service = platform_of(clock, logins, liveBroadcasts=[http_error(503, "backendError", "x")] * 5)
    with pytest.raises(PlatformError) as raised:
        platform.list_upcoming(CHANNEL)
    assert raised.value.code == "transportFailed"
    assert len(service.calls) == 5
    assert [int(delay) for delay in clock.sleeps] == [2, 4, 8, 16]


def test_pause_keeps_requests_apart(clock: RunningClock, logins: FakeLogins) -> None:
    service: FakeService = FakeService(clock, liveStreams=[stream_list(), stream_list(), stream_list()])
    platform: YouTubePlatform = build_platform(service, logins, pause=2)
    for _ in range(3):
        platform.get_stream(CHANNEL, "S1")
    moments: list[float] = [call["at"] for call in service.calls]
    assert all(later - earlier >= 2 for earlier, later in zip(moments, moments[1:]))
    assert clock.sleeps == [2, 2]                       # перед первым обращением ждать нечего


def test_retry_pause_counts_toward_the_request_pause(clock: RunningClock, logins: FakeLogins) -> None:
    """Паузы повторов (от 2 с) уже покрывают паузу между обращениями — лишнего сна нет."""
    service: FakeService = FakeService(clock, liveBroadcasts=[http_error(503, "backendError", "x")] * 3 + [{"items": []}])
    platform: YouTubePlatform = build_platform(service, logins, pause=2)
    assert platform.list_upcoming(CHANNEL) == []
    assert clock.sleeps == expected_delays(3)
    moments: list[float] = [call["at"] for call in service.calls]
    assert all(later - earlier >= 2 for earlier, later in zip(moments, moments[1:]))


def test_zero_pause_never_sleeps(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(clock, logins, liveStreams=[stream_list(), stream_list()])
    platform.get_stream(CHANNEL, "S1")
    platform.get_stream(CHANNEL, "S1")
    assert clock.sleeps == []


def test_fractional_pause_sleeps_the_rest_of_half_a_second(clock: RunningClock, logins: FakeLogins) -> None:
    service: FakeService = FakeService(clock, liveBroadcasts=[{"items": []}, {"items": []}])
    platform: YouTubePlatform = build_platform(service, logins, pause=0.5)
    platform.list_upcoming(CHANNEL)
    clock.advance(0.2)                 # между вызовами прошло 0.2 с — остаток паузы 0.3 с
    platform.list_upcoming(CHANNEL)
    assert clock.sleeps == [pytest.approx(0.3)]
    assert service.calls[1]["at"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("operation", "status", "reason", "behavior"),
    [
        (YouTubeOperation.THUMBNAILS_SET, 429, "uploadRateLimitExceeded", ErrorBehavior.OPERATION),
        (YouTubeOperation.THUMBNAILS_SET, 403, "forbidden", ErrorBehavior.OPERATION),
        (YouTubeOperation.BROADCASTS_LIST, 403, "forbidden", ErrorBehavior.CALL),
        (YouTubeOperation.BROADCASTS_LIST, 403, "quotaExceeded", ErrorBehavior.PROJECT),
        (YouTubeOperation.BROADCASTS_LIST, 401, "authError", ErrorBehavior.CHANNEL),
        (YouTubeOperation.CHANNELS_LIST, None, "authFailed", ErrorBehavior.CHANNEL),
        (YouTubeOperation.CHANNELS_LIST, None, "loginRequired", ErrorBehavior.CALL),
        (YouTubeOperation.BROADCASTS_INSERT, 403, "liveStreamingNotEnabled", ErrorBehavior.OPERATION),
        (YouTubeOperation.BROADCASTS_INSERT, 503, "backendError", ErrorBehavior.CALL),
        (YouTubeOperation.STREAMS_INSERT, None, "transportFailed", ErrorBehavior.CALL),
        (YouTubeOperation.BROADCASTS_INSERT, 403, "rateLimitExceeded", ErrorBehavior.RETRY),
        (YouTubeOperation.BROADCASTS_LIST, 500, "backendError", ErrorBehavior.RETRY),
        (YouTubeOperation.BROADCASTS_LIST, 429, "somethingNew", ErrorBehavior.RETRY),
        (YouTubeOperation.BROADCASTS_LIST, 502, "somethingNew", ErrorBehavior.RETRY),
        (YouTubeOperation.BROADCASTS_LIST, 403, "somethingNew", ErrorBehavior.CALL),
        (YouTubeOperation.VIDEOS_LIST, 404, "videoNotFound", ErrorBehavior.CALL),
        (YouTubeOperation.VIDEOS_LIST, None, "notListed", ErrorBehavior.RETRY),
        (YouTubeOperation.CHANNELS_LIST, None, "channelNotFound", ErrorBehavior.CALL),
    ],
)
def test_error_behavior_table(
    operation: YouTubeOperation, status: int | None, reason: str, behavior: ErrorBehavior
) -> None:
    """Порядок решения: пара «операция, причина» → создающий вызов с неизвестным исходом → таблица → 5xx и 429."""
    assert YouTubeFailure(operation, PlatformError(reason, "x"), status).behavior is behavior


def test_upload_limit_stops_thumbnails_of_that_channel_only(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(
        clock,
        logins,
        thumbnails=[http_error(429, "uploadRateLimitExceeded", "лимит"), {}],
        liveBroadcasts=[{"items": []}],
    )
    with pytest.raises(PlatformError) as first:
        platform.set_thumbnail(CHANNEL, "B1", b"jpg")
    assert first.value.code == "uploadRateLimitExceeded"
    assert len(service.calls) == 1 and clock.sleeps == []      # ни повторов, ни пауз повтора
    with pytest.raises(PlatformError) as second:
        platform.set_thumbnail(CHANNEL, "B2", b"jpg")          # без запроса
    assert second.value.code == "uploadRateLimitExceeded"
    assert len(service.calls) == 1
    platform.set_thumbnail(OTHER_CHANNEL, "B3", b"jpg")        # другой канал — с запросом
    platform.list_upcoming(CHANNEL)                            # другая операция того же канала — с запросом
    assert [(call["resource"], call["method"]) for call in service.calls] == [
        ("thumbnails", "set"),
        ("thumbnails", "set"),
        ("liveBroadcasts", "list"),
    ]


def test_forbidden_thumbnail_is_remembered_but_forbidden_list_is_not(clock: RunningClock, logins: FakeLogins) -> None:
    forbidden: HttpError = http_error(403, "forbidden", "нельзя")
    platform, service = platform_of(clock, logins, thumbnails=[forbidden], liveBroadcasts=[forbidden, {"items": []}])
    for _ in range(2):
        with pytest.raises(PlatformError) as raised:
            platform.set_thumbnail(CHANNEL, "B1", b"jpg")
        assert raised.value.code == "forbidden"
    with pytest.raises(PlatformError) as listed:
        platform.list_upcoming(CHANNEL)
    assert listed.value.code == "forbidden"
    assert platform.list_upcoming(CHANNEL) == []               # CALL: следующий такой же вызов идёт в сеть
    assert [call["resource"] for call in service.calls] == ["thumbnails", "liveBroadcasts", "liveBroadcasts"]


def test_quota_exceeded_stops_every_channel(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, liveBroadcasts=[http_error(403, "quotaExceeded", "квота")])
    for call in (
        lambda: platform.list_upcoming(CHANNEL),
        lambda: platform.list_upcoming(OTHER_CHANNEL),
        lambda: platform.get_stream(CHANNEL, "S1"),
    ):
        with pytest.raises(PlatformError) as raised:
            call()
        assert raised.value.code == "quotaExceeded"
    assert len(service.calls) == 1


def test_remembered_refusal_is_skipped_with_a_log_line(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(clock, logins, liveBroadcasts=[http_error(403, "quotaExceeded", "квота")])
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        for _ in range(2):
            with pytest.raises(PlatformError):
                platform.list_upcoming(CHANNEL)
    [refused] = [line for line in capture.messages(logging.WARNING) if line.startswith("youtube_refused")]
    assert refused == (
        'youtube_refused operation=liveBroadcasts.list channel="Канал UA" handle=@KanalUA http_status=403 '
        'reason=quotaExceeded behavior=project message="HTTP 403: квота"'
    )
    [skipped] = [line for line in capture.messages() if line.startswith("request_skipped")]
    assert skipped.endswith("reason=quotaExceeded behavior=project")


def test_auth_error_stops_only_that_channel(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(
        clock, logins, liveBroadcasts=[http_error(401, "authError", "токен отозван"), {"items": []}]
    )
    with pytest.raises(PlatformError) as first:
        platform.list_upcoming(CHANNEL)
    with pytest.raises(PlatformError) as second:
        platform.get_stream(CHANNEL, "S1")
    assert first.value.code == second.value.code == "authError"
    assert platform.list_upcoming(OTHER_CHANNEL) == []
    assert len(service.calls) == 2


def test_refusals_of_channels_with_one_title_do_not_mix(clock: RunningClock, logins: FakeLogins) -> None:
    """Память отказов — по ключу канала (нику): одинаковое название другого канала отказ не наследует."""
    twin: ChannelConfig = channel(handle="@KanalUA2")
    platform, service = platform_of(
        clock, logins, liveBroadcasts=[http_error(401, "authError", "токен отозван"), {"items": []}]
    )
    with pytest.raises(PlatformError):
        platform.list_upcoming(CHANNEL)
    assert platform.list_upcoming(twin) == []
    assert len(service.calls) == 2


def test_live_streaming_disabled_stops_inserts_of_that_channel(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(
        clock, logins, liveBroadcasts=[http_error(403, "liveStreamingNotEnabled", "выключено"), {"items": []}]
    )
    for _ in range(2):
        with pytest.raises(PlatformError) as raised:
            platform.create_broadcast(CHANNEL, spec())
        assert raised.value.code == "liveStreamingNotEnabled"
    assert platform.list_upcoming(CHANNEL) == []
    assert [call["method"] for call in service.calls] == ["insert", "list"]


@pytest.mark.parametrize(
    ("status", "reason", "code"),
    [
        (500, "backendError", "transportFailed"),
        (503, "somethingNew", "transportFailed"),
        (403, "rateLimitExceeded", "rateLimitExceeded"),
        (403, "userRateLimitExceeded", "userRateLimitExceeded"),
        (429, "somethingNew", "somethingNew"),
    ],
)
def test_retried_refusal_after_all_attempts(
    clock: RunningClock, logins: FakeLogins, status: int, reason: str, code: str
) -> None:
    """5xx и сеть после всех попыток — transportFailed; лимит частоты сохраняет свою причину."""
    platform, service = platform_of(clock, logins, liveBroadcasts=[http_error(status, reason, "x")] * POLICY.max_attempts)
    with pytest.raises(PlatformError) as raised:
        platform.list_upcoming(CHANNEL)
    assert raised.value.code == code
    assert len(service.calls) == POLICY.max_attempts
    assert clock.sleeps == expected_delays(4)


def test_unknown_refusal_without_retry_status_is_asked_once(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, liveBroadcasts=[http_error(403, "somethingNew", "x")])
    with pytest.raises(PlatformError) as raised:
        platform.list_upcoming(CHANNEL)
    assert raised.value.code == "somethingNew"
    assert len(service.calls) == 1 and clock.sleeps == []


def test_retry_line_names_the_operation_and_the_reason(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(clock, logins, liveBroadcasts=[http_error(503, "backendError", "x"), {"items": []}])
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        platform.list_upcoming(CHANNEL)
    [line] = [line for line in capture.messages(logging.WARNING) if line.startswith("request_retry")]
    assert line.startswith('request_retry operation=liveBroadcasts.list channel="Канал UA" handle=@KanalUA retry=1')
    assert "max_retries=4" in line and line.endswith("http_status=503 reason=backendError")


def test_connection_drop_on_reading_call_is_retried(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, liveBroadcasts=[ConnectionResetError("reset"), {"items": []}])
    assert platform.list_upcoming(CHANNEL) == []
    assert len(service.calls) == 2 and clock.sleeps == expected_delays(1)


@pytest.mark.parametrize(
    "failure",
    [
        ServerNotFoundError("Unable to find the server at youtube.googleapis.com"),
        http.client.IncompleteRead(b"partial"),
        TransportError("connection aborted"),
    ],
)
def test_failure_below_http_that_is_not_os_error_is_retried_then_refused(
    clock: RunningClock, logins: FakeLogins, failure: Exception
) -> None:
    """DNS, недочитанный ответ и сбой транспорта google-auth — не OSError, но тоже обрыв связи: повторы, затем отказ."""
    platform, service = platform_of(clock, logins, liveBroadcasts=[failure] * POLICY.max_attempts)
    with pytest.raises(PlatformError) as raised:
        platform.list_upcoming(CHANNEL)
    assert raised.value.code == "transportFailed"
    assert len(service.calls) == POLICY.max_attempts
    assert clock.sleeps == expected_delays(4)


def test_token_revoked_during_a_request_stops_only_that_channel(clock: RunningClock, logins: FakeLogins) -> None:
    """Токен канала не обновился по ходу запроса — authFailed без повтора; канал дальше не спрашивается, другой — да."""
    platform, service = platform_of(
        clock, logins, liveBroadcasts=[RefreshError("invalid_grant: Token has been expired or revoked."), {"items": []}]
    )
    with pytest.raises(PlatformError) as first:
        platform.list_upcoming(CHANNEL)
    with pytest.raises(PlatformError) as second:
        platform.get_stream(CHANNEL, "S1")
    assert first.value.code == second.value.code == "authFailed"
    assert platform.list_upcoming(OTHER_CHANNEL) == []
    assert len(service.calls) == 2 and clock.sleeps == []


# --- создающие вызовы не повторяются вслепую (planers, прогон 18-09-2026, liveBroadcasts.insert)


def unknown_outcome_failures() -> list[Exception]:
    """Отказы, по которым не видно, создан ли объект: обрыв связи и 5xx."""
    return [
        ConnectionResetError("connection reset by peer"),
        ServerNotFoundError("Unable to find the server at youtube.googleapis.com"),
        http_error(503, "backendError", "x"),
        http_error(500, "somethingNew", "x"),
    ]


@pytest.mark.parametrize("failure", unknown_outcome_failures())
def test_broadcast_insert_with_unknown_outcome_is_not_retried(
    clock: RunningClock, logins: FakeLogins, failure: Exception
) -> None:
    platform, service = platform_of(clock, logins, liveBroadcasts=[failure])
    with pytest.raises(PlatformError) as raised:
        platform.create_broadcast(CHANNEL, spec())
    assert raised.value.code == "transportFailed"
    assert [(call["resource"], call["method"]) for call in service.calls] == [("liveBroadcasts", "insert")]
    assert clock.sleeps == []


@pytest.mark.parametrize("failure", unknown_outcome_failures())
def test_stream_insert_with_unknown_outcome_is_not_retried(
    clock: RunningClock, logins: FakeLogins, failure: Exception
) -> None:
    """Эфир создан, поток — неизвестно: второго потока не заводим; эфир без потока доделает следующий запуск."""
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"id": "B1"}], liveStreams=[failure])
    with pytest.raises(PlatformError) as raised:
        platform.create_broadcast(CHANNEL, spec())
    assert raised.value.code == "transportFailed"
    assert [(call["resource"], call["method"]) for call in service.calls] == [
        ("liveBroadcasts", "insert"),
        ("liveStreams", "insert"),
    ]
    assert clock.sleeps == []


@pytest.mark.parametrize("resource", ["liveBroadcasts", "liveStreams"])
def test_rate_limit_on_creating_call_is_still_retried(clock: RunningClock, logins: FakeLogins, resource: str) -> None:
    """Лимит частоты — сервер явно отклонил запрос, объект не создан: повтор безопасен; 429 — тоже."""
    limit: HttpError = http_error(403, "rateLimitExceeded", "slow down")
    broadcasts: list[Any] = [{"id": "B1"}, {"id": "B1"}]
    streams: list[Any] = [stream_response()]
    (broadcasts if resource == "liveBroadcasts" else streams).insert(0, limit)
    platform, service = platform_of(clock, logins, liveBroadcasts=broadcasts, liveStreams=streams)
    created: CreatedBroadcast = platform.create_broadcast(CHANNEL, spec())
    assert created.stream_key == GOOD_KEY
    inserts: list[str] = [call["resource"] for call in service.calls if call["method"] == "insert"]
    assert inserts.count(resource) == 2
    assert clock.sleeps == expected_delays(1)


def test_too_many_requests_on_creating_call_is_retried(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(
        clock,
        logins,
        liveBroadcasts=[http_error(429, "somethingNew", "slow"), {"id": "B1"}, {"id": "B1"}],
        liveStreams=[stream_response()],
    )
    assert platform.create_broadcast(CHANNEL, spec()).broadcast_id == "B1"
    assert [call["method"] for call in service.calls].count("insert") == 3


# --- создание, правка и поток


def test_create_broadcast_inserts_binds_and_returns_key(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"id": "B1"}, {"id": "B1"}], liveStreams=[stream_response()])
    created: CreatedBroadcast = platform.create_broadcast(CHANNEL, spec())
    assert created == CreatedBroadcast(
        broadcast_id="B1",
        broadcast_url="https://www.youtube.com/watch?v=B1",
        stream_id="S1",
        stream_url="rtmp://a.rtmp.youtube.com/live2",
        stream_key=GOOD_KEY,
    )
    insert: dict[str, Any] = service.calls[0]["body"]
    assert insert["snippet"] == {
        "title": "Эфир", "description": "Описание", "scheduledStartTime": "2027-03-17T17:00:00Z", "categoryId": "22"
    }
    assert insert["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    assert insert["contentDetails"] == {"enableAutoStart": True, "enableAutoStop": True, "latencyPreference": "normal"}
    stream_body: dict[str, Any] = service.calls[1]["body"]
    assert stream_body["snippet"]["title"] == MARKER               # метка программы
    assert stream_body["snippet"]["description"].startswith(DESCRIPTION_HEAD)
    assert stream_body["cdn"] == {"ingestionType": "rtmp", "resolution": "variable", "frameRate": "variable"}
    assert (service.calls[2]["method"], service.calls[2]["id"], service.calls[2]["streamId"]) == ("bind", "B1", "S1")
    assert json.loads(json.dumps(insert)) == insert                # тело уходит в JSON как есть


def test_stream_description_names_the_moment_it_was_written(clock: RunningClock, logins: FakeLogins) -> None:
    """Описание ключа — безличное, дата для людей, момент записи — по часам программы."""
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"id": "B1"}, {"id": "B1"}], liveStreams=[stream_response()])
    platform.create_broadcast(CHANNEL, spec())
    assert service.calls[1]["body"]["snippet"]["description"] == (
        DESCRIPTION_HEAD + "; записано программой 16.03.2027 12:00"
    )


def test_broadcast_body_comes_from_the_spec(clock: RunningClock, logins: FakeLogins) -> None:
    """Всё, что уходит в эфир, — из спеки: там же оно сверяется с площадкой."""
    platform, service = platform_of(
        clock, logins, liveBroadcasts=[{"id": "B1"}, {"id": "B1"}, {"id": "B1"}], liveStreams=[stream_response()]
    )
    changed: BroadcastSpec = spec(auto_start=False, category_id="25", privacy="unlisted", latency_preference="low")
    platform.create_broadcast(CHANNEL, changed)
    platform.update_broadcast(CHANNEL, "B1", changed)
    insert: dict[str, Any] = service.calls[0]["body"]
    assert insert["contentDetails"]["enableAutoStart"] is False
    assert insert["contentDetails"]["latencyPreference"] == "low"
    assert insert["status"]["privacyStatus"] == "unlisted"
    assert insert["snippet"]["categoryId"] == "25"
    assert service.calls[3]["body"]["snippet"]["categoryId"] == "25"


def test_unexpected_stream_key_is_an_error_with_a_mask(clock: RunningClock, logins: FakeLogins) -> None:
    """Ключ не того вида — эфир не засчитан: ключ не берём, привязки нет."""
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"id": "B1"}], liveStreams=[stream_response("STRANGE")])
    with LogCapture.on(LogArea.PLATFORMS) as capture, pytest.raises(PlatformError) as raised:
        platform.create_broadcast(CHANNEL, spec())
    assert raised.value.code == "unexpectedStreamKeyFormat"
    assert raised.value.message == "****-ANGE"
    assert [line.split()[0] for line in capture.messages(logging.ERROR)] == ["stream_key_rejected"]
    assert "STRANGE" not in "".join(capture.messages())
    assert [call["method"] for call in service.calls] == ["insert", "insert"]


def test_bound_stream_key_is_masked_in_the_log(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(clock, logins, liveBroadcasts=[{"id": "B1"}, {"id": "B1"}], liveStreams=[stream_response()])
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        platform.create_broadcast(CHANNEL, spec())
    [bound] = [line for line in capture.messages() if line.startswith("stream_bound")]
    assert bound.endswith("broadcast_id=B1 stream_id=S1 stream_key=****-ijkl")
    assert GOOD_KEY not in "".join(capture.messages())


def test_attach_stream_reuses_the_same_path(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"id": "B1"}], liveStreams=[stream_response()])
    created: CreatedBroadcast = platform.attach_stream(CHANNEL, "B1", spec())
    assert created.stream_key == GOOD_KEY
    assert [(call["resource"], call["method"]) for call in service.calls] == [
        ("liveStreams", "insert"),
        ("liveBroadcasts", "bind"),
    ]


def test_update_sends_time_and_category(clock: RunningClock, logins: FakeLogins) -> None:
    """update заменяет snippet целиком: без времени и категории они бы потерялись."""
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"id": "B1"}])
    platform.update_broadcast(CHANNEL, "B1", spec())
    body: dict[str, Any] = service.calls[0]["body"]
    assert service.calls[0]["part"] == "snippet"      # contentDetails тянет monitorStream
    assert body["id"] == "B1"
    assert body["snippet"]["scheduledStartTime"] == "2027-03-17T17:00:00Z"
    assert body["snippet"]["categoryId"] == "22"      # категория из спеки, а не найденная


def test_set_stream_marker_rewrites_snippet_whole(clock: RunningClock, logins: FakeLogins) -> None:
    """liveStreams.update(part=snippet): snippet читается целиком, меняются название и описание."""
    snippet: dict[str, Any] = {"title": "Мой ключ", "description": "", "isDefaultStream": False, "channelId": "UC1"}
    platform, service = platform_of(clock, logins, liveStreams=[{"items": [{"id": "S1", "snippet": snippet}]}, {"id": "S1"}])
    platform.set_stream_marker(CHANNEL, "S1", MARKER)
    assert [(call["method"], call["part"]) for call in service.calls] == [("list", "snippet"), ("update", "snippet")]
    body: dict[str, Any] = service.calls[1]["body"]
    assert body["id"] == "S1"
    assert body["snippet"]["title"] == MARKER
    assert body["snippet"]["description"].startswith(DESCRIPTION_HEAD)
    assert (body["snippet"]["channelId"], body["snippet"]["isDefaultStream"]) == ("UC1", False)   # не затёрты


def test_set_stream_marker_keeps_the_placeholder_mark(clock: RunningClock, logins: FakeLogins) -> None:
    old: str = "Ключ планера: старый; заглушка обложки thumb0=044eb0835668"
    platform, service = platform_of(
        clock, logins, liveStreams=[{"items": [{"id": "S1", "snippet": {"title": "x", "description": old}}]}, {"id": "S1"}]
    )
    platform.set_stream_marker(CHANNEL, "S1", MARKER)
    description: str = service.calls[1]["body"]["snippet"]["description"]
    assert description.startswith(DESCRIPTION_HEAD)
    assert description.endswith("; заглушка обложки thumb0=044eb0835668")


def test_marker_that_is_not_a_slot_id_is_the_date_of_the_description(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(
        clock, logins, liveStreams=[{"items": [{"id": "S1", "snippet": {"title": "x"}}]}, {"id": "S1"}]
    )
    platform.set_stream_marker(CHANNEL, "S1", "Мой поток")
    assert service.calls[1]["body"]["snippet"]["description"].startswith(
        "Ключ Livecraft: канал «Канал UA» @KanalUA, эфир Мой поток , язык ;"
    )


# --- настройки видео и факты


def video_list(**overrides: Any) -> dict[str, Any]:
    snippet: dict[str, Any] = {
        "title": "Эфир", "description": "Описание", "categoryId": "22", "defaultLanguage": "uk", "defaultAudioLanguage": "uk"
    }
    status: dict[str, Any] = {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}
    snippet.update(overrides.get("snippet", {}))
    status.update(overrides.get("status", {}))
    return {"items": [{"id": "B1", "snippet": snippet, "status": status}]}


def facts(**overrides: Any) -> BroadcastFacts:
    """Снимок фактов эфира: минимум обязательных полей, остальное — по месту теста."""
    values: dict[str, Any] = {
        "broadcast_id": "B1",
        "title": "Эфир",
        "description": "Описание",
        "start_utc": None,
        "privacy_status": "unlisted",
        "made_for_kids": False,
        "age_restricted": False,
        "default_language": "uk",
        "default_audio_language": "uk",
        "category_id": "22",
        "bound_stream_id": "S1",
        "stream_marker": MARKER,
    }
    return BroadcastFacts(**{**values, **overrides})


def test_video_settings_are_applied_in_one_write(clock: RunningClock, logins: FakeLogins) -> None:
    """Один list и один update: язык, категория и аудитория правятся вместе, части — целиком."""
    platform, service = platform_of(
        clock,
        logins,
        videos=[
            video_list(snippet={"defaultLanguage": "en", "categoryId": "24"}, status={"selfDeclaredMadeForKids": True}),
            {"id": "B1"},
        ],
    )
    fixes: VideoFixes = platform.apply_video_settings(CHANNEL, "B1", SETTINGS)
    assert (fixes.language_set, fixes.category_set, fixes.audience_cleared, fixes.privacy_set) == (True, True, True, False)
    assert len(service.calls) == 2
    body: dict[str, Any] = service.calls[1]["body"]
    assert service.calls[1]["part"] == "snippet,status"
    assert body["snippet"]["defaultLanguage"] == "uk" and body["snippet"]["defaultAudioLanguage"] == "uk"
    assert body["snippet"]["categoryId"] == "22"
    assert body["snippet"]["title"] == "Эфир"                   # непереданное поле не теряется
    assert body["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}


def test_matching_video_settings_are_not_written(clock: RunningClock, logins: FakeLogins) -> None:
    """Совпало всё — записи не делается вовсе: лишняя квота и лишний риск."""
    platform, service = platform_of(clock, logins, videos=[video_list()])
    fixes: VideoFixes = platform.apply_video_settings(CHANNEL, "B1", SETTINGS)
    assert fixes.any_fix is False and fixes.applied is None
    assert len(service.calls) == 1


def test_channel_level_audience_is_also_fixed(clock: RunningClock, logins: FakeLogins) -> None:
    """madeForKids=true при selfDeclared=false — это аудитория, выставленная на весь канал."""
    platform, _ = platform_of(clock, logins, videos=[video_list(status={"madeForKids": True}), {"id": "B1"}])
    assert platform.apply_video_settings(CHANNEL, "B1", SETTINGS).audience_cleared is True


def test_privacy_is_restored_in_the_same_write(clock: RunningClock, logins: FakeLogins) -> None:
    """Владелец поставил Private: видимость возвращается тем же videos.update, status — целиком."""
    platform, service = platform_of(
        clock, logins, videos=[video_list(status={"privacyStatus": "private", "embeddable": True}), {"id": "B1"}]
    )
    fixes: VideoFixes = platform.apply_video_settings(CHANNEL, "B1", SETTINGS)
    assert (fixes.privacy_set, fixes.language_set, fixes.category_set) == (True, False, False)
    body: dict[str, Any] = service.calls[1]["body"]
    assert body["status"]["privacyStatus"] == "unlisted"
    assert body["status"]["embeddable"] is True


def test_write_response_says_what_the_platform_stored(clock: RunningClock, logins: FakeLogins) -> None:
    """Ответ videos.update — источник записанного: перечитывание сразу после записи отстаёт."""
    stored: dict[str, Any] = {
        "id": "B1",
        "snippet": {"defaultLanguage": "uk", "defaultAudioLanguage": "uk", "categoryId": "22"},
        "status": {"privacyStatus": "unlisted", "madeForKids": False},
    }
    platform, _ = platform_of(
        clock, logins, videos=[video_list(snippet={"defaultLanguage": "ru", "defaultAudioLanguage": "ru"}), stored]
    )
    fixes: VideoFixes = platform.apply_video_settings(CHANNEL, "B1", SETTINGS)
    assert fixes.language_set is True and fixes.applied is not None
    assert (fixes.applied.language, fixes.applied.audio_language) == ("uk", "uk")
    assert (fixes.applied.category_id, fixes.applied.privacy, fixes.applied.made_for_kids) == ("22", "unlisted", False)
    stale: BroadcastFacts = fixes.apply_to_facts(facts(default_language="ru", default_audio_language="ru", title="Старое"))
    assert (stale.default_language, stale.default_audio_language, stale.title) == ("uk", "uk", "Старое")


def test_empty_write_response_leaves_the_read_value(clock: RunningClock, logins: FakeLogins) -> None:
    """Площадка ничего не прислала в ответе — подставлять нечего, перечитанное остаётся как есть."""
    platform, _ = platform_of(clock, logins, videos=[video_list(snippet={"defaultLanguage": "ru"}), {"id": "B1"}])
    fixes: VideoFixes = platform.apply_video_settings(CHANNEL, "B1", SETTINGS)
    assert fixes.applied is not None and fixes.applied.language is None
    assert fixes.apply_to_facts(facts(default_language="ru")).default_language == "ru"


def test_read_facts_collects_language_audience_age_and_stream(clock: RunningClock, logins: FakeLogins) -> None:
    """Язык, аудитория и возраст видны только у видео, поток — у самого эфира."""
    video: dict[str, Any] = {
        "id": "B1",
        "snippet": {"title": "Эфир", "description": "Описание", "defaultLanguage": "ru", "defaultAudioLanguage": "ru",
                    "categoryId": "22"},
        "status": {"privacyStatus": "unlisted", "madeForKids": False},
        "contentDetails": {"contentRating": {"ytRating": "ytAgeRestricted"}},
        "liveStreamingDetails": {"scheduledStartTime": "2027-03-17T17:00:00Z"},   # время старта у videos — здесь
    }
    stream: dict[str, Any] = {
        "id": "S1", "snippet": {"title": MARKER}, "cdn": {"ingestionInfo": {"ingestionAddress": "rtmp://x", "streamName": GOOD_KEY}}
    }
    platform, service = platform_of(
        clock,
        logins,
        videos=[{"items": [video]}],
        liveBroadcasts=[{"items": [broadcast_item("B1", "2027-03-17T17:00:00Z")]}],
        liveStreams=[{"items": [stream]}],
    )
    read: BroadcastFacts = platform.read_facts(CHANNEL, "B1")
    assert (read.default_language, read.default_audio_language, read.made_for_kids) == ("ru", "ru", False)
    assert read.age_restricted is True
    assert (read.privacy_status, read.category_id) == ("unlisted", "22")
    assert (read.bound_stream_id, read.stream_marker) == ("S1", MARKER)
    assert read.start_utc == datetime(2027, 3, 17, 17, 0, tzinfo=timezone.utc)
    assert service.calls[0]["part"] == VIDEO_FACTS_PARTS and "liveStreamingDetails" in VIDEO_FACTS_PARTS


def test_read_facts_without_live_streaming_details_gives_none(clock: RunningClock, logins: FakeLogins) -> None:
    """У эфира без запланированного времени его действительно нет — это не ошибка."""
    video: dict[str, Any] = {"id": "B1", "snippet": {"title": "Эфир", "description": ""}, "status": {}, "contentDetails": {}}
    platform, _ = platform_of(
        clock,
        logins,
        videos=[{"items": [video]}],
        liveBroadcasts=[{"items": [broadcast_item("B1", "2027-03-17T17:00:00Z", stream_id=None)]}],
    )
    read: BroadcastFacts = platform.read_facts(CHANNEL, "B1")
    assert read.start_utc is None and read.bound_stream_id is None


def test_facts_take_chat_and_largest_thumbnail_without_downloading(clock: RunningClock, logins: FakeLogins) -> None:
    """liveChatId живёт у эфира, обложка — у видео; берётся самое крупное разрешение; картинки не скачиваются."""
    item: dict[str, Any] = broadcast_item("B1", "2027-03-17T17:00:00Z", stream_id=None)
    item["snippet"].update({"liveChatId": "CHAT1", "thumbnails": thumbnails()})
    video: dict[str, Any] = {
        "id": "B1",
        "snippet": {"title": "Эфир", "description": "",
                    "thumbnails": {"default": {"url": "small.jpg", "width": 120}, "maxres": {"url": "big.jpg", "width": 1280}}},
    }
    session: FakeSession = FakeSession({})
    service: FakeService = FakeService(clock, videos=[{"items": [video]}], liveBroadcasts=[{"items": [item]}])
    platform: YouTubePlatform = build_platform(service, logins, session=session)
    read: BroadcastFacts = platform.read_facts(CHANNEL, "B1")
    assert (read.live_chat_id, read.thumbnail_url) == ("CHAT1", "big.jpg")
    assert session.calls == []


def test_empty_read_by_id_after_write_is_retried(clock: RunningClock, logins: FakeLogins) -> None:
    """planers, прогон 20-09-2026 23:37: videos.list через 2 с после записи отдал пустой items — повтор, а не сбой."""
    video: dict[str, Any] = {"id": "B1", "snippet": {"title": "Эфир", "description": "", "defaultLanguage": "uk"}}
    platform, service = platform_of(
        clock,
        logins,
        videos=[{"items": []}, {"items": [video]}],
        liveBroadcasts=[{"items": [broadcast_item("B1", "2027-03-17T17:00:00Z", stream_id=None)]}],
    )
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        assert platform.read_facts(CHANNEL, "B1").default_language == "uk"
    assert [call["resource"] for call in service.calls] == ["videos", "videos", "liveBroadcasts"]
    assert clock.sleeps == expected_delays(1)
    assert any(
        line.startswith("request_retry operation=videos.list") and "reason=notListed" in line for line in capture.messages()
    )


def test_empty_read_by_id_on_every_attempt_is_not_listed(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, videos=empties())
    with LogCapture.on(LogArea.PLATFORMS) as capture, pytest.raises(PlatformError) as raised:
        platform.read_facts(CHANNEL, "B1")
    assert raised.value.code == "notListed"
    assert raised.value.message == "videos.list is empty for B1 after 5 attempts"
    assert len(service.calls) == POLICY.max_attempts
    assert [line for line in capture.messages() if line.startswith("read_not_listed")] == [
        'read_not_listed operation=videos.list channel="Канал UA" handle=@KanalUA object_id=B1 attempts=5'
    ]


def test_empty_video_item_and_stream_marker_are_not_listed(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(clock, logins, videos=empties(), liveStreams=empties())
    with pytest.raises(PlatformError) as video_raised:
        platform.apply_video_settings(CHANNEL, "B1", SETTINGS)
    with pytest.raises(PlatformError) as stream_raised:
        platform.set_stream_marker(CHANNEL, "S1", MARKER)
    assert (video_raised.value.code, stream_raised.value.code) == ("notListed", "notListed")


# --- картинка эфира и отпечаток заглушки

PICTURE: bytes = b"placeholder-jpeg"
PICTURE_URL: str = "https://i.ytimg.com/vi/B1/default_live.jpg"


class PictureResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code: int = status_code
        self.content: bytes = content


class FakeSession:
    """requests.Session для картинок: ответ по адресу, момент каждого скачивания — по часам теста."""

    def __init__(self, pictures: dict[str, Any], clock: RunningClock | None = None, seconds: float = 0) -> None:
        self.pictures: dict[str, Any] = pictures
        self.clock: RunningClock | None = clock
        self.seconds: float = seconds          # сколько длится одно скачивание по часам теста
        self.calls: list[tuple[str, float | None]] = []

    def get(self, url: str, timeout: int) -> PictureResponse:
        self.calls.append((url, None if self.clock is None else self.clock.seconds))
        if self.clock is not None:
            self.clock.advance(self.seconds)
        answer: Any = self.pictures.get(url, PictureResponse(404, b""))
        if isinstance(answer, Exception):
            raise answer
        return answer


def thumbnails(url: str = PICTURE_URL) -> dict[str, Any]:
    return {"default": {"url": url, "width": 120}, "high": {"url": url.replace("default", "hq"), "width": 480}}


def test_placeholder_mark_is_twelve_hex_of_sha256() -> None:
    mark: PlaceholderMark = PlaceholderMark.of(PICTURE)
    assert len(mark.sha) == 12 and mark.token == f"thumb0={mark.sha}"
    assert PlaceholderMark.found_in(f"Ключ; заглушка обложки {mark.token}") == mark
    assert PlaceholderMark.found_in("Ключ без метки") is None


def test_create_writes_placeholder_mark_into_stream_description(clock: RunningClock, logins: FakeLogins) -> None:
    service: FakeService = FakeService(
        clock,
        liveBroadcasts=[{"id": "B1", "snippet": {"thumbnails": thumbnails()}}, {"id": "B1"}],
        liveStreams=[stream_response()],
    )
    platform: YouTubePlatform = build_platform(
        service, logins, session=FakeSession({PICTURE_URL: PictureResponse(200, PICTURE)})
    )
    platform.create_broadcast(CHANNEL, spec())
    description: str = service.calls[1]["body"]["snippet"]["description"]
    assert description.endswith("; заглушка обложки thumb0=" + PlaceholderMark.of(PICTURE).sha)
    assert PlaceholderMark.found_in(description) == PlaceholderMark.of(PICTURE)


@pytest.mark.parametrize(
    "answer",
    [PictureResponse(404, b""), PictureResponse(200, b""), requests.ConnectionError("нет сети")],
    ids=["not_found", "empty_body", "network"],
)
def test_create_without_picture_writes_no_mark_and_does_not_fail(
    clock: RunningClock, logins: FakeLogins, answer: Any
) -> None:
    service: FakeService = FakeService(
        clock,
        liveBroadcasts=[{"id": "B1", "snippet": {"thumbnails": thumbnails()}}, {"id": "B1"}],
        liveStreams=[stream_response()],
    )
    platform: YouTubePlatform = build_platform(service, logins, session=FakeSession({PICTURE_URL: answer}))
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        created: CreatedBroadcast = platform.create_broadcast(CHANNEL, spec())
    assert created.stream_key == GOOD_KEY
    assert PlaceholderMark.found_in(service.calls[1]["body"]["snippet"]["description"]) is None
    assert any(line.startswith("thumbnail_picture_unavailable") for line in capture.messages())


def test_attach_stream_does_not_take_a_placeholder(clock: RunningClock, logins: FakeLogins) -> None:
    """На картинке существующего эфира может быть обложка: отпечаток не снимается и не скачивается."""
    session: FakeSession = FakeSession({})
    service: FakeService = FakeService(clock, liveStreams=[stream_response()], liveBroadcasts=[{"id": "B1"}])
    build_platform(service, logins, session=session).attach_stream(CHANNEL, "B1", spec())
    assert session.calls == []
    assert PlaceholderMark.found_in(service.calls[0]["body"]["snippet"]["description"]) is None


def test_list_upcoming_takes_picture_sha_and_survives_a_failed_download(clock: RunningClock, logins: FakeLogins) -> None:
    good: dict[str, Any] = broadcast_item("B1", "2027-03-17T17:00:00Z")
    good["snippet"]["thumbnails"] = thumbnails()
    broken_url: str = "https://i.ytimg.com/vi/B2/default_live.jpg"
    broken: dict[str, Any] = broadcast_item("B2", "2027-03-18T17:00:00Z", stream_id="S2")
    broken["snippet"]["thumbnails"] = thumbnails(broken_url)
    bare: dict[str, Any] = broadcast_item("B3", "2027-03-19T17:00:00Z", stream_id="S3")   # картинок в ответе нет
    session: FakeSession = FakeSession({PICTURE_URL: PictureResponse(200, PICTURE), broken_url: requests.Timeout("долго")})
    service: FakeService = FakeService(clock, liveBroadcasts=[{"items": [good, broken, bare]}])
    broadcasts: list[UpcomingBroadcast] = build_platform(service, logins, session=session).list_upcoming(CHANNEL)
    assert [broadcast.thumbnail_sha for broadcast in broadcasts] == [PlaceholderMark.of(PICTURE).sha, None, None]
    assert [url for url, _ in session.calls] == [PICTURE_URL, broken_url]


def test_picture_downloads_have_no_pause_and_do_not_shift_it(clock: RunningClock, logins: FakeLogins) -> None:
    """Картинки i.ytimg.com — не API: перед ними не спим, и отсчёт паузы до следующего вызова API они не сдвигают."""
    items: list[dict[str, Any]] = []
    pictures: dict[str, Any] = {}
    for number in (1, 2):
        item: dict[str, Any] = broadcast_item(f"B{number}", f"2027-03-1{number + 6}T17:00:00Z")
        url: str = f"https://i.ytimg.com/vi/B{number}/default_live.jpg"
        item["snippet"]["thumbnails"] = thumbnails(url)
        pictures[url] = PictureResponse(200, PICTURE + bytes([number]))
        items.append(item)
    service: FakeService = FakeService(clock, liveBroadcasts=[{"items": items}], liveStreams=[stream_list("S1")])
    session: FakeSession = FakeSession(pictures, clock, seconds=1.5)
    platform: YouTubePlatform = build_platform(service, logins, pause=2, session=session)
    platform.list_upcoming(CHANNEL)
    assert [moment for _, moment in session.calls] == [0.0, 1.5]      # сразу после вызова API, без сна
    platform.get_stream(CHANNEL, "S1")
    # от конца вызова API (0.0) прошло 3.0 с картинок — больше паузы 2: второй вызов без сна
    assert service.calls[1]["at"] == 3.0
    assert clock.sleeps == []


def test_thumbnail_refusal_is_remembered_without_network(clock: RunningClock, logins: FakeLogins) -> None:
    platform, service = platform_of(clock, logins, thumbnails=[http_error(429, "uploadRateLimitExceeded", "лимит")])
    assert platform.thumbnail_refusal(CHANNEL) is None
    with pytest.raises(PlatformError):
        platform.set_thumbnail(CHANNEL, "B1", b"jpg")
    refusal: PlatformError | None = platform.thumbnail_refusal(CHANNEL)
    assert refusal is not None and refusal.code == "uploadRateLimitExceeded"
    assert platform.thumbnail_refusal(OTHER_CHANNEL) is None
    assert len(service.calls) == 1                            # вопрос об отказе к сети не ходит


# --- вход владельца канала


def channel_list() -> dict[str, Any]:
    return {"items": [{"id": "UC1", "snippet": {"title": "Канал UA", "customUrl": "@kanalua"}}]}


def test_owner_logins_use_the_channel_token_and_account(tmp_path: Path) -> None:
    """Вход канала — владелец (§9): токен secrets\\<ник>.token.json, подсказка — почта, новый вход сам не пишется."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    login: GoogleLogin = ChannelLogins.of(paths).login(CHANNEL)
    assert login.token_file == paths.dir(DataDir.SECRETS) / "@KanalUA.token.json"
    assert (login.scopes, login.login_hint, login.saves_new_login) == ((YOUTUBE_SCOPE,), "owner@gmail.com", False)


def test_new_login_is_kept_in_memory_until_the_channel_is_confirmed(clock: RunningClock, tmp_path: Path) -> None:
    """Новый вход файл не пишет — это делает keep_login после подтверждения канала; клиент кешируется."""
    logins: FakeLogins = FakeLogins(tmp_path, needs_browser=True)
    platform, _ = platform_of(clock, logins, channels=[channel_list()], liveBroadcasts=[{"items": []}])
    token_file: Path = tmp_path / "@KanalUA.token.json"
    token_file.write_text("old", encoding="utf-8")
    platform.drop_login(CHANNEL)
    platform.describe_channel(CHANNEL)
    platform.list_upcoming(CHANNEL)                     # клиент кешируется: вход один раз
    assert logins.calls == [("@KanalUA.token.json", True, True)]   # после сброса токен на диске не читается
    assert token_file.read_text(encoding="utf-8") == "old"
    platform.keep_login(CHANNEL)
    assert token_file.read_text(encoding="utf-8") == '{"token": "new"}'
    token_file.write_text("later", encoding="utf-8")
    platform.keep_login(CHANNEL)                        # второй раз записывать нечего
    assert token_file.read_text(encoding="utf-8") == "later"


def test_dropped_login_is_not_written(clock: RunningClock, tmp_path: Path) -> None:
    """Канал не тот: drop_login забывает учётные данные — keep_login после него ничего не пишет."""
    logins: FakeLogins = FakeLogins(tmp_path, needs_browser=True)
    platform, _ = platform_of(clock, logins, channels=[channel_list(), channel_list()])
    platform.describe_channel(CHANNEL)
    platform.drop_login(CHANNEL)
    platform.keep_login(CHANNEL)
    assert not (tmp_path / "@KanalUA.token.json").exists()
    platform.describe_channel(CHANNEL)                  # клиент и описание забыты: вход заново, мимо токена
    assert [force for _, _, force in logins.calls] == [False, True]


def test_operations_other_than_describe_never_open_the_browser(clock: RunningClock, tmp_path: Path) -> None:
    logins: FakeLogins = FakeLogins(tmp_path, needs_browser=True)
    platform, service = platform_of(clock, logins, liveBroadcasts=[{"items": []}])
    with pytest.raises(PlatformError) as raised:
        platform.list_upcoming(CHANNEL)
    assert raised.value.code == "loginRequired"
    assert [allowed for _, allowed, _ in logins.calls] == [False]
    assert service.calls == []


def test_describe_without_login_is_refused_but_not_remembered(clock: RunningClock, tmp_path: Path) -> None:
    """allow_login=False: нужен вход — loginRequired без браузера; следующий обычный вызов входит как всегда."""
    logins: FakeLogins = FakeLogins(tmp_path, needs_browser=True)
    platform, _ = platform_of(clock, logins, channels=[channel_list()])
    with pytest.raises(PlatformError) as refused:
        platform.describe_channel(CHANNEL, allow_login=False)
    assert refused.value.code == "loginRequired"
    assert refused.value.login_reason is AuthErrorReason.LOGIN_REQUIRED
    info: ChannelInfo = platform.describe_channel(CHANNEL)
    assert (info.youtube_channel_id, info.handle_raw) == ("UC1", "@kanalua")
    assert [allowed for _, allowed, _ in logins.calls] == [False, True]


def test_failed_login_is_not_repeated(clock: RunningClock, tmp_path: Path) -> None:
    """Отказ входа — отказ канала: браузер за запуск второй раз не открывается; причина входа — полем ошибки."""
    logins: FakeLogins = FakeLogins(tmp_path, error=AuthError(AuthErrorReason.FLOW_FAILED, "отказ"))
    platform, _ = platform_of(clock, logins)
    for _ in range(2):
        with pytest.raises(PlatformError) as raised:
            platform.list_upcoming(CHANNEL)
        assert raised.value.code == "authFailed"
        assert raised.value.login_reason is AuthErrorReason.FLOW_FAILED
        assert str(raised.value) == msg.AUTH_REASON_TEXT["flow_failed"]
    assert len(logins.calls) == 1


def test_drop_login_forgets_the_refusals_of_the_channel(clock: RunningClock, logins: FakeLogins) -> None:
    """Сброс входа забывает и отказы канала: после нового входа канал снова спрашивается."""
    platform, service = platform_of(
        clock,
        logins,
        liveBroadcasts=[http_error(401, "authError", "токен отозван"), {"items": []}],
        channels=[channel_list()],
    )
    with pytest.raises(PlatformError):
        platform.list_upcoming(CHANNEL)
    platform.drop_login(CHANNEL)
    platform.describe_channel(CHANNEL)
    assert platform.list_upcoming(CHANNEL) == []
    assert [call["resource"] for call in service.calls] == ["liveBroadcasts", "channels", "liveBroadcasts"]


# --- расход


def test_usage_counts_attempts_retries_empty_answers_and_units(clock: RunningClock, logins: FakeLogins) -> None:
    stream: dict[str, Any] = {
        "id": "S1", "snippet": {"title": "m"}, "cdn": {"ingestionInfo": {"ingestionAddress": "rtmp://x", "streamName": GOOD_KEY}}
    }
    platform, _ = platform_of(
        clock, logins, liveStreams=[http_error(503, "backendError", "down"), {"items": []}, {"items": [stream]}]
    )
    assert platform.get_stream(CHANNEL, "S1") is not None
    usage: OperationUsage = platform.gateway.usage.of(YouTubeOperation.STREAMS_LIST)
    assert (usage.attempts, usage.retries, usage.empty, usage.refusals, usage.units) == (3, 2, 1, 0, 3)
    assert len(clock.sleeps) == 2


def test_usage_counts_final_refusals_and_run_totals(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(
        clock, logins, thumbnails=[{}], liveBroadcasts=[http_error(403, "quotaExceeded", "quota")]
    )
    platform.set_thumbnail(CHANNEL, "B1", b"jpg")
    with pytest.raises(PlatformError):
        platform.list_upcoming(CHANNEL)
    listed: OperationUsage = platform.gateway.usage.of(YouTubeOperation.BROADCASTS_LIST)
    assert (listed.attempts, listed.refusals) == (1, 1)
    assert (platform.gateway.usage.attempts, platform.gateway.usage.units) == (2, 51)
    assert platform.gateway.usage.line == msg.YOUTUBE_USAGE_LINE.format(calls=2, units=51)


def test_every_operation_has_a_quota_price() -> None:
    """§9: цены по факту Google Cloud Console за 20–21-09-2026 — 50 только у videos.update и thumbnails.set."""
    assert set(QUOTA_UNITS) == set(YouTubeOperation)
    assert {operation for operation, units in QUOTA_UNITS.items() if units == 50} == {
        YouTubeOperation.VIDEOS_UPDATE,
        YouTubeOperation.THUMBNAILS_SET,
    }
    assert all(units in (1, 50) for units in QUOTA_UNITS.values())
    assert {operation for operation in YouTubeOperation if operation.is_creating} == {
        YouTubeOperation.BROADCASTS_INSERT,
        YouTubeOperation.STREAMS_INSERT,
    }


def test_limits_are_the_slot_text_limits(clock: RunningClock, logins: FakeLogins) -> None:
    platform, _ = platform_of(clock, logins)
    assert (platform.limits.title_max_chars, platform.limits.description_max_chars) == (100, 5000)
    assert (platform.limits.auto_stop, platform.limits.latency_preference) == (True, "normal")


def test_every_successful_call_is_a_log_line_with_attempts_and_units(clock: RunningClock, logins: FakeLogins) -> None:
    """Решение 38: строка `youtube_call` на обращение; у чтения по id — id и все попытки чтения, единицы — цена
    операции на число попыток; повторы внутри не дают второй строки."""
    video: dict[str, Any] = {"id": "B1", "snippet": {"title": "Эфир", "description": "", "defaultLanguage": "uk"}}
    platform, _ = platform_of(
        clock,
        logins,
        videos=[{"items": []}, {"items": [video]}],
        liveBroadcasts=[
            {"items": [broadcast_item("B1", "2027-03-17T17:00:00Z", stream_id=None)]},
            {"items": [broadcast_item("B2", "2027-03-17T17:00:00Z")]},
        ],
    )
    with LogCapture.on(LogArea.PLATFORMS) as capture:
        platform.read_facts(CHANNEL, "B1")
        platform.list_upcoming(CHANNEL)
    assert [line for line in capture.messages() if line.startswith("youtube_call")] == [
        'youtube_call operation=videos.list channel="Канал UA" handle=@KanalUA object_id=B1 attempts=2 units=2',
        'youtube_call operation=liveBroadcasts.list channel="Канал UA" handle=@KanalUA object_id=B1 attempts=1 units=1',
        'youtube_call operation=liveBroadcasts.list channel="Канал UA" handle=@KanalUA attempts=1 units=1',
    ]


def test_the_units_of_a_call_line_are_the_price_times_the_attempts() -> None:
    line: str = YouTubeEvent.CALL.of_call(YouTubeOperation.THUMBNAILS_SET, CHANNEL, 2).text
    assert line == 'youtube_call operation=thumbnails.set channel="Канал UA" handle=@KanalUA attempts=2 units=100'
