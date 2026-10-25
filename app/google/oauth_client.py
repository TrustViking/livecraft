"""Проект Google — OAuth-клиент программы (CLAUDE.md §9, §14 решение 66).

Файл клиента Google человек скачивает в Google Cloud Console при создании клиента типа Desktop app и выбирает в окне
на «Главной»; файл лежит где угодно и называется как угодно — настройки помнят путь к нему (`google.project_file`).
`OAuthClient` — такой файл, разобранный: годится, только если это клиент
типа Desktop (раздел «installed») с непустыми client_id, client_secret, token_uri и project_id — клиент типа Web,
файл другого вида или не JSON программа не принимает. Для людей клиент — «проект Google <ID>» (`label_of`).

Знает ли Google клиент, `ClientProbe` спрашивает без входа: запрос токена по заведомо негодному refresh_token. Google
знает клиент и секрет верный — отвечает invalid_grant (негоден refresh_token); клиент удалён в Google Cloud или секрет
не тот — invalid_client (проверено вживую 10-10-2026). Обрыв связи — «нет интернета», как у прочих обращений к Google;
повторы — `RetryLoop` (§11). Секрет клиента не попадает ни в лог, ни в текст ошибки, ни в repr.
"""
from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

import requests

from app.core.retry import RETRYABLE_HTTP_STATUSES, AttemptFailure, RetryLoop, RetryPolicy, RetryRun, RetryStep
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, LogValue, get_logger
from app.ui.messages import msg

LOGGER = get_logger(LogArea.AUTH)

# Заведомо негодный refresh_token проверки: Google отвечает на него, не выдавая доступа.
PROBE_REFRESH_TOKEN: Final[str] = "livecraft-client-check"
CLIENT_CHECK_TIMEOUT_SEC: Final[int] = 20


class ClientKey(str, Enum):
    """Поля файла клиента Google: раздел клиента типа Desktop и его поля."""

    INSTALLED = "installed"
    CLIENT_ID = "client_id"
    CLIENT_SECRET = "client_secret"
    PROJECT_ID = "project_id"
    TOKEN_URI = "token_uri"


class TokenRequestKey(str, Enum):
    """Поля запроса токена и ответа Google на него."""

    GRANT_TYPE = "grant_type"
    REFRESH_TOKEN = "refresh_token"
    ERROR = "error"


class ClientEvent(str, Enum):
    """События проверки клиента в логе."""

    CHECK_RETRY = "google_client_check_retry"


class ClientAnswer(str, Enum):
    """Что Google сказал о клиенте. Значение — идентификатор и ключ слов для человека (`msg.GOOGLE_CLIENT_ANSWERS`)."""

    KNOWN = "known"                # клиент есть, секрет верный
    NOT_KNOWN = "not_known"        # клиент удалён в Google Cloud или секрет не тот
    NO_NETWORK = "no_network"      # запрос до Google не дошёл
    UNAVAILABLE = "unavailable"    # Google не ответил или ответил не по делу и после повторов

    @property
    def is_known(self) -> bool:
        return self is ClientAnswer.KNOWN

    @property
    def log_mark(self) -> LogValue:
        """Поле known= строки лога: yes, no или unknown — Google не спросили."""
        return _LOG_MARKS.get(self, LogValue.UNKNOWN)

    @property
    def human(self) -> str:
        return msg.GOOGLE_CLIENT_ANSWERS[self.value]


_LOG_MARKS: Final[dict[ClientAnswer, LogValue]] = {ClientAnswer.KNOWN: LogValue.YES, ClientAnswer.NOT_KNOWN: LogValue.NO}
# Код ошибки ответа Google → что он значит о клиенте; прочие ответы — Google не ответил по делу.
TOKEN_ERROR_ANSWERS: Final[dict[str, ClientAnswer]] = {
    "invalid_grant": ClientAnswer.KNOWN,
    "invalid_client": ClientAnswer.NOT_KNOWN,
}
REQUIRED_KEYS: Final[tuple[ClientKey, ...]] = (
    ClientKey.CLIENT_ID, ClientKey.CLIENT_SECRET, ClientKey.PROJECT_ID, ClientKey.TOKEN_URI
)


