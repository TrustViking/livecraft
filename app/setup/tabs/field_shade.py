"""Бледные поля окна настройщика (CLAUDE.md §8.2, §14 решение 37).

Поле активно, если работает хоть одна линия, которой оно нужно (`FieldUse`); иначе все его виджеты недоступны,
подписи серые, а под полем — серая строка «Нужно линиям: …». Поле окна — блок в своей рамке (строка сейфа, ссылка,
папка, таблица каналов, шаги Telegram; строка под ним — последней в рамке) или строка сетки полей (подпись, поле,
подсказка; строка под ней — следующей строкой сетки). `FieldShades` помнит все поля окна и после каждого переключения
линии и каждой записи красит их заново (`apply`) — последним шагом перерисовки окна, поверх того, что нарисовали
вкладки. Цвет подписи, которую вкладка покрасила сама (статус «задано», подсказка), бледность запоминает и возвращает,
когда поле снова нужно.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from dataclasses import dataclass
from tkinter import ttk
from typing import Final

from app.run.line_plan import LinePlan
from app.setup.fields.field_use import FieldUse
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, TEXT_KEY, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_theme import DIM_FOREGROUND
from app.setup.tabs.toggle_switch import ToggleSwitch

ENABLED_STATE: Final[str] = "!" + tk.DISABLED
FOREGROUND_OPTION: Final[str] = "foreground"
GRID_COLUMNS: Final[int] = 3              # строка под полем сетки — во всю ширину: подпись, поле, подсказка


class FieldNote:
    """Серая строка под полем: каким линиям оно нужно. Пустая — не видна. `grid_row` — строка сетки под полем сетки;
    None — строка идёт последней в рамке блока."""

    def __init__(self, parent: tk.Misc, grid_row: int | None) -> None:
        self.label: ttk.Label = ttk.Label(
            parent, foreground=HINT_FOREGROUND, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT
        )
        self.grid_row: int | None = grid_row

    @property
    def text(self) -> str:
        """Что строка показывает; не видна — пусто."""
        return str(self.label.cget(TEXT_KEY)) if self.label.winfo_manager() else ""

    def show(self, text: str) -> None:
        """Показать строку; пусто — убрать."""
        self.label.configure(text=text)
        if self.grid_row is not None and text:
            self.label.grid(row=self.grid_row, column=0, columnspan=GRID_COLUMNS, sticky=tk.W, padx=PAD)
        elif self.grid_row is not None:
            self.label.grid_remove()
        elif text:
            self.label.pack(fill=tk.X, anchor=tk.W)
        else:
            self.label.pack_forget()


@dataclass(frozen=True)
class ShadedField:
    """Поле окна: каким линиям оно нужно, его виджеты (вместе с вложенными) и строка под ним."""

    use: FieldUse
    widgets: tuple[tk.Misc, ...]
    note: FieldNote

    def walk(self) -> Iterator[tk.Misc]:
        """Виджеты поля вглубь, кроме строки под полем."""
        pending: list[tk.Misc] = list(self.widgets)
        while pending:
            widget: tk.Misc = pending.pop()
            if widget is not self.note.label:
                yield widget
                pending.extend(widget.winfo_children())


class FieldShades:
    """Все поля окна и цвета подписей, которые бледность сменила на серый (по имени виджета Tk)."""

    def __init__(self) -> None:
        self.fields: list[ShadedField] = []
        self.colors: dict[str, str] = {}

    def block(self, use: FieldUse, frame: ttk.Frame) -> ShadedField:
        """Поле — блок в рамке `frame` (рамка раскладывает виджеты pack): строка под ним — последней в рамке."""
        return self._add(ShadedField(use, (frame,), FieldNote(frame, None)))

    def row(self, use: FieldUse, widgets: tuple[tk.Misc, ...], note: FieldNote) -> ShadedField:
        """Поле — строка сетки: её виджеты и строка под ней (следующая строка сетки)."""
        return self._add(ShadedField(use, widgets, note))

    def apply(self, plan: LinePlan) -> None:
        """Каждое поле — активно или бледно по работающим линиям `plan`; строка под полем — по тому же правилу."""
        for field in self.fields:
            is_active: bool = field.use.is_active(plan)
            for widget in field.walk():
                self._shade(widget, is_active)
            field.note.show(field.use.note(plan))

    def _add(self, field: ShadedField) -> ShadedField:
        self.fields.append(field)
        return field

    def _shade(self, widget: tk.Misc, is_active: bool) -> None:
        """Виджет доступен или нет; подпись — своим цветом или серая."""
        if isinstance(widget, ToggleSwitch):
            widget.set_enabled(is_active)
        elif isinstance(widget, tk.Listbox):
            widget.configure(state=tk.NORMAL if is_active else tk.DISABLED)
        elif isinstance(widget, ttk.Widget):
            widget.state([ENABLED_STATE if is_active else tk.DISABLED])
            if isinstance(widget, ttk.Label):
                self._paint(widget, is_active)

    def _paint(self, label: ttk.Label, is_active: bool) -> None:
        """Бледная подпись — серая, прежний цвет запомнен; снова нужная — прежним цветом, если вкладка не покрасила
        её заново сама."""
        name: str = str(label)
        color: str = str(label.cget(FOREGROUND_OPTION))
        if not is_active:
            if color != DIM_FOREGROUND:
                self.colors[name] = color
            label.configure(foreground=DIM_FOREGROUND)
        elif color == DIM_FOREGROUND and name in self.colors:
            label.configure(foreground=self.colors.pop(name))
