"""Вкладка окна «Cookies YouTube» — сразу после «Таблицы плана» (CLAUDE.md §8.2, §14 решение 73).

Вступление: что такое cookies, что программе вход в YouTube не нужен (§14 решение 80) — с cookies yt-dlp читает и
описания видео 18+, — что они нужны только таблице плана и что у каждого свои — в токен они не входят. Шаг «Как
выгрузить cookies». Ниже — строка статуса файла, кнопки «Загрузить файл…» и «Проверить» со строками итога, под ними —
синяя строка входа в YouTube (`login`: вход есть, нет или проверить не удалось — на работу программы это не влияет), и
срок напоминания (раздел настроек: поле сохраняется само). Файл выбирает `CookiesFilePicker` (диалог Tk; в тестах —
подделка) в главном потоке, копия и проверка — в фоне (`CheckLine`), модель — `CookiesFileCheck`. После итога статус —
заново, строка входа — из итога. Cookies нужны только yt-dlp, который читает видео таблицы:
статус, кнопки и срок — одно поле окна линии «Таблица плана» (`FieldUse`), при входе «Пакеты» вкладка бледная.
Своих правил у вкладки нет.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Final

from app.config.setting_key import SettingKey
from app.setup.fields.field_use import FieldUse
from app.setup.page import SetupPage
from app.setup.panels.cookies_check import CookiesFileCheck, CookiesVerdict
from app.setup.tabs.check_line import CheckLine, CheckRun, CheckTexts, ResultRow
from app.setup.tabs.settings_section import SettingsSection
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_layout import INFO_FOREGROUND, PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg

COOKIES_FILE_PATTERN: Final[str] = "*.txt"
ANY_FILE_PATTERN: Final[str] = "*.*"
COOKIES_KEYS: Final[tuple[SettingKey, ...]] = (SettingKey.COOKIES_REMIND_DAYS,)


class CookiesFilePicker:
    """Выбор файла cookies диалогом Tk поверх окна `parent` — текстовые и все файлы; человек закрыл диалог — None."""

    def __init__(self, parent: tk.Misc) -> None:
        self.parent: tk.Misc = parent

    def cookies(self) -> Path | None:
        types: tuple[tuple[str, str], ...] = (
            (msg.SETUP_COOKIES_TEXT_FILES, COOKIES_FILE_PATTERN), (msg.SETUP_COOKIES_ALL_FILES, ANY_FILE_PATTERN)
        )
        chosen: str = filedialog.askopenfilename(parent=self.parent, title=msg.SETUP_COOKIES_PICK_TITLE, filetypes=types)
        return Path(chosen) if chosen else None


class CookiesTab:
    """Вкладка «Cookies YouTube»: оболочка, модель `check`, выбор файла `picker`, рамка файла (`block` — статус и
    строка проверки), строка статуса `status`, строка проверки `line` с кнопками загрузки и проверки, синяя строка входа
    в YouTube (`login`) и раздел срока напоминания (`section`)."""

    def __init__(self, context: SetupContext, check: CookiesFileCheck) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.COOKIES, msg.SETUP_COOKIES_INTRO)
        self.check: CookiesFileCheck = check
        self.shell.step(msg.SETUP_COOKIES_HOWTO_TITLE, msg.SETUP_COOKIES_HOWTO)
        self.block: ttk.Frame = ttk.Frame(self.shell.body)
        self.block.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        self.picker: CookiesFilePicker = CookiesFilePicker(self.block)
        self.status: ttk.Label = ttk.Label(self.block, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.status.pack(fill=tk.X, anchor=tk.W)
        self.line: CheckLine = CheckLine(self.block, self._texts, self._load_run, self._checked)
        self.line.add_button(msg.SETUP_COOKIES_BUTTON_CHECK, lambda: self.line.start_run(self._check_run()))
        self.login: ttk.Label = ttk.Label(
            self.block, foreground=INFO_FOREGROUND, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT
        )
        self.login.pack(fill=tk.X, anchor=tk.W)
        context.shades.block(FieldUse.of(SettingKey.COOKIES_REMIND_DAYS), self.block)
        self.section: SettingsSection = SettingsSection(self.shell.body, context, COOKIES_KEYS)
        self.show()

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    @property
    def _texts(self) -> CheckTexts:
        return CheckTexts(
            button=msg.SETUP_COOKIES_BUTTON_LOAD,
            checking=msg.SETUP_COOKIES_CHECKING,
            interrupted=CookiesVerdict.failed(msg.SETUP_COOKIES_INTERRUPTED),
        )

    def show(self) -> None:
        """Статус файла своим цветом — как файл сейчас на диске."""
        text: str = self.check.status_line
        self.status.configure(text=text, foreground=ResultRow(text).state.foreground)

    def _checked(self) -> None:
        """После итога: статус файла — заново, строка входа — из итога (синяя)."""
        self.show()
        verdict: object = self.line.verdict
        self.login.configure(text=verdict.login if isinstance(verdict, CookiesVerdict) else "")

    def _load_run(self) -> CheckRun | None:
        """Файл cookies — диалогом (главный поток); копия и проверка — в фоне. Файл не выбран — ничего."""
        source: Path | None = self.picker.cookies()
        check: CookiesFileCheck = self.check     # поток получает модель, а не вкладку: объекты Tk — в главном потоке
        if source is None:
            return None
        self.login.configure(text="")       # прежняя строка входа — не о новом файле
        return lambda mail: check.choose(source)

    def _check_run(self) -> CheckRun:
        check: CookiesFileCheck = self.check
        self.login.configure(text="")
        return lambda mail: check.check()
