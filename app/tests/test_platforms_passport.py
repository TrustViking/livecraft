from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.config.channel import ChannelConfig, ConfiguredChannels
from app.paths import FileName, LivecraftPaths
from app.platforms.channel_info import ChannelInfo
from app.platforms.passport import ENTRY_FIELDS, ChannelPassport, ChannelVerification, PassportEntry
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.platform import (
    CHECKED_AT,
    FakePlatform,
    changed_channel,
    channel_info,
    channel_sync,
    token_path,
    two_channels,
    written_channels,
)
from app.ui import messages_ru as msg


@pytest.fixture
def channels(livecraft_paths: LivecraftPaths) -> ConfiguredChannels:
    """Корень как у владельца: channels.json и токены обоих каналов."""
    configured: ConfiguredChannels = written_channels(livecraft_paths, *two_channels())
    for channel in configured.channels:
        token_path(livecraft_paths, channel.handle).write_text("{}", encoding="utf-8")
    return configured


def passport_json(paths: LivecraftPaths) -> dict[str, Any]:
    return json.loads(paths.file(FileName.PASSPORT).read_text(encoding="utf-8"))


def test_first_check_records_every_field_and_links(livecraft_paths: LivecraftPaths, channels: ConfiguredChannels) -> None:
    channel_sync(FakePlatform(), livecraft_paths).run(channels)
    raw: dict[str, Any] = passport_json(livecraft_paths)
    assert [entry["handle"] for entry in raw["channels"]] == ["@yt_ru", "@yt_ua"]     # по названию, затем нику
    entry: dict[str, Any] = raw["channels"][1]
    assert tuple(entry) == ENTRY_FIELDS
    assert entry == {
        "handle": "@yt_ua",
        "account_name": "yt_ua",
        "youtube_channel_id": "UCfakeyt_ua",
        "youtube_title": "yt_ua",
        "youtube_handle_raw": "@yt_ua",
        "google_account": "owner@gmail.com",
        "token_file": "@yt_ua.token.json",
        "channel_url": "https://www.youtube.com/channel/UCfakeyt_ua",
        "handle_url": "https://www.youtube.com/@yt_ua",
        "first_verified_at": "16-03-2027 12:00",
        "last_verified_at": "16-03-2027 12:00",
        "previous_handles": [],
        "previous_titles": [],
    }
    assert livecraft_paths.file(FileName.PASSPORT).read_text(encoding="utf-8").endswith("}\n")


def test_repeated_check_keeps_first_time_and_updates_last(
    livecraft_paths: LivecraftPaths, channels: ConfiguredChannels
) -> None:
    channel_sync(FakePlatform(), livecraft_paths, StoppedClock.at(CHECKED_AT - timedelta(days=15))).run(channels)
    channel_sync(FakePlatform(), livecraft_paths).run(channels)
    entry: dict[str, Any] = passport_json(livecraft_paths)["channels"][1]
    assert (entry["first_verified_at"], entry["last_verified_at"]) == ("01-03-2027 12:00", "16-03-2027 12:00")


@pytest.mark.parametrize(
    "text",
    ["{broken", '["a"]', '{"channels": [{"handle": "@x"}]}', '{"channels": [], "extra": 1}'],
    ids=["broken_json", "not_object", "entry_fields", "extra_key"],
)
def test_unreadable_passport_is_reported_and_rewritten(
    livecraft_paths: LivecraftPaths, channels: ConfiguredChannels, text: str
) -> None:
    passport_file: Path = livecraft_paths.file(FileName.PASSPORT)
    passport_file.write_text(text, encoding="utf-8")
    loaded: ChannelPassport = ChannelPassport.load(passport_file)
    assert loaded.entries == () and loaded.problem is not None
    sync = channel_sync(FakePlatform(), livecraft_paths)
    sync.run(channels)
    assert sync.take_warnings() == [msg.WARNING_PASSPORT_UNREADABLE.format(path=passport_file)]
    assert [entry["handle"] for entry in passport_json(livecraft_paths)["channels"]] == ["@yt_ru", "@yt_ua"]


