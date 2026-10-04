"""Бот Telegram: обращения к Bot API через requests (CLAUDE.md §13 задача 4.1, §14 решения 14, 19, 20; §15).

Программа только отправляет: приёма команд нет (§1). `TelegramBot` знает, кто он (`me`), задан ли у него webhook
(`webhook_url`), какие чаты ему писали (`chats`), и умеет отправить текст (`send_text`) и документ (`send_document`).
Итог каждого обращения — значение: ответ или отказ `BotFailure` с причиной `TelegramProblem`; исключений наружу нет.

Отправка: пауза перед каждой (Telegram ограничивает частоту сообщений); 429 — ожидание `retry_after` (нет — 5 с),
не больше трёх попыток; обрыв связи, таймаут и 5xx — повторы `RetryLoop` (§11); 401, 403 и «chat not found» —
отказ сразу, причиной. Группа стала супергруппой (`migrate_to_chat_id`) — отправка повторяется на новый id, и итог
несёт прежний id (`BotDelivery.migrated_from`): новый id в livecraft.json пишет тот, кто знает файл.

Токен бота стоит в пути запроса, поэтому раскрывается в одной точке — методе, строящем адрес (`_url`, §7.4). Текст
исключений requests содержит этот адрес и никуда не идёт: отказ несёт только имя метода, код и пояснение Telegram.
Строку чужой библиотеки с адресом («POST /bot<токен>/sendMessage») вычёркивает фильтр сейфа (`Vault.log_filter`).
Каждое обращение — строкой лога `telegram_call` (§14 решение 38): метод, id чата, если он есть в запросе, все попытки
и ok или причина отказа; ни токена, ни адреса Bot API, ни текста сообщения в ней нет. Пояснение отказа пишет тот, кто
звал бота, — он знает, зачем звал.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Final

import requests

from app.core.retry import RETRYABLE_ERRORS, AttemptFailure, RetryLoop, RetryPolicy, RetryRun
from app.observability.log_event import LogArea, LogEvent, LogValue, get_logger
from app.publish.telegram_api import (
    BotAnswer,
    BotChat,
    BotChats,
    BotDelivery,
    BotDocument,
    BotFailure,
    BotKey,
    BotMethod,
    BotRequest,
    MessageText,
    TelegramProblem,
)
from app.secretsafe.field import SecretField
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault

BOT_API_URL: Final[str] = "https://api.telegram.org/bot{token}/{method}"
REQUEST_TIMEOUT_SEC: Final[float] = 20.0
SEND_PAUSE_SEC: Final[float] = 1.0          # перед каждой отправкой: Telegram ограничивает частоту сообщений
RATE_LIMIT_ATTEMPTS: Final[int] = 3         # попыток обращения на 429

LOGGER = get_logger(LogArea.PUBLISH)


class BotEvent(str, Enum):
    """Обращение к Bot API в логе."""

    CALL = "telegram_call"


@dataclass(frozen=True)
class TelegramBot:
    """Бот на токене из сейфа — бот объявлений или бот поддержки: код один, токен — поле сейфа, которое назвал
    вызывающий. `post` — `requests.post` или подделка; пауза, политика повторов, `rng` и `sleep` —
    полями: в тестах свои."""

    token: SecretValue
    post: Callable[..., requests.Response] = requests.post
    pause_sec: float = SEND_PAUSE_SEC
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def from_vault(
        cls, vault: Vault | None, token_field: SecretField = SecretField.TELEGRAM_BOT_TOKEN
    ) -> TelegramBot | None:
        """Бот на токене поля сейфа `token_field`: объявлениям — бот объявлений, логам — бот поддержки (§14 решение 58).
        Сейф не прочитан или токена в нём нет — бота нет."""
        token: SecretValue | None = None if vault is None else vault.get(token_field)
        return None if token is None else cls(token=token)

    def me(self) -> BotChat | BotFailure:
        """Сам бот (getMe): имя и @имя — по ним человек найдёт его в Telegram."""
        answer: BotAnswer | BotFailure = self._call(BotRequest(BotMethod.GET_ME))
        if isinstance(answer, BotFailure):
            return answer
        return BotChat.of(answer.result if isinstance(answer.result, dict) else {})

    def webhook_url(self) -> str | BotFailure:
        """Адрес webhook бота; пусто — webhook нет, и getUpdates работает."""
        answer: BotAnswer | BotFailure = self._call(BotRequest(BotMethod.GET_WEBHOOK_INFO))
        if isinstance(answer, BotFailure):
            return answer
        info: object = answer.result
        return str(info.get(BotKey.URL.value) or "") if isinstance(info, dict) else ""

    def chats(self) -> BotChats | BotFailure:
        """Чаты, где боту писали или куда его добавили (getUpdates, обновления не подтверждаются).

        У бота webhook — отказ WEBHOOK, а getUpdates не зовётся: Telegram его всё равно отвергнет.
        """
        webhook: str | BotFailure = self.webhook_url()
        if isinstance(webhook, BotFailure):
            return webhook
        if webhook:
            return BotFailure(reason=TelegramProblem.WEBHOOK, method=BotMethod.GET_UPDATES)
        answer: BotAnswer | BotFailure = self._call(BotRequest(BotMethod.GET_UPDATES))
        if isinstance(answer, BotFailure):
            return answer
        return BotChats.from_updates(answer.result)

    def send_text(self, chat_id: str, text: str) -> BotDelivery | BotFailure:
        """Текст с разметкой HTML, нарезанный по переводу строки; куски — по порядку в чат, куда ушёл предыдущий.

        Итог — чат последнего куска и перенос, если он был: так перенесённый id узнаёт тот, кто пишет livecraft.json.
        """
        chunks: tuple[str, ...] = MessageText(text).chunks
        delivery: BotDelivery | BotFailure = self._send(BotRequest.message(chat_id, chunks[0]))
        for chunk in chunks[1:]:
            if isinstance(delivery, BotFailure):
                return delivery
            sent: BotDelivery | BotFailure = self._send(BotRequest.message(delivery.chat.chat_id, chunk))
            if isinstance(sent, BotDelivery):
                sent = BotDelivery(chat=sent.chat, migrated_from=delivery.migrated_from or sent.migrated_from)
            delivery = sent
        return delivery

    def send_document(self, chat_id: str, document: BotDocument) -> BotDelivery | BotFailure:
        """Файл документом (multipart) с подписью."""
        return self._send(BotRequest.file(chat_id, document))

    def _send(self, request: BotRequest) -> BotDelivery | BotFailure:
        """Отправка; группа стала супергруппой — ещё раз на новый id, и итог помнит прежний."""
        answer: BotAnswer | BotFailure = self._call(request)
        migrated_from: str | None = None
        if isinstance(answer, BotAnswer) and answer.migrated_to is not None:
            migrated_from = request.chat_id
            answer = self._call(request.to_chat(answer.migrated_to))
        if isinstance(answer, BotFailure):
            return answer
        return answer.delivery(request.method, migrated_from)

    def _call(self, request: BotRequest) -> BotAnswer | BotFailure:
        """Ответ «ok» или перенос чата; 429 — ждать сколько сказано и повторить, до трёх обменов; прочее — отказ.
        Итог — строкой `telegram_call` с попытками всех обменов."""
        run: RetryRun[BotAnswer] = self._exchange(request)
        attempts: int = run.attempts
        exchanges: int = 1
        while run.value is not None and run.value.status == HTTPStatus.TOO_MANY_REQUESTS:
            if exchanges == RATE_LIMIT_ATTEMPTS:
                break
            self.sleep(run.value.retry_after_sec)
            run = self._exchange(request)
            attempts += run.attempts
            exchanges += 1
        answer: BotAnswer | BotFailure = self._answer(request, run)
        called: LogEvent = LogEvent.of(BotEvent.CALL, method=request.method, chat=request.chat_id, attempts=attempts)
        if isinstance(answer, BotFailure):
            called.extended(result=answer.reason).emit(LOGGER, logging.WARNING)
        else:
            called.extended(result=LogValue.OK).emit(LOGGER)
        return answer

    def _answer(self, request: BotRequest, run: RetryRun[BotAnswer]) -> BotAnswer | BotFailure:
        """Итог обменов: сбой после повторов — отказ по его причине; ответ «ok» или перенос чата — ответ; прочий
        ответ — отказ по коду и пояснению Telegram."""
        if run.failure is not None:
            problem: TelegramProblem = TelegramProblem(run.failure.reason)
            return BotFailure(reason=problem, method=request.method, status=run.failure.status)
        answer: BotAnswer = run.value
        if answer.is_ok or answer.migrated_to is not None:
            return answer
        return answer.failure(request.method)

    def _exchange(self, request: BotRequest) -> RetryRun[BotAnswer]:
        """Обмен с повторами `RetryLoop` на обрыве, таймауте и 5xx; ответ Telegram — как есть. Повтор строкой лога не
        пишется: итог обращения — одна строка `telegram_call` с числом попыток."""
        loop: RetryLoop = RetryLoop(self.policy, self.rng, self.sleep)
        return loop.run(lambda: self._attempt(request), lambda _step: None)

    def _attempt(self, request: BotRequest) -> BotAnswer | AttemptFailure:
        """Одно обращение: перед отправкой — пауза; текст исключения requests (в нём адрес с токеном) не берётся."""
        if request.method.is_sending:
            self.sleep(self.pause_sec)
        try:
            response: requests.Response = self.post(
                self._url(request.method), timeout=REQUEST_TIMEOUT_SEC, **request.options
            )
        except requests.RequestException as error:
            is_retryable: bool = isinstance(error, RETRYABLE_ERRORS)
            return AttemptFailure(TelegramProblem.NETWORK, is_retryable, error_name=type(error).__name__)
        status: int = int(response.status_code)
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            return AttemptFailure(TelegramProblem.SERVER, True, status)
        return BotAnswer.of(response)

    def _url(self, method: BotMethod) -> str:
        """Адрес метода Bot API — единственная точка раскрытия токена бота (§7.4): токен стоит в пути запроса."""
        return BOT_API_URL.format(token=self.token.reveal(), method=method.value)
