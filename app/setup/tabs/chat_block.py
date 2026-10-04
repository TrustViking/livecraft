"""Бот и подключение чата Telegram в окне настройщика — один вид для обеих ролей чата (CLAUDE.md §8.2 пп.7, 11, §14
решения 19, 20, 57, 58).

Бот (`BotKeyBlock`): строка токена бота — поле сейфа вкладки (`KeyRows`: на «Telegram» — бот объявлений, на «Логах» —
бот поддержки) и под ней — кто бот после сохранения (`BotCard` модели чата). Бот вкладки — на токене этой строки, том,
что на вкладке сейчас (`BotKeyBlock.bot`).

Чат: по строке на поиск чатов роли (`ChatRole.searches`): заголовок (у чатов объявлений — вид чата: «Чат с ботом»,
«Группа с ботом»), статус чата, подсказка неподключённого чата (у группы — добавить бота и отправить /start@имя_бота,
`ChatSearch.hint`) и кнопка подключения, которая ищет только чаты своего поиска (надпись — `ChatSearch.button`: у
подключённого чата — «Подключить другой …»). Под строками — оговорка о файле настроек, список чатов (виден, только когда
выбирать из нескольких; выбор строки подключает чат) и строка итога. Ими пользуются вкладка «Telegram» (чат объявлений:
две строки — чат с ботом и группа с ботом) и вкладка «Логи» (чат поддержки: одна строка, чат любого вида): роль — у
модели `PublishPanel`, своих правил у блока нет. Бота блок спрашивает у вкладки в момент действия (`ChatHooks.bot`): в
тестах его подменяют подделкой; после каждого действия модели вкладка узнаёт об этом (`ChatHooks.changed`), и окно
перерисовывает всё, что зависит от чатов, — в том числе блоки других вкладок (`refresh`: чаты с диска, названия этого
окна остаются).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk
from typing import Final

from app.config.telegram import ChatSearch
from app.core.text_format import NEWLINE, PARAGRAPH_BREAK
from app.publish.telegram_api import BotChat
from app.publish.telegram_bot import TelegramBot
from app.secretsafe.field import SecretField
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.publish_panel import BotCard, PublishPanel
from app.setup.tabs.key_rows import KeyRows
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_shell import TabShell
from app.setup.tabs.tab_theme import HEADING_STYLE, status_foreground

CHAT_LIST_ROWS: Final[int] = 6
LISTBOX_SELECT: Final[str] = "<<ListboxSelect>>"


@dataclass(frozen=True)
class ChatHooks:
    """Что блок берёт у вкладки: бота на момент действия (`bot`; токена нет — None) и что сделать после действия модели
    (`changed`)."""

    bot: Callable[[], TelegramBot | None]
    changed: Callable[[], None]


class BotKeyBlock:
    """Бот вкладки в рамке `frame` оболочки `shell`: строка токена бота (`keys` поверх модели поля сейфа вкладки; токен
    записан или убран — `on_saved`) и под ней строка «кто бот» (`line`)."""

    def __init__(self, shell: TabShell, frame: ttk.Frame, keys: KeysPanel, on_saved: Callable[[], None]) -> None:
        self.keys: KeyRows = KeyRows(frame, keys, shell, on_saved)
        self.line: ttk.Label = ttk.Label(frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)

    @property
    def bot(self) -> TelegramBot | None:
        """Бот на токене этой строки — том, что на вкладке сейчас; токена нет — бота нет."""
        token_field: SecretField
        token_field, = self.keys.panel.fields
        return TelegramBot.from_vault(self.keys.panel.vault, token_field)

    @property
    def is_dirty(self) -> bool:
        """Токен введён и не сохранён."""
        return self.keys.panel.is_dirty or self.keys.has_typed

    def show(self, card: BotCard) -> None:
        """Кто бот — по модели чата (назван — зелёным); пустой статус места не занимает."""
        self.line.configure(text=card.status, foreground=status_foreground(card.me is not None))
        if card.status:
            self.line.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0), after=self.keys.frame)
        else:
            self.line.pack_forget()


class ChatRowView:
    """Строка поиска `search` в рамке `parent`: заголовок (если он есть) и статус чата в ряд, под ними — подсказка
    неподключённого чата (если она есть) и кнопка подключения; нажатие отдаёт поиск `on_connect`."""

    def __init__(self, parent: ttk.Frame, search: ChatSearch, on_connect: Callable[[ChatSearch], None]) -> None:
        self.search: ChatSearch = search
        self.frame: ttk.Frame = ttk.Frame(parent)
        top: ttk.Frame = ttk.Frame(self.frame)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        top.pack(fill=tk.X, anchor=tk.W)
        if search.words.title:
            ttk.Label(top, text=search.words.title, style=HEADING_STYLE).pack(side=tk.LEFT, padx=(0, PAD))
        self.line: ttk.Label = ttk.Label(top, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.line.pack(side=tk.LEFT, anchor=tk.W)
        self.hint: ttk.Label = ttk.Label(
            self.frame, foreground=HINT_FOREGROUND, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT
        )
        self.button: ttk.Button = ttk.Button(self.frame, command=lambda: on_connect(search))
        self.button.pack(anchor=tk.W, pady=(PAD, 0))

    def show(self, panel: PublishPanel) -> None:
        """Статус чата поиска (подключён — зелёным), подсказка (пустая места не занимает) и надпись кнопки — по
        модели."""
        is_connected: bool = panel.destination_of(self.search) is not None
        self.line.configure(text=panel.line_of(self.search), foreground=status_foreground(is_connected))
        hint: str = self.search.hint(panel.settings.telegram, panel.bot.username)
        self.hint.configure(text=hint)
        if hint:
            self.hint.pack(anchor=tk.W, pady=(PAD, 0), before=self.button)
        else:
            self.hint.pack_forget()
        self.button.configure(text=self.search.button(panel.settings.telegram))


class ChatConnectBlock:
    """Виджеты подключения чата в рамке `frame` вкладки `shell`: строки поисков роли, модель `panel` (роль чата — её
    поле) и связь с вкладкой `hooks`."""

    def __init__(self, shell: TabShell, frame: ttk.Frame, panel: PublishPanel, hooks: ChatHooks) -> None:
        self.shell: TabShell = shell
        self.panel: PublishPanel = panel
        self.hooks: ChatHooks = hooks
        self.rows: tuple[ChatRowView, ...] = tuple(
            ChatRowView(frame, search, self.connect_chat) for search in panel.role.searches
        )
        self.notice: ttk.Label = ttk.Label(frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.chat_list: tk.Listbox = tk.Listbox(frame, height=CHAT_LIST_ROWS, exportselection=False)
        self.chat_list.bind(LISTBOX_SELECT, lambda _event: self.choose_chat())
        self.status: ttk.Label = ttk.Label(frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.status.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        self.show()

    def connect_chat(self, search: ChatSearch) -> None:
        """Кнопка подключения поиска: модель спрашивает бота; один чат поиска — подключён сразу, несколько — список."""
        self.change(lambda: self.panel.find_chats(self.hooks.bot(), search))

    def choose_chat(self) -> None:
        """Чат выбран в списке: он становится чатом роли."""
        selection: tuple[int, ...] = self.chat_list.curselection()
        if selection:
            chosen: BotChat = self.panel.chats.chats[selection[0]]
            self.change(lambda: self.panel.connect(self.hooks.bot(), chosen))

    def change(self, change: Callable[[], PublishPanel]) -> None:
        """Действие модели; затем блок заново и вкладка узнаёт об этом. Сбой записи livecraft.json — диалог."""
        changed: PublishPanel | None = self.shell.write_settings(change)
        if changed is None:
            return
        self.panel = changed
        self.show()
        self.hooks.changed()

    def reload(self) -> None:
        """Всё заново, как сейчас на диске: загруженный токен доступа мог принести и бота, и чаты — названия чатов этого
        окна и кто бот забываются."""
        self.panel = PublishPanel.from_file(self.panel.file, self.panel.role)
        self.show()

    def refresh(self) -> None:
        """Чаты — как они сейчас на диске (их могла записать другая вкладка); кто бот и названия чатов этого окна
        остаются."""
        self.panel = self.panel.reread()
        self.show()

    def show(self) -> None:
        """Строки поисков, оговорка о файле, список чатов (только когда их несколько) и итог — по модели. Пустая
        оговорка места не занимает."""
        panel: PublishPanel = self.panel
        for row in self.rows:
            row.show(panel)
        self.notice.configure(text=PARAGRAPH_BREAK.join(panel.notices))
        if panel.notices:
            self.notice.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0), before=self.status)
        else:
            self.notice.pack_forget()
        self.chat_list.delete(0, tk.END)
        for chat in panel.chats.chats:
            self.chat_list.insert(tk.END, chat.option)
        if panel.chats.chats:
            self.chat_list.pack(fill=tk.X, anchor=tk.W, pady=PAD, before=self.status)
        else:
            self.chat_list.pack_forget()
        self.status.configure(text=NEWLINE.join(panel.status))
