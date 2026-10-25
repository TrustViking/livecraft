"""Вкладка окна «Токены» (CLAUDE.md §8.2 п.10, §14 решения 16, 44, 45, 70, 77).

Вверху — зачем токен. Раздел «Новый токен»: токен — один файл, передать его любым путём, загрузит любой, у кого он
окажется; срок в сутках (по умолчанию 3); ползунок на каждое значение, которое токен может нести (`TokenItem`), группами
по линиям работы (`TokenGroup`: сначала проект Google, затем линии в порядке «Главной») — у проекта Google и каналов
YouTube подсказки, чем это грозит (при открытии окна выключены, в настройках не хранятся; любое сочетание годно, §14
решение 77); ползунок значения, которого на этой установке нет, бледный и не включается (`TokenPanel.available`);
подписи слева, ползунки и поле срока — одной вертикалью (`TokenGrid`); строка «В токен войдут: …» — названиями, без
значений, — и кнопка «Создать токен». Раздел «Полученный токен»: кнопка «Загрузить токен…» — выбор файла токена. Создание и загрузка
ходят в сеть за временем Google — в фоновом потоке (`CheckLine`: поток получает модель без Tk, что набрано в окне — прочитано в главном
потоке). Файл выбирает `TokenFilePicker` (диалог Tk; в тестах — подделка). Загруженный токен меняет поля сейфа и
настройки, каналы других вкладок — вкладка говорит об этом окну (`after_load`). Своих правил у вкладки нет: всё решает
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
from app.setup.panels.token_scope import TokenGroup, TokenItem, TokenScope
from app.setup.tabs.check_line import CheckLine, CheckRun, CheckTexts
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_grid import INPUT_COLUMN, LABEL_COLUMN
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, SPIN_WIDTH_CHARS, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_shell import TabShell
from app.setup.tabs.tab_theme import HEADING_STYLE
from app.setup.tabs.toggle_switch import ToggleSwitch
from app.ui.messages import msg

FILE_PATTERN: Final[str] = "*{suffix}"
WIDE_SPAN: Final[int] = 2       # заголовок группы и подсказка — на оба столбца сетки «Нового токена»


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


class TokenGrid:
    """Сетка раздела «Новый токен»: подпись — в столбце подписей, ползунок и поле срока — в общем столбце полей, у левого
    края (одна вертикаль при подписях разной длины); заголовки групп и подсказки — на оба столбца. `rows` — строк уже
    занято."""

    def __init__(self, parent: ttk.Frame) -> None:
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, anchor=tk.W)
        # Ширину подсказок на оба столбца сетка отдаёт столбцу полей: иначе столбец подписей растягивался бы до ширины
        # подсказки, и ползунки уходили бы далеко от подписей.
        self.frame.columnconfigure(INPUT_COLUMN, weight=1)
        self.rows: int = 0

    def field(self, label: str, widget: tk.Widget) -> None:
        """Строка «подпись — поле»; поле создано в `frame`."""
        ttk.Label(self.frame, text=label).grid(
            row=self.rows, column=LABEL_COLUMN, sticky=tk.W, padx=(0, PAD), pady=(PAD, 0)
        )
        widget.grid(row=self.rows, column=INPUT_COLUMN, sticky=tk.W, pady=(PAD, 0))
        self.rows += 1

    def wide(self, widget: tk.Widget, top: int) -> None:
        """Строка на оба столбца: заголовок группы (`top` — отступ сверху) или подсказка; виджет создан в `frame`."""
        widget.grid(row=self.rows, column=LABEL_COLUMN, columnspan=WIDE_SPAN, sticky=tk.W, pady=(top, 0))
        self.rows += 1


class TokensTab:
    """Вкладка «Токены»: оболочка, модель `panel`, выбор файла `picker`, срок (`days`) нового токена, ползунки значений
    (`switches`), строка «что войдёт» (`contents`), строки создания (`create_line`) и загрузки (`load_line`) и что
    сделать после загрузки (`after_load`)."""

    def __init__(self, context: SetupContext, panel: TokenPanel, after_load: Callable[[], None]) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.TOKENS, msg.SETUP_TOKENS_INTRO)
        self.panel: TokenPanel = panel
        self.picker: TokenFilePicker = TokenFilePicker(self.shell.frame)
        self.after_load: Callable[[], None] = after_load
        create: ttk.Frame = self.shell.step(msg.SETUP_TOKENS_CREATE_TITLE, msg.SETUP_TOKENS_CREATE_TEXT)
        grid: TokenGrid = TokenGrid(create)
        self.days: ttk.Spinbox = ttk.Spinbox(grid.frame, from_=1, to=MAX_TOKEN_DAYS, width=SPIN_WIDTH_CHARS)
        self.days.set(str(DEFAULT_TOKEN_DAYS))
        grid.field(msg.SETUP_TOKENS_DAYS_LABEL, self.days)
        self._hint(grid, msg.SETUP_TOKENS_DAYS_HINT)
        self.switches: dict[TokenItem, ToggleSwitch] = {}
        for group in TokenGroup.all():
            heading: ttk.Label = ttk.Label(grid.frame, text=group.heading, style=HEADING_STYLE, foreground=HINT_FOREGROUND)
            grid.wide(heading, PAD)
            self.switches.update({item: self._switch(grid, item) for item in group.items})
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

    @property
    def scope(self) -> TokenScope:
        """Что включили ползунки значений."""
        return TokenScope(frozenset(item for item, switch in self.switches.items() if switch.variable.get()))

    def show_contents(self) -> None:
        """Ползунки по тому, что есть на этой установке: значения нет — ползунок бледный и выключен (значение могли
        удалить на другой вкладке); затем строка «В токен войдут: …»."""
        available: frozenset[TokenItem] = self.panel.available(self.own)
        for item, switch in self.switches.items():
            switch.set_enabled(item in available)
            if item not in available and switch.variable.get():
                switch.variable.set(False)
        self.show_line()

    def show_line(self) -> None:
        """«В токен войдут: …» — по своим значениям сейфа окна, настройкам и файлам на диске и ползункам."""
        self.contents.configure(text=self.panel.contents_line(self.own, self.scope))

    def loaded(self) -> None:
        """Загрузка закончилась: слой токена записан в фоновом потоке — сейф окна читается заново; поля сейфа и
        настройки других вкладок — заново, окно — по свежей проверке."""
        self.shell.context.vault.changed()
        self.show_contents()
        self.after_load()

    def _create_run(self) -> CheckRun:
        """Что создать — срок и ползунки, как они в окне сейчас, и свои значения сейфа окна (главный поток);
        создание — в фоне."""
        draft: TokenDraft = TokenDraft(days_text=self.days.get(), scope=self.scope)
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

    def _switch(self, grid: TokenGrid, item: TokenItem) -> ToggleSwitch:
        """Строка «подпись — ползунок» значения `item` и его подсказка, если она есть; ползунок выключен и сразу
        обновляет строку «что войдёт»."""
        switch: ToggleSwitch = ToggleSwitch(grid.frame, tk.BooleanVar(self.shell.frame, value=False), self.show_line)
        grid.field(item.label, switch)
        if item.hint:
            self._hint(grid, item.hint)
        return switch

    def _hint(self, grid: TokenGrid, text: str) -> None:
        hint: ttk.Label = ttk.Label(
            grid.frame, text=text, foreground=HINT_FOREGROUND, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT
        )
        grid.wide(hint, 0)
