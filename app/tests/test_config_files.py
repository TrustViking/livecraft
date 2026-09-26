from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from app.config.channel import ConfiguredChannels
from app.config.files import ChannelsFile, ConfigRead, SettingsFile, ShippedSettings
from app.config.json_node import ConfigError, ConfigProblem
from app.config.settings import LivecraftSettings
from app.core.text_format import TEXT_ENCODING
from app.paths import LivecraftPaths
from app.resources.loader import TextResource
from app.tests.fixtures.config import REPO_CHANNELS_EXAMPLE, channels_data, settings_data, with_pause
from app.tests.fixtures.logs import LogCapture
from app.observability.log_event import LogArea, get_logger
from app.ui import messages_ru as msg

SHIPPED: ShippedSettings = ShippedSettings()


def _channels_file(tmp_path: Path) -> ChannelsFile:
    return ChannelsFile(tmp_path / "channels.json", tmp_path / "channels.previous.json")


# --- поставочный вид livecraft.json: ресурс программы, файла в git нет (§5)


def test_the_shipped_template_is_a_resource_without_anyones_data() -> None:
    """Шаблон разбирается тем же разбором; поставка без чьих-либо данных (§14 решение 16)."""
    assert SHIPPED.template == TextResource("settings_shipped.json").body
    assert SHIPPED.settings.form.url == "" and not SHIPPED.settings.form.is_configured
    for forbidden in ("docs.google.com", "forms.gle"):
        assert forbidden not in SHIPPED.template


def test_the_rendered_shipped_settings_are_the_template_byte_for_byte() -> None:
    """Файл, который кладёт программа, и шаблон ресурса — один и тот же текст."""
    assert SettingsFile(Path("livecraft.json")).render(SHIPPED.settings) == SHIPPED.template


def test_install_creates_the_missing_file_from_the_template(tmp_path: Path) -> None:
    file: SettingsFile = SettingsFile(tmp_path / "livecraft.json")
    assert file.install_shipped() is True
    assert file.path.read_text(encoding=TEXT_ENCODING) == SHIPPED.template
    assert file.load() == SHIPPED.settings


def test_install_leaves_an_existing_file_alone(tmp_path: Path) -> None:
    """В файле — настройки человека или сломанный файл, который назовёт разбор: трогать нельзя."""
    file: SettingsFile = SettingsFile(tmp_path / "livecraft.json")
    for content in (b'{"keep_days": 7}', b"\xff not json"):
        file.path.write_bytes(content)
        assert file.install_shipped() is False
        assert file.path.read_bytes() == content


def test_a_broken_template_is_a_config_error_of_the_program(tmp_path: Path) -> None:
    """Негодный шаблон — ошибка программы: ConfigError с путём ключа и файлом ресурса, файл не пишется."""
    (tmp_path / "settings_shipped.json").write_text(SHIPPED.template.replace('"keep_days": 30', '"keep_days": 0'), encoding=TEXT_ENCODING)
    broken: ShippedSettings = ShippedSettings(resource=TextResource("settings_shipped.json", text_dir=tmp_path))
    with pytest.raises(ConfigError) as raised:
        broken.settings
    assert raised.value.key_path == "keep_days" and raised.value.config_path == tmp_path / "settings_shipped.json"


def test_before_the_settings_are_read_the_clock_runs_in_the_zone_of_the_shipped_template() -> None:
    """Замок, startup.log, имя лога и шапка ставят время до чтения настроек — по поясу поставочного шаблона."""
    assert SHIPPED.clock.zone == SHIPPED.settings.zone
    assert SHIPPED.clock.now().tzinfo == SHIPPED.settings.zone


# --- livecraft.json: чтение, разбор черновика, запись


def test_parsing_read_settings_data_equals_loading_the_file(tmp_path: Path) -> None:
    file: SettingsFile = SettingsFile(tmp_path / "livecraft.json")
    file.install_shipped()
    assert file.parse(settings_data()) == file.load()


def test_parsing_data_names_the_given_path_in_the_error(tmp_path: Path) -> None:
    """Путь файла разбору нужен только ошибке: она называет тот файл, который будет записан."""
    data: dict[str, Any] = settings_data()
    data["keep_days"] = 0
    path: Path = tmp_path / "livecraft.json"
    with pytest.raises(ConfigError) as raised:
        SettingsFile(path).parse(data)
    assert (raised.value.config_path, raised.value.key_path) == (path, "keep_days")


