"""Папка материалов на Google Диске на вкладках «Превью» и «Google-документ» (CLAUDE.md §8.2 п.4, п.5, §14 решения 27,
39).

Одно поле на двух вкладках: строка поля сейфа (`KeyRows` поверх `KeysPanel` своей вкладки — маска, «показать своё»,
«Удалить»), под ней — кнопка «Проверить папку» и строки итога. Проверку делает модель `FolderCheck`; окно запускает её в
фоновом потоке (`CheckLine`): сама — когда сменилась папка, которую возьмёт запуск (сохранена ссылка или убрано своё
значение), иначе — по кнопке. Поле записано на одной вкладке — окно перечитывает его на другой (`reload`). Поле вместе
с проверкой — одно поле окна своей нужды (`FieldUse`): не нужно ни одной работающей линии — бледное. Своих правил нет.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.secretsafe.field import SecretField
from app.secretsafe.vault import VaultEntry
from app.setup.fields.field_use import FieldUse
from app.setup.panels.folder_check import FolderCheck, FolderVerdict
from app.setup.panels.keys_panel import KeysPanel
from app.setup.tabs.check_line import CheckLine, CheckTexts
from app.setup.tabs.key_rows import KeyRowView, KeyRows
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg

FIELD: SecretField = SecretField.DRIVE_FOLDER


class FolderBlock:
    """Поле папки Диска на вкладке: оболочка вкладки, строка сейфа (`keys`), модель проверки `check`, строка проверки
    `line` и папка, которую возьмёт запуск (`folder_entry`)."""

    def __init__(self, shell: TabShell, keys: KeysPanel, check: FolderCheck) -> None:
        self.shell: TabShell = shell
        self.check: FolderCheck = check
        self.folder_entry: VaultEntry | None = keys.vault.entry(FIELD)
        self.frame: ttk.Frame = ttk.Frame(shell.body)
        self.frame.pack(fill=tk.X, anchor=tk.W)
        self.keys: KeyRows = KeyRows(self.frame, keys, shell, self.keys_saved)
        texts: CheckTexts = CheckTexts(
            button=msg.SETUP_FOLDER_BUTTON_CHECK,
            checking=msg.SETUP_FOLDER_CHECKING,
            login=msg.SETUP_FOLDER_LOGIN,
            interrupted=FolderVerdict.failed(msg.SETUP_TABLE_INTERRUPTED),
        )
        self.line: CheckLine = CheckLine(self.frame, texts, lambda: self.check.run)
        shell.context.shades.block(FieldUse.of(FIELD), self.frame)

    @property
    def row(self) -> KeyRowView:
        return self.keys.rows[FIELD]

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — введено в поле."""
        return self.keys.panel.is_dirty or self.keys.has_typed

    def keys_saved(self) -> None:
        """Сейф записан: окно узнаёт о записи (и перечитывает поле на другой вкладке); папка, которую возьмёт запуск,
        сменилась и задана — её проверка."""
        folder: VaultEntry | None = self.keys.panel.vault.entry(FIELD)
        is_new: bool = folder is not None and folder != self.folder_entry
        self.folder_entry = folder
        self.shell.on_saved()
        if is_new:
            self.line.start()

    def reload(self) -> None:
        """Поле — как оно сейчас в сейфе: его могла записать та же строка на другой вкладке."""
        self.keys.reload()
        self.folder_entry = self.keys.panel.vault.entry(FIELD)
