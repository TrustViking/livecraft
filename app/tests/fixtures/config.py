"""Конфиги тестов: данные поставочного livecraft.json и примера channels.json, запись и ошибки разбора файлов."""
from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from app.config.channel import ChannelConfig
from app.config.files import ChannelsFile, SettingsFile, ShippedSettings
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings

REPO_CHANNELS_EXAMPLE: Path = Path(__file__).resolve().parents[3] / "app" / "examples" / "channels.example.json"


def settings_data() -> dict[str, Any]:
    """Данные поставочного livecraft.json — того вида, который кладёт сама программа, а не выдуманные в тесте."""
    return json.loads(ShippedSettings().template)


def channels_data() -> dict[str, Any]:
    return json.loads(REPO_CHANNELS_EXAMPLE.read_text(encoding="utf-8"))


def channel_data(**changes: Any) -> dict[str, Any]:
    """Первый канал примера с изменёнными полями."""
    base: dict[str, Any] = copy.deepcopy(channels_data()["channels"][0])
    base.update(changes)
    return base


def write_json(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def settings_error(tmp_path: Path, data: Any) -> ConfigError:
    """Ошибка чтения livecraft.json с этими данными."""
    path: Path = write_json(tmp_path / "livecraft.json", data)
    with pytest.raises(ConfigError) as raised:
        SettingsFile(path).load()
    return raised.value


def channels_error(tmp_path: Path, data: Any) -> ConfigError:
    """Ошибка чтения channels.json с этими данными."""
    path: Path = write_json(tmp_path / "channels.json", data)
    with pytest.raises(ConfigError) as raised:
        ChannelsFile(path, tmp_path / "channels.previous.json").load()
    return raised.value


def with_pause(settings: LivecraftSettings, seconds: float) -> LivecraftSettings:
    """Те же настройки с другой паузой между обращениями к YouTube — в обход разбора."""
    return dataclasses.replace(settings, youtube_pause_seconds=seconds)


def channels_of(path: Path) -> tuple[ChannelConfig, ...]:
    """Каналы файла `path` — тем же разбором, что у программы."""
    return ChannelsFile(path, path.with_name("channels.previous.json")).load().channels
