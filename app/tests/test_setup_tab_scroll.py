"""Прокручиваемые вкладки окна настройщика (app\\setup\\tabs\\tab_scroll.py; смотр окна 27-09-2026).

На экране 1080 строка папки Диска уходила за нижний край окна (теперь она на «Превью»). Окно в тестах — настоящее, за
краем экрана: размеры и положение виджетов считает сам Tk.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from tkinter import ttk

import pytest

from app.paths import LivecraftPaths
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.package_tab import PackageTab
from app.setup.tabs.previews_tab import PreviewsTab
from app.setup.tabs.tab_scroll import TabScroll
from app.setup.tabs.tab_shell import TabAction
from app.tests.fixtures.setup_window import SetupWindowDriver

SMALL_WINDOW: str = "900x600"
WIDE: int = 1000
TALL: int = 1500                            # выше содержимого «Эфиров YouTube»
WHEEL_DOWN: int = -120
TOUCHPAD_DOWN: int = -30                    # тачпад Windows: событие мельче щелчка колеса
TOUCHPAD_UP: int = 30
TOUCHPAD_STEPS_PER_NOTCH: int = 4


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def _in_view(scroll: TabScroll, widget: tk.Misc) -> bool:
    """Виджет целиком в видимой части холста вкладки."""
    top: int = scroll.canvas.winfo_rooty()
    bottom: int = top + scroll.canvas.winfo_height()
    return top <= widget.winfo_rooty() and widget.winfo_rooty() + widget.winfo_height() <= bottom


def _wheel(driver: SetupWindowDriver, widget: tk.Misc, delta: int = WHEEL_DOWN) -> None:
    """Событие колеса над виджетом — как на Windows: щелчок колеса — delta 120, тачпад — мельче."""
    widget.event_generate("<MouseWheel>", delta=delta)
    driver.window.root.update()


def test_the_bottom_of_the_previews_tab_is_reached_by_scrolling_in_a_600_high_window(driver: SetupWindowDriver) -> None:
    tab: PreviewsTab = driver.tabs.previews
    driver.show(tab.frame, SMALL_WINDOW)
    scroll: TabScroll = tab.shell.scroll
    assert scroll.content_height > scroll.canvas.winfo_height()          # не помещается — прокрутка нужна
    assert not _in_view(scroll, tab.drive.save_button)
    scroll.canvas.yview_moveto(1.0)
    driver.window.root.update()
    assert _in_view(scroll, tab.drive.save_button) and _in_view(scroll, tab.folder.row.accept_button)
    line: ttk.Label = driver.window.readiness_line                   # строка готовности под вкладкой — целиком
    assert line.winfo_height() >= line.winfo_reqheight()


def test_a_tab_that_fits_takes_the_whole_free_height(driver: SetupWindowDriver) -> None:
    """Вкладка, которая помещается, — во всю высоту холста: растягивающимся виджетам есть куда расти."""
    tab: PackageTab = driver.tabs.package
    driver.show(tab.frame, SMALL_WINDOW)
    scroll: TabScroll = tab.shell.scroll
    assert scroll.content_height < scroll.canvas.winfo_height()
    assert tab.shell.body.winfo_height() == scroll.canvas.winfo_height()


def test_a_tall_enough_window_stretches_the_channel_list_over_the_free_height(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    driver.window.root.maxsize(WIDE, TALL)
    driver.show(tab.frame, f"{WIDE}x{TALL}")
    scroll: TabScroll = tab.shell.scroll
    assert scroll.content_height < scroll.canvas.winfo_height()
    assert tab.tree.winfo_height() > tab.tree.winfo_reqheight()


def test_the_visibility_hint_is_whole_and_above_the_buttons_in_a_small_window(driver: SetupWindowDriver) -> None:
    """Подсказка видимости — перечнем в несколько строк: её высота не урезана, кнопки ниже неё."""
    tab: ChannelsTab = driver.channels
    driver.show(tab.frame, SMALL_WINDOW)
    hint: ttk.Label = tab.grid.hints["privacy"]
    assert str(hint.cget("text")).count("\n") == 1
    assert hint.winfo_height() >= hint.winfo_reqheight()
    assert hint.winfo_rooty() + hint.winfo_height() <= tab.buttons[TabAction.SAVE].master.winfo_rooty()


def test_the_wheel_over_the_tab_scrolls_it(driver: SetupWindowDriver) -> None:
    tab: PreviewsTab = driver.tabs.previews
    driver.show(tab.frame, SMALL_WINDOW)
    _wheel(driver, tab.images.frame)
    assert tab.shell.scroll.canvas.yview()[0] > 0


def test_touchpad_steps_scroll_the_tab_both_ways_like_the_wheel(driver: SetupWindowDriver) -> None:
    """Тачпад шлёт delta меньше щелчка: четыре шага по 30 вниз — как один щелчок колеса, четыре вверх — обратно."""
    tab: PreviewsTab = driver.tabs.previews
    driver.show(tab.frame, SMALL_WINDOW)
    canvas: tk.Canvas = tab.shell.scroll.canvas
    for _ in range(TOUCHPAD_STEPS_PER_NOTCH):
        _wheel(driver, tab.images.frame, TOUCHPAD_DOWN)
    by_touchpad: tuple[float, float] = canvas.yview()
    assert by_touchpad[0] > 0
    for _ in range(TOUCHPAD_STEPS_PER_NOTCH):
        _wheel(driver, tab.images.frame, TOUCHPAD_UP)
    assert canvas.yview()[0] == 0
    _wheel(driver, tab.images.frame)
    assert canvas.yview() == by_touchpad


def test_the_wheel_over_the_channel_list_leaves_the_page(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    driver.show(tab.frame, SMALL_WINDOW)
    _wheel(driver, tab.tree)
    assert tab.shell.scroll.canvas.yview()[0] == 0


def test_the_wheel_over_a_closed_choice_does_not_change_it(driver: SetupWindowDriver) -> None:
    """Прокрутка страницы не меняет молча видимость канала: закрытое выпадающее поле колесо не листает."""
    tab: ChannelsTab = driver.channels
    driver.show(tab.frame, SMALL_WINDOW)
    [choice] = [widget for widget in tab.inputs.values() if isinstance(widget, ttk.Combobox)]
    before: str = choice.get()
    _wheel(driver, choice)
    assert choice.get() == before
