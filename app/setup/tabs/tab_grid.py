"""Поля черновика в окне настройщика: переменные Tk и сетка полей (CLAUDE.md §8.2).

`DraftVariables` — значения полей окна и черновик, который модель уже приняла: набранное, но не принятое, —
то, что отличается от принятого. Переменные бывают не у всех полей черновика: дополнительные настройки разложены по
вкладкам линий (§14 решение 37), и раздел вкладки держит только свои поля; остальные поля черновика — из того
черновика, поверх которого кладётся набранное (`typed_over`). Что в черновике не поле окна (название канала, §14
решение 25), переходит из последнего показанного черновика. `FormGrid` — сетка полей черновика: подпись слева, поле по
виду поля (`DraftField.kind`; «да / нет» — ползунок, малое целое — поле со стрелками, §14 решение 75), серая подсказка
справа; под каждой строкой — место для строки итога записи поля (`result_row`, §8.2 «Сохранение — у поля») и под ней — для строки «Нужно линиям: …» бледного поля
(`note_row`); пустая строка сетки места не занимает. Что за поле, какие у него варианты и как они подписаны, знает
модель; сетка только рисует.
"""
from __future__ import annotations

import dataclasses
import tkinter as tk
from collections.abc import Mapping
from tkinter import ttk
from typing import Final, Generic, TypeVar

from app.setup.fields.channel_draft import ChannelDraft
from app.setup.fields.draft_field import DraftField, DraftKind, DraftValue
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.tabs.tab_layout import (
    HINT_FOREGROUND, HINT_WRAP_PIXELS, PAD, READONLY, SPIN_WIDTH_CHARS, SPINBOX_CLASS,
)
from app.setup.tabs.tab_scroll import ScrollEvent
from app.setup.tabs.toggle_switch import ToggleSwitch

# Черновики вкладок с сеткой полей: канал и дополнительные настройки.
DraftT = TypeVar("DraftT", ChannelDraft, SettingsDraft)
# Столбцы сетки: подпись, поле, подсказка.
LABEL_COLUMN: Final[int] = 0
INPUT_COLUMN: Final[int] = 1
HINT_COLUMN: Final[int] = 2
ROW_SPAN: Final[int] = 3        # строка поля, под ней — строка итога записи и строка «Нужно линиям: …»
RESULT_SPAN: Final[int] = 2     # строка итога записи — под полем и подсказкой
GRID_ROW_KEY: Final[str] = "row"


class DraftVariables(Generic[DraftT]):
    """Переменные Tk полей черновика («да / нет» — BooleanVar, прочее — StringVar), последний показанный черновик
    (`shown_draft`) и принятый."""

    def __init__(self, master: tk.Misc, draft: DraftT, fields: tuple[DraftField, ...] | None = None) -> None:
        self.shown_draft: DraftT = draft
        self.fields: tuple[DraftField, ...] = draft.FIELDS if fields is None else fields
        self.variables: dict[str, tk.Variable] = {
            field.name: tk.BooleanVar(master=master) if field.kind is DraftKind.FLAG else tk.StringVar(master=master)
            for field in self.fields
        }
        self.show(draft)
        self.accepted: DraftT = self.typed

    @property
    def typed(self) -> DraftT:
        """Черновик из полей окна: текст — как введён, флажки — bool, языки — кодами, варианты — значениями;
        прочее — из показанного черновика."""
        return self.typed_over(self.shown_draft)

    def typed_over(self, draft: DraftT) -> DraftT:
        """Черновик `draft`, в котором поля окна — как в окне сейчас."""
        values: dict[str, DraftValue] = {
            field.name: field.draft_value(self.variables[field.name].get()) for field in self.fields
        }
        return dataclasses.replace(draft, **values)

    @property
    def has_typed(self) -> bool:
        """В полях набрано то, чего модель ещё не приняла."""
        return self.typed != self.accepted

    def show(self, draft: DraftT) -> None:
        """Поля окна — по черновику."""
        self.shown_draft = draft
        for field in self.fields:
            self.variables[field.name].set(field.shown(getattr(draft, field.name)))

    def accept(self) -> None:
        """То, что сейчас в полях, модель приняла или сама показала: набранного больше нет."""
        self.accepted = self.typed


