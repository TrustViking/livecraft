"""Раздел broadcasts livecraft.json (app\\config\\broadcasts.py, §14 решения 36, 50): поставочный вид, дописывание
раздела старому файлу, ошибки с путём, прежний ключ источника текстов и запись раздела поверх свежего файла."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.config.broadcasts import BroadcastSettings
from app.config.files import SettingsFile, ShippedSettings
from app.config.json_node import ConfigError, ConfigProblem
from app.config.settings import LivecraftSettings
from app.core.text_format import TEXT_ENCODING
from app.tests.fixtures.config import settings_data, settings_error, write_json
from app.ui import messages_ru as msg

SHIPPED: LivecraftSettings = ShippedSettings().settings


def test_the_shipped_section_does_not_resend() -> None:
    """Поставка: ключи повторно не уходят («новые»); источника текстов в разделе нет."""
    assert SHIPPED.broadcasts == BroadcastSettings(resend_keys=False)
    assert settings_data()["broadcasts"] == {"resend_keys": False}


def test_a_file_without_the_section_gets_it_from_the_template(tmp_path: Path) -> None:
    """Файл прежней версии: раздел дописывается из шаблона, правка человека цела."""
    data: dict[str, Any] = settings_data()
    data["keep_days"] = 9
    del data["broadcasts"]
    file: SettingsFile = SettingsFile(write_json(tmp_path / "livecraft.json", data))
    assert file.complete_sections() == ("broadcasts",)
    settings: LivecraftSettings = file.load()
    assert settings.broadcasts == SHIPPED.broadcasts and settings.keep_days == 9
    assert list(json.loads(file.path.read_text(encoding=TEXT_ENCODING))) == list(settings_data())


def test_the_former_text_source_key_is_an_unknown_field_for_the_parser(tmp_path: Path) -> None:
    """Прежний ключ источника текстов разбор не знает: до разбора его убирает перенос (app\\setup\\migration.py)."""
    data: dict[str, Any] = settings_data()
    data["broadcasts"]["text_source"] = "package"
    error: ConfigError = settings_error(tmp_path, data)
    assert error.key_path == "broadcasts.text_source"


def test_a_resend_flag_that_is_not_a_boolean_is_an_error_with_its_path(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["broadcasts"]["resend_keys"] = "yes"
    assert settings_error(tmp_path, data).key_path == "broadcasts.resend_keys"


def test_a_missing_field_of_the_section_is_named(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    del data["broadcasts"]["resend_keys"]
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.reason) == ("broadcasts.resend_keys", ConfigProblem.FIELD_MISSING)


def test_the_section_round_trips_through_the_file(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["broadcasts"] = {"resend_keys": True}
    file: SettingsFile = SettingsFile(write_json(tmp_path / "livecraft.json", data))
    settings: LivecraftSettings = file.load()
    assert settings.broadcasts == BroadcastSettings(True)
    assert settings.to_data()["broadcasts"] == data["broadcasts"]


def test_save_broadcasts_writes_only_the_section_over_the_fresh_file(tmp_path: Path) -> None:
    """Раздел — поверх файла, как он на диске: правка другой вкладки не откатывается."""
    data: dict[str, Any] = settings_data()
    data["keep_days"] = 11
    file: SettingsFile = SettingsFile(write_json(tmp_path / "livecraft.json", data))
    file.save_broadcasts(BroadcastSettings(True))
    written: dict[str, Any] = json.loads(file.path.read_text(encoding=TEXT_ENCODING))
    assert written["broadcasts"] == {"resend_keys": True}
    assert {key: value for key, value in written.items() if key != "broadcasts"} == {
        key: value for key, value in data.items() if key != "broadcasts"
    }


def test_with_resend_changes_the_switch() -> None:
    changed: BroadcastSettings = SHIPPED.broadcasts.with_resend(True)
    assert changed == BroadcastSettings(True)
    assert not changed.with_resend(False).resend_keys


@pytest.mark.parametrize("name", ["Europe/Kyiv", "UTC"])
def test_a_canonical_zone_name_has_no_problem(tmp_path: Path, name: str) -> None:
    """Правило имени пояса переехало в ZoneName: годное имя по-прежнему читается."""
    data: dict[str, Any] = settings_data()
    data["timezone"] = name
    assert SettingsFile(write_json(tmp_path / "livecraft.json", data)).load().timezone == name


def test_a_zone_name_off_the_database_is_still_refused(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["timezone"] = "Europe/Kyiv "
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.problem) == ("timezone", msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN)