@dataclass(frozen=True)
class OAuthClient:
    """Клиент Google типа Desktop: проект, id клиента, адрес выдачи токенов и секрет (в repr его нет)."""

    project_id: str
    client_id: str
    token_uri: str
    secret: str = field(repr=False)

    @classmethod
    def of_text(cls, text: str) -> OAuthClient | None:
        """Клиент из текста файла; не JSON, не клиент типа Desktop или нет нужного поля — None."""
        try:
            data: object = json.loads(text)
        except ValueError:
            return None
        section: object = data.get(ClientKey.INSTALLED.value) if isinstance(data, dict) else None
        if not isinstance(section, dict):
            return None
        values: dict[ClientKey, object] = {key: section.get(key.value) for key in REQUIRED_KEYS}
        if not all(isinstance(value, str) and value for value in values.values()):
            return None
        return cls(
            project_id=str(values[ClientKey.PROJECT_ID]),
            client_id=str(values[ClientKey.CLIENT_ID]),
            token_uri=str(values[ClientKey.TOKEN_URI]),
            secret=str(values[ClientKey.CLIENT_SECRET]),
        )

    @classmethod
    def of_file(cls, path: Path) -> OAuthClient | None:
        """Клиент из файла `path`; файла нет, он не читается или не клиент типа Desktop — None."""
        if not path.is_file():
            return None
        try:
            return cls.of_text(path.read_text(encoding=TEXT_ENCODING))
        except (OSError, UnicodeDecodeError):
            return None

    @classmethod
    def label_of(cls, text: str) -> str:
        """Файл клиента для людей: «проект Google <ID>»; файл не годится — так и сказать."""
        client: OAuthClient | None = cls.of_text(text)
        return msg.GOOGLE_PROJECT_UNFIT if client is None else client.label

    @property
    def label(self) -> str:
        return msg.GOOGLE_PROJECT.format(project=self.project_id)

    @property
    def probe_form(self) -> dict[str, str]:
        """Запрос токена по негодному refresh_token — тело проверки клиента; с секретом, в лог не идёт."""
        return {
            ClientKey.CLIENT_ID.value: self.client_id,
            ClientKey.CLIENT_SECRET.value: self.secret,
            TokenRequestKey.GRANT_TYPE.value: TokenRequestKey.REFRESH_TOKEN.value,
            TokenRequestKey.REFRESH_TOKEN.value: PROBE_REFRESH_TOKEN,
        }


@dataclass(frozen=True)
class ClientProbe:
    """Знает ли Google клиент — запрос без входа. `post` — `requests.post` или подделка; `policy`, `rng`, `sleep` —
    повторы (§11)."""

    post: Callable[..., requests.Response] = requests.post
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    def answer(self, client: OAuthClient) -> ClientAnswer:
        """Ответ Google о клиенте; повторы кончились — почему спросить не вышло."""
        loop: RetryLoop = RetryLoop(self.policy, self.rng, self.sleep)
        run: RetryRun[ClientAnswer] = loop.run(lambda: self._attempt(client), self._note_retry)
        if run.failure is None:
            return ClientAnswer(run.value)
        return ClientAnswer(run.failure.reason)

    def _attempt(self, client: OAuthClient) -> ClientAnswer | AttemptFailure:
        """Одно обращение: ответ о клиенте или неудача; обрыв связи, таймаут, 429 и 5xx — повторяемые."""
        try:
            response: requests.Response = self.post(
                client.token_uri, data=client.probe_form, timeout=CLIENT_CHECK_TIMEOUT_SEC
            )
        except requests.ConnectionError as error:
            return AttemptFailure(ClientAnswer.NO_NETWORK, True, error_name=type(error).__name__, cause=error)
        except requests.RequestException as error:
            is_timeout: bool = isinstance(error, requests.Timeout)
            return AttemptFailure(ClientAnswer.UNAVAILABLE, is_timeout, error_name=type(error).__name__, cause=error)
        known: ClientAnswer | None = TOKEN_ERROR_ANSWERS.get(self._error_code(response))
        if known is not None:
            return known
        status: int = response.status_code
        return AttemptFailure(ClientAnswer.UNAVAILABLE, status in RETRYABLE_HTTP_STATUSES, status=status)

    def _error_code(self, response: requests.Response) -> str:
        """Код ошибки ответа Google; ответ не JSON или кода нет — пусто."""
        try:
            payload: object = response.json()
        except ValueError:
            return ""
        code: object = payload.get(TokenRequestKey.ERROR.value) if isinstance(payload, dict) else None
        return code if isinstance(code, str) else ""

    def _note_retry(self, step: RetryStep) -> None:
        retry: LogEvent = LogEvent.of(ClientEvent.CHECK_RETRY, **step.failure.log_fields)
        retry.extended(retry=step.retry, delay_sec=round(step.delay_sec, 1)).emit(LOGGER, logging.WARNING)
