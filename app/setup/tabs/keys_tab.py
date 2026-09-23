"""Вкладка окна «Ключи и ссылки» поверх модели `KeysPanel` (CLAUDE.md §8.2 п.1, §7.4).

Вкладка рисует строки модели (`KeyRow`): название поля, откуда оно, маску и кнопки по доступным действиям.
Ввод своего значения — поле со скрытыми символами; принято моделью — поле очищается, отказ — красная строка
под полем, а введённое остаётся. Кнопка «Сохранить» отдаёт модели сейф этой установки (`VaultStore.open`).

Значение сейфа в виджет не попадает: вкладка не вызывает раскрытие значения и берёт из модели только маску.
В строке видно лишь то, что человек печатает сам, и то скрытыми символами. Буфер обмена не трогается.
Действие «показать своё» (`RowAction.REVEAL`) в этой версии окна не рисуется (задача 2.3a).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Final

from app.paths import LivecraftPaths
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.dpapi import DpapiUnavailable
from app.secretsafe.store import VaultStore
from app.secretsafe.value import SecretField
from app.setup.panels.keys_panel import KeyRow, KeysPanel, KeysPanelEdit, RowAction
from app.setup.tabs import NOTICE_JOINER, PAD, TEXT_WRAP_PIXELS, ProblemLine
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


class KeyRowView:
    """Виджеты одной строки сейфа: подписи, маска, поле ввода, кнопки и строка проблемы."""

    def __init__(
        self,
        parent: ttk.Frame,
        field: SecretField,
        position: int,
        on_accept: Callable[[SecretField], None],
        on_reset: Callable[[SecretField], None],
    ) -> None:
        self.field: SecretField = field
        self.label: ttk.Label = ttk.Label(parent)
        self.origin: ttk.Label = ttk.Label(parent)
        self.display: ttk.Label = ttk.Label(parent)
        self.entry: ttk.Entry = ttk.Entry(parent, show=SECRET_ECHO, width=ENTRY_WIDTH_CHARS)
        self.accept_button: ttk.Button = ttk.Button(
            parent, text=msg.SETUP_KEYS_BUTTON_ACCEPT, command=lambda: on_accept(field)
        )
        self.reset_button: ttk.Button = ttk.Button(
            parent, text=msg.SETUP_KEYS_BUTTON_RESET, command=lambda: on_reset(field)
        )
        self.problem: ProblemLine = ProblemLine(parent, {})
        self._place(HEADER_ROWS + position * ROWS_PER_FIELD)

    @property
    def raw(self) -> str:
        """Что человек ввёл в поле."""
        return self.entry.get()

    def show(self, row: KeyRow) -> None:
        """Нарисовать строку модели: подписи, маска и только те кнопки, что разрешены действиями строки."""
        self.label.configure(text=row.label)
        self.origin.configure(text=row.origin_label)
        self.display.configure(text=row.display)
        can_input: bool = bool(row.actions & INPUT_ACTIONS)
        for widget in (self.entry, self.accept_button):
            if can_input:
                widget.grid()
            else:
                widget.grid_remove()
        if RowAction.RESET in row.actions:
            self.reset_button.grid()
        else:
            self.reset_button.grid_remove()

    def accepted(self) -> None:
        """Модель приняла ввод: поле и строка проблемы очищаются."""
        self.entry.delete(0, tk.END)
        self.problem.show_text(None)

    def refused(self, problem: str | None) -> None:
        """Модель отказала: причина — красной строкой, введённое остаётся в поле."""
        self.problem.show_text(problem)

    def _place(self, grid_row: int) -> None:
        widgets: tuple[ttk.Widget, ...] = (
            self.label, self.origin, self.display, self.entry, self.accept_button, self.reset_button
        )
        for column, widget in enumerate(widgets):
            widget.grid(row=grid_row, column=column, sticky=tk.W, padx=PAD, pady=(PAD, 0))
        self.problem.label.grid(
            row=grid_row + 1, column=PROBLEM_COLUMN, columnspan=PROBLEM_COLUMN_SPAN, sticky=tk.W, padx=PAD
        )


class KeysTab:
    """Вкладка «Ключи и ссылки». `panel` — текущая модель; после каждого действия её заменяет ответ модели.

    Файл сейфа чужого формата — модели нет (`panel` None): вкладка называет причину и ничего не даёт править.
    """

    def __init__(self, notebook: ttk.Notebook, paths: LivecraftPaths, on_saved: Callable[[], None]) -> None:
        self.paths: LivecraftPaths = paths
        self.frame: ttk.Frame = ttk.Frame(notebook, padding=PAD)
        self.notice: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.notice.pack(fill=tk.X, anchor=tk.W)
        self.rows_frame: ttk.Frame = ttk.Frame(self.frame)
        self.rows_frame.pack(fill=tk.X, anchor=tk.W, pady=PAD)
        for column, header in enumerate(HEADERS):
            ttk.Label(self.rows_frame, text=header).grid(row=0, column=column, sticky=tk.W, padx=PAD)
        self.rows: dict[SecretField, KeyRowView] = {
            field: KeyRowView(self.rows_frame, field, position, self.accept, self.reset)
            for position, field in enumerate(SecretField)
        }
        self.save_button: ttk.Button = ttk.Button(self.frame, text=msg.SETUP_BUTTON_SAVE, command=self.save)
        self.save_button.pack(anchor=tk.E, pady=PAD)
        self._on_saved: Callable[[], None] = on_saved
        self.panel: KeysPanel | None = None
        self.load_error: VaultFormatError | None = None
        self._load()

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённое — по модели."""
        return self.panel is not None and self.panel.is_dirty

    def accept(self, field: SecretField) -> None:
        """«Сохранить значение»: введённое — модели; принято — строка перерисована и поле очищено."""
        if self.panel is None:
            return
        view: KeyRowView = self.rows[field]
        edit: KeysPanelEdit = self.panel.replace(field, view.raw)
        if not edit.is_applied:
            view.refused(edit.problem)
            return
        self.panel = edit.panel
        view.accepted()
        self._show()

    def reset(self, field: SecretField) -> None:
        """«Сбросить к поставке»: модель убирает своё значение поля."""
        if self.panel is None:
            return
        self.panel = self.panel.reset(field)
        self.rows[field].problem.show_text(None)
        self._show()

    def save(self) -> None:
        """«Сохранить»: модель пишет личный сейф. Отказ — диалог без значения и без пути к сейфу."""
        if self.panel is None:
            return
        try:
            self.panel = self.panel.save(VaultStore.open(self.paths))
        except DpapiUnavailable:
            messagebox.showerror(msg.SETUP_SAVE_FAILED_TITLE, msg.SETUP_INPUT_OWN_UNAVAILABLE, parent=self.frame)
            return
        except OSError:
            messagebox.showerror(msg.SETUP_SAVE_FAILED_TITLE, msg.SETUP_KEYS_SAVE_FAILED_OS, parent=self.frame)
            return
        self._show()
        self._on_saved()

    def _load(self) -> None:
        """Прочитать оба файла сейфа в модель; файл чужого формата — причина вместо строк."""
        try:
            self.panel = KeysPanel.from_store(VaultStore.open(self.paths))
        except VaultFormatError as error:
            self.load_error = error
        self._show()

    def _show(self) -> None:
        """Перерисовать вкладку по модели: оговорки сверху, строки полей, доступность «Сохранить»."""
        if self.panel is None:
            self.notice.configure(text=msg.VAULT_FILE_BROKEN.format(error=self.load_error))
            self.rows_frame.pack_forget()
            self.save_button.state(["disabled"])
            return
        self.notice.configure(text=NOTICE_JOINER.join(self.panel.notices))
        for row in self.panel.rows:
            self.rows[row.field].show(row)
