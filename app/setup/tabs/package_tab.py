"""Вкладка окна «Пакет» — линия PACKAGE (CLAUDE.md §8.2, §14 решения 13, 18, 37).

Вверху — ползунок линии. Ниже — папка пакетов (`FolderRow`, выбор папки): в неё пакет пишется, из неё же эфиры берут
пакеты, когда таблица плана выключена, а таблица — тексты уже упакованных эфиров. Поле нужно не только пакету
(`FieldUse`): бледное, только когда не работает ни одна линия, которая её читает или пишет. Своих правил у вкладки
нет.
"""
from __future__ import annotations

from tkinter import ttk

from app.config.setting_key import SettingKey
from app.setup.page import SetupPage
from app.setup.tabs.folder_row import FolderRow
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_shell import TabShell


class PackageTab:
    """Вкладка «Пакет»: оболочка и папка пакетов (`packages`)."""

    def __init__(self, context: SetupContext) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.PACKAGE)
        self.packages: FolderRow = FolderRow.placed(self.shell, SettingKey.FOLDERS_PACKAGES)

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page
