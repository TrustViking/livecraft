"""Словарь и значения Bot API Telegram (CLAUDE.md §13 задача 4.1, §14 решения 14, 19): методы, поля, причины
отказа, чаты, запрос и ответ. Ходит к Telegram `TelegramBot` (app\\publish\\telegram_bot.py); здесь — только то, что
он шлёт и что получает назад, без сети и без токена.

Ответ разбирается один раз (`BotAnswer`): отказ — `BotFailure` с причиной `TelegramProblem`, отправленное —
`BotDelivery` с чатом из ответа. Отказ несёт имя метода, код и пояснение Telegram — токена в них нет (§7.4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Any, Final

import requests

from app.config.channel import ChannelHandle
from app.config.telegram import ChatTarget
from app.core.text_format import NEWLINE, SPACE
from app.observability.log_event import LogEvent
from app.ui.messages import msg

RATE_LIMIT_WAIT_SEC: Final[float] = 5.0     # ожидание на 429 без retry_after
TEXT_CHUNK_CHARS: Final[int] = 3500         # предел Telegram 4096 знаков; запас — на HTML-разметку
PARSE_MODE_HTML: Final[str] = "HTML"
CHAT_NOT_FOUND_MARK: Final[str] = "chat not found"
STATUS_DESCRIPTION: Final[str] = "HTTP {status}"     # пояснение отказа, когда Telegram ответил не JSON
ZIP_MIME: Final[str] = "application/zip"             # тип архива документом: пакет .bcast и архив логов


class BotMethod(str, Enum):
    """Методы Bot API, которыми пользуется программа."""

    GET_ME = "getMe"
    GET_WEBHOOK_INFO = "getWebhookInfo"
    GET_UPDATES = "getUpdates"
    SEND_MESSAGE = "sendMessage"
    SEND_DOCUMENT = "sendDocument"

    @property
    def is_sending(self) -> bool:
        """Отправка сообщения: перед ней пауза."""
        return self in (BotMethod.SEND_MESSAGE, BotMethod.SEND_DOCUMENT)


class BotKey(str, Enum):
    """Поля запросов и ответов Bot API."""

    OK = "ok"
    RESULT = "result"
    DESCRIPTION = "description"
    PARAMETERS = "parameters"
    RETRY_AFTER = "retry_after"
    MIGRATE_TO_CHAT_ID = "migrate_to_chat_id"
    URL = "url"
    CHAT = "chat"
    ID = "id"
    TYPE = "type"
    TITLE = "title"
    USERNAME = "username"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    CHAT_ID = "chat_id"
    TEXT = "text"
    PARSE_MODE = "parse_mode"
    CAPTION = "caption"
    DOCUMENT = "document"
    JSON = "json"
    DATA = "data"
    FILES = "files"


# Обновления getUpdates, в которых есть чат: сообщение, его правка, пост канала, бота добавили или убрали.
UPDATE_KINDS: Final[tuple[str, ...]] = ("message", "edited_message", "channel_post", "my_chat_member")
PERSON_NAME_KEYS: Final[tuple[BotKey, ...]] = (BotKey.FIRST_NAME, BotKey.LAST_NAME)


class TelegramProblem(str, Enum):
    """Почему обращение к боту не удалось. Текст для человека — `human`, в каталоге msg."""

    BAD_TOKEN = "bad_token"             # 401: токен не тот
    CHAT_NOT_FOUND = "chat_not_found"   # 400 «chat not found»
    FORBIDDEN = "forbidden"             # 403: бота удалили из группы или заблокировали в личке
    OTHER_POLLER = "other_poller"       # 409: getUpdates бота зовёт другая программа
    WEBHOOK = "webhook"                 # у бота webhook: getUpdates не работает
    RATE_LIMITED = "rate_limited"       # 429 и после всех попыток
    NETWORK = "network"                 # обрыв связи или таймаут
    SERVER = "server"                   # 5xx и после повторов
    REJECTED = "rejected"               # прочий отказ

    @classmethod
    def of_answer(cls, status: int, description: str) -> TelegramProblem:
        """Причина по коду ответа и пояснению Telegram."""
        if status == HTTPStatus.BAD_REQUEST and CHAT_NOT_FOUND_MARK in description.lower():
            return cls.CHAT_NOT_FOUND
        return STATUS_PROBLEMS.get(status, cls.REJECTED)


STATUS_PROBLEMS: Final[dict[int, TelegramProblem]] = {
    HTTPStatus.UNAUTHORIZED: TelegramProblem.BAD_TOKEN,
    HTTPStatus.FORBIDDEN: TelegramProblem.FORBIDDEN,
    HTTPStatus.CONFLICT: TelegramProblem.OTHER_POLLER,
    HTTPStatus.TOO_MANY_REQUESTS: TelegramProblem.RATE_LIMITED,
}


class TelegramEvent(str, Enum):
    """События бота в логе: их пишет вызывающий — он знает, зачем обращался."""

    FAILED = "telegram_failed"


class ChatKind(str, Enum):
    """Вид чата Telegram."""

    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"

    @property
    def human(self) -> str:
        return msg.TELEGRAM_CHAT_KINDS[self.value]


@dataclass(frozen=True)
class BotFailure:
    """Отказ обращения: причина, метод, код ответа и пояснение Telegram. Токена в них нет."""

    reason: TelegramProblem
    method: BotMethod
    status: int | None = None
    description: str = ""

    @property
    def human(self) -> str:
        return msg.TELEGRAM_PROBLEMS[self.reason.value].format(description=self.description)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(TelegramEvent.FAILED, method=self.method.value, reason=self.reason).extended(
            status=self.status, description=self.description
        )

    @property
    def log_line(self) -> str:
        return self.event.text


@dataclass(frozen=True)
class BotChat:
    """Чат из ответа Bot API: id строкой, вид (None — вид, которого программа не знает), название — `title` группы
    или имя человека — и @имя без «@» (`username`; пусто — его нет): по нему бота открывают по ссылке t.me."""

    chat_id: str
    kind: ChatKind | None
    title: str
    username: str = ""

    @classmethod
    def of(cls, raw: dict[str, Any]) -> BotChat:
        """Название — `title` группы или имя человека; @имя — отдельно."""
        name: str = str(raw.get(BotKey.TITLE.value) or SPACE.join(str(raw[key.value]) for key in PERSON_NAME_KEYS
                                                                     if raw.get(key.value)))
        kinds: dict[str, ChatKind] = {kind.value: kind for kind in ChatKind}
        return cls(
            chat_id=str(raw.get(BotKey.ID.value)),
            kind=kinds.get(str(raw.get(BotKey.TYPE.value))),
            title=name,
            username=str(raw.get(BotKey.USERNAME.value) or ""),
        )

    @property
    def target(self) -> ChatTarget:
        """Куда такой чат годится: личный — в личный чат с ботом, группа, супергруппа и канал — в группу."""
        return ChatTarget.PRIVATE if self.kind is ChatKind.PRIVATE else ChatTarget.GROUP

    @property
    def handle(self) -> str:
        """@имя: тот же знак, что у ника канала; @имени нет — пусто."""
        return ChannelHandle.PREFIX + self.username if self.username else ""

    @property
    def label(self) -> str:
        """Как назвать чат человеку: название и @имя, а без них — id."""
        return SPACE.join(part for part in (self.title, self.handle) if part) or self.chat_id

    @property
    def option(self) -> str:
        """Строка списка найденных чатов: вид, название и id."""
        kind: str = "" if self.kind is None else self.kind.human
        return msg.SETUP_TELEGRAM_CHAT_OPTION.format(kind=kind, title=self.label, chat_id=self.chat_id)


@dataclass(frozen=True)
class BotChats:
    """Чаты, которые видит бот: по одному на id, личные первыми."""

    chats: tuple[BotChat, ...]

    @classmethod
    def from_updates(cls, updates: object) -> BotChats:
        """Чаты из обновлений getUpdates; поздний чат с тем же id заменяет ранний (название могло смениться)."""
        found: dict[str, BotChat] = {}
        for update in updates if isinstance(updates, list) else []:
            for kind in UPDATE_KINDS:
                entry: object = update.get(kind) if isinstance(update, dict) else None
                raw: object = entry.get(BotKey.CHAT.value) if isinstance(entry, dict) else None
                chat: BotChat | None = BotChat.of(raw) if isinstance(raw, dict) else None
                if chat is not None and chat.kind is not None:
                    found[chat.chat_id] = chat
        ordered: list[BotChat] = sorted(found.values(), key=lambda chat: chat.kind is not ChatKind.PRIVATE)
        return cls(chats=tuple(ordered))

    def of_targets(self, targets: tuple[ChatTarget, ...]) -> BotChats:
        """Только чаты, которые годятся в назначения `targets` (вид чата — `BotChat.target`); порядок прежний."""
        return BotChats(chats=tuple(chat for chat in self.chats if chat.target in targets))


@dataclass(frozen=True)
class BotDelivery:
    """Отправлено: в какой чат и с какого id его перенесли (группа стала супергруппой); не переносили — None."""

    chat: BotChat
    migrated_from: str | None = None

    @property
    def is_migrated(self) -> bool:
        return self.migrated_from is not None


@dataclass(frozen=True)
class BotDocument:
    """Документ для sendDocument: имя файла, байты, тип и подпись (пусто — без подписи)."""

    name: str
    data: bytes
    mime: str
    caption: str = ""


@dataclass(frozen=True)
class MessageText:
    """Текст сообщения и его нарезка: длинный текст режется по переводу строки, строка длиннее куска — по пределу."""

    text: str
    limit: int = TEXT_CHUNK_CHARS

    @property
    def chunks(self) -> tuple[str, ...]:
        chunks: list[str] = []
        start: int = 0
        while len(self.text) - start > self.limit:
            cut: int = self.text.rfind(NEWLINE, start, start + self.limit)
            end: int = cut + 1 if cut > start else start + self.limit
            chunks.append(self.text[start:end])
            start = end
        chunks.append(self.text[start:])
        return tuple(chunks)


@dataclass(frozen=True)
class BotRequest:
    """Одно обращение к Bot API: метод, поля и документ (только у sendDocument)."""

    method: BotMethod
    fields: dict[str, object] = field(default_factory=dict)
    document: BotDocument | None = None

    @classmethod
    def message(cls, chat_id: str, text: str) -> BotRequest:
        fields: dict[str, object] = {BotKey.CHAT_ID.value: chat_id, BotKey.TEXT.value: text}
        return cls(BotMethod.SEND_MESSAGE, {**fields, BotKey.PARSE_MODE.value: PARSE_MODE_HTML})

    @classmethod
    def file(cls, chat_id: str, document: BotDocument) -> BotRequest:
        caption: dict[str, object] = {BotKey.CAPTION.value: document.caption} if document.caption else {}
        return cls(BotMethod.SEND_DOCUMENT, {BotKey.CHAT_ID.value: chat_id, **caption}, document)

    @property
    def chat_id(self) -> str:
        return str(self.fields.get(BotKey.CHAT_ID.value, ""))

    def to_chat(self, chat_id: str) -> BotRequest:
        """То же обращение в другой чат: группа стала супергруппой."""
        return BotRequest(self.method, {**self.fields, BotKey.CHAT_ID.value: chat_id}, self.document)

    @property
    def options(self) -> dict[str, object]:
        """Тело запроса для requests: документ — формой multipart, прочее — JSON."""
        if self.document is None:
            return {BotKey.JSON.value: self.fields}
        upload: tuple[str, bytes, str] = (self.document.name, self.document.data, self.document.mime)
        return {BotKey.DATA.value: self.fields, BotKey.FILES.value: {BotKey.DOCUMENT.value: upload}}


@dataclass(frozen=True)
class BotAnswer:
    """Ответ Bot API: код и разобранный JSON (ответ не JSON — пустой объект)."""

    status: int
    payload: dict[str, Any]

    @classmethod
    def of(cls, response: requests.Response) -> BotAnswer:
        try:
            payload: object = response.json()
        except ValueError:
            payload = {}
        return cls(status=int(response.status_code), payload=payload if isinstance(payload, dict) else {})

    @property
    def is_ok(self) -> bool:
        return self.payload.get(BotKey.OK.value) is True

    @property
    def result(self) -> Any:
        return self.payload.get(BotKey.RESULT.value)

    @property
    def parameters(self) -> dict[str, Any]:
        parameters: object = self.payload.get(BotKey.PARAMETERS.value)
        return parameters if isinstance(parameters, dict) else {}

    @property
    def retry_after_sec(self) -> float:
        """Сколько ждать после 429: сказал Telegram — столько, не сказал — 5 с."""
        return float(self.parameters.get(BotKey.RETRY_AFTER.value) or RATE_LIMIT_WAIT_SEC)

    @property
    def migrated_to(self) -> str | None:
        """Новый id группы, ставшей супергруппой; переноса нет — None."""
        new_id: object = self.parameters.get(BotKey.MIGRATE_TO_CHAT_ID.value)
        return None if new_id is None else str(new_id)

    @property
    def description(self) -> str:
        return str(self.payload.get(BotKey.DESCRIPTION.value) or STATUS_DESCRIPTION.format(status=self.status))

    def failure(self, method: BotMethod) -> BotFailure:
        reason: TelegramProblem = TelegramProblem.of_answer(self.status, self.description)
        return BotFailure(reason=reason, method=method, status=self.status, description=self.description)

    def delivery(self, method: BotMethod, migrated_from: str | None) -> BotDelivery | BotFailure:
        """Отправлено — чат из ответа; отказ (в том числе второй перенос подряд) — причиной."""
        result: object = self.result
        if not self.is_ok or not isinstance(result, dict):
            return self.failure(method)
        chat: object = result.get(BotKey.CHAT.value)
        return BotDelivery(chat=BotChat.of(chat if isinstance(chat, dict) else {}), migrated_from=migrated_from)
