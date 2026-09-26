"""Поле выбора языка канала на вкладке «Каналы YouTube» поверх `LanguagePicker` (CLAUDE.md §8.2 п.2).

Выпадающее поле того же вида и ширины, что «видимость». В поле можно печатать: пока человек печатает в поле,
список раскрывается сам и показывает только подходящие языки; выбор строки списка — выбор языка, Esc
возвращает прежний выбор. Раскрытый список Tk забирает клавиатуру себе — поэтому буквы и Backspace, нажатые в
списке, объект отдаёт полю: печать продолжается, а стрелки, Enter и Esc работают в списке как обычно.

Под полем — строка «при сохранении останется …» (канал старого файла с несколькими языками) и
строка-предупреждение о языке не из формы. Коды для черновика объект пишет в переменную поля языка черновика.
Правил у объекта нет: что выбрано и что об этом сказать, решает `LanguagePicker`.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Iterable, Sequence
from tkinter import ttk
from typing import Final

from app.config.json_node import SettingProblem
from app.core.text_format import SPACE
from app.setup.fields.draft_field import DraftField
from app.setup.fields.language_choice import LanguagePicker
from app.setup.tabs.tab_event import BREAK, TkEvent
from app.setup.tabs.tab_layout import ProblemLine

VARIABLE_WRITE: Final[str] = "write"                  # трасса переменной Tk: значение записано
BACKSPACE_KEYSYM: Final[str] = "BackSpace"
# Команды Tcl выпадающего списка ttk::combobox и путь его списка внутри окна списка.
POPDOWN_WINDOW_COMMAND: Final[str] = "ttk::combobox::PopdownWindow"
POST_COMMAND: Final[str] = "ttk::combobox::Post"
UNPOST_COMMAND: Final[str] = "ttk::combobox::Unpost"
POPDOWN_LISTBOX_SUFFIX: Final[str] = ".f.l"
TCL_BIND: Final[str] = "bind"
TCL_FOCUS: Final[str] = "focus"
# Привязка клавиш списка: символ (%A) и имя клавиши (%K) — обработчику; «break» — дальше событие не идёт.
FORWARD_BINDING: Final[str] = 'if {{"[{command} %A %K]" == "break"}} break'


class LanguageBox:
    """Поле выбора языка. Поля: выбор (`picker`), текст поля, само поле, переменная кодов черновика и две строки
    под полем."""

    def __init__(self, cell: ttk.Frame, field: DraftField, picker: LanguagePicker, codes: tk.StringVar) -> None:
        self.picker: LanguagePicker = picker
        self.codes: tk.StringVar = codes
        self.text: tk.StringVar = tk.StringVar(master=cell)
        self.box: ttk.Combobox = ttk.Combobox(cell, textvariable=self.text, values=picker.choices, width=field.width)
        self.box.pack(anchor=tk.W)
        self.box.bind(TkEvent.ESCAPE, lambda _event: self.restore())
        self.note: ProblemLine = ProblemLine(cell, {})
        self.note.label.pack(anchor=tk.W)
        self.warning: ProblemLine = ProblemLine(cell, {})
        self.warning.label.pack(anchor=tk.W)
        self.listbox: str = str(self.box.tk.call(POPDOWN_WINDOW_COMMAND, self.box)) + POPDOWN_LISTBOX_SUFFIX
        command: str = self.box.register(self.forward_key)
        self.box.tk.call(TCL_BIND, self.listbox, TkEvent.KEY_PRESS, FORWARD_BINDING.format(command=command))
        self.text.trace_add(VARIABLE_WRITE, lambda *_args: self.typed())

    @property
    def problem(self) -> SettingProblem | None:
        """Текст поля — не строка списка: черновик с ним модели не отдаётся."""
        return self.picker.problem

    @property
    def has_focus(self) -> bool:
        """Клавиатура у поля или у его раскрытого списка: человек печатает здесь."""
        return str(self.box.tk.call(TCL_FOCUS)).startswith(str(self.box))

    def choose(self, codes: Sequence[str]) -> None:
        """Языки канала целиком (строка таблицы, новый канал): в поле — подпись первого."""
        self._show(self.picker.chose(codes))

    def including(self, codes: Iterable[str]) -> None:
        """Коды каналов таблицы — в справочник выбора: их названия и подписи не теряются."""
        self.picker = self.picker.including(codes)

    def with_form(self, form_codes: Iterable[str], known_codes: Iterable[str]) -> None:
        """Варианты формы сменились: пометки и предупреждение — по новой форме, выбор тот же."""
        self._show(self.picker.with_form(form_codes, known_codes))

    def restore(self) -> None:
        """Esc: в поле — подпись прежнего выбора, набранный текст отбрасывается."""
        self.text.set(self.picker.restored().text)

    def typed(self) -> None:
        """Текст поля изменился: выбор и строки под полем — по ответу `LanguagePicker`. Человек печатает в поле, и
        в нём не подпись языка — список раскрыт и показывает подходящие языки; подходящих нет — список закрыт, а
        клавиатура снова у поля."""
        self.picker = self.picker.typed(self.text.get())
        self.box.configure(values=self.picker.choices)
        self._render()
        if self.picker.is_label or not self.has_focus:
            return
        if self.picker.choices:
            self.box.tk.call(POST_COMMAND, self.box)
            return
        self.box.tk.call(UNPOST_COMMAND, self.box)
        self.box.focus_set()

    def forward_key(self, char: str, keysym: str) -> str | None:
        """Клавиша, нажатая в раскрытом списке: буква — в поле, Backspace — стереть знак перед курсором поля.

        Прочие клавиши (стрелки, Enter, Esc) остаются списку.
        """
        if keysym == BACKSPACE_KEYSYM:
            cursor: int = self.box.index(tk.INSERT)
            if cursor:
                self.box.delete(cursor - 1)
            return BREAK
        if len(char) != 1 or not char.isprintable():
            return None
        self.box.insert(tk.INSERT, char)
        return BREAK

    def _show(self, picker: LanguagePicker) -> None:
        """Новый выбор целиком: текст поля — подпись выбора; трасса текста перерисует остальное."""
        self.picker = picker
        self.text.set(picker.text)

    def _render(self) -> None:
        """Коды — в черновик; строки под полем — по выбору."""
        self.codes.set(SPACE.join(self.picker.draft_codes))
        self.note.show_text(self.picker.note)
        self.warning.show_text(self.picker.warning)