def test_passport_write_failure_is_a_warning_not_a_stop(
    livecraft_paths: LivecraftPaths, channels: ConfiguredChannels
) -> None:
    livecraft_paths.file(FileName.PASSPORT).mkdir()          # на месте файла — папка: запись не пройдёт
    sync = channel_sync(FakePlatform(), livecraft_paths)
    assert sync.run(channels) == channels
    [warning] = sync.take_warnings()
    assert warning.startswith(msg.WARNING_PASSPORT_WRITE_FAILED.split("{", 1)[0])
    assert str(livecraft_paths.file(FileName.PASSPORT)) in warning


def test_entries_of_channels_missing_from_the_list_are_kept(
    livecraft_paths: LivecraftPaths, channels: ConfiguredChannels
) -> None:
    channel_sync(FakePlatform(), livecraft_paths).run(channels)
    only_ua: ConfiguredChannels = written_channels(livecraft_paths, channels.channels[0])
    channel_sync(FakePlatform(), livecraft_paths).run(only_ua)
    assert [entry["handle"] for entry in passport_json(livecraft_paths)["channels"]] == ["@yt_ru", "@yt_ua"]


def test_record_replaces_entry_of_the_same_channel_id(tmp_path: Path) -> None:
    passport: ChannelPassport = ChannelPassport(tmp_path / "channels_passport.json")
    old: ChannelConfig = two_channels()[0]
    new: ChannelConfig = changed_channel(old, handle="@yt_ua_new", account_name="Новое")
    info: ChannelInfo = FakePlatform.default_channel_info(old)
    passport.record_verified(ChannelVerification(old, old, info, "@yt_ua.token.json", "01-01-2027 10:00"))
    renamed: ChannelInfo = channel_info(old, title="Новое")
    entry: PassportEntry = passport.record_verified(
        ChannelVerification(old, new, renamed, "@yt_ua_new.token.json", "02-01-2027 10:00")
    )
    assert passport.entries == (entry,)
    assert (entry.previous_handles, entry.previous_titles, entry.first_verified_at) == (
        ("@yt_ua",), ("yt_ua",), "01-01-2027 10:00"
    )
    assert passport.save() is None
    loaded: ChannelPassport = ChannelPassport.load(passport.path)
    assert loaded.problem is None and loaded.entries == (entry,)


def test_previous_handles_are_kept_once_by_key(tmp_path: Path) -> None:
    """Прежние ники — без повторов по ключу и без нынешнего; написание — первое встреченное."""
    passport: ChannelPassport = ChannelPassport(tmp_path / "channels_passport.json")
    first: ChannelConfig = two_channels()[0]
    second: ChannelConfig = changed_channel(first, handle="@YT_UA_2")
    third: ChannelConfig = changed_channel(first, handle="@yt_ua_3")
    info: ChannelInfo = FakePlatform.default_channel_info(first)
    passport.record_verified(ChannelVerification(first, second, info, "t", "01-01-2027 10:00"))
    passport.record_verified(ChannelVerification(changed_channel(first, handle="@Yt_Ua"), third, info, "t", "x"))
    [entry] = passport.entries
    assert entry.previous_handles == ("@yt_ua", "@YT_UA_2")


def test_passport_of_planers_is_read_as_is(tmp_path: Path) -> None:
    """Файл, записанный planers, читается без правок, и livecraft пишет его в том же виде."""
    path: Path = tmp_path / "channels_passport.json"
    planers_text: str = json.dumps(
        {
            "channels": [
                {
                    "handle": "@Kanal.X",
                    "account_name": "Kanal X",
                    "youtube_channel_id": "UC123",
                    "youtube_title": "Kanal X",
                    "youtube_handle_raw": None,
                    "google_account": "owner@example.com",
                    "token_file": "@Kanal.X.token.json",
                    "channel_url": "https://www.youtube.com/channel/UC123",
                    "handle_url": "https://www.youtube.com/@Kanal.X",
                    "first_verified_at": "13-09-2026 10:00",
                    "last_verified_at": "19-09-2026 18:30",
                    "previous_handles": ["@kanal"],
                    "previous_titles": [],
                }
            ]
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    path.write_text(planers_text, encoding="utf-8")
    passport: ChannelPassport = ChannelPassport.load(path)
    assert passport.problem is None
    assert passport.find_by_key("kanal.x") is not None and passport.find_by_channel_id("UC123") is not None
    assert passport.render() == planers_text
