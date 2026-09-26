"""Вкладка окна «Ключи и ссылки» поверх модели `KeysPanel` (CLAUDE.md §8.2 п.1, §7.4).

Вкладка рисует строки модели (`KeyRow`): название поля, откуда оно, маску и кнопки по доступным действиям.
Ввод своего значения — поле со скрытыми символами; принято моделью — поле очищается, отказ — красная строка
под полем, а введённое остаётся. Принятое сразу записывается в сейф этой установки — одним шагом, как и сброс
своего значения: общей кнопки «Сохранить» на вкладке нет. Запись не удалась — диалог, вкладка остаётся на
прочитанном с диска, введённое — в поле, чтобы нажать «Сохранить значение» ещё раз. Введённое, но не
сохранённое значение — несохранённое вкладки: окно спросит перед закрытием.

Значение сейфа в виджет по умолчанию не попадает: строка рисует маску из модели, а поле ввода — то, что
человек печатает сам, и то скрытыми символами. Буфер обмена не трогается: в поле ввода вставлять и выделять
можно, а копировать и вырезать — нет (привязка на самом поле гасит `<<Copy>>` и `<<Cut>>` в любой раскладке).

«Показать своё» (`RowAction.REVEAL`, §14 решение 11): кнопка есть только у поля, которое человек ввёл сам.
По явному нажатию значение просит у модели (`KeysPanel.own_value` — единственная точка раскрытия в
настройщике) и кладёт только в подпись маски своей строки — ttk.Label, из которого текст не выделяется и не
копируется; не в поле ввода, не в лог, не в диалог. Любое действие вкладки, её перерисовка и уход с
вкладки снова прячут значение за маску.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Final

from app.secretsafe.dpapi import DpapiUnavailable
from app.secretsafe.value import SecretField
from app.setup.panels.keys_panel import KeyRow, KeysPanel, RowAction
from app.setup.panels.panel_edit import PanelEdit
from app.setup.tabs.tab_event import BREAK, TkEvent
from app.setup.tabs.tab_layout import PAD, ProblemLine
from app.setup.tabs.tab_shell import TabShell
from app.ui import messages_ru as msg

SECRET_ECHO: Final[str] = "•"             # символ вместо каждого введённого: значение не видно через плечо
ENTRY_WIDTH_CHARS: Final[int] = 48
INPUT_ACTIONS: Final[frozenset[RowAction]] = frozenset({RowAction.ENTER, RowAction.REPLACE})
ROWS_PER_FIELD: Final[int] = 2            # строка поля и строка его проблемы
HEADER_ROWS: Final[int] = 1
HEADERS: Final[tuple[str, ...]] = (
    msg.SETUP_KEYS_HEADER_FIELD,
    msg.SETUP_KEYS_HEADER_ORIGIN,
    msg.SETUP_KEYS_HEADER_VALUE,
    msg.SETUP_KEYS_HEADER_INPUT,
)
PROBLEM_COLUMN: Final[int] = 3
PROBLEM_COLUMN_SPAN: Final[int] = 3
# Из поля ключа введённое не уходит: ни копированием, ни вырезанием.
BLOCKED_ENTRY_EVENTS: Final[tuple[TkEvent, ...]] = (TkEvent.COPY, TkEvent.CUT)


class KeyRowView:
    """Виджеты одной строки сейфа: подписи, маска, поле ввода, кнопки и строка проблемы; кнопки зовут вкладку."""

    def __init__(self, parent: ttk.Frame, field: SecretField, position: int, tab: KeysTab) -> None:
        self.field: SecretField = field
        self.label: ttk.Label = ttk.Label(parent)
        self.origin: ttk.Label = ttk.Label(parent)
        self.display: ttk.Label = ttk.Label(parent)
        self.entry: ttk.Entry = ttk.Entry(parent, show=SECRET_ECHO, width=ENTRY_WIDTH_CHARS)
        for blocked in BLOCKED_ENTRY_EVENTS:
            self.entry.bind(blocked, lambda _event: BREAK)
        self.accept_button: ttk.Button = ttk.Button(
            parent, text=msg.SETUP_KEYS_BUTTON_ACCEPT, command=lambda: tab.accept(field)
        )
        self.reset_button: ttk.Button = ttk.Button(parent, command=lambda: tab.reset(field))
        self.reveal_button: ttk.Button = ttk.Button(
            parent, text=msg.SETUP_KEYS_BUTTON_REVEAL, command=lambda: tab.toggle_own_value(field)
        )
        self.problem: ProblemLine = ProblemLine(parent, {})
        self.is_revealed: bool = False
        self._mask: str = ""
        self._place(HEADER_ROWS + position * ROWS_PER_FIELD)

    @property
    def raw(self) -> str:
        """Что человек ввёл в поле."""
        return self.entry.get()

    def show(self, row: KeyRow) -> None:
        """Нарисовать строку модели: подписи, маска и только те кнопки, что разрешены действиями строки.

        Перерисовка всегда возвращает маску: показанное значение не переживает ни одного ответа модели.
        """
        self.label.configure(text=row.label)
        self.origin.configure(text=row.origin_label)
        self.reset_button.configure(text=row.reset_label or "")
        self._mask = row.display
        self.hide()
        can_input: bool = bool(row.actions & INPUT_ACTIONS)
        shown: dict[ttk.Widget, bool] = {
            self.entry: can_input,
            self.accept_button: can_input,
            self.reset_button: RowAction.RESET in row.actions,
            self.reveal_button: RowAction.REVEAL in row.actions,
        }
        for widget, is_shown in shown.items():
            if is_shown:
                widget.grid()
            else:
                widget.grid_remove()

    def show_value(self, value: str) -> None:
        """Показать своё значение в подписи маски — только на экране, до следующего `hide`."""
        self.display.configure(text=value)
        self.reveal_button.configure(text=msg.SETUP_KEYS_BUTTON_HIDE)
        self.is_revealed = True

    def hide(self) -> None:
        """Вернуть маску строки."""
        self.display.configure(text=self._mask)
        self.reveal_button.configure(text=msg.SETUP_KEYS_BUTTON_REVEAL)
        self.is_revealed = False

    def accepted(self) -> None:
        """Модель приняла ввод: поле и строка проблемы очищаются."""
        self.entry.delete(0, tk.END)
        self.problem.show_text(None)

    def _place(self, grid_row: int) -> None:
        widgets: tuple[ttk.Widget, ...] = (
            self.label, self.origin, self.display, self.entry, self.accept_button, self.reset_button,
            self.reveal_button,
        )
        for column, widget in enumerate(widgets):
            widget.grid(row=grid_row, column=column, sticky=tk.W, padx=PAD, pady=(PAD, 0))
        self.problem.label.grid(
            row=grid_row + 1, column=PROBLEM_COLUMN, columnspan=PROBLEM_COLUMN_SPAN, sticky=tk.W, padx=PAD
        )


class KeysTab:
    """Вкладка «Ключи и ссылки» в оболочке `shell`; `rows` — виджеты строк по полям сейфа.

    Файл сейфа программы не прочитан — у модели нет строк: вкладка называет причину и ничего не даёт править.
    """

    def __init__(self, notebook: ttk.Notebook, panel: KeysPanel, on_saved: Callable[[], None]) -> None:
        self.shell: TabShell[KeysPanel] = TabShell(notebook, panel, on_saved)
        self.frame: ttk.Frame = self.shell.frame
        self.notice: ttk.Label = self.shell.notice
        self.rows_frame: ttk.Frame = ttk.Frame(self.frame)
        self.rows_frame.pack(fill=tk.X, anchor=tk.W, pady=PAD)
        for column, header in enumerate(HEADERS):
            ttk.Label(self.rows_frame, text=header).grid(row=0, column=column, sticky=tk.W, padx=PAD)
        self.rows: dict[SecretField, KeyRowView] = {
            field: KeyRowView(self.rows_frame, field, position, self)
            for position, field in enumerate(SecretField.current())
        }
        self._show()

    @property
    def panel(self) -> KeysPanel:
        return self.shell.panel

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — в модели или введено в поле и не сохранено."""
        return self.shell.is_dirty(any(view.raw for view in self.rows.values()))

    def accept(self, field: SecretField) -> None:
        """«Сохранить значение»: введённое — модели; принято — сразу в сейф, строка перерисована, поле очищено.

        Модель отказала — причина под полем; запись не удалась — диалог. В обоих случаях введённое остаётся.
        """
        self.hide_revealed()
        view: KeyRowView = self.rows[field]
        edit: PanelEdit[KeysPanel] = self.panel.replace(field, view.raw)
        if edit.problem is not None:
            view.problem.show_text(edit.problem.text)
            return
        if self._save(edit.panel):
            view.accepted()

    def reset(self, field: SecretField) -> None:
        """Сброс своего значения — сразу в сейф: вернётся поставочное, а если его нет, поле опустеет."""
        self.hide_revealed()
        if self._save(self.panel.reset(field)):
            self.rows[field].problem.show_text(None)

    def toggle_own_value(self, field: SecretField) -> None:
        """«Показать»/«скрыть» своё значение поля. Модель не отдала значение (поставка, поля нет) — ничего."""
        view: KeyRowView = self.rows[field]
        if view.is_revealed:
            view.hide()
            return
        value: str | None = self.panel.own_value(field)
        if value is not None:
            view.show_value(value)

    def hide_revealed(self) -> None:
        """Спрятать за маску всё показанное: перед любым действием вкладки и при уходе с неё."""
        for view in self.rows.values():
            if view.is_revealed:
                view.hide()

    def _save(self, edited: KeysPanel) -> bool:
        """Модель с правкой пишет личный сейф; записано — вкладка на прочитанном заново и True.

        Отказ — диалог без значения и без пути к сейфу, вкладка прежняя (в модели несохранённого не остаётся),
        False.
        """
        try:
            saved: PanelEdit[KeysPanel] = edited.save()
        except DpapiUnavailable:
            self.shell.refuse_save(msg.SETUP_INPUT_OWN_UNAVAILABLE)
            return False
        except OSError:
            self.shell.refuse_save(msg.SETUP_KEYS_SAVE_FAILED_OS)
            return False
        self.shell.panel = saved.panel
        self._show()
        self.shell.on_saved()
        return True

    def _show(self) -> None:
        """Перерисовать вкладку по модели: оговорки сверху и строки полей; строк у модели нет — только оговорки."""
        self.shell.show_notices()
        if not self.panel.rows:
            self.rows_frame.pack_forget()
        for row in self.panel.rows:
            self.rows[row.field].show(row)
