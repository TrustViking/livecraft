"""Вкладка окна «Telegram» — линия ANNOUNCE: объявления в три шага (CLAUDE.md §8.2 п.7, §14 решения 19, 20, 37, 57,
58).

Вверху — ползунок линии, ниже — зачем объявления, затем три шага с номерами. Шаг 1 — бот объявлений (`BotKeyBlock`:
строка токена бота поверх `KeysPanel` вкладки, тот же вид, что у бота поддержки на «Логах», и кто бот после сохранения —
`PublishPanel.describe_bot`). Шаг 2 — «Открыть бота в Telegram»: модель узнаёт у Telegram, кто бот, окно открывает его
адрес открывалкой `opener` (в программе — браузер; в тестах — подделка). Шаг 3 — чаты объявлений (`ChatConnectBlock` —
тот же вид, что у чата поддержки на вкладке «Логи»): строки «Чат с ботом» и «Группа с ботом», у каждой статус и своя
кнопка подключения (пробное сообщение уходит в чат при подключении; у неподключённой группы над кнопкой — что сделать
сначала), под ними выбор «Куда слать объявления» — две кнопки по видам чата (`SegmentedChoice`): неподключённый вид
выбрать нельзя, нажатая — назначение из файла, — и строка, куда объявления уходят сейчас
(`PublishPanel.destination_line`). Полей id чатов нет. Своих правил у вкладки нет. Три шага — поля нужды «бот Telegram»
(`FieldUse`): объявления не работают — шаги бледные.

После любого действия вкладки окно перерисовывается целиком (`show_chats` — чаты с диска, выбор назначения и строка
назначения): чат могла записать вкладка «Логи». Бот — на токене строки шага 1 этой вкладки (`telegram_bot`); в тестах
его подменяют подделкой (`bot_source`).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from app.config.files import SettingsFile
from app.config.telegram import ChatTarget, TelegramSettings
from app.paths import LivecraftPaths
from app.publish.telegram_bot import TelegramBot
from app.secretsafe.field import SecretField
from app.run.mode import Need
from app.setup.fields.field_use import FieldUse
from app.setup.page import SetupPage
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.publish_panel import PublishPanel
from app.setup.setup_vault import SetupVault
from app.setup.tabs.chat_block import BotKeyBlock, ChatConnectBlock, ChatHooks
from app.setup.tabs.key_rows import KeyRowView
from app.setup.tabs.segmented_choice import ChoiceRow, ChoiceSpec
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg


@dataclass(frozen=True)
class TelegramModels:
    """Модели вкладки «Telegram»: строка токена бота (поле сейфа вкладки) и объявления (раздел telegram)."""

    keys: KeysPanel
    publish: PublishPanel

    @classmethod
    def of(cls, paths: LivecraftPaths, vault: SetupVault) -> TelegramModels:
        """Модели на сейфе окна и livecraft.json этой установки."""
        keys: KeysPanel = KeysPanel.of(vault, SetupPage.TELEGRAM)
        return cls(keys=keys, publish=PublishPanel.from_file(SettingsFile.of(paths)))


class PublishTab:
    """Вкладка «Telegram» в оболочке `shell`: шаги 1–3 (бот объявлений — `bot_key`, подключение чатов с моделью
    объявлений — `chat`, выбор назначения — `targets` по переменной `target`, строка назначения — `destination`), бот
    (`bot_source`; в программе — на токене строки шага 1, в тестах — подделка) и открывалка адреса бота (`opener`)."""

    def __init__(self, context: SetupContext, models: TelegramModels, opener: Callable[[str], object]) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.TELEGRAM, msg.SETUP_TELEGRAM_INTRO)
        self.bot_source: Callable[[], TelegramBot | None] = self.telegram_bot
        self.opener: Callable[[str], object] = opener
        step_1: ttk.Frame = self.shell.step(msg.SETUP_TELEGRAM_STEP_1_TITLE, msg.SETUP_TELEGRAM_STEP_1_TEXT)
        self.bot_key: BotKeyBlock = BotKeyBlock(self.shell, step_1, models.keys, self.token_saved)
        step_2: ttk.Frame = self.shell.step(msg.SETUP_TELEGRAM_STEP_2_TITLE, msg.SETUP_TELEGRAM_STEP_2_TEXT)
        self.open_button: ttk.Button = ttk.Button(step_2, text=msg.SETUP_TELEGRAM_BUTTON_OPEN_BOT, command=self.open_bot)
        self.open_button.pack(side=tk.LEFT, anchor=tk.W, padx=(0, PAD), pady=(PAD, 0))
        step_3: ttk.Frame = self.shell.step(msg.SETUP_TELEGRAM_STEP_3_TITLE, msg.SETUP_TELEGRAM_STEP_3_TEXT)
        hooks: ChatHooks = ChatHooks(bot=lambda: self.bot_source(), changed=context.on_saved)
        self.chat: ChatConnectBlock = ChatConnectBlock(self.shell, step_3, models.publish, hooks)
        self.target: tk.StringVar = tk.StringVar(step_3)
        choice: ChoiceSpec = ChoiceSpec(self.target, msg.SETUP_TELEGRAM_TARGET_LABELS, self.choose_target)
        self.targets: ChoiceRow = ChoiceRow(step_3, msg.SETUP_TELEGRAM_TARGET_CHOICE, choice)
        self.targets.frame.pack_configure(before=self.chat.status)
        self.targets.text.pack_forget()
        self.destination: ttk.Label = ttk.Label(step_3, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.destination.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0), before=self.chat.status)
        for step in (step_1, step_2, step_3):
            context.shades.block(FieldUse.of(Need.TELEGRAM), step)
        self.show()

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    def telegram_bot(self) -> TelegramBot | None:
        """Бот объявлений на токене строки шага 1 — том, что на вкладке сейчас; токена нет — бота нет."""
        return self.bot_key.bot

    @property
    def panel(self) -> PublishPanel:
        """Модель объявлений — та, что у подключения чата: шаги 1 и 2 спрашивают бота через неё же."""
        return self.chat.panel

    @property
    def rows(self) -> dict[SecretField, KeyRowView]:
        return self.bot_key.keys.rows

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — только введённый и не сохранённый токен: всё остальное вкладка пишет сразу."""
        return self.bot_key.is_dirty

    def token_saved(self) -> None:
        """Токен записан или убран: кто теперь бот — строкой шага 1 (бот сменился — названия чатов прежнего бота
        забываются); окно — заново."""
        self.chat.change(lambda: self.panel.describe_bot(self.bot_source()))

    def open_bot(self) -> None:
        """«Открыть бота в Telegram»: кто бот; назван — его адрес открывается, токена нет — сначала шаг 1."""
        self.chat.change(lambda: self.panel.describe_bot(self.bot_source()))
        url: str | None = self.panel.bot.url
        if url is not None:
            self.opener(url)

    def choose_target(self) -> None:
        """«Куда слать объявления»: назначение — нажатый вид чата."""
        target: ChatTarget = ChatTarget(self.target.get())
        self.chat.change(lambda: self.panel.choose_target(target))

    def reload(self) -> None:
        """Токен бота и чаты — как они сейчас на диске: их мог записать загруженный токен доступа. Бот не спрашивается:
        кто он, скажет «Открыть бота» или кнопка подключения."""
        self.bot_key.keys.reload()
        self.chat.reload()
        self.show()

    def show_chats(self) -> None:
        """Окно перерисовывается: чаты — как они сейчас на диске (их могла записать вкладка «Логи»), затем вкладка."""
        self.chat.refresh()
        self.show()

    def hide_revealed(self) -> None:
        """Уход с вкладки прячет показанный свой токен (§14 решение 11)."""
        self.bot_key.keys.hide_revealed()

    def show(self) -> None:
        """Кто бот, выбор назначения и строка назначения по модели: нажато назначение файла, неподключённый вид не
        нажимается."""
        telegram_chats: TelegramSettings = self.panel.settings.telegram
        self.target.set(telegram_chats.target.value)
        for target in ChatTarget:
            self.targets.choice.allow(target.value, telegram_chats.is_connected(target))
        self.destination.configure(text=self.panel.destination_line)
        self.bot_key.show(self.panel.bot)
