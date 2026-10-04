"""Вкладка окна «Дополнительно» (CLAUDE.md §8.2, §14 решение 37).

Сверху — оговорка: значения по умолчанию подходят; не читается livecraft.json — почему и на чём открыто окно
(оговорки модели настроек окна). Ниже — то, что нужно при любых линиях: часовой пояс программы и срок хранения старых
файлов (раздел настроек со своей кнопкой «Сохранить»). Остальные настройки — на вкладках своих линий. Своих правил у
вкладки нет.
"""
from __future__ import annotations

from tkinter import ttk
from typing import Final

from app.config.setting_key import SettingKey
from app.setup.page import SetupPage
from app.setup.tabs.settings_section import SettingsSection
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg

ADVANCED_KEYS: Final[tuple[SettingKey, ...]] = (SettingKey.TIMEZONE, SettingKey.KEEP_DAYS)


class AdvancedTab:
    """Вкладка «Дополнительно»: оболочка и раздел настроек (`section`)."""

    def __init__(self, context: SetupContext) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.ADVANCED, msg.SETUP_ADVANCED_INTRO)
        self.section: SettingsSection = SettingsSection(self.shell.body, context, ADVANCED_KEYS)
        self.shell.show_notices(context.settings.panel.notices)

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    def show_notices(self) -> None:
        """Оговорки модели настроек окна — после записи: прочитанный файл оговорок не даёт."""
        self.shell.show_notices(self.section.book.panel.notices)
