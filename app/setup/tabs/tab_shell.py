"""Общее у трёх вкладок окна настройщика (CLAUDE.md §8.2).

`TabShell` — рамка вкладки на блокноте, оговорки модели сверху, текущая модель вкладки, ряд кнопок по центру
окна, диалог о несостоявшейся записи и одно правило «несохранённое» для всех вкладок: несохранённое есть в
модели или в полях набрано то, чего модель ещё не приняла. Своих правил у оболочки нет: API моделей один
(`title`, `notices`, `is_dirty`, `save`), и его держит тест моделей.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from enum import Enum
from tkinter import messagebox, ttk
from typing import Final, Generic, TypeVar

from app.core.text_format import PARAGRAPH_BREAK
from app.setup.panels.channels_panel import ChannelsPanel
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.settings_panel import SettingsPanel
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.ui import messages_ru as msg

PanelT = TypeVar("PanelT", KeysPanel, ChannelsPanel, SettingsPanel)


class TabAction(str, Enum):
    """Кнопка ряда вкладки. Значение — английский идентификатор, подпись — `BUTTON_TEXTS`."""

    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    SAVE = "save"


BUTTON_TEXTS: Final[dict[TabAction, str]] = {
    TabAction.ADD: msg.SETUP_CHANNELS_BUTTON_ADD,
    TabAction.UPDATE: msg.SETUP_CHANNELS_BUTTON_UPDATE,
    TabAction.REMOVE: msg.SETUP_CHANNELS_BUTTON_REMOVE,
    TabAction.SAVE: msg.SETUP_BUTTON_SAVE,
}


class TabShell(Generic[PanelT]):
    """Оболочка вкладки. Поля: текущая модель, рамка, строка оговорок, ряд кнопок и что сделать после записи."""

    def __init__(self, notebook: ttk.Notebook, panel: PanelT, on_saved: Callable[[], None]) -> None:
        self.panel: PanelT = panel
        self.frame: ttk.Frame = ttk.Frame(notebook, padding=PAD)
        self.notice: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.notice.pack(fill=tk.X, anchor=tk.W)
        self.buttons_frame: ttk.Frame = ttk.Frame(self.frame)
        self.on_saved: Callable[[], None] = on_saved

    def is_dirty(self, has_typed: bool) -> bool:
        """Несохранённое есть в модели или в полях набрано то, чего модель ещё не приняла."""
        return self.panel.is_dirty or has_typed

    def show_notices(self) -> None:
        """Оговорки модели — абзацами над полями вкладки."""
        self.notice.configure(text=PARAGRAPH_BREAK.join(self.panel.notices))

    def button_row(self, commands: Mapping[TabAction, Callable[[], None]]) -> dict[TabAction, ttk.Button]:
        """Ряд кнопок по центру окна, кнопки своего размера, в порядке `commands`; ставится под уже созданным."""
        self.buttons_frame.pack(side=tk.TOP, anchor=tk.CENTER, pady=PAD)
        buttons: dict[TabAction, ttk.Button] = {}
        for action, command in commands.items():
            button: ttk.Button = ttk.Button(self.buttons_frame, text=BUTTON_TEXTS[action], command=command)
            button.pack(side=tk.LEFT, padx=PAD)
            buttons[action] = button
        return buttons

    def refuse_save(self, text: str) -> None:
        """Запись не состоялась: диалог с причиной; значений и путей к сейфу в нём нет."""
        messagebox.showerror(msg.SETUP_SAVE_FAILED_TITLE, text, parent=self.frame)
