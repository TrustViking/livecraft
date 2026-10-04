from __future__ import annotations

from pathlib import Path

from app.config.channel import ChannelConfig, ConfiguredChannels
from app.config.files import ChannelsFile
from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.platforms.channel import Channel, ChannelStatus, LoginNeed
from app.platforms.channel_info import ChannelInfo
from app.platforms.channel_sync import ChannelSync
from app.platforms.error import PlatformError
from app.platforms.passport import ChannelPassport, ChannelVerification, PassportEntry
from app.tests.fixtures.platform import (
    FakePlatform,
    channel_info,
    channel_of,
    channel_sync,
    token_path,
    two_channels,
    written_channels,
    written_token,
)
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

OLD: str = "@yt_ua"
NEW: str = "@yt_ua_new"
CHANNEL_ID: str = "UCyt_ua"


def answer(platform: FakePlatform, key: str, channel: ChannelConfig, **changes: object) -> ChannelInfo:
    """Что YouTube отвечает на токен канала с ключом key: тот же id CHANNEL_ID, поля — из changes."""
    info: ChannelInfo = channel_info(channel, youtube_channel_id=CHANNEL_ID, **changes)
    platform.channel_info[key] = info
    return info


def seed_passport(paths: LivecraftPaths, channel: ChannelConfig) -> None:
    passport: ChannelPassport = ChannelPassport(paths.file(FileName.PASSPORT))
    info: ChannelInfo = channel_info(channel, youtube_channel_id=CHANNEL_ID)
    token: str = token_path(paths, channel.handle).name
    passport.record_verified(ChannelVerification(channel, channel, info, token, "01-09-2026 10:00"))
    assert passport.save() is None


def statuses(sync: ChannelSync) -> dict[str, ChannelStatus]:
    return {channel.key: channel.status for channel in sync.take_channels()}


def entry(paths: LivecraftPaths, key: str) -> PassportEntry | None:
    return ChannelPassport.load(paths.file(FileName.PASSPORT)).find_by_key(key)


def aligned(title_before: str, handle_before: str, title_after: str, handle_after: str) -> str:
    return msg.WARNING_CHANNEL_ALIGNED.format(
        youtube_channel_id=CHANNEL_ID, title_before=title_before, handle_before=handle_before,
        title_after=title_after, handle_after=handle_after,
    )


