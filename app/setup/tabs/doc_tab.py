"""Вкладка окна «Google-документ» — линии DOC и DOC_COPY разделами (CLAUDE.md §8.2, §14 решения 27, 33, 37, 39).

Раздел «Google-документ»: ползунок линии, папка материалов на Google Диске — поле сейфа вместе с её проверкой
(`FolderBlock`: то же поле, что на «Превью»; документ ложится в корень этой папки), доступ к документу по ссылке и
контакты для стримеров в его шапке (раздел настроек). Раздел «Копия документа»: ползунок линии и папка копий .docx
(`FolderRow`). Поле не нужно ни одной работающей линии — бледное (`FieldUse`). Своих правил у вкладки нет.
"""
from __future__ import annotations

from tkinter import ttk

from app.config.setting_key import SettingKey
from app.run.mode import RunPart
from app.setup.page import SetupPage
from app.setup.panels.folder_check import FolderCheck
from app.setup.panels.keys_panel import KeysPanel
from app.setup.tabs.folder_block import FolderBlock
from app.setup.tabs.folder_row import FolderRow
from app.setup.tabs.settings_section import SettingsSection
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_shell import TabShell


class DocTab:
    """Вкладка «Google-документ»: папка материалов на Диске с проверкой (`folder`), доступ и контакты (`doc`) и папка
    копий (`copies`)."""

    def __init__(self, context: SetupContext, keys: KeysPanel, check: FolderCheck) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.DOC)
        self.shell.header(RunPart.DOC)
        self.folder: FolderBlock = FolderBlock(self.shell, keys, check)
        keys_of_doc: tuple[SettingKey, ...] = (SettingKey.DOCS_ACCESS, SettingKey.DOCS_CONTACTS)
        self.doc: SettingsSection = SettingsSection(self.shell.body, context, keys_of_doc)
        self.shell.header(RunPart.DOC_COPY)
        self.copies: FolderRow = FolderRow.placed(self.shell, SettingKey.FOLDERS_DOCS)

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — введено в поле папки Диска; разделы настроек считает модель настроек окна."""
        return self.folder.is_dirty

    def hide_revealed(self) -> None:
        """Уход с вкладки прячет показанное своё значение (§14 решение 11)."""
        self.folder.keys.hide_revealed()
