"""Раздел lines livecraft.json (app\\config\\lines.py, §14 решение 37): поставочный вид, поле на линию, дописывание
раздела старому файлу, ошибки с путём и какие линии включены."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config.files import SettingsFile, ShippedSettings
from app.config.json_node import ConfigError, ConfigProblem
from app.config.lines import LineSettings
from app.config.settings import LivecraftSettings
from app.core.text_format import TEXT_ENCODING
from app.run.line_plan import LinePlan
from app.run.mode import LINE_ORDER, RunPart
from app.tests.fixtures.config import settings_data, settings_error, write_json
from app.tests.fixtures.settings import lines_on

SHIPPED: LivecraftSettings = ShippedSettings().settings


def test_the_shipped_section_switches_every_line_on() -> None:
    """Поставка: включены все линии — программа делает всё, что настроено."""
    assert SHIPPED.lines.switched_on == frozenset(LINE_ORDER)
    assert settings_data()["lines"] == {part.value: True for part in LINE_ORDER}


def test_a_field_of_the_section_is_the_value_of_its_line() -> None:
    """Поле раздела — значение члена RunPart линии, в порядке «Главной»; чтения пакетов среди них нет."""
    assert tuple(settings_data()["lines"]) == tuple(part.value for part in LINE_ORDER)
    assert RunPart.PACKAGES_IN.value not in settings_data()["lines"]


def test_the_section_knows_which_lines_are_on() -> None:
    lines: LineSettings = lines_on(RunPart.PLAN, RunPart.KEYS)
    assert lines.switched_on == frozenset({RunPart.PLAN, RunPart.KEYS})
    assert lines.is_on(RunPart.PLAN) and not lines.is_on(RunPart.MERGE) and not lines.is_on(RunPart.PACKAGES_IN)
    assert lines.line_plan == LinePlan(frozenset({RunPart.PLAN, RunPart.KEYS}))


def test_the_section_round_trips_through_the_file(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["lines"]["announce"] = False
    data["lines"]["keys"] = False
    file: SettingsFile = SettingsFile(write_json(tmp_path / "livecraft.json", data))
    settings: LivecraftSettings = file.load()
    assert settings.lines.switched_on == frozenset(LINE_ORDER) - {RunPart.ANNOUNCE, RunPart.KEYS}
    assert settings.to_data()["lines"] == data["lines"]


def test_a_file_without_the_section_gets_it_from_the_template(tmp_path: Path) -> None:
    """Файл прежней версии: раздел дописывается из шаблона (все линии включены), правка человека цела."""
    data: dict[str, Any] = settings_data()
    data["keep_days"] = 9
    del data["lines"]
    file: SettingsFile = SettingsFile(write_json(tmp_path / "livecraft.json", data))
    assert file.complete_sections() == ("lines",)
    settings: LivecraftSettings = file.load()
    assert settings.lines == SHIPPED.lines and settings.keep_days == 9
    assert list(json.loads(file.path.read_text(encoding=TEXT_ENCODING))) == list(settings_data())


def test_a_switch_that_is_not_a_boolean_is_an_error_with_its_path(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["lines"]["doc_copy"] = "yes"
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.reason) == ("lines.doc_copy", ConfigProblem.INVALID)


def test_a_missing_line_of_the_section_is_named(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    del data["lines"]["keys"]
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.reason) == ("lines.keys", ConfigProblem.FIELD_MISSING)


def test_an_unknown_line_is_an_error(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["lines"]["packages_in"] = True
    assert settings_error(tmp_path, data).key_path.startswith("lines")
