"""Ползунки линий работы и выбор «Главной» в окне настройщика (CLAUDE.md §8.2, §14 решения 37, 47, 48).

`LineSwitches` — одна переменная Tk на линию на всё окно: ползунок линии на «Главной» и вверху её вкладки — одно
значение; плюс вход (таблица плана или пакеты) и выбор ключей («новые | все») «Главной». Переключение и выбор сразу
пишут свой раздел (модель `LinesPanel`) по общему правилу записи окна (`SettingsWrite`: сбой диска — диалог), и окно
перерисовывает «Главную», бледность полей всех вкладок и строку готовности (`on_change`); перерисовка вернёт
записанное. `LineHeader` — строка линии: ползунок, название жирным, что линия делает серым и её состояние цветом
(готова — зелёный, чего-то не хватает — красный, выключена или ждёт опору — серый); на «Главной» у строки есть
«Перейти» — на вкладку линии. Ползунок линии без опоры недоступен. Своих правил у строк нет: всё говорит модель
(`LineRow`).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Final

from app.run.mode import LINE_ORDER, RunPart
from app.setup.page import SetupPage
from app.setup.panels.lines_panel import KeysChoice, LineRow, LinesPanel, LineTone
from app.setup.tabs.settings_write import SettingsWrite
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_theme import HEADING_STYLE, STATUS_SET_FOREGROUND, STATUS_UNSET_FOREGROUND
from app.setup.tabs.toggle_switch import ToggleSwitch
from app.ui.messages import msg

SWITCH_COLUMN: Final[int] = 0
TEXT_COLUMN: Final[int] = 1
GO_COLUMN: Final[int] = 2
TEXT_ROWS: Final[int] = 3               # название, что делает, состояние
STATE_ROW: Final[int] = 2
STATE_WRAP_PIXELS: Final[int] = 620
TONE_FOREGROUNDS: Final[dict[LineTone, str]] = {
    LineTone.READY: STATUS_SET_FOREGROUND,
    LineTone.BLOCKED: STATUS_UNSET_FOREGROUND,
    LineTone.QUIET: HINT_FOREGROUND,
}


class LineSwitches:
    """Переключатели линий и выбор «Главной». Поля: окно (родитель диалога), модель линий, переменные по линиям, вход
    (значение `RunPart` входа), выбор ключей (значение `KeysChoice`), строки линий всех вкладок и что сделать после
    записи."""

    def __init__(self, master: tk.Misc, panel: LinesPanel, on_change: Callable[[], None]) -> None:
        self.master: tk.Misc = master
        self.panel: LinesPanel = panel
        self.variables: dict[RunPart, tk.BooleanVar] = {
            part: tk.BooleanVar(master=master, value=panel.lines.is_on(part)) for part in LINE_ORDER
        }
        self.source: tk.StringVar = tk.StringVar(master=master, value=panel.plan.source.value)
        self.keys: tk.StringVar = tk.StringVar(master=master, value=panel.keys_choice.value)
        self.headers: list[LineHeader] = []
        self.on_change: Callable[[], None] = on_change

    def header(self, parent: ttk.Frame, part: RunPart, go_to: Callable[[SetupPage], None] | None = None) -> LineHeader:
        """Строка линии `part` в `parent`; с `go_to` — с кнопкой «Перейти» на вкладку линии."""
        header: LineHeader = LineHeader(parent, part, self, go_to)
        self.headers.append(header)
        return header

    def flip(self, part: RunPart) -> None:
        """Ползунок линии переключён: раздел `lines` — в файл."""
        is_on: bool = self.variables[part].get()
        self._write(lambda: self.panel.switch(part, is_on))

    def choose_input(self) -> None:
        """Выбран вход «Таблица плана» или «Пакеты»: линия таблицы — в файл."""
        source: RunPart = RunPart(self.source.get())
        self._write(lambda: self.panel.choose_input(source))

    def choose_keys(self) -> None:
        """Выбрано «новые» или «все»: раздел broadcasts — в файл."""
        choice: KeysChoice = KeysChoice(self.keys.get())
        self._write(lambda: self.panel.choose_keys(choice))

    def show(self, panel: LinesPanel, rows: tuple[LineRow, ...]) -> None:
        """Переменные — по записанному в файле, строки линий — по свежим строкам модели."""
        self.panel = panel
        for part, variable in self.variables.items():
            if variable.get() != panel.lines.is_on(part):
                variable.set(panel.lines.is_on(part))
        self.source.set(panel.plan.source.value)
        self.keys.set(panel.keys_choice.value)
        by_part: dict[RunPart, LineRow] = {row.part: row for row in rows}
        for header in self.headers:
            header.show(by_part[header.part])

    def _write(self, write: Callable[[], LinesPanel]) -> None:
        """Запись по общему правилу окна: записано — модель по файлу; сбой — диалог. Окно перерисовывается всегда."""
        written: LinesPanel | None = SettingsWrite(self.master).run(write)
        if written is not None:
            self.panel = written
        self.on_change()


class LineHeader:
    """Строка линии: ползунок, название, что делает, состояние и (на «Главной») «Перейти»."""

    def __init__(
        self, parent: ttk.Frame, part: RunPart, switches: LineSwitches, go_to: Callable[[SetupPage], None] | None
    ) -> None:
        self.part: RunPart = part
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        self.frame.columnconfigure(TEXT_COLUMN, weight=1)
        self.switch: ToggleSwitch = ToggleSwitch(self.frame, switches.variables[part], lambda: switches.flip(part))
        self.switch.grid(row=0, column=SWITCH_COLUMN, rowspan=TEXT_ROWS, sticky=tk.NW, padx=(0, PAD))
        self.title: ttk.Label = ttk.Label(self.frame, style=HEADING_STYLE)
        self.title.grid(row=0, column=TEXT_COLUMN, sticky=tk.W)
        self.does: ttk.Label = ttk.Label(
            self.frame, text=msg.SETUP_LINE_DOES[part.value], foreground=HINT_FOREGROUND, wraplength=TEXT_WRAP_PIXELS
        )
        self.does.grid(row=1, column=TEXT_COLUMN, sticky=tk.W)
        self.state: ttk.Label = ttk.Label(self.frame, wraplength=STATE_WRAP_PIXELS, justify=tk.LEFT)
        self.state.grid(row=STATE_ROW, column=TEXT_COLUMN, sticky=tk.W)
        self.go_button: ttk.Button | None = None
        if go_to is not None:
            page: SetupPage = SetupPage.of_line(part)
            self.go_button = ttk.Button(self.frame, text=msg.SETUP_HOME_GO, command=lambda: go_to(page))
            self.go_button.grid(row=0, column=GO_COLUMN, rowspan=TEXT_ROWS, sticky=tk.E, padx=(PAD, 0))

    def show(self, row: LineRow) -> None:
        """Название, доступен ли ползунок и состояние линии — по строке модели."""
        self.title.configure(text=row.title)
        self.switch.set_enabled(row.is_switchable)
        self.state.configure(text=row.state, foreground=TONE_FOREGROUNDS[row.tone])
