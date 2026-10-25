"""Подключение и проверка чатов объявлений Telegram без окна (CLAUDE.md §8.2 п.7, §14 решения 19, 57, 58, 63).

Три шага человека — три действия модели. Шаг 1: токен бота вводится строкой сейфа (`KeysPanel` вкладки), а модель
после сохранения говорит, кто этот бот (`describe_bot`, getMe → `BotCard`). Шаг 2: человек открывает бота в Telegram по
адресу `BotCard.url` и пишет ему (в группе — /start@имя_бота: обычные сообщения группы бот не видит). Шаг 3: кнопка
подключения поиска (`find_chats`) — бот смотрит, кто ему писал, и берёт только чаты своего вида (`ChatSearch`): один
чат — он сразу подключается (`connect`), несколько — человек выбирает в списке, ни одного — строка, что сделать.
Подключение — запись в файл и та же проверка, что у кнопки «Проверить» подключённого чата (`check`): одно правило
пробного сообщения. id чатов человек не вводит.

Поиска два — чат с ботом и группа с ботом (§14 решение 57): подключённый чат становится назначением, только когда у
назначения ещё нет чата (§14 решение 58); между подключёнными видами человек выбирает, куда слать (`choose_target`), и
строка назначения говорит, куда объявления уходят сейчас (`destination_line`). Пишет модель только раздел telegram —
поверх файла, как он сейчас на диске (`SettingsFile.latest`): сохранённое другими вкладками не откатывается; записанное
другой вкладкой модель перечитывает (`reread`). Группа стала супергруппой — новый id сразу в livecraft.json
(`ChatMigration`).
Названия чатов знает только Telegram: окно само спрашивает их без сообщений (`with_names`, getChat), а проверенный или
подключённый чат называет ответ на пробное сообщение; что окно знает о чатах этим ботом — `KnownChats`: названия и
отказы getChat у своих чатов (бота удалили из группы, чат не найден). Бот сменился — всё это забывается, строки — по
файлу (id). Отказ бота — его текст строкой вкладки и строка в лог. Бота модели даёт окно — из сейфа установки; токена
нет — бота нет. Модель неизменяемая: каждое действие отдаёт новую.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Final

from app.config.files import ConfigRead, SettingsFile, ShippedSettings
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings
from app.config.telegram import ChatSearch, ChatTarget
from app.observability.log_event import LogArea, get_logger
from app.publish.telegram_api import BotChat, BotChats, BotDelivery, BotFailure, MessageText
from app.publish.telegram_bot import TelegramBot
from app.publish.telegram_chat import ChatDestination, ChatMigration
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)
BOT_URL: Final[str] = "https://t.me/{username}"    # бот в Telegram: там человек нажимает «Старт»


@dataclass(frozen=True)
class BotCard:
    """Кто бот — строка шага 1: бот из getMe (`me`; None — не назван: токена нет или Telegram отказал) и статус."""

    me: BotChat | None = None
    status: str = ""

    @classmethod
    def of(cls, bot: TelegramBot | None) -> BotCard:
        """Спросить Telegram, кто бот (getMe). Токена нет — пусто; отказ — его текст статусом и строка в лог."""
        if bot is None:
            return cls()
        me: BotChat | BotFailure = bot.me()
        if isinstance(me, BotFailure):
            me.event.emit(LOGGER, logging.WARNING)
            return cls(status=me.human)
        return cls.named(me)

    @classmethod
    def named(cls, me: BotChat) -> BotCard:
        """Бот назван: «✓ бот «Имя» @имя»."""
        return cls(me=me, status=msg.SETUP_TELEGRAM_BOT_READY.format(name=me.title, username=me.username))

    @property
    def username(self) -> str | None:
        """@имя бота без «@»; бот не назван — None."""
        return None if self.me is None else self.me.username

    @property
    def url(self) -> str | None:
        """Адрес бота в Telegram; бот не назван — None."""
        return None if self.username is None else BOT_URL.format(username=self.username)

    def is_same_bot(self, other: BotCard) -> bool:
        """Оба названы, и это один бот (по id): названия чатов, подключённых им, ещё верны."""
        return self.me is not None and other.me is not None and self.me.chat_id == other.me.chat_id


@dataclass(frozen=True)
class ChatRefusal:
    """Отказ getChat у подключённого чата: id чата и причина словами."""

    chat_id: str
    text: str


@dataclass(frozen=True)
class KnownChats:
    """Что окно знает о чатах из ответов Telegram этим ботом: чаты с названиями (`chats`) и отказы getChat у своих чатов
    (`refusals`). У одного id — либо название, либо отказ: свежий ответ заменяет прежний."""

    chats: tuple[BotChat, ...] = ()
    refusals: tuple[ChatRefusal, ...] = ()

    def chat(self, chat_id: str) -> BotChat | None:
        """Чат с названием по id; не знает — None."""
        return next((chat for chat in self.chats if chat.chat_id == chat_id), None)

    def refusal(self, chat_id: str) -> str:
        """Причина отказа getChat у чата `chat_id` строкой со знаком «✗»; отказа нет — пусто."""
        refused: ChatRefusal | None = next((item for item in self.refusals if item.chat_id == chat_id), None)
        return "" if refused is None else msg.CHECK_PROBLEM_LINE.format(line=refused.text)

    def with_chat(self, chat: BotChat) -> KnownChats:
        """Чат ответил: он с названием — первым, его прежний ответ и отказ уходят."""
        rest: KnownChats = self._without(chat.chat_id)
        return KnownChats(chats=(chat, *rest.chats), refusals=rest.refusals)

    def refused(self, chat_id: str, text: str) -> KnownChats:
        """getChat отказал у чата `chat_id`: его название забывается, причина — у него."""
        rest: KnownChats = self._without(chat_id)
        return KnownChats(chats=rest.chats, refusals=(*rest.refusals, ChatRefusal(chat_id=chat_id, text=text)))

    def _without(self, chat_id: str) -> KnownChats:
        """Всё, что известно, кроме чата `chat_id`."""
        chats: tuple[BotChat, ...] = tuple(known for known in self.chats if known.chat_id != chat_id)
        return KnownChats(chats=chats, refusals=tuple(item for item in self.refusals if item.chat_id != chat_id))


@dataclass(frozen=True)
class PublishPanel:
    """Чаты объявлений вкладки «Telegram».

    `settings` — настройки файла (не прочитан — поставочный вид), `notices` — почему не прочитан и что с ним сделает
    подключение (прочитан — пусто). `bot` — кто бот (шаг 1). `chats` — чаты для выбора (только когда их несколько),
    `named` — что окно знает о чатах этим ботом (по нему строки чатов — с названиями), `status` — итог последнего
    действия строками.
    """

    settings: LivecraftSettings
    notices: tuple[str, ...]
    file: SettingsFile
    bot: BotCard = BotCard()
    chats: BotChats = BotChats(chats=())
    named: KnownChats = KnownChats()
    status: tuple[str, ...] = ()

    @classmethod
    def from_file(cls, file: SettingsFile) -> PublishPanel:
        """Прочитать файл настроек. Не прочитался — вкладка на шаблоне программы и оговорка с причиной от разбора."""
        read: ConfigRead[LivecraftSettings] = file.read()
        error: ConfigError | None = read.error
        notices: tuple[str, ...] = ()
        if error is not None:
            notices = (msg.SETUP_TELEGRAM_NOTICE_UNREADABLE.format(key=error.key_path, problem=error.problem),)
        settings: LivecraftSettings = ShippedSettings().settings if read.value is None else read.value
        return cls(settings=settings, notices=notices, file=file)

    def reread(self) -> PublishPanel:
        """Чаты — как они сейчас на диске: их могла записать другая вкладка окна или загруженный токен. Кто бот,
        названия чатов этого окна, список для выбора и итог последнего действия остаются."""
        fresh: PublishPanel = PublishPanel.from_file(self.file)
        return dataclasses.replace(self, settings=fresh.settings, notices=fresh.notices)

    def destination_of(self, search: ChatSearch) -> ChatDestination | None:
        """Подключённый чат поиска: названный этим ботом — с названием, иначе по файлу — id; не подключён — None. Без
        обращения к Telegram."""
        chat_id: str = search.chat_of(self.settings.telegram)
        if not chat_id:
            return None
        named: BotChat | None = self.named.chat(chat_id)
        if named is not None:
            return ChatDestination.of_chat(named)
        return ChatDestination(target=ChatTarget.of_chat_id(chat_id), chat_id=chat_id)

    def line_of(self, search: ChatSearch) -> str:
        """Строка поиска: какой чат подключён или что чат ещё не подключён."""
        destination: ChatDestination | None = self.destination_of(search)
        return msg.SETUP_TELEGRAM_CHAT_NOT_CONNECTED if destination is None else destination.line

    @property
    def destination_line(self) -> str:
        """Куда объявления уходят сейчас: «Сейчас объявления уходят в …» — чат назначения; у назначения нет чата —
        что объявлениям пока некуда уходить."""
        destination: ChatDestination | None = self.destination_of(self.settings.telegram.target.search)
        if destination is None:
            return msg.SETUP_TELEGRAM_DESTINATION_NONE
        return msg.SETUP_TELEGRAM_DESTINATION_NOW.format(destination=destination.text)

    def choose_target(self, target: ChatTarget) -> PublishPanel:
        """«Куда слать объявления»: назначение — чат вида `target`, поверх файла, как он сейчас на диске; id чатов не
        меняются. OSError записи — наружу."""
        fresh: LivecraftSettings = self.file.latest
        written: LivecraftSettings = dataclasses.replace(fresh, telegram=fresh.telegram.with_target(target))
        self.file.save(written)
        return dataclasses.replace(self, settings=written, notices=(), status=())

    def describe_bot(self, bot: TelegramBot | None) -> PublishPanel:
        """Кто теперь бот (getMe): после сохранения, удаления или возврата токена из токена доступа и по «Открыть бота
        в Telegram» (окно откроет адрес `bot.url`). Бот сменился — названия чатов прежнего бота забываются: строки
        чатов — по файлу. Токена нет — сначала бот."""
        card: BotCard = BotCard.of(bot)
        named: KnownChats = self.named if card.is_same_bot(self.bot) else KnownChats()
        described: PublishPanel = dataclasses.replace(self, bot=card, named=named)
        return described if bot is not None else described._said(msg.SETUP_TELEGRAM_STEP_1_FIRST)

    def with_names(self, bot: TelegramBot | None) -> PublishPanel:
        """Названия подключённых чатов без сообщений: кто бот (getMe), затем getChat по каждому подключённому чату. Ответ
        — чат с названием среди известных; отказ (бота удалили из группы, чат не найден) — причина у этого чата и строка
        в лог. Бот сменился — прежние названия забываются; бот не назван (отказ getMe) — его причина строкой шага 1, чаты
        не спрашиваются. Токена нет — ничего."""
        if bot is None:
            return self
        card: BotCard = BotCard.of(bot)
        known: KnownChats = self.named if card.is_same_bot(self.bot) else KnownChats()
        for chat_id in self.settings.telegram.chat_ids if card.me is not None else ():
            answer: BotChat | BotFailure = bot.chat(chat_id)
            if isinstance(answer, BotFailure):
                answer.event.emit(LOGGER, logging.WARNING)
                known = known.refused(chat_id, answer.human)
            else:
                known = known.with_chat(answer)
        return dataclasses.replace(self, bot=card, named=known)

    def find_chats(self, bot: TelegramBot | None, search: ChatSearch) -> PublishPanel:
        """Кнопка подключения поиска `search`: кто бот, затем чаты, которые ему писали, — только вида поиска. Один —
        подключить сразу; несколько — список для выбора; ни одного — что сделать, называя бота."""
        if bot is None:
            return self._said(msg.SETUP_TELEGRAM_STEP_1_FIRST)
        me: BotChat | BotFailure = bot.me()
        if isinstance(me, BotFailure):
            return self._failed(me)
        asked: PublishPanel = dataclasses.replace(self, bot=BotCard.named(me), chats=BotChats(chats=()))
        found: BotChats | BotFailure = bot.chats()
        if isinstance(found, BotFailure):
            return asked._failed(found)
        sought: BotChats = found.of_targets((search.target,))
        if len(sought.chats) == 1:
            return asked.connect(bot, sought.chats[0])
        if sought.chats:
            return dataclasses.replace(asked, chats=sought, status=(search.words.choose,))
        button: str = search.button(self.settings.telegram)
        return asked._said(search.words.no_chats.format(username=me.username, button=button))

    def connect(self, bot: TelegramBot | None, chat: BotChat) -> PublishPanel:
        """Чат становится чатом объявлений своего вида: раздел telegram — поверх файла, как он сейчас на диске
        (назначение — по правилу `TelegramSettings.connected`), затем та же проверка, что у кнопки «Проверить»
        (`check`). Токена уже нет — сначала бот, файл не трогается. OSError записи — наружу."""
        if bot is None:
            return self._said(msg.SETUP_TELEGRAM_STEP_1_FIRST)
        fresh: LivecraftSettings = self.file.latest
        written: LivecraftSettings = dataclasses.replace(fresh, telegram=fresh.telegram.connected(chat.target, chat.chat_id))
        self.file.save(written)
        saved: PublishPanel = dataclasses.replace(
            self, settings=written, notices=(), chats=BotChats(chats=()), named=self.named.with_chat(chat)
        )
        return saved.check(bot, chat.target.search)

    def check(self, bot: TelegramBot | None, search: ChatSearch) -> PublishPanel:
        """«Проверить» у подключённого чата поиска `search`: пробное сообщение в этот чат. Дошло — чат с названием среди
        известных и строка «✓ пробное сообщение дошло в …»; группа стала супергруппой — новый id сразу в файл поверх
        файла, как он на диске: прежний id уже мёртв (`ChatMigration`, как у объявлений запуска). Отказ — текст причины
        строкой и строка в лог. Токена нет — сначала бот. OSError записи — наружу."""
        if bot is None:
            return self._said(msg.SETUP_TELEGRAM_STEP_1_FIRST)
        chat_id: str = search.chat_of(self.settings.telegram)
        sent: BotDelivery | BotFailure = bot.send_text(chat_id, MessageText(msg.SETUP_TELEGRAM_TEST_TEXT))
        if isinstance(sent, BotFailure):
            return self._failed(sent)
        destination: str = ChatDestination.of_chat(sent.chat).text
        checked: str = msg.CHECK_OK_LINE.format(line=msg.SETUP_TELEGRAM_CHECKED.format(destination=destination))
        known: KnownChats = self.named.with_chat(sent.chat)
        if sent.migrated_from is None:
            return dataclasses.replace(self, named=known, status=(checked,))
        migration: ChatMigration = ChatMigration(old_chat_id=sent.migrated_from, new_chat_id=sent.chat.chat_id)
        migration.event.emit(LOGGER)
        moved: LivecraftSettings = migration.written(self.file.latest, search.target)
        self.file.save(moved)
        return dataclasses.replace(self, settings=moved, notices=(), named=known, status=(migration.line, checked))

    def _said(self, *lines: str) -> PublishPanel:
        """Та же вкладка с итогом действия строками."""
        return dataclasses.replace(self, status=lines)

    def _failed(self, failure: BotFailure) -> PublishPanel:
        """Отказ бота: строка в лог и текст причины строкой вкладки."""
        failure.event.emit(LOGGER, logging.WARNING)
        return self._said(failure.human)
