"""Окно настройщика в тестах: открыть, найти виджеты, набрать и выбрать так, как это делает человек.

Окно создаётся и прячется (withdraw); кнопки нажимаются через invoke. Окно без рабочего стола не создаётся —
такой прогон падает с TclError, а не пропускается: настройщик на машине оператора обязан открываться.
"""
from __future__ import annotations

import dataclasses
import tkinter as tk
from collections.abc import Iterator
from tkinter import ttk

import pytest

from app.config.settings import FormQuestion, FormSettings, LivecraftSettings
from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField
from app.setup.app import SetupWindow
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.keys_tab import KeyRowView
from app.setup.tabs.language_box import LanguageBox
from app.setup.tabs.settings_tab import SettingsTab
from app.setup.tabs.tab_event import TkEvent
from app.setup.tabs.tab_shell import TabAction

CAPTURE_OPTION: str = "capture"
FD_CAPTURE: str = "fd"
FD_CAPTURE_PROBLEM: str = "окно Tk под --capture=fd ломает стандартные каналы Tcl: нужен перехват из pytest.ini"
OFF_SCREEN: str = "+-10000+-10000"


class SetupWindowDriver:
    """Окно настройщика и действия человека в нём: набрать, выбрать, нажать, закрыть."""

    def __init__(self, window: SetupWindow) -> None:
        self.window: SetupWindow = window

    @classmethod
    def opened(cls, paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
        """Окно создаётся и прячется; после теста разрушается, если его не закрыл сам тест.

        Tcl берёт описатели ОС стандартных потоков своими стандартными каналами один раз на поток и держит их до
        конца процесса. Перехват pytest на уровне дескрипторов (--capture=fd) на каждой паузе и возобновлении
        делает dup2 на 0–2 и тем закрывает эти описатели; Windows отдаёт их номера следующим открытым файлам, и
        очередное окно не читает init.tcl. Поэтому pytest.ini в корне ставит перехват на уровне sys, а под
        --capture=fd окно не создаётся: тест падает с этой причиной, а не случайной TclError в другом тесте.
        """
        assert pytestconfig.getoption(CAPTURE_OPTION) != FD_CAPTURE, FD_CAPTURE_PROBLEM
        window: SetupWindow = SetupWindow(paths)
        window.root.withdraw()
        try:
            yield cls(window)
        finally:
            if not window.is_closed:
                window.root.destroy()

    @property
    def language(self) -> LanguageBox:
        return self.window.channels_tab.language

    def widgets(self, root: tk.Misc | None = None) -> Iterator[tk.Misc]:
        """Все виджеты окна (или `root`) вглубь."""
        for child in (self.window.root if root is None else root).winfo_children():
            yield child
            yield from self.widgets(child)

    def visible_texts(self) -> list[str]:
        """Всё, что окно показывает человеку: подписи, кнопки, поля ввода, строки таблиц, вкладки и заголовок."""
        window: SetupWindow = self.window
        texts: list[str] = [window.root.title()]
        texts.extend(str(window.notebook.tab(index, "text")) for index in range(window.notebook.index(tk.END)))
        for widget in self.widgets():
            if isinstance(widget, (ttk.Label, ttk.Button, ttk.Checkbutton, tk.Label, tk.Button)):
                texts.append(str(widget.cget("text")))
            if isinstance(widget, (ttk.Entry, tk.Entry)):     # ttk.Combobox — тоже Entry
                texts.append(widget.get())
            if isinstance(widget, ttk.Treeview):
                for item in widget.get_children():
                    texts.extend(str(value) for value in widget.item(item, "values"))
        return texts

    def type(self, entry: ttk.Entry, text: str) -> None:
        """Поле ввода целиком заменено текстом."""
        entry.delete(0, tk.END)
        entry.insert(0, text)

    def box_values(self) -> tuple[str, ...]:
        """Значения выпадающего поля языка — как их покажет список поля."""
        box: ttk.Combobox = self.language.box
        return tuple(box.tk.splitlist(box.cget("values")))

    def pick_language(self, code: str) -> None:
        """Выбор языка так, как это делает человек: печать кода в поле сужает список, затем выбор строки списка."""
        box: ttk.Combobox = self.language.box
        box.set(code)
        [label] = [label for label in self.box_values() if self.language.picker.directory.code_of(label) == code]
        box.set(label)
        box.event_generate(TkEvent.COMBOBOX_SELECTED)

    def fill_channel(self, **values: str) -> None:
        """Поля канала; язык — кодом, он выбирается в выпадающем поле."""
        tab: ChannelsTab = self.window.channels_tab
        for name, value in values.items():
            if name == "languages":
                self.pick_language(value)
                continue
            widget: ttk.Widget = tab.inputs[name]
            if isinstance(widget, ttk.Combobox):
                widget.set(value)
            else:
                self.type(widget, value)

    def press_button(self, tab: ChannelsTab | SettingsTab, action: TabAction) -> None:
        tab.buttons[action].invoke()

    def accept_key(self, field: SecretField, value: str) -> KeyRowView:
        """Своё значение поля сейфа введено и принято кнопкой строки."""
        view: KeyRowView = self.window.keys_tab.rows[field]
        self.type(view.entry, value)
        view.accept_button.invoke()
        assert view.problem.text == ""
        return view

    def focus(self, tab_frame: ttk.Frame, entry: ttk.Entry) -> None:
        """Окно за краем экрана, вкладка выбрана, фокус в поле: нажатие Tk доставляет только в поле с фокусом."""
        root: tk.Tk = self.window.root
        root.geometry(OFF_SCREEN)
        root.deiconify()
        self.window.notebook.select(tab_frame)
        root.update()
        entry.focus_force()
        root.update()
        assert root.focus_get() is entry

    def press(self, entry: ttk.Entry, keycode: int) -> None:
        entry.event_generate(TkEvent.CONTROL_KEY_PRESS, keycode=keycode)
        self.window.root.update()

    def put_in_clipboard(self, text: str) -> None:
        root: tk.Tk = self.window.root
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()

    def type_language(self, text: str) -> None:
        """Человек печатает в поле языка по букве: пока список закрыт, буква идёт в поле; раскрытый список
        забирает клавиатуру себе, и букву поле получает от списка."""
        box: ttk.Combobox = self.language.box
        self.focus(self.window.channels_tab.frame, box)
        for char in text:
            if self.is_language_list_open:
                self.language.forward_key(char, char)
            else:
                box.insert(tk.INSERT, char)
            self.window.root.update()

    @property
    def is_language_list_open(self) -> bool:
        box: ttk.Combobox = self.language.box
        return bool(box.tk.getboolean(box.tk.call("winfo", "ismapped", self.language.listbox)))

    @property
    def language_list(self) -> tuple[str, ...]:
        """Строки раскрытого списка языков."""
        box: ttk.Combobox = self.language.box
        return tuple(box.tk.splitlist(box.tk.call(self.language.listbox, "get", 0, tk.END)))

    def save_form_languages(self, languages: dict[str, str]) -> None:
        """Варианты языка формы сменились (контракт формы на вкладке не правится — он приходит с настройками):
        модель вкладки настроек получает новые варианты, и человек жмёт «Сохранить» — боевой путь записи."""
        tab: SettingsTab = self.window.settings_tab
        settings: LivecraftSettings = tab.panel.settings
        values: dict[str, dict[str, str]] = {**settings.form.values, FormQuestion.LANGUAGE.value: languages}
        form: FormSettings = dataclasses.replace(settings.form, values=values)
        tab.shell.panel = dataclasses.replace(tab.panel, settings=dataclasses.replace(settings, form=form))
        tab.buttons[TabAction.SAVE].invoke()
        assert tab.problem.text == ""

