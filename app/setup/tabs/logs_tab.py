"""Вкладка окна «Логи» (CLAUDE.md §8.2 п.11, §13 задача 7.2, §14 решения 20, 43, 46, 58).

Вверху — зачем логи. Раздел «Бот поддержки»: логи носит свой бот, отдельный от бота объявлений — строка токена бота
поддержки (поле сейфа вкладки) и кто бот после сохранения (`BotKeyBlock`, тот же вид, что у бота объявлений на вкладке
«Telegram»). Раздел «Чат поддержки»: подключение чата ботом поддержки — тот же вид и тот же порядок действий, что у чата
объявлений (`ChatConnectBlock` с моделью роли `ChatRole.SUPPORT`). Раздел «Отправить логи»: что уходит и что не уходит
никогда, строка над кнопкой — куда ляжет архив, и строка отправки (`CheckLine`: архив собирается, ложится в logs\\ и
уходит в фоновом потоке, окно не замирает). Надпись кнопки и строка над ней — по одному правилу с отправкой
(`LogsPanel.route`): есть бот поддержки и чат поддержки — «Отправить логи» и «уйдёт в чат поддержки», иначе —
«Сохранить архив логов» и почему архив остаётся в logs\\; окно обновляет их после каждой записи (`show_chats`). Бот — бот
поддержки на токене строки этой вкладки (`telegram_bot`), бот объявлений вкладка не берёт никогда; в тестах его
подменяют подделкой (`bot_source`). Своих правил у вкладки нет.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from app.config.files import SettingsFile
from app.config.telegram import ChatRole
from app.paths import LivecraftPaths
from app.publish.telegram_bot import TelegramBot
from app.runtime.log_archive import LOG_ARCHIVE_LIMIT_MEGABYTES
from app.secretsafe.field import SecretField
from app.setup.page import SetupPage
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.logs_panel import LogsPanel, LogsRoute, LogsVerdict
from app.setup.panels.publish_panel import PublishPanel
from app.setup.tabs.chat_block import BotKeyBlock, ChatConnectBlock, ChatHooks
from app.setup.tabs.check_line import CheckLine, CheckRun, CheckTexts
from app.setup.tabs.key_rows import KeyRowView
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg


class LogsTab:
    """Вкладка «Логи»: оболочка, бот поддержки (`bot_key`), подключение чата поддержки (`chat`), модель отправки
    `panel`, строка над кнопкой — куда ляжет архив (`route_line`), строка отправки (`send_line`) и бот (`bot_source`;
    в программе — бот поддержки, в тестах — подделка)."""

    def __init__(self, context: SetupContext, keys: KeysPanel, panel: LogsPanel) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.LOGS, msg.SETUP_LOGS_INTRO)
        self.panel: LogsPanel = panel
        self.bot_source: Callable[[], TelegramBot | None] = self.telegram_bot
        hooks: ChatHooks = ChatHooks(bot=lambda: self.bot_source(), changed=context.on_saved)
        bot_frame: ttk.Frame = self.shell.step(msg.SETUP_LOGS_BOT_TITLE, msg.SETUP_LOGS_BOT_TEXT)
        self.bot_key: BotKeyBlock = BotKeyBlock(self.shell, bot_frame, keys, self.token_saved)
        chat_panel: PublishPanel = PublishPanel.from_file(SettingsFile.of(self.paths), ChatRole.SUPPORT)
        support: ttk.Frame = self.shell.step(msg.SETUP_LOGS_CHAT_TITLE, msg.SETUP_LOGS_CHAT_TEXT)
        self.chat: ChatConnectBlock = ChatConnectBlock(self.shell, support, chat_panel, hooks)
        sending: str = msg.SETUP_LOGS_SEND_TEXT.format(limit=LOG_ARCHIVE_LIMIT_MEGABYTES)
        send: ttk.Frame = self.shell.step(msg.SETUP_LOGS_SEND_TITLE, sending)
        self.route_line: ttk.Label = ttk.Label(send, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.route_line.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        interrupted: LogsVerdict = LogsVerdict.problem(msg.SETUP_LOGS_INTERRUPTED)
        texts: CheckTexts = CheckTexts(msg.SETUP_LOGS_BUTTON_SAVE, msg.SETUP_LOGS_WORKING, interrupted)
        self.send_line: CheckLine = CheckLine(send, texts, self._send_run)
        self.show()

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    @property
    def paths(self) -> LivecraftPaths:
        return self.shell.context.paths

    @property
    def rows(self) -> dict[SecretField, KeyRowView]:
        return self.bot_key.keys.rows

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — только введённый и не сохранённый токен бота поддержки."""
        return self.bot_key.is_dirty

    def telegram_bot(self) -> TelegramBot | None:
        """Бот поддержки на токене строки этой вкладки (свой или из токена доступа); токена нет — бота нет."""
        return self.bot_key.bot

    def token_saved(self) -> None:
        """Токен бота поддержки записан или убран: кто теперь бот (бот сменился — названия чатов прежнего бота
        забываются); окно — заново."""
        self.chat.change(lambda: self.chat.panel.describe_bot(self.bot_source()))

    def show(self) -> None:
        """Кто бот поддержки, надпись кнопки отправки и строка над ней — по боту поддержки и чату поддержки, как они
        сейчас на диске."""
        route: LogsRoute = self.panel.route(self.bot_source(), SettingsFile.of(self.paths).latest.telegram)
        self.send_line.button.configure(text=route.button)
        self.route_line.configure(text=route.line)
        self.bot_key.show(self.chat.panel.bot)

    def show_chats(self) -> None:
        """Окно перерисовывается: чат поддержки — как он сейчас на диске (его могла записать вкладка «Telegram»), затем
        вкладка."""
        self.chat.refresh()
        self.show()

    def reload(self) -> None:
        """Бот и чат поддержки — как они сейчас на диске: их мог принести загруженный токен доступа."""
        self.bot_key.keys.reload()
        self.chat.reload()
        self.show()

    def hide_revealed(self) -> None:
        """Уход с вкладки прячет показанный свой токен бота поддержки (§14 решение 11)."""
        self.bot_key.keys.hide_revealed()

    def _send_run(self) -> CheckRun:
        """Бот поддержки — сейчас, в главном потоке; сборка и отправка архива — в фоне."""
        bot: TelegramBot | None = self.bot_source()
        panel: LogsPanel = self.panel      # поток получает модель, а не вкладку: объекты Tk — только в главном потоке
        return lambda _mail: panel.run(bot)
