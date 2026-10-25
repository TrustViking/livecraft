from __future__ import annotations

import pytest

from app.config.channel import ChannelConfig, ConfiguredChannels
from app.paths import LivecraftPaths
from app.platforms.channel import ChannelBindingError, ChannelRefusal
from app.platforms.channel_book import ChannelBook
from app.platforms.error import PlatformCode, PlatformError
from app.platforms.notice import PlatformNotice, PlatformNoticeKind
from app.platforms.spec import BroadcastSpec
from app.platforms.verified import VerifiedPlatform
from app.tests.fixtures.platform import (
    CHECKED_AT,
    FakePlatform,
    channel_sync,
    two_channels,
    written_channels,
    written_token,
)

SPEC: BroadcastSpec = BroadcastSpec(start_minute=CHECKED_AT, marker="17-03-2027_1900_uk", title="Эфир", description="")


def started(platform: FakePlatform, paths: LivecraftPaths) -> VerifiedPlatform:
    """Как при запуске: проверка каналов без браузера, затем шлюз над площадкой."""
    channels: ConfiguredChannels = written_channels(paths, *two_channels())
    for channel in channels.channels:
        written_token(paths, channel.handle)
    book: ChannelBook = ChannelBook(platform, channel_sync(platform, paths))
    book.check_without_login(channels)
    return VerifiedPlatform(platform, book)


def test_ready_channel_goes_through_without_second_describe(livecraft_paths: LivecraftPaths) -> None:
    fake: FakePlatform = FakePlatform()
    platform: VerifiedPlatform = started(fake, livecraft_paths)
    channel: ChannelConfig = two_channels()[0]
    platform.list_upcoming(channel)
    assert platform.describe_channel(channel) == FakePlatform.default_channel_info(channel)
    assert fake.describe_calls == ["yt_ua", "yt_ru"]       # только проверка при старте
    assert fake.list_calls == ["yt_ua"]


def test_not_ready_channel_never_reaches_the_platform(livecraft_paths: LivecraftPaths) -> None:
    fake: FakePlatform = FakePlatform()
    platform: VerifiedPlatform = VerifiedPlatform(fake, ChannelBook(fake, channel_sync(fake, livecraft_paths)))
    with pytest.raises(PlatformError) as raised:
        platform.create_broadcast(two_channels()[0], SPEC)
    assert raised.value.code == PlatformCode.LOGIN_REQUIRED.value
    assert fake.created == [] and fake.describe_calls == []


def test_refused_channel_raises_its_stored_error(livecraft_paths: LivecraftPaths) -> None:
    fake: FakePlatform = FakePlatform()
    platform: VerifiedPlatform = started(fake, livecraft_paths)
    channel: ChannelConfig = two_channels()[0]
    error: ChannelBindingError = ChannelBindingError(ChannelRefusal.HANDLE_MISMATCH, "не тот канал", "detail")
    platform.require_ready(channel).mark_refused(FakePlatform.default_channel_info(channel), error)
    for _ in range(2):
        with pytest.raises(ChannelBindingError) as raised:
            platform.list_upcoming(channel)
        assert raised.value is error and str(raised.value) == "не тот канал"
    assert fake.list_calls == []
    assert platform.thumbnail_refusal(channel) is None


def test_failed_channel_raises_the_platform_error(livecraft_paths: LivecraftPaths) -> None:
    fake: FakePlatform = FakePlatform()
    fake.fail_describe["yt_ua"] = PlatformError("backendError", "503")
    platform: VerifiedPlatform = started(fake, livecraft_paths)
    with pytest.raises(PlatformError) as raised:
        platform.get_stream(two_channels()[0], "S1")
    assert raised.value.code == "backendError"
    assert fake.stream_calls == []


def test_every_method_of_the_platform_asks_the_channel_first(livecraft_paths: LivecraftPaths) -> None:
    """Канал не READY — ни один метод площадки до подделки не доходит; вход и сброс через шлюз ничего не делают."""
    fake: FakePlatform = FakePlatform()
    fake.fail_describe["yt_ua"] = PlatformError("backendError", "503")
    platform: VerifiedPlatform = started(fake, livecraft_paths)
    channel: ChannelConfig = two_channels()[0]
    calls = (
        lambda: platform.update_broadcast(channel, "B1", SPEC),
        lambda: platform.attach_stream(channel, "B1", SPEC),
        lambda: platform.set_stream_marker(channel, "S1", SPEC.marker),
        lambda: platform.set_thumbnail(channel, "B1", b"jpeg"),
        lambda: platform.read_facts(channel, "B1"),
    )
    for call in calls:
        with pytest.raises(PlatformError):
            call()
    platform.keep_login(channel)
    platform.drop_login(channel)
    assert (fake.updated, fake.attached, fake.markers_set, fake.thumbnail_attempts, fake.facts_calls) == ([],) * 5
    assert fake.dropped_logins == [] and fake.kept_logins == []


def test_notices_carry_channel_warnings_of_the_run(livecraft_paths: LivecraftPaths) -> None:
    fake: FakePlatform = FakePlatform()
    book: ChannelBook = ChannelBook(fake, channel_sync(fake, livecraft_paths))
    platform: VerifiedPlatform = VerifiedPlatform(fake, book)
    fake.seed_undated_broadcast("yt_ua", "Без времени")
    book.sync.add_warning("предупреждение канала")
    notices: tuple[PlatformNotice, ...] = platform.take_notices()
    assert [notice.kind for notice in notices] == [PlatformNoticeKind.UNDATED_BROADCAST, PlatformNoticeKind.CHANNEL]
    assert notices[1].text == "предупреждение канала"
    assert platform.take_notices() == ()


def test_limits_come_from_the_wrapped_platform(livecraft_paths: LivecraftPaths) -> None:
    fake: FakePlatform = FakePlatform()
    platform: VerifiedPlatform = VerifiedPlatform(fake, ChannelBook(fake, channel_sync(fake, livecraft_paths)))
    assert platform.limits == fake.limits
