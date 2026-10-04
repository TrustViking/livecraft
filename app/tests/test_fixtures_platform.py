from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config.channel import ChannelConfig
from app.config.files import ShippedSettings
from app.core.youtube_video import YouTubeVideoId
from app.platforms.broadcast import BroadcastFacts, CreatedBroadcast, UpcomingBroadcast
from app.platforms.error import PlatformError
from app.platforms.placeholder import PlaceholderMark
from app.platforms.spec import BroadcastSpec
from app.platforms.stream import StreamInfo
from app.platforms.video import VideoFixes, VideoSettings
from app.platforms.youtube import YOUTUBE_STREAM_KEY_PATTERN
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.fixtures.platform import CHECKED_AT, FakeCall, FakePlatform, fake_key, two_channels

TOMORROW: datetime = CHECKED_AT + timedelta(days=1)


def stream_slot(start: datetime = TOMORROW, title: str = "Эфир", description: str = "Опис") -> StreamSlot:
    texts: SlotTexts = SlotTexts(title=title, description=description, origin=SlotTextOrigin.SOURCE_SINGLE)
    return StreamSlot(SlotKey(start, "uk"), texts, (), ("https://www.youtube.com/watch?v=dQw4w9WgXcQ",))


def spec_of(platform: FakePlatform, slot: StreamSlot, channel: ChannelConfig) -> BroadcastSpec:
    """Площадка получает спеку, а не слот."""
    return BroadcastSpec.from_slot(slot, platform.limits, channel, ShippedSettings().settings)


@pytest.fixture
def fake() -> FakePlatform:
    return FakePlatform()


def test_seed_with_marker_creates_bound_stream(fake: FakePlatform) -> None:
    channel, _ = two_channels()
    seeded: UpcomingBroadcast = fake.seed_broadcast(
        channel.handle, TOMORROW, "Название", "Описание", marker="17-03-2027_1200_uk"
    )
    [listed] = fake.list_upcoming(channel)
    assert listed == seeded
    assert listed.start_utc.utcoffset() == timedelta(0)
    assert listed.stream_id is not None
    stream: StreamInfo | None = fake.get_stream(channel, listed.stream_id)
    assert stream is not None and stream.title == "17-03-2027_1200_uk"
    assert YOUTUBE_STREAM_KEY_PATTERN.fullmatch(stream.stream_name)


def test_seed_without_marker_has_no_stream(fake: FakePlatform) -> None:
    channel, _ = two_channels()
    fake.seed_broadcast("yt_ua", CHECKED_AT, "Ручной", "")
    [listed] = fake.list_upcoming(channel)
    assert listed.stream_id is None


def test_create_broadcast_is_deterministic_and_marked(fake: FakePlatform) -> None:
    channel, _ = two_channels()
    slot: StreamSlot = stream_slot()
    created: CreatedBroadcast = fake.create_broadcast(channel, spec_of(fake, slot, channel))
    assert created.broadcast_id == "fakebc00001"
    assert created.broadcast_url == YouTubeVideoId("fakebc00001").watch_url == "https://www.youtube.com/watch?v=fakebc00001"
    assert (created.stream_url, created.stream_key) == ("rtmp://a.rtmp.youtube.com/live2", "fake-0001-0000-0000-0000")
    assert YOUTUBE_STREAM_KEY_PATTERN.fullmatch(created.stream_key)
    [listed] = fake.list_upcoming(channel)
    assert (listed.title, listed.description, listed.start_utc) == (slot.title, slot.description, slot.start)
    stream: StreamInfo | None = fake.get_stream(channel, created.stream_id)
    assert stream is not None and stream.title == slot.slot_id
    assert fake.created == [FakeCall("yt_ua", created.broadcast_id, slot.slot_id, None)]


def test_update_changes_texts_and_unknown_broadcast_fails(fake: FakePlatform) -> None:
    channel, _ = two_channels()
    slot: StreamSlot = stream_slot(title="Новое", description="Новое описание")
    seeded: UpcomingBroadcast = fake.seed_broadcast(channel.handle, slot.start, "Старое", "Старое описание")
    fake.update_broadcast(channel, seeded.broadcast_id, spec_of(fake, slot, channel))
    [listed] = fake.list_upcoming(channel)
    assert (listed.title, listed.description) == ("Новое", "Новое описание")
    assert fake.updated == [FakeCall("yt_ua", seeded.broadcast_id, slot.slot_id, None)]
    with pytest.raises(PlatformError):
        fake.update_broadcast(channel, "nope", spec_of(fake, slot, channel))


def test_failures_are_configurable(fake: FakePlatform) -> None:
    channel, _ = two_channels()
    slot: StreamSlot = stream_slot()
    fake.fail_list[channel.key] = PlatformError("quotaExceeded", "квота")
    fake.fail_create[slot.slot_id] = PlatformError("liveStreamingNotEnabled", "трансляции выключены")
    with pytest.raises(PlatformError) as listed:
        fake.list_upcoming(channel)
    with pytest.raises(PlatformError) as created:
        fake.create_broadcast(channel, spec_of(fake, slot, channel))
    assert (listed.value.code, created.value.code) == ("quotaExceeded", "liveStreamingNotEnabled")
    assert fake.created == []


def test_channels_are_isolated_and_named_by_handle_or_key(fake: FakePlatform) -> None:
    first, second = two_channels()
    fake.seed_broadcast("@YT_UA", CHECKED_AT, "Первый", "")
    assert fake.list_upcoming(second) == []
    assert [item.title for item in fake.list_upcoming(first)] == ["Первый"]
    assert fake.list_calls == ["yt_ru", "yt_ua"]
    assert fake_key("@YT_UA") == fake_key("yt_ua") == "yt_ua"


def test_new_broadcast_shows_channel_placeholder_until_thumbnail_is_set(fake: FakePlatform) -> None:
    """Как у площадки: картинка нового эфира — заглушка канала, её метка — в описании потока."""
    channel, _ = two_channels()
    created: CreatedBroadcast = fake.create_broadcast(channel, spec_of(fake, stream_slot(), channel))
    [listed] = fake.list_upcoming(channel)
    placeholder: str = fake.placeholder_of(channel.handle)
    assert listed.thumbnail_sha == placeholder
    stream: StreamInfo | None = fake.get_stream(channel, created.stream_id)
    assert stream is not None and PlaceholderMark.found_in(stream.description) == PlaceholderMark(placeholder)
    fake.set_thumbnail(channel, created.broadcast_id, b"preview")
    [listed] = fake.list_upcoming(channel)
    assert listed.thumbnail_sha == PlaceholderMark.of(b"preview").sha


def test_video_settings_write_once_and_say_what_was_written(fake: FakePlatform) -> None:
    channel, _ = two_channels()
    created: CreatedBroadcast = fake.create_broadcast(channel, spec_of(fake, stream_slot(), channel))
    settings: VideoSettings = VideoSettings(language="uk", category_id="22", privacy="unlisted")
    fixes: VideoFixes = fake.apply_video_settings(channel, created.broadcast_id, settings)
    assert fixes.any_fix and fixes.applied is not None and fixes.applied.privacy == "unlisted"
    assert not fake.apply_video_settings(channel, created.broadcast_id, settings).any_fix
    assert fake.settings_writes == [created.broadcast_id]
    facts: BroadcastFacts = fake.read_facts(channel, created.broadcast_id)
    assert (facts.default_language, facts.privacy_status, facts.stream_marker) == ("uk", "unlisted", stream_slot().slot_id)
    assert facts.start_utc == TOMORROW.astimezone(timezone.utc)
