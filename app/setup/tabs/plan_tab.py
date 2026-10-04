"""Вкладка окна «Таблица плана» — линия PLAN (CLAUDE.md §8.2, §14 решения 26, 37).

Вверху — ползунок линии. Ниже — строка поля сейфа «Google-таблица с планом стримов» (`KeyRows` поверх `KeysPanel`
вкладки), под ней — какой должна быть таблица и её проверка (`TableBlock` поверх `TableCheck`). Сменилась таблица,
которую прочтёт запуск (сохранена ссылка или убрано своё значение), — проверка таблицы идёт сама; при открытии окна
проверок нет. Строка таблицы вместе с проверкой — одно поле нужды «таблица плана» (`FieldUse`, рамка `field`): не
работает ни одна линия, которой нужна таблица, — оно бледное. Своих правил у вкладки нет.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from app.run.mode import Need
from app.secretsafe.field import SecretField
from app.secretsafe.vault import VaultEntry
from app.setup.fields.field_use import FieldUse
from app.setup.page import SetupPage
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.table_check import TableCheck
from app.setup.tabs.key_rows import KeyRowView, KeyRows
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_shell import TabShell
from app.setup.tabs.table_block import TableBlock


class PlanTab:
    """Вкладка «Таблица плана»: оболочка, рамка поля таблицы (`field`) со строкой сейфа (`keys`), образцом и проверкой
    таблицы (`table`) и таблица, которую прочтёт запуск (`table_entry`)."""

    def __init__(self, context: SetupContext, keys: KeysPanel, table: TableCheck) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.PLAN)
        self.window_saved: Callable[[], None] = context.on_saved
        self.table_entry: VaultEntry | None = keys.vault.entry(SecretField.SHEETS_ID)
        self.field: ttk.Frame = ttk.Frame(self.shell.body)
        self.field.pack(fill=tk.X, anchor=tk.W)
        self.keys: KeyRows = KeyRows(self.field, keys, self.shell, self.keys_saved)
        self.table: TableBlock = TableBlock(self.field, table, context.settings.panel.settings.timezone)
        context.shades.block(FieldUse.of(Need.SHEETS_VAULT), self.field)

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    @property
    def rows(self) -> dict[SecretField, KeyRowView]:
        return self.keys.rows

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — в модели или введено в поле."""
        return self.keys.panel.is_dirty or self.keys.has_typed

    def hide_revealed(self) -> None:
        """Уход с вкладки прячет показанное своё значение (§14 решение 11)."""
        self.keys.hide_revealed()

    def keys_saved(self) -> None:
        """Сейф записан: окно узнаёт о записи; таблица, которую прочтёт запуск, сменилась и задана — её проверка."""
        self.window_saved()
        table: VaultEntry | None = self.keys.panel.vault.entry(SecretField.SHEETS_ID)
        is_new: bool = table is not None and table != self.table_entry
        self.table_entry = table
        if is_new:
            self.table.line.start()
