"""Вход в Google по OAuth: скоупы, токены, браузер (CLAUDE.md §9).

Перенос `planers\\app\\google\\auth.py` в ООП-форме: вход — объект `GoogleLogin` со своими файлами,
скоупами и правилом «сохранять ли новый вход». Только OAuth, без service account.

Две личности (§9) — два входа с раздельными токенами:
- оператор читает план из Google Sheets и пишет в него ссылки на копии превью, кладёт превью и документы в папку
  Google Диска (§14 решение 27) — `GoogleLogin.operator`, скоупы `spreadsheets`, `documents` и `drive`, токен
  `secrets\\sheets.token.json`; подтверждать ему нечего, поэтому новый вход пишется в файл сразу;
- владелец канала планирует эфиры — `GoogleLogin.owner`, скоуп только `youtube`, токен на канал
  `secrets\\<ник>.token.json`; новый вход пишет площадка и только после подтверждения канала, иначе чужой токен
  запоминается навсегда (planers, 17-09-2026).

Токен годен, только если его права покрывают нужные входу (`GoogleLogin.missing_scopes`): токен прежней версии с
меньшими правами — как нет токена, нужен вход в браузере; прежний файл заменяется только новым входом. В окне входа
человек может снять часть разрешений — тогда вход не принимается и токен не пишется (`SCOPES_NOT_GRANTED`).

Скоупы задаются здесь и больше нигде. Порт локального сервера — 0 (свободный): занятый порт кладёт вход.
Ожидание браузера ограничено LOGIN_TIMEOUT_SEC; строка про ссылку в консоли и страница «вход выполнен»
в браузере — из каталога msg на языке окна, а не тексты библиотеки. Тексты `AuthError` называют только имя
файла, без полного пути.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError

from app.core.dates import SECONDS_PER_MINUTE
from app.core.errors import os_error_reason
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, LogValue, get_logger
from app.paths import FileName, LivecraftPaths, write_text_atomically
from app.ui.messages import msg

LOGGER = get_logger(LogArea.AUTH)

# Единственный источник скоупов в проекте (CLAUDE.md §9, §14 решение 27).
SPREADSHEETS_SCOPE: Final[str] = "https://www.googleapis.com/auth/spreadsheets"
DOCUMENTS_SCOPE: Final[str] = "https://www.googleapis.com/auth/documents"
DRIVE_SCOPE: Final[str] = "https://www.googleapis.com/auth/drive"
YOUTUBE_SCOPE: Final[str] = "https://www.googleapis.com/auth/youtube"
LOCAL_SERVER_PORT: Final[int] = 0          # 0 — любой свободный порт
ACCESS_TYPE: Final[str] = "offline"        # без него Google не выдаст refresh-токен
# select_account — экран выбора аккаунта даже при login_hint; consent — refresh-токен выдаётся заново.
PROMPT: Final[str] = "select_account consent"
# Ожидание входа в браузере: без предела запуск висит, пока окно не закроют (planers, 17-09-2026).
# 10 минут — с запасом: живой первый вход (выбор аккаунта, канала и экран «не проверено») занял 8,5 минуты.
LOGIN_TIMEOUT_SEC: Final[int] = 600
LOGIN_TIMEOUT_MINUTES: Final[int] = LOGIN_TIMEOUT_SEC // SECONDS_PER_MINUTE
DETAIL_TEMPLATE: Final[str] = "{file}: {problem}"
ERROR_DETAIL_TEMPLATE: Final[str] = "{name}: {error}"
DETAIL_LOGIN_TIMEOUT: Final[str] = "no answer in {seconds} s"
DETAIL_NO_CREDENTIALS: Final[str] = "flow returned no credentials"
DETAIL_SCOPES_MISSING: Final[str] = "not granted: {scopes}"
# Права, которые Google выдал на самом деле: oauthlib кладёт их в своё предупреждение о смене прав.
GRANTED_SCOPES_ATTRIBUTE: Final[str] = "new_scope"


class AuthEvent(str, Enum):
    """События входа в Google в логе."""

    FAILED = "auth_failed"
    TOKEN_DROPPED = "token_dropped"
    LOGIN_NOT_ALLOWED = "login_not_allowed"
    LOGIN_COMPLETED = "login_completed"
    TOKEN_REFRESH_REJECTED = "token_refresh_rejected"
    TOKEN_REFRESHED = "token_refreshed"
    TOKEN_SCOPES_SHORT = "token_scopes_short"


class FlowArgument(str, Enum):
    """Параметры браузерного входа `InstalledAppFlow.run_local_server`."""

    PORT = "port"
    ACCESS_TYPE = "access_type"
    PROMPT = "prompt"
    TIMEOUT_SECONDS = "timeout_seconds"
    PROMPT_MESSAGE = "authorization_prompt_message"
    SUCCESS_MESSAGE = "success_message"
    LOGIN_HINT = "login_hint"


class AuthErrorReason(str, Enum):
    CLIENT_SECRET_MISSING = "client_secret_missing"
    TOKEN_UNREADABLE = "token_unreadable"     # файл токена есть, но не читается или не разбирается
    TOKEN_UNWRITABLE = "token_unwritable"     # файл токена не удаётся записать или удалить
    FLOW_FAILED = "flow_failed"
    REFRESH_FAILED = "refresh_failed"
    LOGIN_REQUIRED = "login_required"   # нужен браузер, а вызывающий вход запретил (allow_login=False)
    LOGIN_TIMEOUT = "login_timeout"     # вход в браузере не завершён за LOGIN_TIMEOUT_SEC
    SCOPES_NOT_GRANTED = "scopes_not_granted"   # в окне входа сняты разрешения, без которых вход не работает

    @property
    def human(self) -> str:
        """Строка причины для человека; текст — в каталоге msg (§11)."""
        return msg.AUTH_REASON_TEXT[self.value].format(minutes=LOGIN_TIMEOUT_MINUTES)


class AuthError(Exception):
    """Единственное исключение, которое выпускает этот модуль наружу. Текст — причина для человека
    (контракт ошибок, §11); `detail` — машинная подробность только для лога: имя файла и короткая причина,
    без полного пути.
    """

    def __init__(self, reason: AuthErrorReason, detail: str = "") -> None:
        self.reason: AuthErrorReason = reason
        self.detail: str = detail
        super().__init__(self.human)

    @property
    def human(self) -> str:
        return self.reason.human

    @property
    def log_line(self) -> str:
        return LogEvent.of(AuthEvent.FAILED, reason=self.reason, detail=self.detail).text

    def __str__(self) -> str:
        return self.human


@dataclass(frozen=True)
class GoogleLogin:
    """Вход одной личности Google: паспорт программы, файл токена, скоупы и правило записи нового входа.

    `login_hint` — почта аккаунта: браузер сразу предлагает её. У оператора подсказки нет — Google предлагает
    последний аккаунт браузера: каким аккаунтом входить, каким вошли и повторный вход (`force_reauth`), когда аккаунту
    таблица не открыта, — правило входа оператора (app\\sheets\\operator.py).
    `saves_new_login` — писать ли токен сразу после входа в браузере. Обновление действующего токена
    пишется в файл всегда.
    """

    client_secret_file: Path
    token_file: Path
    scopes: tuple[str, ...]
    login_hint: str | None
    saves_new_login: bool

    @classmethod
    def operator(cls, paths: LivecraftPaths) -> GoogleLogin:
        """Личность оператора (§9): таблица плана, документы и папка Google Диска; один токен на установку, вход
        пишется сразу."""
        return cls(
            client_secret_file=paths.file(FileName.CLIENT_SECRET),
            token_file=paths.file(FileName.SHEETS_TOKEN),
            scopes=(SPREADSHEETS_SCOPE, DOCUMENTS_SCOPE, DRIVE_SCOPE),
            login_hint=None,
            saves_new_login=True,
        )

    @classmethod
    def owner(cls, paths: LivecraftPaths, token_stem: str, google_account: str) -> GoogleLogin:
        """Личность владельца канала (§9): скоуп только youtube, свой токен на канал, подсказка — почта аккаунта канала.
        Новый вход в файл не пишется: токен пишет площадка (`save`), когда канал за этим входом подтверждён."""
        return cls(
            client_secret_file=paths.file(FileName.CLIENT_SECRET),
            token_file=paths.token_file(token_stem),
            scopes=(YOUTUBE_SCOPE,),
            login_hint=google_account,
            saves_new_login=False,
        )

    def credentials(
        self,
        allow_login: bool = True,
        force_reauth: bool = False,
        on_login: Callable[[], None] | None = None,
    ) -> Credentials:
        """Готовые к работе учётные данные: из токена, обновлением или через браузер.

        on_login вызывается ровно перед открытием браузера: по нему вызывающий знает, что вход новый.
        force_reauth — вход в браузере без чтения токена; файл токена до входа не трогается.
        allow_login=False — браузер не открывается: нужен вход — AuthError(LOGIN_REQUIRED), токен не трогается.
        """
        if not self.client_secret_file.is_file():
            raise AuthError(AuthErrorReason.CLIENT_SECRET_MISSING, self.client_secret_file.name)
        if force_reauth:
            return self._log_in(allow_login, on_login)
        credentials: Credentials | None = self._load_token()
        if credentials is None:
            return self._log_in(allow_login, on_login)
        if credentials.valid:
            return credentials
        refreshed: Credentials | None = self._refresh(credentials)
        if refreshed is not None:
            return refreshed
        return self._log_in(allow_login, on_login)

    def missing_scopes(self, granted: Iterable[str] | None) -> tuple[str, ...]:
        """Нужные входу права, которых нет среди `granted` — прав токена или выданных при входе, по порядку входа."""
        have: frozenset[str] = frozenset(granted or ())
        return tuple(scope for scope in self.scopes if scope not in have)

    def save(self, credentials: Credentials) -> None:
        """Записать токен атомарно; единственная запись файла токена. Оборванная запись оставляет прежний файл."""
        try:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomically(self.token_file, credentials.to_json(), TEXT_ENCODING)
        except OSError as error:
            raise AuthError(AuthErrorReason.TOKEN_UNWRITABLE, self._detail(error)) from error

    def drop(self) -> None:
        """Удалить файл токена: единственное место удаления (токен ведёт не на тот аккаунт)."""
        try:
            self.token_file.unlink(missing_ok=True)
        except OSError as error:
            raise AuthError(AuthErrorReason.TOKEN_UNWRITABLE, self._detail(error)) from error
        LogEvent.of(AuthEvent.TOKEN_DROPPED, file=self.token_file.name).emit(LOGGER)

    def _log_in(self, allow_login: bool, on_login: Callable[[], None] | None) -> Credentials:
        """Вход через браузер — единственный путь к нему; запрет входа проверяется здесь же."""
        if not allow_login:
            LogEvent.of(AuthEvent.LOGIN_NOT_ALLOWED, file=self.token_file.name).emit(LOGGER)
            raise AuthError(AuthErrorReason.LOGIN_REQUIRED, self.token_file.name)
        if on_login is not None:
            on_login()
        credentials: Credentials = self._run_flow()
        LogEvent.of(AuthEvent.LOGIN_COMPLETED, file=self.token_file.name, saved=self.saves_new_login).emit(LOGGER)
        if self.saves_new_login:
            self.save(credentials)
        return credentials

    def _load_token(self) -> Credentials | None:
        """Токен из файла с его правами. Нет файла или права токена не покрывают нужные — None (пойдём в браузер,
        файл заменит только новый вход); файл есть, но не читается — это ошибка."""
        if not self.token_file.is_file():
            return None
        try:
            credentials: Credentials = Credentials.from_authorized_user_file(str(self.token_file))
        except (OSError, ValueError, KeyError) as error:
            raise AuthError(AuthErrorReason.TOKEN_UNREADABLE, self._detail(error)) from error
        missing: tuple[str, ...] = self.missing_scopes(credentials.scopes)
        if missing:
            short: LogEvent = LogEvent.of(AuthEvent.TOKEN_SCOPES_SHORT, file=self.token_file.name, missing=missing)
            short.emit(LOGGER, logging.WARNING)
            return None
        return credentials

    def _refresh(self, credentials: Credentials) -> Credentials | None:
        """None — токен отозван, нужен браузер; сетевой сбой — AuthError, браузер тут не поможет."""
        if not credentials.refresh_token:
            return None
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            rejected: LogEvent = LogEvent.of(AuthEvent.TOKEN_REFRESH_REJECTED, file=self.token_file.name, reason=error)
            rejected.emit(LOGGER, logging.WARNING)
            return None
        except TransportError as error:
            raise AuthError(AuthErrorReason.REFRESH_FAILED, self._detail(error)) from error
        self.save(credentials)
        LogEvent.of(AuthEvent.TOKEN_REFRESHED, file=self.token_file.name).emit(LOGGER)
        return credentials

    def _run_flow(self) -> Credentials:
        """Браузер не дольше LOGIN_TIMEOUT_SEC; вход принимается, только если Google выдал все нужные права.

        WSGITimeoutError наследует AttributeError — ловится отдельно, до общих сбоев. Снятое в окне входа разрешение
        oauthlib встречает предупреждением о смене прав (Warning) с выданными правами — это тот же отказ, что и
        неполные `granted_scopes`. Не сказал Google, какие права выдал, — выданы запрошенные (RFC 6749, п. 5.1).
        """
        try:
            flow: InstalledAppFlow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secret_file),
                scopes=list(self.scopes),
            )
            credentials: Credentials = flow.run_local_server(**self._flow_arguments())
        except WSGITimeoutError as error:
            detail: str = DETAIL_LOGIN_TIMEOUT.format(seconds=LOGIN_TIMEOUT_SEC)
            raise AuthError(AuthErrorReason.LOGIN_TIMEOUT, detail) from error
        except Warning as warning:
            raise self._not_granted(getattr(warning, GRANTED_SCOPES_ATTRIBUTE)) from warning
        except (OSError, ValueError, RefreshError, TransportError) as error:
            raise AuthError(AuthErrorReason.FLOW_FAILED, self._detail(error, self.client_secret_file)) from error
        if credentials is None:
            raise AuthError(AuthErrorReason.FLOW_FAILED, DETAIL_NO_CREDENTIALS)
        granted: Iterable[str] = self.scopes if credentials.granted_scopes is None else credentials.granted_scopes
        if self.missing_scopes(granted):
            raise self._not_granted(granted)
        return credentials

    def _not_granted(self, granted: Iterable[str]) -> AuthError:
        """Отказ входа, в котором выданы не все нужные права: каких нет — в подробность для лога."""
        missing: str = LogValue.LIST_SEPARATOR.value.join(self.missing_scopes(granted))
        return AuthError(AuthErrorReason.SCOPES_NOT_GRANTED, DETAIL_SCOPES_MISSING.format(scopes=missing))

    def _flow_arguments(self) -> dict[str, Any]:
        """Параметры браузерного входа; подсказка аккаунта — только если она есть."""
        arguments: dict[FlowArgument, Any] = {
            FlowArgument.PORT: LOCAL_SERVER_PORT,
            FlowArgument.ACCESS_TYPE: ACCESS_TYPE,
            FlowArgument.PROMPT: PROMPT,
            FlowArgument.TIMEOUT_SECONDS: LOGIN_TIMEOUT_SEC,
            FlowArgument.PROMPT_MESSAGE: msg.AUTH_OPEN_LINK,
            FlowArgument.SUCCESS_MESSAGE: msg.AUTH_BROWSER_DONE,
        }
        if self.login_hint is not None:
            arguments[FlowArgument.LOGIN_HINT] = self.login_hint
        return {argument.value: value for argument, value in arguments.items()}

    def _detail(self, error: Exception, file: Path | None = None) -> str:
        """Имя файла и причина без полного пути: у OSError путь лежит в filename, берётся только strerror."""
        if isinstance(error, OSError):
            problem: str = os_error_reason(error)
        else:
            problem = ERROR_DETAIL_TEMPLATE.format(name=type(error).__name__, error=error)
        return DETAIL_TEMPLATE.format(file=(file or self.token_file).name, problem=problem)
