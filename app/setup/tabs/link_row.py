"""Строка открытой ссылки livecraft.json на вкладке окна поверх модели `SettingLink` (CLAUDE.md §8.2, §14 решение 15).

Ссылка на форму ключей — на «Ключах в форму». Строка выглядит как строка поля сейфа: подпись и подсказка, статус, поле
ввода и кнопки. Ссылка — не секрет: статус показывает её как есть, поле ввода — обычное. «Сохранить» и «Удалить» пишут
сразу. Строка — поле окна со своими линиями (`FieldUse`): не нужна ни одной работающей — бледная. Своих правил у строки
нет.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Final

from app.setup.fields.field_use import FieldUse
from app.setup.panels.link_panel import SettingLink
from app.setup.panels.panel_edit import PanelEdit
from app.setup.tabs.key_rows import FieldBlock
from app.setup.tabs.tab_layout import PAD
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg

LINK_WIDTH_CHARS: Final[int] = 64       # ссылка длинная: в узком поле её не проверить глазами


class LinkRowView:
    """Строка открытой ссылки: каркас строки, открытое поле ввода, «Сохранить» и «Удалить» (есть, когда ссылка
    задана). `link` — модель строки; запись не удалась — диалог оболочки вкладки; `after_save` — что сделать, когда
    ссылка записана."""

    def __init__(self, parent: ttk.Frame, link: SettingLink, shell: TabShell, after_save: Callable[[], None]) -> None:
        self.link: SettingLink = link
        self.shell: TabShell = shell
        self.after_save: Callable[[], None] = after_save
        self.block: FieldBlock = FieldBlock(parent, link.label, link.hint)
        self.entry: ttk.Entry = ttk.Entry(self.block.input_row, width=LINK_WIDTH_CHARS)
        self.entry.pack(side=tk.LEFT)
        self.save_button: ttk.Button = self.block.button(msg.SETUP_BUTTON_SAVE, self.save)
        self.clear_button: ttk.Button = self.block.button(msg.SETUP_KEYS_BUTTON_DELETE_OWN, self.clear)
        shell.context.shades.block(FieldUse.of(link.key), self.block.frame)
        self.show()

    @property
    def frame(self) -> ttk.Frame:
        return self.block.frame

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — в модели или набрано в поле."""
        return self.link.is_dirty or bool(self.entry.get())

    def save(self) -> None:
        """«Сохранить»: ввод — модели; принято — сразу в livecraft.json, поле очищено. Отказ — строка проблемы."""
        edit: PanelEdit[SettingLink] = self.link.replace(self.entry.get())
        if edit.problem is not None:
            self.block.problem.show_text(edit.problem.text)
            return
        if self._written(edit.panel):
            self.entry.delete(0, tk.END)

    def clear(self) -> None:
        """«Удалить»: ссылки больше нет — сразу в livecraft.json."""
        self._written(self.link.clear())

    def reload(self) -> None:
        """Ссылка — как она сейчас в livecraft.json: её мог записать загруженный токен."""
        self.link = SettingLink.from_file(self.link.file, self.link.key)
        self.show()

    def show(self) -> None:
        """Статус по модели; «Удалить» — только у заданной ссылки."""
        self.block.show_status(self.link.status, self.link.is_set)
        if self.link.is_set:
            self.clear_button.pack(side=tk.LEFT, padx=(PAD, 0))
        else:
            self.clear_button.pack_forget()

    def _written(self, edited: SettingLink) -> bool:
        """Модель с правкой пишет файл; записано — модель, прочитанная заново, и True; сбой диска — диалог и False."""
        written: SettingLink | None = self.shell.write_settings(lambda: edited.save().panel)
        if written is None:
            return False
        self.link = written
        self.block.problem.show_text(None)
        self.show()
        self.shell.on_saved()
        self.after_save()
        return True
