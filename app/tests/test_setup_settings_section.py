"""Поля разделов настроек на настоящем окне Tk за краем экрана (CLAUDE.md §8.2, §14 решения 63, 75): стрелки малых чисел
сохраняют по щелчку и по Enter, колесо их не меняет; модели OpenAI — выпадающие списки с ценой, выбор сохраняется,
модель вне списка показывается как есть."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from tkinter import ttk

import pytest

from app.config.files import SettingsFile
from app.config.settings import LivecraftSettings
from app.paths import LivecraftPaths
from app.setup.fields.settings_draft import MODEL_CHOICES, MODEL_LABELS, SettingsDraft
from app.setup.tabs.tab_event import TkEvent
from app.tests.fixtures.drafts import draft_with
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.ui import messages_ru as msg

INCREMENT: str = "<<Increment>>"        # стрелка «больше»: событие класса ttk.Spinbox
DECREMENT: str = "<<Decrement>>"
WHEEL: str = "<MouseWheel>"
SPIN_FIELDS: dict[str, tuple[str, str, str]] = {
    "keep_days": ("1", "365", "1"),
    "cookies_remind_days": ("1", "60", "1"),
    "min_lead_minutes": ("0", "1440", "5"),
}
PLAIN_FIELDS: tuple[str, ...] = ("llm_timeout_sec", "llm_max_output_tokens", "youtube_pause_seconds", "category_id")


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def _saved(driver: SetupWindowDriver) -> LivecraftSettings:
    return SettingsFile.of(driver.window.paths).load()


def _spin(driver: SetupWindowDriver, name: str) -> ttk.Spinbox:
    widget: tk.Widget = driver.settings_input(name)
    assert isinstance(widget, ttk.Spinbox)
    return widget


def _press(driver: SetupWindowDriver, widget: tk.Widget, sequence: str, **options: int) -> None:
    widget.event_generate(sequence, **options)
    driver.window.root.update()


@pytest.mark.parametrize("name", list(SPIN_FIELDS))
def test_a_small_number_has_arrows_with_its_limits_and_step(driver: SetupWindowDriver, name: str) -> None:
    spin: ttk.Spinbox = _spin(driver, name)
    limits: tuple[str, str, str] = tuple(str(spin.cget(option)) for option in ("from", "to", "increment"))
    assert tuple(float(value) for value in limits) == tuple(float(value) for value in SPIN_FIELDS[name])


@pytest.mark.parametrize("name", PLAIN_FIELDS)
def test_big_numbers_and_codes_stay_plain_entries(driver: SetupWindowDriver, name: str) -> None:
    widget: tk.Widget = driver.settings_input(name)
    assert type(widget) is ttk.Entry


def test_an_arrow_click_saves_at_once(driver: SetupWindowDriver) -> None:
    before: int = _saved(driver).keep_days
    spin: ttk.Spinbox = _spin(driver, "keep_days")
    _press(driver, spin, INCREMENT)
    assert spin.get() == str(before + 1)
    assert _saved(driver).keep_days == before + 1
    assert driver.setting_line("keep_days") == msg.SETUP_FIELD_SAVED


def test_the_lead_arrow_steps_by_five_minutes(driver: SetupWindowDriver) -> None:
    driver.save_setting("min_lead_minutes", "30")
    _press(driver, _spin(driver, "min_lead_minutes"), DECREMENT)
    assert _saved(driver).min_lead_minutes == 25


def test_a_typed_number_is_saved_by_enter(driver: SetupWindowDriver) -> None:
    driver.enter_setting("cookies_remind_days", "12")
    assert _saved(driver).cookies.remind_days == 12
    assert driver.setting_line("cookies_remind_days") == msg.SETUP_FIELD_SAVED


def test_the_wheel_does_not_change_a_number(driver: SetupWindowDriver) -> None:
    before: int = _saved(driver).keep_days
    spin: ttk.Spinbox = _spin(driver, "keep_days")
    _press(driver, spin, WHEEL, delta=120)
    assert spin.get() == str(before) and _saved(driver).keep_days == before
    assert driver.setting_line("keep_days") == ""


def test_both_models_are_drop_down_lists_with_prices(driver: SetupWindowDriver) -> None:
    saved: LivecraftSettings = _saved(driver)
    for name, model in (("llm_model", saved.llm.model), ("llm_fallback_model", saved.llm.fallback_model)):
        box: tk.Widget = driver.settings_input(name)
        assert isinstance(box, ttk.Combobox)
        assert tuple(box.cget("values")) == MODEL_LABELS
        assert box.get() == MODEL_LABELS[MODEL_CHOICES.index(model)]


def test_a_chosen_model_is_saved(driver: SetupWindowDriver) -> None:
    box: tk.Widget = driver.settings_input("llm_fallback_model")
    assert isinstance(box, ttk.Combobox)
    box.set(MODEL_LABELS[0])
    _press(driver, box, TkEvent.COMBOBOX_SELECTED)
    assert _saved(driver).llm.fallback_model == MODEL_CHOICES[0]
    assert driver.setting_line("llm_fallback_model") == msg.SETUP_FIELD_SAVED


def test_a_model_off_the_list_is_shown_and_kept(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> None:
    file: SettingsFile = SettingsFile.of(ready_paths)
    settings: LivecraftSettings = file.load()
    file.save(file.parse(draft_with(SettingsDraft.of(settings), llm_model="gpt-6-astra").to_data(settings)))
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        assert driver.settings_input("llm_model").get() == "gpt-6-astra"  # type: ignore[attr-defined]
        driver.enter_setting("keep_days", "9")                            # другое поле пишет файл — модель на месте
        assert file.load().llm.model == "gpt-6-astra"
