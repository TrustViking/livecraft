"""Раздел `telegram` файла `secrets\\livecraft.json` (CLAUDE.md §5, §14 решения 19, 20).

Чаты Telegram — открытые настройки: без токена бота (он в сейфе, §7.5) они бесполезны. Раздел строит себя сам из узла
JSON (`from_node`) в пару к `to_data` и сам говорит, что с ним не так по смыслу (`problem`). Чат подключают две роли
(`ChatRole`): чат объявлений и чат поддержки, куда уходят логи (§13 задача 7.2); куда записать подключённый чат и
какими словами о нём говорить окну, решает роль. Кнопка подключения ищет чаты своего поиска (`ChatSearch`): у
объявлений — по поиску на вид чата, чат с ботом и группа с ботом (§14 решение 57), у поддержки — один поиск чата любого
вида. Подключение чата объявлений меняет назначение, только когда у назначения ещё нет чата (§14 решение 58): иначе
назначение меняет только выбор «Куда слать объявления».
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final

from app.config.json_node import JsonNode, SettingProblem, json_value
from app.config.setting_key import SettingKey
from app.ui.messages import msg

# id чата Telegram — целое со знаком; у группы и супергруппы — отрицательное.
CHAT_ID_PATTERN: Final[re.Pattern[str]] = re.compile("-?[0-9]+")
GROUP_CHAT_ID_SIGN: Final[str] = "-"


class ChatTarget(str, Enum):
    """Куда слать объявления (§14 решение 19): в группу с ботом или в чат с ботом (личный)."""

    GROUP = "group"
    PRIVATE = "private"

    @property
    def chat_key(self) -> SettingKey:
        return SettingKey.TELEGRAM_GROUP_CHAT_ID if self is ChatTarget.GROUP else SettingKey.TELEGRAM_PRIVATE_CHAT_ID

    @classmethod
    def of_chat_id(cls, chat_id: str) -> ChatTarget:
        """Вид чата по его id: у группы, супергруппы и канала id отрицательный, у личного чата — положительный."""
        return cls.GROUP if chat_id.startswith(GROUP_CHAT_ID_SIGN) else cls.PRIVATE

    @property
    def search(self) -> ChatSearch:
        """Поиск чатов этого вида для объявлений: id подключённого — в поле этого вида, слова — по виду."""
        words: SearchWords = SearchWords(
            title=msg.SETUP_TELEGRAM_TARGET_TITLES[self.value], connect=msg.SETUP_TELEGRAM_TARGET_CONNECT[self.value],
            reconnect=msg.SETUP_TELEGRAM_TARGET_RECONNECT[self.value],
            choose=msg.SETUP_TELEGRAM_TARGET_CHOOSE[self.value], no_chats=msg.SETUP_TELEGRAM_TARGET_NO_CHATS[self.value],
            connected=msg.SETUP_TELEGRAM_CHAT_CONNECTED, not_connected=msg.SETUP_TELEGRAM_CHAT_NOT_CONNECTED,
            hint=msg.SETUP_TELEGRAM_TARGET_HINTS.get(self.value, ""),
            hint_unnamed=msg.SETUP_TELEGRAM_TARGET_HINTS_UNNAMED.get(self.value, ""),
        )
        return ChatSearch(targets=(self,), key=self.chat_key, words=words)


# Поиски чатов объявлений в порядке окна: сначала чат с ботом — он по умолчанию (§8.2 п.7).
ANNOUNCE_TARGETS: Final[tuple[ChatTarget, ...]] = (ChatTarget.PRIVATE, ChatTarget.GROUP)


@dataclass(frozen=True)
class SearchWords:
    """Что окно говорит о поиске чатов: заголовок строки (пусто — без заголовка), надпись кнопки до и после
    подключения, выбор из нескольких, ни одного чата ({username} — @имя бота, {button} — надпись кнопки), чат
    подключён ({destination} — вид и чат в винительном падеже, {chat} — сам чат) и не подключён; подсказка под
    неподключённым чатом — с @именем бота ({username}) и без него, пока бот не назван (пусто — подсказки нет)."""

    title: str
    connect: str
    reconnect: str
    choose: str
    no_chats: str
    connected: str
    not_connected: str
    hint: str = ""
    hint_unnamed: str = ""


@dataclass(frozen=True)
class ChatSearch:
    """Что ищет кнопка подключения: чаты видов `targets`; id подключённого чата — поле `key` раздела telegram;
    `words` — слова окна об этом поиске."""

    targets: tuple[ChatTarget, ...]
    key: SettingKey
    words: SearchWords

    def chat_of(self, telegram: TelegramSettings) -> str:
        """id подключённого чата этого поиска; пусто — не подключён."""
        return str(getattr(telegram, self.key.leaf))

    def button(self, telegram: TelegramSettings) -> str:
        """Надпись кнопки: чат не подключён — «подключить», подключён — «подключить другой»: пробное сообщение уже
        ушло при подключении, и кнопка нужна только для смены чата."""
        return self.words.reconnect if self.chat_of(telegram) else self.words.connect

    def hint(self, telegram: TelegramSettings, username: str | None) -> str:
        """Что сделать до кнопки, пока чат не подключён: у группы — добавить бота и отправить /start@имя_бота (обычные
        сообщения группы бот не видит), с @именем бота, когда он назван (`username`; None — ещё нет). Подключён —
        пусто."""
        if self.chat_of(telegram):
            return ""
        return self.words.hint_unnamed if username is None else self.words.hint.format(username=username)


@dataclass(frozen=True)
class ChatWords:
    """Что окно говорит о чате роли: что он подключён, сначала бот и пробное сообщение в чат."""

    connected: str
    bot_first: str
    test_message: str


class ChatRole(str, Enum):
    """Роль подключённого чата: объявления об эфирах или поддержка — туда уходят логи. Значение — идентификатор."""

    ANNOUNCE = "announce"
    SUPPORT = "support"

    def chat_of(self, telegram: TelegramSettings) -> str:
        """id чата роли; пусто — не подключён."""
        return telegram.chat_id if self is ChatRole.ANNOUNCE else telegram.support_chat_id

    @property
    def searches(self) -> tuple[ChatSearch, ...]:
        """Поиски чатов роли — по кнопке подключения на каждый: у объявлений — по виду чата, у поддержки — один, чат
        любого вида. Строка чата поддержки называет только чат, как строки объявлений: уйдут ли туда логи, решает и
        бот поддержки — это говорит вкладка «Логи» над кнопкой отправки."""
        if self is ChatRole.ANNOUNCE:
            return tuple(target.search for target in ANNOUNCE_TARGETS)
        words: SearchWords = SearchWords(
            title="", connect=msg.SETUP_LOGS_BUTTON_CONNECT, reconnect=msg.SETUP_LOGS_BUTTON_RECONNECT,
            choose=msg.SETUP_LOGS_CHAT_CHOOSE, no_chats=msg.SETUP_LOGS_CHAT_NO_CHATS,
            connected=msg.SETUP_TELEGRAM_CHAT_CONNECTED, not_connected=msg.SETUP_TELEGRAM_CHAT_NOT_CONNECTED,
        )
        return (ChatSearch(targets=tuple(ChatTarget), key=SettingKey.TELEGRAM_SUPPORT_CHAT_ID, words=words),)

    def connected(self, telegram: TelegramSettings, target: ChatTarget, chat_id: str) -> TelegramSettings:
        """Раздел telegram с подключённым чатом вида `target`. Объявления: id — в поле этого вида всегда; назначение
        становится этим видом, только когда у прежнего назначения нет чата (§14 решение 58): иначе повторное
        подключение одного чата уводило бы объявления от выбранного другого. Поддержка: только id чата поддержки — для
        неё годен чат любого вида, чаты объявлений не меняются."""
        if self is ChatRole.SUPPORT:
            return dataclasses.replace(telegram, support_chat_id=chat_id)
        destination: ChatTarget = telegram.target if telegram.is_connected(telegram.target) else target
        return dataclasses.replace(telegram, target=destination, **{target.chat_key.leaf: chat_id})

    @property
    def words(self) -> ChatWords:
        if self is ChatRole.ANNOUNCE:
            return ChatWords(connected=msg.SETUP_TELEGRAM_CONNECTED, bot_first=msg.SETUP_TELEGRAM_STEP_1_FIRST,
                             test_message=msg.SETUP_TELEGRAM_CONNECT_TEXT)
        return ChatWords(connected=msg.SETUP_LOGS_CHAT_CONNECTED, bot_first=msg.SETUP_LOGS_BOT_FIRST,
                         test_message=msg.SETUP_LOGS_CHAT_CONNECT_TEXT)


@dataclass(frozen=True)
class TelegramSettings:
    """Telegram (§14 решения 19, 20): куда слать объявления и id чатов группы, личного чата с ботом и поддержки.
    id — строка: пустая — чат не задан (не ошибка файла); иначе целое со знаком, у группы — отрицательное."""

    CHAT_KEYS: ClassVar[tuple[SettingKey, ...]] = (SettingKey.TELEGRAM_GROUP_CHAT_ID, SettingKey.TELEGRAM_PRIVATE_CHAT_ID,
                                                   SettingKey.TELEGRAM_SUPPORT_CHAT_ID)

    target: ChatTarget
    group_chat_id: str
    private_chat_id: str
    support_chat_id: str

    @classmethod
    def from_node(cls, node: JsonNode) -> TelegramSettings:
        node.mapping(SettingKey.leaves(SettingKey.TELEGRAM))
        chats: dict[str, str] = {key.leaf: node.field(key.leaf).string() for key in cls.CHAT_KEYS}
        return cls(target=node.field(SettingKey.TELEGRAM_TARGET.leaf).choice(ChatTarget), **chats)

    def to_data(self) -> dict[str, Any]:
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.TELEGRAM)}

    @property
    def chat_id(self) -> str:
        """id чата выбранного назначения; пусто — не задан."""
        return self.target.search.chat_of(self)

    def is_connected(self, target: ChatTarget) -> bool:
        """Чат вида `target` подключён: его id задан — туда можно слать объявления."""
        return bool(target.search.chat_of(self))

    def with_target(self, target: ChatTarget) -> TelegramSettings:
        """Объявления — в чат вида `target`; id чатов не меняются."""
        return dataclasses.replace(self, target=target)

    def migrated(self, old_chat_id: str, new_chat_id: str) -> TelegramSettings:
        """Группа стала супергруппой (у неё новый id): каждый id, равный старому, заменён новым."""
        chats: dict[str, str] = {key.leaf: getattr(self, key.leaf) for key in self.CHAT_KEYS}
        return dataclasses.replace(self, **{leaf: new_chat_id if old == old_chat_id else old for leaf, old in chats.items()})

    @property
    def problem(self) -> SettingProblem | None:
        """Что не так с id чатов: не целое со знаком или id группы не отрицательное; путь — от корня файла."""
        for key in self.CHAT_KEYS:
            chat_id: str = getattr(self, key.leaf)
            if chat_id and CHAT_ID_PATTERN.fullmatch(chat_id) is None:
                return SettingProblem(key=key.value, text=msg.CONFIG_PROBLEM_CHAT_ID)
        if self.group_chat_id and not self.group_chat_id.startswith(GROUP_CHAT_ID_SIGN):
            return SettingProblem(key=SettingKey.TELEGRAM_GROUP_CHAT_ID.value, text=msg.CONFIG_PROBLEM_GROUP_CHAT_ID)
        return None
