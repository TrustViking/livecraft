"""Запись настроек окна настройщика — одно правило на всё окно (CLAUDE.md §8.2).

Модель пишет livecraft.json сама; окно отдаёт ей запись и говорит человеку о сбое: OSError — диалог с причиной поверх
окна, значений и путей к сейфу в нём нет. Так пишут ползунки и выбор «Главной» (`LineSwitches`), разделы настроек
вкладок (`SettingsSection`) и вкладки (`TabShell.write_settings`). Своих правил у записи нет: что писать, решает модель.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox
from typing import TypeVar

from app.ui.messages import msg

WrittenT = TypeVar("WrittenT")


class SettingsWrite:
    """Запись настроек поверх окна `parent` (родитель диалога сбоя)."""

    def __init__(self, parent: tk.Misc) -> None:
        self.parent: tk.Misc = parent

    def run(self, write: Callable[[], WrittenT]) -> WrittenT | None:
        """Запись моделью (`write`): записано — итог записи; сбой диска — диалог с причиной и None."""
        try:
            return write()
        except OSError as error:
            self.refuse(msg.SETUP_SETTINGS_SAVE_FAILED.format(error=error))
            return None

    def refuse(self, text: str) -> None:
        """Запись не состоялась: диалог с причиной."""
        messagebox.showerror(msg.SETUP_SAVE_FAILED_TITLE, text, parent=self.parent)
