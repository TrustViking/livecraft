"""Проект Google — первым на вкладке «Главная» (CLAUDE.md §8.2 п.1, §9, §14 решение 66).

Раздел: что такое проект Google и где взять файл клиента, строка статуса («✓ проект <ID> — путь — чей он» или «✗» с
причиной: не выбран, файл не найден, не годится), кнопки «Выбрать файл…» и «Проверить», под ними строки итога. Выбор и
проверка — модель `ClientCheck`; окно запускает их в фоновом потоке (`CheckLine`): файл выбирает `ClientFilePicker`
(диалог Tk; в тестах — подделка) в главном потоке, запись пути в настройки и вопрос Google — в фоне. После итога
статус — заново, окно — по свежей проверке (готовность, «В токен войдут»). Раздел не знает вкладки: ему дают рамку и
что сделать после итога. Своих правил нет.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Final

from app.setup.panels.client_check import ClientCheck, ClientVerdict
from app.setup.tabs.check_line import CheckLine, CheckRun, CheckTexts, ResultRow
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_theme import HEADING_STYLE
from app.ui.messages import msg

CLIENT_FILE_PATTERN: Final[str] = "*.json"


class ClientFilePicker:
    """Выбор файла клиента Google диалогом Tk поверх окна `parent`; человек закрыл диалог — None."""

    def __init__(self, parent: tk.Misc) -> None:
        self.parent: tk.Misc = parent

    def client(self) -> Path | None:
        title: str = msg.SETUP_CLIENT_PICK_TITLE
        chosen: str = filedialog.askopenfilename(
            parent=self.parent, title=title, filetypes=((title, CLIENT_FILE_PATTERN),)
        )
        return Path(chosen) if chosen else None


class ClientBlock:
    """Раздел «Проект Google»: рамка раздела `frame`, модель `check`, что сделать после итога (`on_saved` — окно по
    свежей проверке), выбор файла `picker`, строка статуса `status`, строка проверки `line` с кнопками выбора и
    проверки (`check_button`)."""

    def __init__(self, parent: ttk.Frame, check: ClientCheck, on_saved: Callable[[], None]) -> None:
        self.check: ClientCheck = check
        self.on_saved: Callable[[], None] = on_saved
        self.picker: ClientFilePicker = ClientFilePicker(parent)
        self.frame: ttk.Frame = ttk.Frame(parent)
        ttk.Label(self.frame, text=msg.SETUP_CLIENT_TITLE, style=HEADING_STYLE).pack(anchor=tk.W)
        about: ttk.Label = ttk.Label(self.frame, text=msg.SETUP_CLIENT_TEXT, wraplength=TEXT_WRAP_PIXELS)
        about.configure(justify=tk.LEFT)
        about.pack(fill=tk.X, anchor=tk.W)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        self.status: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.status.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        texts: CheckTexts = CheckTexts(
            button=msg.SETUP_CLIENT_BUTTON_PICK,
            checking=msg.SETUP_CLIENT_CHECKING,
            interrupted=ClientVerdict.failed(msg.SETUP_CLIENT_INTERRUPTED),
        )
        self.line: CheckLine = CheckLine(self.frame, texts, self._choose_run, self.done)
        self.check_button: ttk.Button = self.line.add_button(msg.SETUP_CLIENT_BUTTON_CHECK, self._start_check)
        self.show()

    def show(self) -> None:
        """Статус проекта своим цветом; настройки и файл читаются с диска: их мог поменять загруженный токен доступа."""
        status: str = self.check.files.status_line
        self.status.configure(text=status, foreground=ResultRow(status).state.foreground)

    def done(self) -> None:
        """Итог выбора или проверки: статус заново, окно — по свежей проверке."""
        self.show()
        self.on_saved()

    def _choose_run(self) -> CheckRun | None:
        """Файл клиента — диалогом (главный поток); запись и проверка — в фоне. Файл не выбран — ничего."""
        source: Path | None = self.picker.client()
        if source is None:
            return None
        check: ClientCheck = self.check      # поток получает модель, а не раздел: объекты Tk — только в главном потоке
        return lambda _mail: check.choose(source)

    def _start_check(self) -> None:
        self.line.start_run(self.check.run)
