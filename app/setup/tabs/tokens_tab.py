"""Вкладка окна «Токены» (CLAUDE.md §8.2 п.10, §14 решения 16, 44, 45).

Вверху — зачем токен. Раздел «Новый токен»: токен — один файл, передать его любым путём, загрузит любой, у кого он
окажется; срок в сутках (по умолчанию 3), строка «В токен войдут: …» — названиями, без значений, — и кнопка «Создать
токен». Раздел «Полученный токен»: кнопка «Загрузить токен…» — выбор файла токена. Создание и загрузка ходят в сеть за
временем Google — в фоновом потоке (`CheckLine`: поток получает модель без Tk, что набрано в окне — прочитано в главном
потоке). Файл выбирает `TokenFilePicker` (диалог Tk; в тестах — подделка). Загруженный токен меняет поля сейфа и
настройки других вкладок — вкладка говорит об этом окну (`after_load`). Своих правил у вкладки нет: всё решает
`TokenPanel`.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Final

from app.secretsafe.token import TOKEN_SUFFIX
from app.secretsafe.vault import Vault
from app.setup.page import SetupPage
from app.setup.panels.token_panel import (
    DEFAULT_TOKEN_DAYS,
    MAX_TOKEN_DAYS,
    TokenDraft,
    TokenPanel,
    TokenVerdict,
)
from app.setup.tabs.check_line import CheckLine, CheckRun, CheckTexts
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg

FILE_PATTERN: Final[str] = "*{suffix}"
DAYS_WIDTH_CHARS: Final[int] = 6


class TokenFilePicker:
    """Выбор файла токена диалогом Tk поверх окна `parent`; человек закрыл диалог — None."""

    def __init__(self, parent: tk.Misc) -> None:
        self.parent: tk.Misc = parent

    def token(self) -> Path | None:
        title: str = msg.SETUP_TOKENS_PICK_TOKEN
        chosen: str = filedialog.askopenfilename(
            parent=self.parent, title=title, filetypes=((title, FILE_PATTERN.format(suffix=TOKEN_SUFFIX)),)
        )
        return Path(chosen) if chosen else None


class TokensTab:
    """Вкладка «Токены»: оболочка, модель `panel`, выбор файла `picker`, срок (`days`) нового токена, строка «что
    войдёт» (`contents`), строки создания (`create_line`) и загрузки (`load_line`) и что сделать после загрузки
    (`after_load`)."""

    def __init__(self, context: SetupContext, panel: TokenPanel, after_load: Callable[[], None]) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.TOKENS, msg.SETUP_TOKENS_INTRO)
        self.panel: TokenPanel = panel
        self.picker: TokenFilePicker = TokenFilePicker(self.shell.frame)
        self.after_load: Callable[[], None] = after_load
        create: ttk.Frame = self.shell.step(msg.SETUP_TOKENS_CREATE_TITLE, msg.SETUP_TOKENS_CREATE_TEXT)
        days_row: ttk.Frame = self._row(create, msg.SETUP_TOKENS_DAYS_LABEL)
        self.days: ttk.Spinbox = ttk.Spinbox(days_row, from_=1, to=MAX_TOKEN_DAYS, width=DAYS_WIDTH_CHARS)
        self.days.set(str(DEFAULT_TOKEN_DAYS))
        self.days.pack(side=tk.LEFT)
        self._hint(create, msg.SETUP_TOKENS_DAYS_HINT)
        self.contents: ttk.Label = ttk.Label(create, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.contents.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        creating: CheckTexts = self._texts(msg.SETUP_TOKENS_BUTTON_CREATE, msg.SETUP_TOKENS_CREATING)
        self.create_line: CheckLine = CheckLine(create, creating, self._create_run)
        received: ttk.Frame = self.shell.step(msg.SETUP_TOKENS_LOAD_TITLE, msg.SETUP_TOKENS_LOAD_TEXT)
        self.load_line: CheckLine = CheckLine(
            received, self._texts(msg.SETUP_TOKENS_BUTTON_LOAD, msg.SETUP_TOKENS_LOADING), self._load_run, self.loaded
        )
        self.show_contents()

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    @property
    def own(self) -> Vault:
        """Свои значения сейфа окна: свои значения могли записать другие вкладки."""
        return self.shell.context.vault.lenient.own

    def show_contents(self) -> None:
        """«В токен войдут: …» — по своим значениям сейфа окна и настройкам на диске."""
        self.contents.configure(text=self.panel.contents_line(self.own))

    def loaded(self) -> None:
        """Загрузка закончилась: слой токена записан в фоновом потоке — сейф окна читается заново; поля сейфа и
        настройки других вкладок — заново, окно — по свежей проверке."""
        self.shell.context.vault.changed()
        self.show_contents()
        self.after_load()

    def _create_run(self) -> CheckRun:
        """Что создать — срок, как он в окне сейчас, и свои значения сейфа окна (главный поток); создание — в фоне."""
        draft: TokenDraft = TokenDraft(days_text=self.days.get())
        own: Vault = self.own
        panel: TokenPanel = self.panel      # поток получает модель, а не вкладку: объекты Tk — только в главном потоке
        return lambda _mail: panel.create(draft, own)

    def _load_run(self) -> CheckRun | None:
        """Файл токена — диалогом (главный поток); загрузка — в фоне. Файл не выбран — загружать нечего."""
        token: Path | None = self.picker.token()
        if token is None:
            return None
        panel: TokenPanel = self.panel
        return lambda _mail: panel.load(token)

    def _texts(self, button: str, working: str) -> CheckTexts:
        interrupted: TokenVerdict = TokenVerdict.problem(msg.SETUP_TOKENS_INTERRUPTED)
        return CheckTexts(button=button, checking=working, interrupted=interrupted)

    def _row(self, parent: ttk.Frame, label: str) -> ttk.Frame:
        """Ряд «подпись — поле»."""
        row: ttk.Frame = ttk.Frame(parent)
        row.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        ttk.Label(row, text=label).pack(side=tk.LEFT, padx=(0, PAD))
        return row

    def _hint(self, parent: ttk.Frame, text: str) -> None:
        ttk.Label(parent, text=text, foreground=HINT_FOREGROUND, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT).pack(
            fill=tk.X, anchor=tk.W
        )
