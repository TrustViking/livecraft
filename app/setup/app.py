"""Окно настройщика: livecraft.bat --setup (CLAUDE.md §8).

`SetupApp` — запуск окна: осведомлённость о DPI до создания Tk (иначе шрифт на HiDPI мыльный, §8.1),
окно и цикл событий. `SetupWindow` — само окно: три вкладки поверх моделей, строка готовности внизу и
вопрос при закрытии с несохранённым. Правил у окна нет: что годно, что писать и готова ли программа к
запуску, решают модели вкладок и `Readiness`. Значения сейфа окно показывает только масками; исключение —
своё значение по кнопке «показать» на вкладке «Ключи и ссылки» (§14 решение 11), которое прячется при уходе
с вкладки. Буфер обмена окно не трогает; строка готовности — только проблемы `Readiness`, в них значений нет.
"""
from __future__ import annotations

import ctypes
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Final

from app.paths import LivecraftPaths
from app.setup.readiness import Readiness
from app.setup.tabs import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.keys_tab import KeysTab
from app.setup.tabs.settings_tab import SettingsTab
from app.ui import messages_ru as msg
from app.version import APP_VERSION

PROCESS_SYSTEM_DPI_AWARE: Final[int] = 1   # SetProcessDpiAwareness: осведомлённость о DPI системы
CLOSE_PROTOCOL: Final[str] = "WM_DELETE_WINDOW"
READINESS_JOINER: Final[str] = "\n"
TAB_CHANGED_EVENT: Final[str] = "<<NotebookTabChanged>>"


class SetupWindow:
    """Окно на три вкладки. Поля: пути установки, корень Tk, вкладки, строка готовности, признак закрытия."""

    def __init__(self, paths: LivecraftPaths) -> None:
        self.paths: LivecraftPaths = paths
        self.root: tk.Tk = tk.Tk()
        self.root.title(msg.SETUP_WINDOW_TITLE.format(version=APP_VERSION))
        self.is_closed: bool = False
        self.notebook: ttk.Notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)
        self.keys_tab: KeysTab = KeysTab(self.notebook, paths, self.refresh_readiness)
        self.channels_tab: ChannelsTab = ChannelsTab(self.notebook, paths, self.refresh_readiness)
        self.settings_tab: SettingsTab = SettingsTab(self.notebook, paths, self.refresh_readiness)
        self.notebook.add(self.keys_tab.frame, text=msg.SETUP_TAB_KEYS)
        self.notebook.add(self.channels_tab.frame, text=msg.SETUP_TAB_CHANNELS)
        self.notebook.add(self.settings_tab.frame, text=msg.SETUP_TAB_SETTINGS)
        # Уход с вкладки «Ключи и ссылки» прячет показанное своё значение (§14 решение 11).
        self.notebook.bind(TAB_CHANGED_EVENT, lambda _event: self.keys_tab.hide_revealed())
        self.readiness_line: ttk.Label = ttk.Label(self.root, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.readiness_line.pack(fill=tk.X, padx=PAD, pady=PAD)
        self.root.protocol(CLOSE_PROTOCOL, self.request_close)
        self.refresh_readiness()

    @property
    def is_dirty(self) -> bool:
        """Хотя бы на одной вкладке есть несохранённое."""
        return any(tab.is_dirty for tab in (self.keys_tab, self.channels_tab, self.settings_tab))

    def refresh_readiness(self) -> None:
        """Строка готовности по свежей проверке: готово — одна строка, нет — проблемы Readiness."""
        readiness: Readiness = Readiness.check(self.paths)
        text: str = msg.SETUP_READY if readiness.is_ready else READINESS_JOINER.join(readiness.problems)
        self.readiness_line.configure(text=text)

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
        """DPI до создания Tk, затем окно и его цикл событий до закрытия."""
        self._enable_dpi_awareness()
        SetupWindow(self.paths).mainloop()

    @staticmethod
    def _enable_dpi_awareness() -> None:
        """Чёткий шрифт на HiDPI (§8.1). Не Windows или нет shcore — окно просто будет с системным масштабом."""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_SYSTEM_DPI_AWARE)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return
