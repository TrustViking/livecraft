"""Окно настройщика: livecraft.bat --setup (CLAUDE.md §8).

`SetupApp` — запуск окна для установки. `SetupWindow.open` — окно так, как его открывает программа:
осведомлённость о DPI до создания Tk (иначе шрифт на HiDPI мыльный, §8.1), затем окно. `SetupWindow` — само
окно: три вкладки поверх моделей, строка готовности внизу и вопрос при закрытии с несохранённым. Правил у окна
нет: что годно, что писать и готова ли программа к запуску, решают модели вкладок и `Readiness`; несохранённое —
одно правило оболочки вкладки (`TabShell.is_dirty`). Значения сейфа окно показывает только масками; исключение —
своё значение по кнопке «показать» на вкладке «Ключи и ссылки» (§14 решение 11), которое прячется при уходе
с вкладки. Буфер обмена окно не трогает; строка готовности — только проблемы `Readiness`, в них значений нет.
Вставка, выделение, вырезание и копирование в полях работают в любой раскладке (`EditShortcuts`).
"""
from __future__ import annotations

import ctypes
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Final

from app.paths import LivecraftPaths
from app.setup.panels.channels_panel import ChannelsPanel
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.settings_panel import SettingsPanel
from app.setup.readiness import Readiness
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.keys_tab import KeysTab
from app.setup.tabs.settings_tab import SettingsTab
from app.setup.tabs.tab_event import EditShortcuts, TkEvent
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_theme import SetupTheme
from app.ui import messages_ru as msg
from app.version import APP_VERSION

PROCESS_SYSTEM_DPI_AWARE: Final[int] = 1   # SetProcessDpiAwareness: осведомлённость о DPI системы
CLOSE_PROTOCOL: Final[str] = "WM_DELETE_WINDOW"


@dataclass(frozen=True)
class DpiAwareness:
    """Осведомлённость процесса о DPI экрана (§8.1): ставится до создания Tk, одна на процесс."""

    level: int = PROCESS_SYSTEM_DPI_AWARE

    def apply(self) -> None:
        """Чёткий шрифт на HiDPI. Не Windows или нет shcore — окно просто будет с системным масштабом."""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(self.level)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return


class SetupWindow:
    """Окно на три вкладки. Поля: пути установки, корень Tk, стиль, вкладки, строка готовности, признак закрытия."""

    def __init__(self, paths: LivecraftPaths) -> None:
        self.paths: LivecraftPaths = paths
        self.root: tk.Tk = tk.Tk()
        self.root.title(msg.SETUP_WINDOW_TITLE.format(version=APP_VERSION))
        self.is_closed: bool = False
        self.edit_shortcuts: EditShortcuts = EditShortcuts.install(self.root)
        self.theme: SetupTheme = SetupTheme.applied_to(self.root)
        self.notebook: ttk.Notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)
        settings: SettingsPanel = SettingsPanel.from_paths(paths)
        self.keys_tab: KeysTab = KeysTab(self.notebook, KeysPanel.from_paths(paths), self.refresh_readiness)
        self.channels_tab: ChannelsTab = ChannelsTab(
            self.notebook, ChannelsPanel.from_paths(paths), self.refresh_readiness, settings.form_languages
        )
        self.settings_tab: SettingsTab = SettingsTab(self.notebook, settings, self.settings_saved)
        for tab in self.tabs:
            self.notebook.add(tab.frame, text=tab.panel.title)
        # Уход с вкладки «Ключи и ссылки» прячет показанное своё значение (§14 решение 11).
        self.notebook.bind(TkEvent.TAB_CHANGED, lambda _event: self.keys_tab.hide_revealed())
        self.readiness_line: ttk.Label = ttk.Label(self.root, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.readiness_line.pack(fill=tk.X, padx=PAD, pady=PAD)
        self.root.protocol(CLOSE_PROTOCOL, self.request_close)
        self.refresh_readiness()

    @classmethod
    def open(cls, paths: LivecraftPaths) -> SetupWindow:
        """Окно так, как его открывает программа: осведомлённость о DPI до создания Tk, затем окно."""
        DpiAwareness().apply()
        return cls(paths)

    @property
    def tabs(self) -> tuple[KeysTab | ChannelsTab | SettingsTab, ...]:
        """Вкладки в порядке окна."""
        return (self.keys_tab, self.channels_tab, self.settings_tab)

    @property
    def is_dirty(self) -> bool:
        """Хотя бы на одной вкладке есть несохранённое."""
        return any(tab.is_dirty for tab in self.tabs)

    def refresh_readiness(self) -> None:
        """Строка готовности по свежей проверке: готово — одна строка, нет — проблемы (`Readiness.window_line`)."""
        self.readiness_line.configure(text=Readiness.check(self.paths).window_line)

    def settings_saved(self) -> None:
        """Настройки записаны: строка готовности и пометки языков формы на вкладке каналов — без перезапуска окна."""
        self.refresh_readiness()
        self.channels_tab.refresh_form_languages(self.settings_tab.panel.form_languages)

    def request_close(self) -> None:
        """Закрытие окна: есть несохранённое — спросить; «нет» — окно остаётся открытым."""
        if self.is_dirty and not messagebox.askyesno(
            msg.SETUP_CLOSE_DIRTY_TITLE, msg.SETUP_CLOSE_DIRTY_TEXT, parent=self.root
        ):
            return
        self.is_closed = True
        self.root.destroy()

    def mainloop(self) -> None:
        self.root.mainloop()


class SetupApp:
    """Запуск настройщика для установки `paths`. tkinter.TclError (нет Tk или рабочего стола) — наружу, в main."""

    def __init__(self, paths: LivecraftPaths) -> None:
        self.paths: LivecraftPaths = paths

    def run(self) -> None:
        """Окно так, как его открывает программа, и его цикл событий до закрытия."""
        SetupWindow.open(self.paths).mainloop()
