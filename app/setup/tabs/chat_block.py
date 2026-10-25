"""Бот и чаты объявлений Telegram в окне настройщика (CLAUDE.md §8.2 п.7, §14 решения 19, 57, 58, 63).

Бот (`BotKeyBlock`): строка токена бота — поле сейфа вкладки (`KeyRows`) и под ней — кто бот (`BotCard` модели чатов).
Бот вкладки — на токене этой строки, том, что на вкладке сейчас (`BotKeyBlock.bot`).

Чаты: по строке на вид чата (`ANNOUNCE_TARGETS`: «Чат с ботом», «Группа с ботом»): заголовок, статус чата, под ними —
подсказка неподключённого чата (у группы — добавить бота и отправить /start@имя_бота, `ChatSearch.hint`) или отказ
Telegram у подключённого (бота удалили из группы, чат не найден — `KnownChats.refusal`), кнопка подключения, которая
ищет только чаты своего вида (надпись — `ChatSearch.button`), и у подключённого чата — «Проверить» (пробное сообщение,
`PublishPanel.check`). Под строками — оговорка о файле настроек, список чатов (виден, только когда выбирать из
нескольких; выбор строки подключает чат) и строка итога. Своих правил у блока нет: всё решает модель `PublishPanel`.

Названия подключённых чатов окно узнаёт у Telegram само, без сообщений (`name_chats` → `PublishPanel.with_names`), в
фоновом потоке (`MailPoll`): getChat к сети, а окно не должно замирать. Поток получает только модель и бота — ни одного
объекта Tk. Пока шёл ответ, модель могла смениться (подключение, другой бот, токен доступа) — тогда ответ устарел, и
названия спрашиваются заново у модели, какая она теперь.

Бота блок спрашивает у вкладки в момент действия (`ChatHooks.bot`), бота для названий — так же (`ChatHooks.names`): в
тестах их подменяют подделками; после каждого действия модели вкладка узнаёт об этом (`ChatHooks.changed`), и окно
перерисовывает всё, что зависит от чатов.
"""
from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk
from typing import Final

from app.config.telegram import ANNOUNCE_TARGETS, ChatSearch
from app.core.text_format import NEWLINE, PARAGRAPH_BREAK
from app.publish.telegram_api import BotChat
from app.publish.telegram_bot import TelegramBot
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.publish_panel import BotCard, PublishPanel
from app.setup.tabs.check_line import MailPoll
from app.setup.tabs.key_rows import KeyRows
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_shell import TabShell
from app.setup.tabs.tab_theme import HEADING_STYLE, STATUS_UNSET_FOREGROUND, status_foreground
from app.ui.messages import msg

CHAT_LIST_ROWS: Final[int] = 6
LISTBOX_SELECT: Final[str] = "<<ListboxSelect>>"


@dataclass(frozen=True)
class ChatHooks:
    """Что блок берёт у вкладки: бота на момент действия (`bot`; токена нет — None), что сделать после действия модели
    (`changed`) и бота, у которого окно само спрашивает названия чатов (`names`; в программе — тот же бот)."""

    bot: Callable[[], TelegramBot | None]
    changed: Callable[[], None]
    names: Callable[[], TelegramBot | None]


class BotKeyBlock:
    """Бот вкладки в рамке `frame` оболочки `shell`: строка токена бота (`keys` поверх модели поля сейфа вкладки; токен
    записан или убран — `on_saved`) и под ней строка «кто бот» (`line`)."""

    def __init__(self, shell: TabShell, frame: ttk.Frame, keys: KeysPanel, on_saved: Callable[[], None]) -> None:
        self.keys: KeyRows = KeyRows(frame, keys, shell, on_saved)
        self.line: ttk.Label = ttk.Label(frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)

    @property
    def bot(self) -> TelegramBot | None:
        """Бот на токене этой строки — том, что на вкладке сейчас; токена нет — бота нет."""
        return TelegramBot.from_vault(self.keys.panel.vault)

    @property
    def is_dirty(self) -> bool:
        """Токен введён и не сохранён."""
        return self.keys.panel.is_dirty or self.keys.has_typed

    def show(self, card: BotCard) -> None:
        """Кто бот — по модели чатов (назван — зелёным); пустой статус места не занимает."""
        self.line.configure(text=card.status, foreground=status_foreground(card.me is not None))
        if card.status:
            self.line.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0), after=self.keys.frame)
        else:
            self.line.pack_forget()


@dataclass(frozen=True)
class ChatRowActions:
    """Кнопки строки чата: подключить чат поиска (`connect`) и проверить подключённый (`check`)."""

    connect: Callable[[ChatSearch], None]
    check: Callable[[ChatSearch], None]


