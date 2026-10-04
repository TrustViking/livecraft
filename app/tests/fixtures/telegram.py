"""Bot API Telegram в тестах: сохранённые ответы (app\\tests\\data\\telegram\\) и подделка requests.post.

К настоящему Telegram тесты не ходят: бот строится только на `FakeTelegram.bot`, где `post` — подделка, а паузы
записываются, а не выжидаются. `connect_private_chat` — корень с ботом и подключённым личным чатом, как их записывает
вкладка «Telegram».
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from app.config.files import SettingsFile
from app.config.telegram import ChatTarget, TelegramSettings
from app.paths import LivecraftPaths
from app.publish.telegram_bot import TelegramBot
from app.secretsafe.field import SecretField
from app.secretsafe.value import SecretValue
from app.tests.fixtures.vault import save_own_values

TELEGRAM_DATA: Path = Path(__file__).resolve().parents[1] / "data" / "telegram"
BOT_TOKEN: str = "123456789:AAFtest-Ab3dEfGhIjKlMnOpQrStUvWxYz_0123"
BOT_SECRET: SecretValue = SecretValue(field=SecretField.TELEGRAM_BOT_TOKEN, value=BOT_TOKEN)
HTTP_OK: int = 200
ERROR_CODE_KEY: str = "error_code"
PRIVATE_CHAT_ID: str = "111000111"          # личный чат сохранённых ответов send_message_private


class FakeBotResponse:
    """Ответ requests: код и тело JSON; не JSON — `json()` падает, как у requests."""

    def __init__(self, payload: object, status_code: int) -> None:
        self.payload: object = payload
        self.status_code: int = status_code

    @classmethod
    def saved(cls, name: str) -> FakeBotResponse:
        """Сохранённый ответ Bot API: код — error_code отказа, у ответа «ok» — 200."""
        payload: dict[str, object] = json.loads((TELEGRAM_DATA / f"{name}.json").read_text(encoding="utf-8"))
        status: object = payload.get(ERROR_CODE_KEY, HTTP_OK)
        return cls(payload, status if isinstance(status, int) else HTTP_OK)

    def json(self) -> object:
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


@dataclass(frozen=True)
class BotCall:
    """Одно обращение бота: адрес и именованные параметры requests.post."""

    url: str
    options: dict[str, object]

    @property
    def method(self) -> str:
        return self.url.rsplit("/", 1)[-1]

    @property
    def body(self) -> dict[str, object]:
        """Поля запроса: JSON или форма multipart."""
        body: object = self.options.get("json", self.options.get("data"))
        assert isinstance(body, dict)
        return body


@dataclass
class FakeTelegram:
    """Подделка Telegram: ответы по порядку (ответ или исключение requests), записанные обращения и паузы; ответы
    кончились — ответ `rest` (None — ответов больше нет)."""

    outcomes: list[FakeBotResponse | Exception]
    calls: list[BotCall] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)
    rest: FakeBotResponse | None = None

    @classmethod
    def answering(cls, *outcomes: str | FakeBotResponse | Exception) -> FakeTelegram:
        """Строка — имя сохранённого ответа."""
        return cls([FakeBotResponse.saved(item) if isinstance(item, str) else item for item in outcomes])

    @classmethod
    def delivering(cls, *outcomes: str | FakeBotResponse | Exception) -> FakeTelegram:
        """Эти ответы по порядку, затем на всё — «отправлено в личный чат»."""
        fake: FakeTelegram = cls.answering(*outcomes)
        fake.rest = FakeBotResponse.saved("send_message_private")
        return fake

    def post(self, url: str, **options: object) -> FakeBotResponse:
        self.calls.append(BotCall(url=url, options=options))
        if not self.outcomes and self.rest is not None:
            return self.rest
        outcome: FakeBotResponse | Exception = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def bot(self) -> TelegramBot:
        return TelegramBot(token=BOT_SECRET, post=self.post, rng=random.Random(0), sleep=self.sleeps.append)

    @property
    def methods(self) -> list[str]:
        return [call.method for call in self.calls]


def connect_private_chat(paths: LivecraftPaths) -> None:
    """Свой токен бота в сейфе и подключённый личный чат в livecraft.json — объявлениям в Telegram есть куда уходить."""
    save_own_values(paths, {SecretField.TELEGRAM_BOT_TOKEN: BOT_TOKEN})
    file: SettingsFile = SettingsFile.of(paths)
    file.save(file.load().with_telegram(TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_CHAT_ID, "")))
