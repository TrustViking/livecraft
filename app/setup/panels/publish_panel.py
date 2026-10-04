"""Подключение чата Telegram без окна: куда уходят объявления и логи (CLAUDE.md §8.2 пп.7, 11, §14 решения 19, 20).

Три шага человека — три действия модели. Шаг 1: токен бота вводится строкой сейфа (`KeysPanel` вкладки), а модель
после сохранения говорит, кто этот бот (`describe_bot`, getMe → `BotCard`). Шаг 2: человек открывает бота в Telegram по
адресу `BotCard.url` и пишет ему (в группе — /start@имя_бота: обычные сообщения группы бот не видит). Шаг 3: кнопка
подключения поиска (`find_chats`) — бот смотрит, кто ему писал, и берёт только чаты своего поиска (`ChatSearch`): один
чат — он сразу подключается (`connect`), несколько — человек выбирает в списке, ни одного — строка, что сделать.
Пробное сообщение уходит в чат при подключении, отдельной кнопки для него нет; у подключённого чата кнопка —
«Подключить другой …» (`ChatSearch.button`): она нужна только для смены чата. id чатов человек не вводит.

У объявлений поиска два — чат с ботом и группа с ботом (§14 решение 57): подключённый чат становится назначением, только
когда у назначения ещё нет чата (§14 решение 58); между подключёнными видами человек выбирает, куда слать
(`choose_target`), и строка назначения говорит, куда объявления уходят сейчас (`destination_line`). Чат подключают две
роли (`ChatRole`) одним порядком действий: вкладка «Telegram» — чат объявлений ботом объявлений, вкладка «Логи» — чат
поддержки ботом поддержки; куда записать чат и какими словами о нём говорить, решает роль. Пишет модель только раздел
telegram — поверх файла, как он сейчас на диске (`SettingsFile.latest`): сохранённое другими вкладками не откатывается;
записанное другой вкладкой модель перечитывает (`reread`). Группа стала супергруппой — новый id сразу в livecraft.json
(`ChatMigration`).
Названия чатов знает только Telegram: модель помнит чаты, подключённые в этом окне её ботом (`named`), и показывает их
названиями; бот сменился — названия забываются, строки — по файлу (id). Отказ бота — его текст строкой вкладки и строка
в лог. Бота модели даёт окно — из сейфа установки; токена нет — бота нет. Модель неизменяемая: каждое действие отдаёт
новую.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Final

from app.config.files import ConfigRead, SettingsFile, ShippedSettings
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings
from app.config.telegram import ChatRole, ChatSearch, ChatTarget, SearchWords, TelegramSettings
from app.observability.log_event import LogArea, get_logger
from app.publish.telegram_api import BotChat, BotChats, BotDelivery, BotFailure
from app.publish.telegram_bot import TelegramBot
from app.publish.telegram_chat import ChatMigration
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)
BOT_URL: Final[str] = "https://t.me/{username}"    # бот в Telegram: там человек нажимает «Старт»


@dataclass(frozen=True)
class ChatConnection:
    """Чат, выбранный чатом роли `role`: у объявлений его вид задаёт назначение (личный чат с ботом или группа), id —
    поле этого назначения в разделе telegram; у поддержки id — поле чата поддержки."""

    chat: BotChat
    role: ChatRole = ChatRole.ANNOUNCE

    def written(self, fresh: LivecraftSettings) -> LivecraftSettings:
        """Что записать в файл: чат — по правилу роли; прочее — как в `fresh`."""
        return fresh.with_telegram(self.role.connected(fresh.telegram, self.chat.target, self.chat.chat_id))

    def moved(self, fresh: LivecraftSettings, migration: ChatMigration) -> LivecraftSettings:
        """Группа стала супергруппой, и этот чат — она под новым id: id файла, равные прежнему, — новым (и чат
        объявлений, и чат поддержки), затем чат — по правилу роли."""
        telegram: TelegramSettings = fresh.telegram.migrated(migration.old_chat_id, migration.new_chat_id)
        return self.written(fresh.with_telegram(telegram))

    @property
    def done_line(self) -> str:
        return self.role.words.connected.format(destination=ChatDestination.of_chat(self.chat).text)


@dataclass(frozen=True)
class ChatDestination:
    """Подключённый чат: вид, id и название (`title`; пусто — известен только id из livecraft.json, название знают
    лишь чаты, подключённые в этом окне)."""

    target: ChatTarget
    chat_id: str
    title: str = ""

    @classmethod
    def of_chat(cls, chat: BotChat) -> ChatDestination:
        """Чат из ответа бота — с названием."""
        return cls(target=chat.target, chat_id=chat.chat_id, title=chat.label)

    @property
    def text(self) -> str:
        """В винительном падеже, после «уходят в»: «группу с ботом «Livecraft group»», по файлу — «чат с ботом (id
        111000111)»."""
        into: str = msg.SETUP_TELEGRAM_TARGETS_INTO[self.target.value]
        if self.title:
            return msg.SETUP_TELEGRAM_DESTINATION_BY_TITLE.format(into=into, title=self.title)
        return msg.SETUP_TELEGRAM_DESTINATION_BY_ID.format(into=into, chat_id=self.chat_id)

    @property
    def shown(self) -> str:
        """Сам чат, без вида: название, а по файлу — «id 111000111»."""
        return self.title or msg.SETUP_TELEGRAM_CHAT_BY_ID.format(chat_id=self.chat_id)

    def line(self, words: SearchWords) -> str:
        """Строка подключённого чата словами поиска."""
        return words.connected.format(destination=self.text, chat=self.shown)


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
class PublishPanel:
    """Подключение чата роли `role`: на вкладке «Telegram» — чат объявлений, на вкладке «Логи» — чат поддержки.

    `settings` — настройки файла (не прочитан — поставочный вид), `notices` — почему не прочитан и что с ним сделает
    подключение (прочитан — пусто). `bot` — кто бот (шаг 1). `chats` — чаты для выбора (только когда их несколько),
    `named` — чаты, подключённые в этом окне этим ботом (по ним строки чатов — с названиями), `status` — итог
    последнего действия строками.
    """

    settings: LivecraftSettings
    notices: tuple[str, ...]
    file: SettingsFile
    role: ChatRole = ChatRole.ANNOUNCE
    bot: BotCard = BotCard()
    chats: BotChats = BotChats(chats=())
    named: tuple[BotChat, ...] = ()
    status: tuple[str, ...] = ()

    @classmethod
    def from_file(cls, file: SettingsFile, role: ChatRole = ChatRole.ANNOUNCE) -> PublishPanel:
        """Прочитать файл настроек для чата роли `role`. Не прочитался — вкладка на шаблоне программы и оговорка с
        причиной от разбора."""
        read: ConfigRead[LivecraftSettings] = file.read()
        error: ConfigError | None = read.error
        notices: tuple[str, ...] = ()
        if error is not None:
            notices = (msg.SETUP_TELEGRAM_NOTICE_UNREADABLE.format(key=error.key_path, problem=error.problem),)
        settings: LivecraftSettings = ShippedSettings().settings if read.value is None else read.value
        return cls(settings=settings, notices=notices, file=file, role=role)

    def reread(self) -> PublishPanel:
        """Чаты — как они сейчас на диске: их могла записать другая вкладка окна. Кто бот, названия чатов этого окна,
        список для выбора и итог последнего действия остаются."""
        fresh: PublishPanel = PublishPanel.from_file(self.file, self.role)
        return dataclasses.replace(self, settings=fresh.settings, notices=fresh.notices)

    def destination_of(self, search: ChatSearch) -> ChatDestination | None:
        """Подключённый чат поиска: подключённый в этом окне этим ботом — с названием, иначе по файлу — id; не
        подключён — None. Без обращения к Telegram."""
        chat_id: str = search.chat_of(self.settings.telegram)
        if not chat_id:
            return None
        named: BotChat | None = next((chat for chat in self.named if chat.chat_id == chat_id), None)
        if named is not None:
            return ChatDestination.of_chat(named)
        return ChatDestination(target=ChatTarget.of_chat_id(chat_id), chat_id=chat_id)

    def line_of(self, search: ChatSearch) -> str:
        """Строка поиска: какой чат подключён или что чат ещё не подключён."""
        destination: ChatDestination | None = self.destination_of(search)
        return search.words.not_connected if destination is None else destination.line(search.words)

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
        written: LivecraftSettings = fresh.with_telegram(fresh.telegram.with_target(target))
        self.file.save(written)
        return dataclasses.replace(self, settings=written, notices=(), status=())

    def describe_bot(self, bot: TelegramBot | None) -> PublishPanel:
        """Кто теперь бот (getMe): после сохранения, удаления или возврата токена из токена доступа и по «Открыть бота
        в Telegram» (окно откроет адрес `bot.url`). Бот сменился — названия чатов прежнего бота забываются: строки
        чатов — по файлу. Токена нет — сначала бот."""
        card: BotCard = BotCard.of(bot)
        named: tuple[BotChat, ...] = self.named if card.is_same_bot(self.bot) else ()
        described: PublishPanel = dataclasses.replace(self, bot=card, named=named)
        return described if bot is not None else described._said(self.role.words.bot_first)

    def find_chats(self, bot: TelegramBot | None, search: ChatSearch) -> PublishPanel:
        """Кнопка подключения поиска `search`: кто бот, затем чаты, которые ему писали, — только видов поиска. Один —
        подключить сразу; несколько — список для выбора; ни одного — что сделать, называя бота."""
        if bot is None:
            return self._said(self.role.words.bot_first)
        me: BotChat | BotFailure = bot.me()
        if isinstance(me, BotFailure):
            return self._failed(me)
        asked: PublishPanel = dataclasses.replace(self, bot=BotCard.named(me), chats=BotChats(chats=()))
        found: BotChats | BotFailure = bot.chats()
        if isinstance(found, BotFailure):
            return asked._failed(found)
        sought: BotChats = found.of_targets(search.targets)
        if len(sought.chats) == 1:
            return asked.connect(bot, sought.chats[0])
        if sought.chats:
            return dataclasses.replace(asked, chats=sought, status=(search.words.choose,))
        button: str = search.button(self.settings.telegram)
        return asked._said(search.words.no_chats.format(username=me.username, button=button))

    def connect(self, bot: TelegramBot | None, chat: BotChat) -> PublishPanel:
        """Чат становится чатом роли: раздел telegram — поверх файла, как он сейчас на диске; затем в чат уходит пробное
        сообщение. Чат с названием — среди чатов этого окна (`named`), рядом с подключёнными раньше. Группа стала
        супергруппой — новый id сразу в файл поверх файла, как он на диске: прежний id уже мёртв (`ChatMigration`, как у
        объявлений запуска), и чат этого окна — под новым id. Токена уже нет — сначала бот, файл не трогается. OSError
        записи — наружу."""
        if bot is None:
            return self._said(self.role.words.bot_first)
        written: LivecraftSettings = ChatConnection(chat, self.role).written(self.file.latest)
        self.file.save(written)
        named: tuple[BotChat, ...] = (chat, *(known for known in self.named if known.chat_id != chat.chat_id))
        saved: PublishPanel = dataclasses.replace(
            self, settings=written, notices=(), chats=BotChats(chats=()), named=named
        )
        sent: BotDelivery | BotFailure = bot.send_text(chat.chat_id, self.role.words.test_message)
        if isinstance(sent, BotFailure):
            return saved._failed(sent)
        connection: ChatConnection = ChatConnection(sent.chat, self.role)
        if sent.migrated_from is None:
            return saved._said(connection.done_line)
        migration: ChatMigration = ChatMigration(old_chat_id=sent.migrated_from, new_chat_id=sent.chat.chat_id)
        migration.event.emit(LOGGER)
        moved: LivecraftSettings = connection.moved(self.file.latest, migration)
        self.file.save(moved)
        lines: tuple[str, ...] = (migration.line, connection.done_line)
        moved_named: tuple[BotChat, ...] = (sent.chat, *named[1:])
        return dataclasses.replace(saved, settings=moved, named=moved_named, status=lines)

    def _said(self, *lines: str) -> PublishPanel:
        """Та же вкладка с итогом действия строками."""
        return dataclasses.replace(self, status=lines)

    def _failed(self, failure: BotFailure) -> PublishPanel:
        """Отказ бота: строка в лог и текст причины строкой вкладки."""
        failure.event.emit(LOGGER, logging.WARNING)
        return self._said(failure.human)