class ChatRowView:
    """Строка поиска `search` в рамке `parent`: заголовок и статус чата в ряд, под ними — подсказка неподключённого
    чата или отказ Telegram у подключённого (если они есть) и ряд кнопок: подключение и «Проверить» (только у
    подключённого чата)."""

    def __init__(self, parent: ttk.Frame, search: ChatSearch, actions: ChatRowActions) -> None:
        self.search: ChatSearch = search
        self.frame: ttk.Frame = ttk.Frame(parent)
        top: ttk.Frame = ttk.Frame(self.frame)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        top.pack(fill=tk.X, anchor=tk.W)
        ttk.Label(top, text=search.words.title, style=HEADING_STYLE).pack(side=tk.LEFT, padx=(0, PAD))
        self.line: ttk.Label = ttk.Label(top, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.line.pack(side=tk.LEFT, anchor=tk.W)
        self.hint: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.buttons: ttk.Frame = ttk.Frame(self.frame)
        self.buttons.pack(anchor=tk.W, pady=(PAD, 0))
        self.button: ttk.Button = ttk.Button(self.buttons, command=lambda: actions.connect(search))
        self.button.pack(side=tk.LEFT)
        self.check_button: ttk.Button = ttk.Button(
            self.buttons, text=msg.SETUP_TELEGRAM_BUTTON_CHECK, command=lambda: actions.check(search)
        )

    def show(self, panel: PublishPanel) -> None:
        """Статус чата поиска (подключён — зелёным), подсказка или отказ (пустые места не занимают), надпись кнопки
        подключения и «Проверить» у подключённого чата — по модели."""
        is_connected: bool = panel.destination_of(self.search) is not None
        self.line.configure(text=panel.line_of(self.search), foreground=status_foreground(is_connected))
        refusal: str = panel.named.refusal(self.search.chat_of(panel.settings.telegram))
        hint: str = refusal or self.search.hint(panel.settings.telegram, panel.bot.username)
        self.hint.configure(text=hint, foreground=STATUS_UNSET_FOREGROUND if refusal else HINT_FOREGROUND)
        if hint:
            self.hint.pack(anchor=tk.W, pady=(PAD, 0), before=self.buttons)
        else:
            self.hint.pack_forget()
        self.button.configure(text=self.search.button(panel.settings.telegram))
        if is_connected:
            self.check_button.pack(side=tk.LEFT, padx=(PAD, 0))
        else:
            self.check_button.pack_forget()


class ChatConnectBlock:
    """Виджеты чатов объявлений в рамке `frame` вкладки `shell`: строки видов чата, модель `panel`, связь с вкладкой
    `hooks`, фоновый опрос названий (`naming`) и модель, у которой спрашиваются названия сейчас (`asked`; None —
    не спрашиваются)."""

    def __init__(self, shell: TabShell, frame: ttk.Frame, panel: PublishPanel, hooks: ChatHooks) -> None:
        self.shell: TabShell = shell
        self.panel: PublishPanel = panel
        self.hooks: ChatHooks = hooks
        actions: ChatRowActions = ChatRowActions(connect=self.connect_chat, check=self.check_chat)
        self.rows: tuple[ChatRowView, ...] = tuple(
            ChatRowView(frame, target.search, actions) for target in ANNOUNCE_TARGETS
        )
        self.notice: ttk.Label = ttk.Label(frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.chat_list: tk.Listbox = tk.Listbox(frame, height=CHAT_LIST_ROWS, exportselection=False)
        self.chat_list.bind(LISTBOX_SELECT, lambda _event: self.choose_chat())
        self.status: ttk.Label = ttk.Label(frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.status.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        self.naming: MailPoll[PublishPanel] = MailPoll(self.status, self._named)
        self.asked: PublishPanel | None = None
        self.show()

    def connect_chat(self, search: ChatSearch) -> None:
        """Кнопка подключения поиска: модель спрашивает бота; один чат поиска — подключён сразу, несколько — список."""
        self.change(lambda: self.panel.find_chats(self.hooks.bot(), search))

    def check_chat(self, search: ChatSearch) -> None:
        """«Проверить» у подключённого чата: пробное сообщение в него."""
        self.change(lambda: self.panel.check(self.hooks.bot(), search))

    def choose_chat(self) -> None:
        """Чат выбран в списке: он становится чатом объявлений своего вида."""
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

    def name_chats(self) -> None:
        """Названия подключённых чатов — у Telegram, в фоне, без сообщений. Токена нет — ничего; названия уже
        спрашиваются — ничего: устаревший ответ спросит их заново сам."""
        bot: TelegramBot | None = self.hooks.names()
        if bot is None or self.naming.is_running:
            return
        asked: PublishPanel = self.panel
        inbox: queue.Queue[PublishPanel] = self.naming.inbox      # поток держит только модель, бота и очередь
        self.asked = asked
        self.naming.start(lambda: inbox.put(asked.with_names(bot)))

    def _named(self, named: PublishPanel) -> bool:
        """Ответ с названиями — в главном потоке: модель с тех пор не менялась — она и есть ответ; сменилась — ответ
        устарел, названия спрашиваются заново. Этот опрос кончается в любом случае."""
        if self.panel is not self.asked:
            self.name_chats()
            return True
        self.asked = None
        self.panel = named
        self.show()
        self.hooks.changed()
        return True

    def reload(self) -> None:
        """Всё заново, как сейчас на диске: загруженный токен доступа мог принести и бота, и чаты — названия чатов этого
        окна и кто бот забываются."""
        self.panel = PublishPanel.from_file(self.panel.file)
        self.show()

    def refresh(self) -> None:
        """Чаты — как они сейчас на диске (их мог записать загруженный токен доступа); кто бот и названия чатов этого
        окна остаются."""
        self.panel = self.panel.reread()
        self.show()

    def show(self) -> None:
        """Строки видов чата, оговорка о файле, список чатов (только когда их несколько) и итог — по модели. Пустая
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
