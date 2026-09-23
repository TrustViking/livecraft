"""Вкладка окна «Ключи и ссылки» поверх модели `KeysPanel` (CLAUDE.md §8.2 п.1, §7.4).

Вкладка рисует строки модели (`KeyRow`): название поля, откуда оно, маску и кнопки по доступным действиям.
Ввод своего значения — поле со скрытыми символами; принято моделью — поле очищается, отказ — красная строка
под полем, а введённое остаётся. Кнопка «Сохранить» отдаёт модели сейф этой установки (`VaultStore.open`).

Значение сейфа в виджет по умолчанию не попадает: строка рисует маску из модели, а поле ввода — то, что
человек печатает сам, и то скрытыми символами. Буфер обмена не трогается.

«Показать своё» (`RowAction.REVEAL`, §14 решение 11): кнопка есть только у поля, которое человек ввёл сам.
По явному нажатию значение просит у модели (`KeysPanel.own_value` — единственная точка раскрытия в
настройщике) и кладёт только в подпись маски своей строки — ttk.Label, из которого текст не выделяется и не
копируется; не в поле ввода, не в лог, не в диалог. Любое действие вкладки, её перерисовка и уход с
вкладки снова прячут значение за маску.
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
        on_toggle_own_value: Callable[[SecretField], None],
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
        self.reveal_button: ttk.Button = ttk.Button(
            parent, text=msg.SETUP_KEYS_BUTTON_REVEAL, command=lambda: on_toggle_own_value(field)
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
        self._mask = row.display
        self.hide()
        can_input: bool = bool(row.actions & INPUT_ACTIONS)
        for widget in (self.entry, self.accept_button):
            if can_input:
                widget.grid()
            else:
                widget.grid_remove()
        for button, action in ((self.reset_button, RowAction.RESET), (self.reveal_button, RowAction.REVEAL)):
            if action in row.actions:
                button.grid()
            else:
                button.grid_remove()

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

    def refused(self, problem: str | None) -> None:
        """Модель отказала: причина — красной строкой, введённое остаётся в поле."""
        self.problem.show_text(problem)

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
            field: KeyRowView(self.rows_frame, field, position, self.accept, self.reset, self.toggle_own_value)
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
        self.hide_revealed()
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
        self.hide_revealed()
        self.panel = self.panel.reset(field)
        self.rows[field].problem.show_text(None)
        self._show()

    def save(self) -> None:
        """«Сохранить»: модель пишет личный сейф. Отказ — диалог без значения и без пути к сейфу."""
        if self.panel is None:
            return
        self.hide_revealed()
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

    def toggle_own_value(self, field: SecretField) -> None:
        """«Показать»/«скрыть» своё значение поля. Модель не отдала значение (поставка, поля нет) — ничего."""
        view: KeyRowView = self.rows[field]
        if view.is_revealed:
            view.hide()
            return
        if self.panel is None:
            return
        value: str | None = self.panel.own_value(field)
        if value is None:
            return
        view.show_value(value)

    def hide_revealed(self) -> None:
        """Спрятать за маску всё показанное: перед любым действием вкладки и при уходе с неё."""
        for view in self.rows.values():
            if view.is_revealed:
                view.hide()

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