def test_parsing_data_with_nan_gives_the_same_error_as_the_file(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["youtube_pause_seconds"] = float("nan")
    with pytest.raises(ConfigError) as raised:
        SettingsFile(tmp_path / "livecraft.json").parse(data)
    assert (raised.value.key_path, raised.value.problem) == ("youtube_pause_seconds", msg.CONFIG_PROBLEM_NUMBER_FINITE)


def test_the_saved_settings_file_reads_back_into_an_equal_object(livecraft_paths: LivecraftPaths) -> None:
    file: SettingsFile = SettingsFile.of(livecraft_paths)
    file.save(SHIPPED.settings)
    assert file.load() == SHIPPED.settings
    assert file.path.read_text(encoding=TEXT_ENCODING) == SHIPPED.template


def test_rendering_settings_built_around_the_parser_with_nan_fails() -> None:
    """Страховка записи: нестандартного JSON в livecraft.json не бывает."""
    settings: LivecraftSettings = with_pause(SHIPPED.settings, float("nan"))
    with pytest.raises(ValueError):
        SettingsFile(Path("livecraft.json")).render(settings)


# --- channels.json: чтение, запись с копией прежнего


def test_parsing_read_channels_data_equals_loading_the_file() -> None:
    file: ChannelsFile = ChannelsFile(REPO_CHANNELS_EXAMPLE, Path("previous.json"))
    assert file.parse(channels_data()) == file.load()


def test_the_rendered_channels_file_is_the_example_and_reads_back(tmp_path: Path) -> None:
    channels: ConfiguredChannels = ChannelsFile(REPO_CHANNELS_EXAMPLE, Path("previous.json")).load()
    file: ChannelsFile = _channels_file(tmp_path)
    text: str = file.render(channels)
    assert text == REPO_CHANNELS_EXAMPLE.read_text(encoding=TEXT_ENCODING)
    assert "Канал UA" in text and "\\u" not in text
    file.path.write_text(text, encoding=TEXT_ENCODING)
    assert file.load() == channels


def test_saving_moves_the_previous_file_aside(livecraft_paths: LivecraftPaths) -> None:
    """Прежний channels.json байт в байт — в channels.previous.json; новый — тем же файлом каналов (§8.2)."""
    old: bytes = REPO_CHANNELS_EXAMPLE.read_bytes()
    file: ChannelsFile = ChannelsFile.of(livecraft_paths)
    file.path.write_bytes(old)
    first: ConfiguredChannels = ConfiguredChannels(channels=file.load().channels[:1])
    file.save(first)
    assert file.previous.read_bytes() == old
    assert file.load() == first


def test_saving_the_first_channels_file_needs_no_previous_one(livecraft_paths: LivecraftPaths) -> None:
    """Настройщик на чистой установке: прежнего файла нет — и сохранять в previous нечего."""
    channels: ConfiguredChannels = ChannelsFile(REPO_CHANNELS_EXAMPLE, Path("previous.json")).load()
    file: ChannelsFile = ChannelsFile.of(livecraft_paths)
    file.save(channels)
    assert file.load() == channels and not file.previous.exists()


def test_the_channels_template_loads_with_the_same_parser(tmp_path: Path) -> None:
    """Шаблон каналов из лога, вписанный как есть, проходит тот же разбор."""
    file: ChannelsFile = _channels_file(tmp_path)
    file.path.write_text(msg.CONFIG_CHANNELS_TEMPLATE, encoding=TEXT_ENCODING)
    assert len(file.load().channels) == 1
    assert file.template_lines[-1] == msg.CONFIG_CHANNELS_TEMPLATE
    assert any("public, unlisted" in line for line in file.template_lines)


# --- итог чтения одним значением


def test_a_read_is_the_value_or_the_error(tmp_path: Path) -> None:
    missing: ConfigRead[LivecraftSettings] = SettingsFile(tmp_path / "livecraft.json").read()
    assert missing.value is None and missing.is_missing and not missing.is_broken
    (tmp_path / "livecraft.json").write_text(json.dumps({"keep_days": 1}), encoding=TEXT_ENCODING)
    broken: ConfigRead[LivecraftSettings] = SettingsFile(tmp_path / "livecraft.json").read()
    assert broken.error is not None and broken.error.reason is ConfigProblem.FIELD_MISSING and broken.is_broken
    SettingsFile(tmp_path / "livecraft.json").save(SHIPPED.settings)
    read: ConfigRead[LivecraftSettings] = SettingsFile(tmp_path / "livecraft.json").read()
    assert (read.value, read.error) == (SHIPPED.settings, None)


def test_a_read_writes_its_outcome_to_the_log(tmp_path: Path) -> None:
    logger: logging.Logger = get_logger(LogArea.MAIN)
    with LogCapture.on(LogArea.MAIN, logging.DEBUG) as capture:
        _channels_file(tmp_path).read().log(logger)
        (tmp_path / "channels.json").write_text("{", encoding=TEXT_ENCODING)
        _channels_file(tmp_path).read().log(logger)
    lines: list[str] = capture.messages()
    assert lines[0] == f"config_missing path={tmp_path / 'channels.json'}"
    assert lines[1].startswith(f"config_error path={tmp_path / 'channels.json'} key={msg.CONFIG_ROOT_KEY} kind=invalid")
