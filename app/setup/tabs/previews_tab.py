"""Вкладка окна «Превью» — линии LOCAL_PREVIEWS и DRIVE_PREVIEWS разделами (CLAUDE.md §8.2, §14 решения 27, 37, 39).

Раздел «Превью на диске»: ползунок линии, папка превью (`FolderRow`, выбор папки) и шаблон подпапок превью в ней (раздел
настроек). Раздел «Превью на Google Диске»: ползунок линии, папка материалов на Google Диске — поле сейфа вместе с её
проверкой (`FolderBlock`: то же поле, что на «Google-документе») — и шаблон подпапок превью на Диске (раздел настроек).
Поле не нужно ни одной работающей линии — бледное (`FieldUse`). Своих правил у вкладки нет.
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


class PreviewsTab:
    """Вкладка «Превью»: папка превью (`images`) и её шаблон (`local`), папка материалов на Диске с проверкой (`folder`)
    и шаблон подпапок на Диске (`drive`)."""

    def __init__(self, context: SetupContext, keys: KeysPanel, check: FolderCheck) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.PREVIEWS)
        body: ttk.Frame = self.shell.body
        self.shell.header(RunPart.LOCAL_PREVIEWS)
        self.images: FolderRow = FolderRow.placed(self.shell, SettingKey.FOLDERS_IMAGES)
        self.local: SettingsSection = SettingsSection(body, context, (SettingKey.IMAGE_DIR_TEMPLATE,))
        self.shell.header(RunPart.DRIVE_PREVIEWS)
        self.folder: FolderBlock = FolderBlock(self.shell, keys, check)
        self.drive: SettingsSection = SettingsSection(body, context, (SettingKey.DRIVE_PREVIEW_PATH_TEMPLATE,))

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
