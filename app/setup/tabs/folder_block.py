"""Папка Google Диска на вкладке «Превью» (папка превью) или «Google-документ» (папка документов объявлений) (CLAUDE.md
§8.2 пп. 4, 5, §14 решения 27, 39, 60).

Блок — на поле, которое ему дала его проверка (`FolderCheck.field`): строка поля сейфа (`KeyRows` поверх `KeysPanel`
своей вкладки — маска, «показать своё», «Удалить»), под ней — кнопка «Проверить папку» и строки итога. Проверку делает
модель `FolderCheck`; окно запускает её в фоновом потоке (`CheckLine`): сама — когда сменилась папка, которую возьмёт
запуск (сохранена ссылка или убрано своё значение), иначе — по кнопке. Запись поля другую папку не меняет; после
загрузки токена доступа окно перечитывает поле (`reload`). Поле вместе с проверкой — одно поле окна своей нужды
(`FieldUse`): не нужно ни одной работающей линии — бледное. Своих правил нет.
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


class FolderBlock:
    """Поле папки Диска на вкладке: оболочка вкладки, поле сейфа (`field` — то, что проверяет `check`), строка сейфа
    (`keys`), модель проверки `check`, строка проверки `line` и папка, которую возьмёт запуск (`folder_entry`)."""

    def __init__(self, shell: TabShell, keys: KeysPanel, check: FolderCheck) -> None:
        self.shell: TabShell = shell
        self.check: FolderCheck = check
        self.field: SecretField = check.field
        self.folder_entry: VaultEntry | None = keys.vault.entry(self.field)
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
        shell.context.shades.block(FieldUse.of(self.field), self.frame)

    @property
    def row(self) -> KeyRowView:
        return self.keys.rows[self.field]

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — введено в поле."""
        return self.keys.panel.is_dirty or self.keys.has_typed

    def keys_saved(self) -> None:
        """Сейф записан: окно узнаёт о записи; папка, которую возьмёт запуск, сменилась и задана — её проверка."""
        before: VaultEntry | None = self.folder_entry
        self.folder_entry = self.keys.panel.vault.entry(self.field)
        self.shell.on_saved()
        if self.folder_entry is not None and self.folder_entry != before:
            self.line.start()

    def reload(self) -> None:
        """Поле — как оно сейчас в сейфе: его мог заменить загруженный токен доступа; окно перечитывает поле и при
        обновлении."""
        self.keys.reload()
        self.folder_entry = self.keys.panel.vault.entry(self.field)
