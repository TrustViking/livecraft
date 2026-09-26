from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config.channel import (
    ChannelConfig,
    ChannelHandle,
    ChannelKey,
    ChannelProblem,
    ConfiguredChannels,
    Platform,
    Privacy,
)
from app.config.files import ChannelsFile
from app.config.json_node import ConfigError, ConfigProblem, SettingProblem
from app.tests.fixtures.config import REPO_CHANNELS_EXAMPLE, channel_data, channels_data, channels_error, write_json
from app.ui import messages_ru as msg

EXAMPLE: ConfiguredChannels = ChannelsFile(REPO_CHANNELS_EXAMPLE, Path("previous.json")).load()


def _load(tmp_path: Path, *channels: dict[str, Any]) -> ConfiguredChannels:
    path: Path = write_json(tmp_path / "channels.json", {"channels": list(channels)})
    return ChannelsFile(path, tmp_path / "channels.previous.json").load()


def _error(tmp_path: Path, *channels: dict[str, Any]) -> ConfigError:
    return channels_error(tmp_path, {"channels": list(channels)})


def test_the_channels_example_loads() -> None:
    assert [channel.handle for channel in EXAMPLE.channels] == ["@kanal_ua", "@kanal_ru"]
    assert EXAMPLE.channels[1].languages == ("ru",)
    assert EXAMPLE.channels[0].privacy is Privacy.PUBLIC and EXAMPLE.channels[1].privacy is Privacy.UNLISTED
    assert all(channel.platform is Platform.YOUTUBE for channel in EXAMPLE.channels)


def test_the_channel_data_keep_the_key_order_of_the_file() -> None:
    keys: tuple[str, ...] = ("platform", "account_name", "handle", "google_account", "languages", "privacy")
    assert ChannelKey.leaves() == keys
    assert all(tuple(channel.to_data()) == keys for channel in EXAMPLE.channels)
    assert EXAMPLE.to_data() == channels_data()


@pytest.mark.parametrize("key", [key.value for key in ChannelKey])
def test_every_channel_field_is_required(tmp_path: Path, key: str) -> None:
    channel: dict[str, Any] = channel_data()
    del channel[key]
    error: ConfigError = _error(tmp_path, channel)
    assert error.key_path == f"channels[0].{key}" and error.reason is ConfigProblem.FIELD_MISSING


def test_a_missing_channels_file_is_reported_as_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        ChannelsFile(tmp_path / "channels.json", tmp_path / "previous.json").load()
    assert raised.value.reason is ConfigProblem.FILE_MISSING


def test_an_empty_channel_list_is_an_error(tmp_path: Path) -> None:
    assert channels_error(tmp_path, {"channels": []}).key_path == "channels"


# --- ник — ключ канала (§6 инвариант 5)


@pytest.mark.parametrize(
    "handle",
    [
        "@ab",                    # короче 3 символов после @
        "@" + "a" * 31,           # длиннее 30
        "kanal_ua",               # без @
        "@kanal ua",              # пробел
        "@kanal/ua",              # запрещённый символ
        "@kanal?ua",
        "@kanal\tua",             # управляющий символ
    ],
)
def test_a_bad_handle_is_an_error(tmp_path: Path, handle: str) -> None:
    error: ConfigError = _error(tmp_path, channel_data(handle=handle))
    assert error.key_path == "channels[0].handle" and error.problem == ChannelHandle.of(handle).problem


def test_the_handle_rule_is_one_object() -> None:
    assert ChannelHandle.of("@Kanal_UA").key == "kanal_ua"
    assert ChannelHandle.of("@kanal_ua").problem is None
    assert ChannelHandle.of("kanal").problem == msg.CONFIG_PROBLEM_HANDLE_PREFIX.format(value="kanal", prefix="@")
    decomposed: str = "@кӑнал"
    assert ChannelHandle.of(decomposed).text == "@кӑнал"


def test_the_channel_key_is_the_normalized_handle(tmp_path: Path) -> None:
    assert [channel.key for channel in EXAMPLE.channels] == ["kanal_ua", "kanal_ru"]
    assert _load(tmp_path, channel_data(handle="@Kanal_UA")).channels[0].key == "kanal_ua"


def test_a_repeated_handle_is_an_error_whatever_the_case(tmp_path: Path) -> None:
    """Ник — ключ канала; большие и маленькие буквы не различаются (§6 инвариант 5)."""
    error: ConfigError = _error(tmp_path, channel_data(handle="@Kanal_UA"), channel_data(handle="@kanal_ua"))
    assert error.key_path == "channels[1].handle"
    assert error.problem == msg.CONFIG_PROBLEM_HANDLE_DUPLICATE.format(value="@kanal_ua", other="@Kanal_UA")