class FormGrid:
    """Сетка полей черновика. `labels`, `inputs` и `hints` — виджеты подписей, полей и подсказок по имени поля
    черновика.

    Подпись и подсказка берутся по пути ключа поля (`DraftField.key_path`) из словарей вкладки (messages_ru).
    Поле языка — ячейка, в которую вкладка кладёт своё поле выбора: подпись и подсказка такой строки прижаты к верху.
    """

    def __init__(self, parent: ttk.Frame, labels: Mapping[str, str], hints: Mapping[str, str]) -> None:
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=PAD)
        self._labels: Mapping[str, str] = labels
        self._hints: Mapping[str, str] = hints
        self.labels: dict[str, ttk.Label] = {}
        self.inputs: dict[str, tk.Widget] = {}
        self.hints: dict[str, ttk.Label] = {}

    def add(self, field: DraftField, variable: tk.Variable) -> tk.Widget:
        """Строка поля: подпись, поле по виду поля и подсказка, если она есть. Язык — пустая ячейка."""
        row: int = len(self.inputs) * ROW_SPAN
        is_cell: bool = field.kind is DraftKind.LANGUAGE
        label: ttk.Label = ttk.Label(self.frame, text=self._labels[field.key_path])
        label.grid(row=row, column=LABEL_COLUMN, sticky=tk.NW if is_cell else tk.W, padx=PAD, pady=(PAD, 0))
        self.labels[field.name] = label
        widget: tk.Widget = ttk.Frame(self.frame) if is_cell else self._input(field, variable)
        widget.grid(row=row, column=INPUT_COLUMN, sticky=tk.W, padx=PAD, pady=(PAD, 0))
        self.inputs[field.name] = widget
        hint: str | None = self._hints.get(field.key_path)
        if hint is not None:
            hint_label: ttk.Label = ttk.Label(self.frame, text=hint, foreground=HINT_FOREGROUND, wraplength=HINT_WRAP_PIXELS)
            hint_label.grid(row=row, column=HINT_COLUMN, sticky=tk.NW if is_cell else tk.W, padx=PAD, pady=(PAD, 0))
            self.hints[field.name] = hint_label
        return widget

    def row_widgets(self, name: str) -> tuple[tk.Misc, ...]:
        """Виджеты строки поля `name`: подпись, поле и подсказка, если она есть."""
        hint: ttk.Label | None = self.hints.get(name)
        return (self.labels[name], self.inputs[name], *(() if hint is None else (hint,)))

    def result_row(self, name: str) -> int:
        """Строка сетки сразу под полем `name`: в ней — строка итога записи поля."""
        return int(self.labels[name].grid_info()[GRID_ROW_KEY]) + 1

    def note_row(self, name: str) -> int:
        """Строка сетки под строкой итога поля `name`: в ней — строка «Нужно линиям: …» бледного поля."""
        return self.result_row(name) + 1

    def place_result(self, name: str, line: tk.Misc) -> None:
        """Строка итога записи поля `name` — под его полем и подсказкой."""
        line.grid(row=self.result_row(name), column=INPUT_COLUMN, columnspan=RESULT_SPAN, sticky=tk.W, padx=PAD)

    def _input(self, field: DraftField, variable: tk.Variable) -> tk.Widget:
        """Ползунок «да / нет», выбор из вариантов модели, поле целого числа со стрелками или поле ввода.

        Колесо мыши над полем со стрелками число не меняет, а прокручивает вкладку — как над закрытым выпадающим полем
        (`TabScroll`): иначе прокрутка страницы молча меняла бы и сохраняла срок или запас до эфира."""
        if isinstance(variable, tk.BooleanVar):
            return ToggleSwitch(self.frame, variable)
        if field.kind is DraftKind.CHOICE:
            return ttk.Combobox(
                self.frame, textvariable=variable, values=field.options, state=READONLY, width=field.input_width
            )
        if field.spin is not None:
            self.frame.bind_class(SPINBOX_CLASS, ScrollEvent.MOUSE_WHEEL, lambda _event: None)
            return ttk.Spinbox(
                self.frame, textvariable=variable, from_=field.spin.low, to=field.spin.high,
                increment=field.spin.step, width=SPIN_WIDTH_CHARS,
            )
        return ttk.Entry(self.frame, textvariable=variable, width=field.input_width)
