"""Строки полей сейфа на вкладке окна поверх модели `KeysPanel` (CLAUDE.md §8.2 п.2, п.3, §7.4).

Строка поля — блок: подпись, серая подсказка под ней, статус (задано — зелёный, не задано — красный), поле ввода и
кнопки по доступным действиям, под ними — красная строка проблемы. Ввод своего значения — поле со скрытыми символами;
принято моделью — поле очищается, отказ — красная строка, а введённое остаётся. Принятое сразу записывается в сейф
этой установки — одним шагом, как и сброс своего значения. Запись не удалась — диалог, модель остаётся на прочитанном с
диска, введённое — в поле, чтобы нажать «Сохранить» ещё раз. Введённое, но не сохранённое значение — несохранённое
вкладки: окно спросит перед закрытием.

Значение сейфа в виджет по умолчанию не попадает: статус рисует короткую маску из модели, а поле ввода — то, что
человек печатает сам, и то скрытыми символами. Буфер обмена не трогается: в поле ввода вставлять и выделять можно, а
копировать и вырезать — нет (привязка на самом поле гасит `<<Copy>>` и `<<Cut>>` в любой раскладке).

«Показать своё» (`RowAction.REVEAL`, §14 решение 11): кнопка есть только у поля, которое человек ввёл сам. По явному
нажатию значение просит у модели (`KeysPanel.own_value` — единственная точка раскрытия в настройщике) и кладёт только
в статус своей строки — ttk.Label, из которого текст не выделяется и не копируется; не в поле ввода, не в лог, не в
диалог. Любое действие вкладки, её перерисовка и уход с вкладки снова прячут значение за маску.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Final

from app.secretsafe.dpapi import DpapiUnavailable
from app.secretsafe.value import SecretField
from app.setup.fields.field_use import FieldUse
from app.setup.panels.keys_panel import KeyRow, KeysPanel, RowAction
from app.setup.panels.panel_edit import PanelEdit
from app.setup.tabs.field_shade import FieldShades
from app.setup.tabs.tab_event import BREAK, TkEvent
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, TEXT_WRAP_PIXELS, ProblemLine
from app.setup.tabs.tab_shell import TabShell
from app.setup.tabs.tab_theme import HEADING_STYLE, status_foreground
from app.ui.messages import msg

SECRET_ECHO: Final[str] = "•"             # символ вместо каждого введённого: значение не видно через плечо
ENTRY_WIDTH_CHARS: Final[int] = 64
INPUT_ACTIONS: Final[frozenset[RowAction]] = frozenset({RowAction.ENTER, RowAction.REPLACE})
# Из поля ключа введённое не уходит: ни копированием, ни вырезанием.
BLOCKED_ENTRY_EVENTS: Final[tuple[TkEvent, ...]] = (TkEvent.COPY, TkEvent.CUT)


class FieldBlock:
    """Каркас строки поля: подпись, серая подсказка, статус, ряд ввода (поле и кнопки) и строка проблемы. Одинаков у
    полей сейфа и у открытых ссылок: вкладка выглядит одной таблицей полей."""

    def __init__(self, parent: ttk.Frame, label: str, hint: str) -> None:
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        ttk.Label(self.frame, text=label, style=HEADING_STYLE).pack(anchor=tk.W)
        self.hint: ttk.Label = ttk.Label(
            self.frame, text=hint, foreground=HINT_FOREGROUND, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT
        )
        if hint:
            self.hint.pack(anchor=tk.W)
        self.status: ttk.Label = ttk.Label(self.frame)
        self.status.pack(anchor=tk.W)
        self.input_row: ttk.Frame = ttk.Frame(self.frame)
        self.input_row.pack(fill=tk.X, anchor=tk.W)
        self.problem: ProblemLine = ProblemLine(self.frame, {})
        self.problem.label.pack(fill=tk.X, anchor=tk.W)

    def show_status(self, text: str, is_set: bool) -> None:
        self.status.configure(text=text, foreground=status_foreground(is_set))

    def button(self, text: str, command: Callable[[], None]) -> ttk.Button:
        """Кнопка ряда ввода, справа от поля."""
        button: ttk.Button = ttk.Button(self.input_row, text=text, command=command)
        button.pack(side=tk.LEFT, padx=(PAD, 0))
        return button


class KeyRowView:
    """Виджеты одной строки сейфа: каркас строки, поле ввода и кнопки; кнопки зовут `KeyRows`."""

    def __init__(self, parent: ttk.Frame, row: KeyRow, rows: KeyRows) -> None:
        self.field: SecretField = row.field
        self.row: KeyRow = row
        self.block: FieldBlock = FieldBlock(parent, row.label, row.hint)
        self.entry: ttk.Entry = ttk.Entry(self.block.input_row, show=SECRET_ECHO, width=ENTRY_WIDTH_CHARS)
        self.entry.pack(side=tk.LEFT)
        for blocked in BLOCKED_ENTRY_EVENTS:
            self.entry.bind(blocked, lambda _event: BREAK)
        self.accept_button: ttk.Button = self.block.button(msg.SETUP_BUTTON_SAVE, lambda: rows.accept(self.field))
        self.reset_button: ttk.Button = self.block.button("", lambda: rows.reset(self.field))
        self.reveal_button: ttk.Button = self.block.button(
            msg.SETUP_KEYS_BUTTON_REVEAL, lambda: rows.toggle_own_value(self.field)
        )
        self.buttons: tuple[ttk.Button, ...] = (self.accept_button, self.reset_button, self.reveal_button)
        self.is_revealed: bool = False

    @property
    def status(self) -> ttk.Label:
        return self.block.status

    @property
    def problem(self) -> ProblemLine:
        return self.block.problem

    @property
    def raw(self) -> str:
        """Что человек ввёл в поле."""
        return self.entry.get()

    def show(self, row: KeyRow) -> None:
        """Нарисовать строку модели: статус и только те поле и кнопки, что разрешены действиями строки.

        Перерисовка всегда возвращает маску: показанное значение не переживает ни одного ответа модели.
        """
        self.row = row
        self.reset_button.configure(text=row.reset_label or "")
        self.hide()
        can_input: bool = bool(row.actions & INPUT_ACTIONS)
        shown: dict[ttk.Widget, bool] = {
            self.entry: can_input,
            self.accept_button: can_input,
            self.reset_button: RowAction.RESET in row.actions,
            self.reveal_button: RowAction.REVEAL in row.actions,
        }
        for widget in (self.entry, *self.buttons):
            widget.pack_forget()
        for widget, is_shown in shown.items():
            if is_shown:
                widget.pack(side=tk.LEFT, padx=(0 if widget is self.entry else PAD, 0))

    def show_value(self, value: str) -> None:
        """Показать своё значение в статусе строки вместо маски — только на экране, до следующего `hide`."""
        self.status.configure(text=msg.SETUP_KEY_STATUS_OWN.format(mask=value))
        self.reveal_button.configure(text=msg.SETUP_KEYS_BUTTON_HIDE)
        self.is_revealed = True

    def hide(self) -> None:
        """Вернуть маску строки."""
        self.block.show_status(self.row.status, self.row.is_set)
        self.reveal_button.configure(text=msg.SETUP_KEYS_BUTTON_REVEAL)
        self.is_revealed = False

    def accepted(self) -> None:
        """Модель приняла ввод: поле и строка проблемы очищаются."""
        self.entry.delete(0, tk.END)
        self.problem.show_text(None)


class KeyRows:
    """Строки полей сейфа вкладки: модель `panel`, оболочка вкладки `shell` (оговорки и диалог), виджеты строк —
    `rows` по полям, и что сделать после записи сейфа (`on_saved`).
    """

    def __init__(self, parent: ttk.Frame, panel: KeysPanel, shell: TabShell, on_saved: Callable[[], None]) -> None:
        self.panel: KeysPanel = panel
        self.shell: TabShell = shell
        self.on_saved: Callable[[], None] = on_saved
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, anchor=tk.W)
        self.rows: dict[SecretField, KeyRowView] = {
            field: KeyRowView(self.frame, panel.row(field), self) for field in panel.fields
        }
        self.show()

    @property
    def has_typed(self) -> bool:
        """Введено в поле и не сохранено."""
        return any(view.raw for view in self.rows.values())

    def accept(self, field: SecretField) -> None:
        """«Сохранить»: введённое — модели; принято — сразу в сейф, строка перерисована, поле очищено.

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
        """Сброс своего значения — сразу в сейф: вернётся значение из токена, а если его нет, поле опустеет."""
        self.hide_revealed()
        if self._save(self.panel.reset(field)):
            self.rows[field].problem.show_text(None)

    def toggle_own_value(self, field: SecretField) -> None:
        """«Показать»/«скрыть» своё значение поля. Модель не отдала значение (из токена, поля нет) — ничего."""
        view: KeyRowView = self.rows[field]
        if view.is_revealed:
            view.hide()
            return
        value: str | None = self.panel.own_value(field)
        if value is not None:
            view.show_value(value)

    def shade(self, shades: FieldShades) -> None:
        """Каждая строка — поле окна своего поля сейфа: не нужна ни одной работающей линии — бледная."""
        for field, view in self.rows.items():
            shades.block(FieldUse.of(field), view.block.frame)

    def hide_revealed(self) -> None:
        """Спрятать за маску всё показанное: перед любым действием вкладки и при уходе с неё."""
        for view in self.rows.values():
            if view.is_revealed:
                view.hide()

    def reload(self) -> None:
        """Модель — как сейф сейчас у окна: поле могла записать строка того же поля на другой вкладке."""
        self.panel = KeysPanel.of(self.panel.setup_vault, self.panel.page)
        self.show()

    def show(self) -> None:
        """Перерисовать по модели: оговорки оболочки и строки полей."""
        self.shell.show_notices(self.panel.notices)
        for row in self.panel.rows:
            self.rows[row.field].show(row)

    def _save(self, edited: KeysPanel) -> bool:
        """Модель с правкой пишет личный сейф; записано — модель, прочитанная заново, и True.

        Отказ — диалог без значения и без пути к сейфу, модель прежняя (в ней несохранённого не остаётся), False.
        """
        try:
            saved: PanelEdit[KeysPanel] = edited.save()
        except DpapiUnavailable:
            self.shell.refuse_save(msg.SETUP_INPUT_OWN_UNAVAILABLE)
            return False
        except OSError:
            self.shell.refuse_save(msg.SETUP_KEYS_SAVE_FAILED_OS)
            return False
        self.panel = saved.panel
        self.show()
        self.on_saved()
        return True
