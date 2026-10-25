"""Сбой одного обращения к API Google как неудача попытки цикла повторов (CLAUDE.md §9, §11).

Таблица плана (`app\\sheets\\client.py`), Google Диск (`app\\google\\drive.py`) и Google Docs (`app\\google\\docs.py`)
ходят в API Google одинаково: ответ с кодом, отозванный по ходу запроса токен или сбой ниже HTTP. `CallFailures`
переводит такой сбой в `AttemptFailure` с причиной вызывающего: у каждого клиента — своё перечисление причин и своё
правило «код ответа → причина».

Создающее обращение (новый документ на Диске, вставка в документ) повторять вслепую нельзя: после 5xx или обрыва
неизвестно, выполнил ли его Google, и повтор задвоил бы документ или текст в нём (как инвариант 9 для YouTube). Для
таких обращений у сбоев есть причина «исход неизвестен» (`unknown`, `creating`): 5xx и транспорт дают её без повтора,
а 429 — отказ до выполнения — повторяется, как у чтения.

Адрес сервера Google не найден (`ServerNotFoundError`) — это не «Google не ответил», а нет интернета на компьютере:
клиент, который назвал причину `no_network` (таблица плана, Google Диск, Google Docs), получает её вместо «недоступен»
и говорит человеку прямо. Создающее обращение получает её так же: запрос до Google не дошёл, и повтор ничего не задвоит.
Та же причина — у входа, когда действующий вход не обновился из-за сбоя сети (`login_reason`): лечится повтором
запуска, а не настройкой.

`GoogleApi` — API по имени и версии: клиент строится одинаково на входе оператора, а неудачный вход становится
исключением вызывающего с причиной по его правилу входа (`CallFailures.login_reason`).

Текст исходной ошибки не выводится никуда: у `HttpError` в нём URL, а в URL таблицы — её id (§7.4). Исходная ошибка
остаётся только причиной (`cause`) неудачи.
"""
from __future__ import annotations

import dataclasses
import http.client
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus
from typing import Final, TypeVar

from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from app.core.retry import AttemptFailure, RetryLoop, RetryRun
from app.google.auth import AuthError, AuthErrorReason, GoogleLogin

T = TypeVar("T")

# Сбои ниже HTTP: обрыв, таймаут, SSL, сервер не найден (DNS), сбой транспорта google-auth при обновлении
# токена по ходу запроса. Повторяются с той же паузой, что и 429.
TRANSPORT_ERRORS: Final[tuple[type[Exception], ...]] = (
    OSError,
    http.client.HTTPException,
    ServerNotFoundError,
    TransportError,
)


@dataclass(frozen=True)
class GoogleApi:
    """API Google по имени и версии: клиент строится на входе оператора."""

    name: str
    version: str

    def open(
        self,
        login: GoogleLogin,
        on_login: Callable[[], None] | None,
        failures: CallFailures,
        error: Callable[[Enum, AuthError], Exception],
    ) -> Resource:
        """Вход (при нужде — в браузере, перед ним `on_login`) и клиент API; вход не удался — исключение вызывающего
        (`error`) с причиной по правилу входа его сбоев `failures` и ошибкой входа причиной."""
        try:
            credentials: object = login.credentials(allow_login=True, on_login=on_login)
        except AuthError as failure:
            raise error(failures.login_reason(failure.reason), failure) from failure
        return build(self.name, self.version, credentials=credentials, cache_discovery=False)


@dataclass(frozen=True)
class CallFailures:
    """Причины вызывающего для сбоев обращения: по коду ответа (`for_status`), отозванный вход (`auth`) и
    «Google временно недоступен» (`unavailable`) — она повторяется. `unknown` задан — обращение создающее: 5xx и
    транспорт дают эту причину без повтора. `no_network` задана — адрес сервера Google не найден (нет интернета) —
    своя причина: до Google запрос не дошёл, и она повторяется, как `unavailable`."""

    for_status: Callable[[int], Enum]
    auth: Enum
    unavailable: Enum
    unknown: Enum | None = None
    no_network: Enum | None = None

    def creating(self, unknown: Enum) -> CallFailures:
        """Те же причины для создающего обращения: исход 5xx и обрыва неизвестен — причина `unknown`, без повтора."""
        return dataclasses.replace(self, unknown=unknown)

    def login_reason(self, reason: AuthErrorReason) -> Enum:
        """Причина вызывающего по отказу входа: действующий вход не обновился из-за сбоя сети и у вызывающего есть
        причина `no_network` — она (лечится повтором запуска, а не настройкой); прочее — вход не удался (`auth`)."""
        if reason is AuthErrorReason.REFRESH_FAILED and self.no_network is not None:
            return self.no_network
        return self.auth

    def attempt(self, request: Callable[[], T]) -> T | AttemptFailure:
        """Одно обращение: ответ или неудача; неожиданное исключение — наружу, это ошибка программы."""
        try:
            return request()
        except HttpError as error:
            status: int = int(error.resp.status)
            reason: Enum = self._unreached(self.for_status(status), status)
            return AttemptFailure(reason, reason is self.unavailable, status, type(error).__name__, error)
        except RefreshError as error:
            return AttemptFailure(self.auth, False, error_name=type(error).__name__, cause=error)
        except TRANSPORT_ERRORS as error:
            reason = self._below_http(error)
            is_retryable: bool = reason in (self.unavailable, self.no_network)
            return AttemptFailure(reason, is_retryable, error_name=type(error).__name__, cause=error)

    def call(self, loop: RetryLoop, request: Callable[[], T], error: Callable[[AttemptFailure], Exception]) -> T:
        """Обращение с повторами цикла `loop`: ответ; повторы кончились или сбой неповторяемый — исключение
        вызывающего (`error`) с исходной ошибкой причиной."""
        run: RetryRun[T] = loop.run(lambda: self.attempt(request), lambda step: None)
        if run.failure is not None:
            raise error(run.failure) from run.failure.cause
        return run.value

    def _below_http(self, error: Exception) -> Enum:
        """Причина сбоя ниже HTTP: адрес сервера не найден — «нет связи», когда вызывающий назвал такую причину;
        прочее — «Google недоступен» (у создающего обращения — исход неизвестен)."""
        if self.no_network is not None and isinstance(error, ServerNotFoundError):
            return self.no_network
        return self._unreached(self.unavailable, None)

    def _unreached(self, reason: Enum, status: int | None) -> Enum:
        """Причина сбоя «Google недоступен» у создающего обращения: 429 — отказ до выполнения, прочее — исход
        неизвестен."""
        if self.unknown is None or reason is not self.unavailable or status == HTTPStatus.TOO_MANY_REQUESTS:
            return reason
        return self.unknown