def test_a_repeat_is_found_before_a_later_broken_channel(tmp_path: Path) -> None:
    """Повтор ника называется у повторившего канала — раньше, чем поломка следующего."""
    broken: dict[str, Any] = channel_data(handle="@third", privacy="private")
    error: ConfigError = _error(tmp_path, channel_data(), channel_data(), broken)
    assert error.key_path == "channels[1].handle"


def test_the_list_knows_its_repeated_handle() -> None:
    one: ChannelConfig = EXAMPLE.channels[0]
    repeated: ConfiguredChannels = ConfiguredChannels(channels=(one, EXAMPLE.channels[1], one))
    text: str = msg.CONFIG_PROBLEM_HANDLE_DUPLICATE.format(value=one.handle, other=one.handle)
    assert repeated.problem == ChannelProblem(index=2, problem=SettingProblem(key="handle", text=text))
    assert EXAMPLE.problem is None


def test_equal_account_names_are_allowed(tmp_path: Path) -> None:
    assert len(_load(tmp_path, channel_data(handle="@one_ch"), channel_data(handle="@two_ch")).channels) == 2


# --- поля канала


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, " Канал", "Канал ", "Канал\nUA"])
def test_a_bad_account_name_is_an_error(tmp_path: Path, name: str) -> None:
    assert _error(tmp_path, channel_data(account_name=name)).key_path == "channels[0].account_name"


def test_the_account_name_is_stored_in_nfc(tmp_path: Path) -> None:
    decomposed: str = "Канал й"          # «й» двумя символами
    assert _load(tmp_path, channel_data(account_name=decomposed)).channels[0].account_name == "Канал й"


@pytest.mark.parametrize("account", ["you", "you@", "@gmail.com", "you@@gmail.com", "you@gm ail.com", ""])
def test_a_bad_google_account_is_an_error(tmp_path: Path, account: str) -> None:
    assert _error(tmp_path, channel_data(google_account=account)).key_path == "channels[0].google_account"


def test_the_channel_names_its_first_problem_in_field_order() -> None:
    channel: ChannelConfig = ChannelConfig(
        platform=Platform.YOUTUBE, account_name=" Канал", handle="kanal", google_account="you",
        languages=("uk",), privacy=Privacy.PUBLIC,
    )
    assert channel.problem is not None and channel.problem.key == "account_name"


@pytest.mark.parametrize("languages", [[], "uk", ["UK"], [" uk"], [""], [1], ["uk", "uk"]])
def test_bad_languages_are_an_error(tmp_path: Path, languages: Any) -> None:
    assert _error(tmp_path, channel_data(languages=languages)).key_path == "channels[0].languages"


@pytest.mark.parametrize("code", ["uk", "en", "ru"])
def test_an_iso_639_1_code_is_a_language(tmp_path: Path, code: str) -> None:
    assert _load(tmp_path, channel_data(languages=[code])).channels[0].languages == (code,)


@pytest.mark.parametrize("code", ["uk-ua", "ukr", "UK", " uk", "xx", "", 5])
def test_a_code_outside_iso_639_1_is_named_in_the_problem(tmp_path: Path, code: Any) -> None:
    """Код вне справочника канал молча оставил бы без слотов: проблема называет само значение."""
    error: ConfigError = _error(tmp_path, channel_data(languages=["uk", code]))
    assert error.key_path == "channels[0].languages"
    assert error.problem == msg.CONFIG_PROBLEM_LANGUAGE_UNKNOWN.format(value=code)
    assert f"«{code}»" in error.problem


@pytest.mark.parametrize("languages", [[], "uk", None, {"uk": 1}])
def test_languages_that_are_not_a_list_keep_the_list_rule(tmp_path: Path, languages: Any) -> None:
    error: ConfigError = _error(tmp_path, channel_data(languages=languages))
    assert (error.key_path, error.problem) == ("channels[0].languages", msg.CONFIG_PROBLEM_LANGUAGES)


@pytest.mark.parametrize("platform", ["facebook", "rumble", "YouTube", ""])
def test_an_unknown_platform_is_an_error(tmp_path: Path, platform: str) -> None:
    """Площадки v1 — только YouTube (§1)."""
    assert _error(tmp_path, channel_data(platform=platform)).key_path == "channels[0].platform"


@pytest.mark.parametrize("privacy", ["private", "Public", "", None])
def test_an_unknown_privacy_is_an_error(tmp_path: Path, privacy: Any) -> None:
    assert _error(tmp_path, channel_data(privacy=privacy)).key_path == "channels[0].privacy"


# --- список каналов


def test_the_served_languages_are_the_languages_of_all_channels() -> None:
    """Одно правило «языки каналов» — для сводки и для отбора слотов по каналам."""
    assert EXAMPLE.served_languages == ("ru", "uk")


def test_channels_are_found_by_the_key_of_their_handle() -> None:
    assert EXAMPLE.by_handle["kanal_ru"] is EXAMPLE.channels[1]
    assert tuple(EXAMPLE.by_handle) == ("kanal_ua", "kanal_ru")
