"""Поля черновика в окне настройщика: переменные Tk и сетка полей (CLAUDE.md §8.2).

`DraftVariables` — значения полей окна и черновик, который модель уже приняла: набранное, но не принятое, —
то, что отличается от принятого (одно правило «несохранённое» у всех вкладок). `FormGrid` — сетка полей
черновика: подпись слева, поле по виду поля (`DraftField.kind`), серая подсказка справа. Что за поле и какие у
него варианты, знает модель; сетка только рисует.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Mapping
from tkinter import ttk
from typing import Final, Generic, TypeVar

from app.setup.fields.channel_draft import ChannelDraft
from app.setup.fields.draft_field import DraftField, DraftKind, DraftValue
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.tabs.tab_layout import HINT_FOREGROUND, HINT_WRAP_PIXELS, PAD, READONLY

DraftT = TypeVar("DraftT", ChannelDraft, SettingsDraft)
# Столбцы сетки: подпись, поле, подсказка.
LABEL_COLUMN: Final[int] = 0
INPUT_COLUMN: Final[int] = 1
HINT_COLUMN: Final[int] = 2


class DraftVariables(Generic[DraftT]):
    """Переменные Tk полей черновика (флажок — BooleanVar, прочее — StringVar) и принятый черновик."""

    def __init__(self, master: tk.Misc, draft: DraftT) -> None:
        self.draft_type: type[DraftT] = type(draft)
        self.fields: tuple[DraftField, ...] = draft.FIELDS
        self.variables: dict[str, tk.Variable] = {
            field.name: tk.BooleanVar(master=master) if field.kind is DraftKind.FLAG else tk.StringVar(master=master)
            for field in self.fields
        }
        self.show(draft)
        self.accepted: DraftT = self.typed

    @property
    def typed(self) -> DraftT:
        """Черновик из полей окна: текст — как введён, флажки — bool, языки — кодами."""
        values: dict[str, DraftValue] = {
            field.name: field.draft_value(self.variables[field.name].get()) for field in self.fields
        }
        return self.draft_type(**values)

    @property
    def has_typed(self) -> bool:
        """В полях набрано то, чего модель ещё не приняла."""
        return self.typed != self.accepted

    def show(self, draft: DraftT) -> None:
        """Поля окна — по черновику."""
        for field in self.fields:
            self.variables[field.name].set(field.shown(getattr(draft, field.name)))

    def accept(self) -> None:
        """То, что сейчас в полях, модель приняла или сама показала: набранного больше нет."""
        self.accepted = self.typed


class FormGrid:
    """Сетка полей черновика. `inputs` и `hints` — виджеты полей и подсказок по имени поля черновика.

    Подпись и подсказка берутся по пути ключа поля (`DraftField.key_path`) из словарей вкладки (messages_ru).
    Поле языка — ячейка, в которую вкладка кладёт своё поле выбора: подпись такой строки прижата к верху.
    """

    def __init__(self, parent: ttk.Frame, labels: Mapping[str, str], hints: Mapping[str, str]) -> None:
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=PAD)
        self._labels: Mapping[str, str] = labels
        self._hints: Mapping[str, str] = hints
        self.inputs: dict[str, ttk.Widget] = {}
        self.hints: dict[str, ttk.Label] = {}

    def add(self, field: DraftField, variable: tk.Variable) -> ttk.Widget:
        """Строка поля: подпись, поле по виду поля и подсказка, если она есть. Язык — пустая ячейка."""
        row: int = len(self.inputs)
        is_cell: bool = field.kind is DraftKind.LANGUAGE
        label: ttk.Label = ttk.Label(self.frame, text=self._labels[field.key_path])
        label.grid(row=row, column=LABEL_COLUMN, sticky=tk.NW if is_cell else tk.W, padx=PAD, pady=(PAD, 0))
        widget: ttk.Widget = ttk.Frame(self.frame) if is_cell else self._input(field, variable)
        widget.grid(row=row, column=INPUT_COLUMN, sticky=tk.W, padx=PAD, pady=(PAD, 0))
        self.inputs[field.name] = widget
        hint: str | None = self._hints.get(field.key_path)
        if hint is not None:
            hint_label: ttk.Label = ttk.Label(self.frame, text=hint, foreground=HINT_FOREGROUND, wraplength=HINT_WRAP_PIXELS)
            hint_label.grid(row=row, column=HINT_COLUMN, sticky=tk.W, padx=PAD, pady=(PAD, 0))
            self.hints[field.name] = hint_label
        return widget

    def _input(self, field: DraftField, variable: tk.Variable) -> ttk.Widget:
        """Флажок, выбор из вариантов модели или поле ввода."""
        if field.kind is DraftKind.FLAG:
            return ttk.Checkbutton(self.frame, variable=variable)
        if field.kind is DraftKind.CHOICE:
            return ttk.Combobox(
                self.frame, textvariable=variable, values=field.choices, state=READONLY, width=field.width
            )
        return ttk.Entry(self.frame, textvariable=variable, width=field.width)