def test_title_changed_on_youtube_is_aligned(livecraft_paths: LivecraftPaths) -> None:
    channel: ChannelConfig = channel_of(OLD, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    before: bytes = livecraft_paths.file(FileName.CHANNELS).read_bytes()
    token: Path = written_token(livecraft_paths, OLD)
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", channel, title="Новое название")
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    synced: ConfiguredChannels = sync.run(channels)
    assert [item.account_name for item in synced.channels] == ["Новое название"]
    assert [item.account_name for item in ChannelsFile.of(livecraft_paths).load().channels] == ["Новое название"]
    assert livecraft_paths.file(FileName.CHANNELS_PREVIOUS).read_bytes() == before
    assert token.read_text(encoding="utf-8") == "token"
    found: PassportEntry | None = entry(livecraft_paths, "yt_ua")
    assert found is not None and found.account_name == "Новое название" and found.previous_titles == ("Канал UA",)
    assert sync.take_warnings() == [aligned("Канал UA", OLD, "Новое название", OLD)]
    assert platform.logins == [] and platform.describe_without_login == ["yt_ua"]


def test_new_channel_with_handle_for_title_gets_the_youtube_title(livecraft_paths: LivecraftPaths) -> None:
    """§14 решение 25: окно пишет вместо названия ник без «@» — проверка ставит название с YouTube."""
    channel: ChannelConfig = channel_of(OLD, "yt_ua")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    written_token(livecraft_paths, OLD)
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", channel, title="Українка Я")
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    assert [item.account_name for item in sync.run(channels).channels] == ["Українка Я"]
    [ready] = sync.take_channels()
    assert (ready.status, ready.config.account_name) == (ChannelStatus.READY, "Українка Я")


def test_handle_changed_on_youtube_is_aligned_by_passport(livecraft_paths: LivecraftPaths) -> None:
    channel: ChannelConfig = channel_of(OLD, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    seed_passport(livecraft_paths, channel)
    written_token(livecraft_paths, OLD)
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", channel, handle_raw="@YT_UA_new")
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    synced: ConfiguredChannels = sync.run(channels)
    assert [item.handle for item in synced.channels] == ["@YT_UA_new"]     # написание — как прислал YouTube
    [ready] = sync.take_channels()
    assert (ready.key, ready.status, ready.config) == ("yt_ua_new", ChannelStatus.READY, synced.channels[0])
    assert ready.token_file == token_path(livecraft_paths, "@YT_UA_new")
    assert not token_path(livecraft_paths, OLD).exists()
    assert token_path(livecraft_paths, "@YT_UA_new").read_text(encoding="utf-8") == "token"
    assert entry(livecraft_paths, "yt_ua") is None
    found: PassportEntry | None = entry(livecraft_paths, "yt_ua_new")
    assert found is not None
    assert (found.previous_handles, found.token_file, found.first_verified_at) == (
        (OLD,), "@YT_UA_new.token.json", "01-09-2026 10:00"
    )
    assert sync.take_warnings() == [aligned("Канал UA", OLD, "Канал UA", "@YT_UA_new")]
    assert platform.logins == []


def test_foreign_token_is_dropped_at_start(livecraft_paths: LivecraftPaths) -> None:
    """Живой прогон planers 17-09-2026: токен вёл на канал с другим ником, паспорт этого не подтверждает — файл
    удалён, NEEDS_LOGIN."""
    channel: ChannelConfig = channel_of(OLD, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    before: bytes = livecraft_paths.file(FileName.CHANNELS).read_bytes()
    token: Path = written_token(livecraft_paths, OLD)
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", channel, handle_raw="@lisathomson-v3l", title="Lisa Thomson")
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    assert sync.run(channels) == channels and livecraft_paths.file(FileName.CHANNELS).read_bytes() == before
    assert not token.exists()
    assert sync.take_warnings() == [
        msg.WARNING_TOKEN_REJECTED.format(
            account_name="Канал UA", handle=OLD, youtube_title="Lisa Thomson",
            youtube_handle="@lisathomson-v3l", youtube_channel_id=CHANNEL_ID,
        )
    ]
    assert statuses(sync) == {"yt_ua": ChannelStatus.NEEDS_LOGIN}
    assert platform.dropped_logins == ["yt_ua"] and platform.logins == []


def test_same_handle_with_other_id_in_passport_drops_the_token(livecraft_paths: LivecraftPaths) -> None:
    channel: ChannelConfig = channel_of(OLD, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    seed_passport(livecraft_paths, channel)
    token: Path = written_token(livecraft_paths, OLD)
    platform: FakePlatform = FakePlatform()
    platform.channel_info["yt_ua"] = channel_info(channel, youtube_channel_id="UCother")
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    sync.run(channels)
    assert not token.exists()
    assert statuses(sync) == {"yt_ua": ChannelStatus.NEEDS_LOGIN}


def test_channel_without_handle_confirmed_by_passport_is_refused_and_token_kept(
    livecraft_paths: LivecraftPaths,
) -> None:
    """Паспорт подтверждает id, но ника на YouTube нет: токен свой — не удаляется, канал — отказ."""
    channel: ChannelConfig = channel_of(OLD, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    seed_passport(livecraft_paths, channel)
    token: Path = written_token(livecraft_paths, OLD)
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", channel, handle_raw=None)
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    sync.run(channels)
    assert token.exists() and sync.take_warnings() == []
    [refused] = sync.take_channels()
    assert refused.status is ChannelStatus.REFUSED
    assert refused.error is not None and refused.error.code == "channelHandleMissing"
    assert str(refused.error).startswith("канал «Канал UA» @yt_ua: у канала YouTube «Канал UA» (id UCyt_ua) нет ника")


def test_handle_fixed_by_hand_finds_token_under_old_handle(livecraft_paths: LivecraftPaths) -> None:
    old_channel: ChannelConfig = channel_of(OLD, "Канал UA")
    seed_passport(livecraft_paths, old_channel)
    written_token(livecraft_paths, OLD)
    new_channel: ChannelConfig = channel_of(NEW, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, new_channel)
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", old_channel, handle_raw=NEW)       # токен старого файла ведёт на канал с новым ником
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    assert sync.run(channels).channels == channels.channels
    assert statuses(sync) == {"yt_ua_new": ChannelStatus.READY}
    assert not token_path(livecraft_paths, OLD).exists()
    assert token_path(livecraft_paths, NEW).read_text(encoding="utf-8") == "token"
    found: PassportEntry | None = entry(livecraft_paths, "yt_ua_new")
    assert found is not None and found.previous_handles == (OLD,) and entry(livecraft_paths, "yt_ua") is None
    assert sync.take_warnings() == [aligned("Канал UA", NEW, "Канал UA", NEW)]
    assert platform.logins == [] and platform.describe_without_login == ["yt_ua"]


def test_existing_target_token_blocks_the_rename(livecraft_paths: LivecraftPaths) -> None:
    channel: ChannelConfig = channel_of(OLD, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    before: bytes = livecraft_paths.file(FileName.CHANNELS).read_bytes()
    seed_passport(livecraft_paths, channel)
    written_token(livecraft_paths, OLD, "old")
    written_token(livecraft_paths, NEW, "other")
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", channel, handle_raw=NEW)
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    assert sync.run(channels) == channels and livecraft_paths.file(FileName.CHANNELS).read_bytes() == before
    assert token_path(livecraft_paths, OLD).read_text(encoding="utf-8") == "old"
    assert token_path(livecraft_paths, NEW).read_text(encoding="utf-8") == "other"
    assert sync.take_warnings() == [
        msg.WARNING_TOKEN_RENAME_SKIPPED.format(
            account_name="Канал UA", handle=OLD, youtube_channel_id=CHANNEL_ID, handle_after=NEW,
            target=token_path(livecraft_paths, NEW),
        )
    ]
    found: PassportEntry | None = entry(livecraft_paths, "yt_ua")
    assert found is not None and found.handle == OLD


def test_unwritable_channels_file_puts_the_token_back(livecraft_paths: LivecraftPaths) -> None:
    """channels.json не записался: файл токена возвращается под прежний ник, файлы не тронуты."""
    channel: ChannelConfig = channel_of(OLD, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    seed_passport(livecraft_paths, channel)
    written_token(livecraft_paths, OLD)
    livecraft_paths.file(FileName.CHANNELS).unlink()
    livecraft_paths.file(FileName.CHANNELS).mkdir()             # на месте файла — папка: не читается и не пишется
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", channel, handle_raw=NEW)
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    assert sync.run(channels) == channels
    assert token_path(livecraft_paths, OLD).read_text(encoding="utf-8") == "token"
    assert not token_path(livecraft_paths, NEW).exists()
    [warning] = sync.take_warnings()
    assert warning.startswith(msg.WARNING_CHANNEL_ALIGN_FAILED.split("{reason}", 1)[0].format(
        account_name="Канал UA", handle=OLD, youtube_channel_id=CHANNEL_ID
    ))


def test_channel_without_token_is_not_asked_at_all(livecraft_paths: LivecraftPaths) -> None:
    channels: ConfiguredChannels = written_channels(livecraft_paths, *two_channels())
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua", "yt_ru"}
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    assert sync.run(channels) == channels and sync.take_warnings() == []
    assert statuses(sync) == {"yt_ua": ChannelStatus.NEEDS_LOGIN, "yt_ru": ChannelStatus.NEEDS_LOGIN}
    assert platform.describe_calls == [] and platform.logins == []
    assert not livecraft_paths.file(FileName.PASSPORT).exists()


def test_describe_failure_skips_the_channel(livecraft_paths: LivecraftPaths) -> None:
    """Сверка без браузера: сбой площадки — FAILED, отозванный токен — NEEDS_LOGIN, вход не открывается."""
    channels: ConfiguredChannels = written_channels(livecraft_paths, *two_channels())
    for channel in channels.channels:
        written_token(livecraft_paths, channel.handle)
    platform: FakePlatform = FakePlatform()
    platform.fail_describe["yt_ua"] = PlatformError("backendError", "503")
    platform.tokens_missing = {"yt_ru"}                          # токен отозван: нужен вход, но не сейчас
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    assert sync.run(channels) == channels and sync.take_warnings() == []
    assert platform.logins == []
    assert platform.describe_without_login == ["yt_ua", "yt_ru"]
    found: dict[str, Channel] = {channel.key: channel for channel in sync.take_channels()}
    assert found["yt_ua"].status is ChannelStatus.FAILED
    assert found["yt_ua"].error is not None and found["yt_ua"].error.code == "backendError"
    assert found["yt_ru"].status is ChannelStatus.NEEDS_LOGIN


# --- причина входа (LoginNeed): строка лога login_needed при старте


def test_channel_without_token_needs_a_first_login(livecraft_paths: LivecraftPaths) -> None:
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel_of(OLD, "Канал UA"))
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua"}
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    with LogCapture.on(LogArea.PLATFORMS) as log:
        sync.run(channels)
    [channel] = sync.take_channels()
    assert (channel.status, channel.login_need) == (ChannelStatus.NEEDS_LOGIN, LoginNeed.NO_TOKEN)
    assert 'login_needed channel="Канал UA" handle=@yt_ua reason=no_token' in log.messages()


def test_revoked_token_needs_a_login_again(livecraft_paths: LivecraftPaths) -> None:
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel_of(OLD, "Канал UA"))
    written_token(livecraft_paths, OLD)
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua"}                          # Google токен больше не принимает
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    with LogCapture.on(LogArea.PLATFORMS) as log:
        sync.run(channels)
    [channel] = sync.take_channels()
    assert (channel.status, channel.login_need) == (ChannelStatus.NEEDS_LOGIN, LoginNeed.TOKEN_REVOKED)
    assert 'login_needed channel="Канал UA" handle=@yt_ua reason=token_revoked' in log.messages()


def test_foreign_token_needs_a_login_as_foreign(livecraft_paths: LivecraftPaths) -> None:
    channel: ChannelConfig = channel_of(OLD, "Канал UA")
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel)
    written_token(livecraft_paths, OLD)
    platform: FakePlatform = FakePlatform()
    answer(platform, "yt_ua", channel, handle_raw="@lisathomson-v3l", title="Lisa Thomson")
    sync: ChannelSync = channel_sync(platform, livecraft_paths)
    with LogCapture.on(LogArea.PLATFORMS) as log:
        sync.run(channels)
    [found] = sync.take_channels()
    assert (found.status, found.login_need) == (ChannelStatus.NEEDS_LOGIN, LoginNeed.FOREIGN_TOKEN)
    assert any(line.endswith("reason=foreign_token") for line in log.messages())


def test_a_ready_channel_writes_no_login_line(livecraft_paths: LivecraftPaths) -> None:
    channels: ConfiguredChannels = written_channels(livecraft_paths, channel_of(OLD, "Канал UA"))
    written_token(livecraft_paths, OLD)
    sync: ChannelSync = channel_sync(FakePlatform(), livecraft_paths)
    with LogCapture.on(LogArea.PLATFORMS) as log:
        sync.run(channels)
    assert statuses(sync) == {"yt_ua": ChannelStatus.READY}
    assert not any(line.startswith("login_needed") for line in log.messages())
