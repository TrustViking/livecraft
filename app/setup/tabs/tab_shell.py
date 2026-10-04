"""Общее у вкладок окна настройщика (CLAUDE.md §8.2, §14 решение 37).

`TabShell` — прокручиваемая страница вкладки на блокноте (`TabScroll`: блокноту — её внешняя рамка `frame`,
содержимое — в `body`). Вверху вкладки одной линии — ползунок этой линии с тем, что она делает (то же значение, что на
«Главной»); у вкладки из двух разделов ползунок стоит вверху каждого раздела — его ставит сама вкладка. Ниже —
вступление вкладки («зачем» — одним абзацем, если оно есть), оговорки моделей, ряд кнопок по центру окна и запись
настроек вкладки по общему правилу окна (`write_settings` — `SettingsWrite`: сбой диска — диалог с причиной). Своих
правил у оболочки нет: что годно и что записано, решают модели вкладки.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from enum import Enum
from tkinter import ttk
from typing import Final

from app.core.text_format import PARAGRAPH_BREAK
from app.run.mode import RunPart
from app.setup.page import SetupPage
from app.setup.tabs.line_switches import LineHeader
from app.setup.tabs.settings_write import SettingsWrite, WrittenT
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_scroll import TabScroll
from app.setup.tabs.tab_theme import HEADING_STYLE
from app.ui.messages import msg


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


class TabShell:
    """Оболочка вкладки. Поля: вкладка окна, общее у вкладок окна (`context`), страница (`scroll`: внешняя рамка
    `frame` — блокноту, рамка содержимого `body`), вступление, строка оговорок и что сделать после записи."""

    def __init__(self, context: SetupContext, page: SetupPage, intro: str = "") -> None:
        self.page: SetupPage = page
        self.context: SetupContext = context
        self.scroll: TabScroll = TabScroll(context.notebook)
        if len(page.lines) == 1:
            self.header(page.lines[0])
        self.intro: ttk.Label = ttk.Label(self.body, text=intro, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        if intro:
            self.intro.pack(fill=tk.X, anchor=tk.W, pady=(PAD, PAD))
        self.notice: ttk.Label = ttk.Label(self.body, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.notice.pack(fill=tk.X, anchor=tk.W)
        self.on_saved: Callable[[], None] = context.on_saved

    @property
    def frame(self) -> ttk.Frame:
        """Страница блокнота."""
        return self.scroll.frame

    @property
    def body(self) -> ttk.Frame:
        """Рамка содержимого вкладки."""
        return self.scroll.body

    @property
    def title(self) -> str:
        return self.page.title

    def header(self, part: RunPart) -> LineHeader:
        """Ползунок линии `part` с тем, что она делает, — вверху вкладки или её раздела."""
        return self.context.switches.header(self.body, part)

    def step(self, title: str, text: str) -> ttk.Frame:
        """Раздел вкладки (шаг «Telegram», раздел «Токенов»): жирный заголовок, пояснение и рамка для его строк."""
        frame: ttk.Frame = ttk.Frame(self.body)
        frame.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        ttk.Label(frame, text=title, style=HEADING_STYLE).pack(anchor=tk.W)
        ttk.Label(frame, text=text, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT).pack(anchor=tk.W)
        return frame

    def show_notices(self, notices: tuple[str, ...]) -> None:
        """Оговорки моделей вкладки — абзацами над её полями."""
        self.notice.configure(text=PARAGRAPH_BREAK.join(notices))

    def button_row(
        self, parent: ttk.Frame, commands: Mapping[TabAction, Callable[[], None]]
    ) -> dict[TabAction, ttk.Button]:
        """Ряд кнопок в `parent` по центру окна, кнопки своего размера, в порядке `commands`; ставится под уже
        созданным."""
        row: ttk.Frame = ttk.Frame(parent)
        row.pack(side=tk.TOP, anchor=tk.CENTER, pady=PAD)
        buttons: dict[TabAction, ttk.Button] = {}
        for action, command in commands.items():
            button: ttk.Button = ttk.Button(row, text=BUTTON_TEXTS[action], command=command)
            button.pack(side=tk.LEFT, padx=PAD)
            buttons[action] = button
        return buttons

    def write_settings(self, write: Callable[[], WrittenT]) -> WrittenT | None:
        """Запись настроек вкладки моделью (`write`) по общему правилу окна (`SettingsWrite`): записано — итог записи;
        сбой диска — диалог с причиной и None."""
        return SettingsWrite(self.frame).run(write)

    def refuse_save(self, text: str) -> None:
        """Запись не состоялась: диалог с причиной; значений и путей к сейфу в нём нет."""
        SettingsWrite(self.frame).refuse(text)
