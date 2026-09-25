"""Вход в Google по OAuth: скоупы, токены, браузер (CLAUDE.md §9).

Перенос `planers\\app\\google\\auth.py` в ООП-форме: вход — объект `GoogleLogin` со своими файлами,
скоупами и правилом «сохранять ли новый вход». Только OAuth: ни service account, ни Docs, ни Drive.

Две личности (§9) — два входа с раздельными токенами и минимальными скоупами:
- оператор читает план из Google Sheets — `GoogleLogin.operator`, скоуп только `spreadsheets.readonly`,
  токен `secrets\\sheets.token.json`; подтверждать ему нечего, поэтому новый вход пишется в файл сразу;
- владелец канала планирует эфиры — скоуп только `youtube`, токен на канал; новый вход пишет вызывающий и
  только после подтверждения канала (этап 4), иначе чужой токен запоминается навсегда (planers, 17-09-2026).

Скоупы задаются здесь и больше нигде. Порт локального сервера — 0 (свободный): занятый порт кладёт вход.
Ожидание браузера ограничено LOGIN_TIMEOUT_SEC; строка про ссылку в консоли и страница «вход выполнен»
в браузере — из messages_ru, а не английские тексты библиотеки. Тексты `AuthError` называют только имя
файла, без полного пути.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError

from app.observability.logging_setup import get_logger
from app.paths import LivecraftPaths, write_text_atomically
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "auth"
LOGGER = get_logger(LOGGER_NAME)

# Единственный источник скоупов в проекте (CLAUDE.md §9).
SHEETS_SCOPE: Final[str] = "https://www.googleapis.com/auth/spreadsheets.readonly"
YOUTUBE_SCOPE: Final[str] = "https://www.googleapis.com/auth/youtube"
LOCAL_SERVER_PORT: Final[int] = 0          # 0 — любой свободный порт
ACCESS_TYPE: Final[str] = "offline"        # без него Google не выдаст refresh-токен
# select_account — экран выбора аккаунта даже при login_hint; consent — refresh-токен выдаётся заново.
PROMPT: Final[str] = "select_account consent"
# Ожидание входа в браузере: без предела запуск висит, пока окно не закроют (planers, 17-09-2026).
# 10 минут — с запасом: живой первый вход (выбор аккаунта, канала и экран «не проверено») занял 8,5 минуты.
LOGIN_TIMEOUT_SEC: Final[int] = 600
SECONDS_PER_MINUTE: Final[int] = 60
LOGIN_TIMEOUT_MINUTES: Final[int] = LOGIN_TIMEOUT_SEC // SECONDS_PER_MINUTE
TOKEN_ENCODING: Final[str] = "utf-8"
DETAIL_TEMPLATE: Final[str] = "{file}: {problem}"


class AuthErrorReason(str, Enum):
    CLIENT_SECRET_MISSING = "client_secret_missing"
    TOKEN_UNREADABLE = "token_unreadable"     # файл токена есть, но не читается или не разбирается
    TOKEN_UNWRITABLE = "token_unwritable"     # файл токена не удаётся записать или удалить
    FLOW_FAILED = "flow_failed"
    REFRESH_FAILED = "refresh_failed"
    LOGIN_REQUIRED = "login_required"   # нужен браузер, а вызывающий вход запретил (allow_login=False)
    LOGIN_TIMEOUT = "login_timeout"     # вход в браузере не завершён за LOGIN_TIMEOUT_SEC

    @property
    def human(self) -> str:
        """Русская строка причины; текст — в messages_ru (§11)."""
        return msg.AUTH_REASON_TEXT[self.value].format(minutes=LOGIN_TIMEOUT_MINUTES)


class AuthError(Exception):
    """Единственное исключение, которое выпускает этот модуль наружу.

    `detail` — машинная подробность для лога: имя файла и короткая причина, без полного пути.
    """

    def __init__(self, reason: AuthErrorReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason: AuthErrorReason = reason
        self.detail: str = detail

    @property
    def human(self) -> str:
        return self.reason.human


@dataclass(frozen=True)
class GoogleLogin:
    """Вход одной личности Google: паспорт программы, файл токена, скоупы и правило записи нового входа.

    `login_hint` — почта аккаунта: браузер сразу предлагает её (у оператора подсказки нет).
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
        """Личность оператора (§9): только чтение таблиц, один токен на установку, вход пишется сразу."""
        return cls(
            client_secret_file=paths.client_secret_file,
            token_file=paths.sheets_token_file,
            scopes=(SHEETS_SCOPE,),
            login_hint=None,
            saves_new_login=True,
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

    def save(self, credentials: Credentials) -> None:
        """Записать токен атомарно; единственная запись файла токена. Оборванная запись оставляет прежний файл."""
        try:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomically(self.token_file, credentials.to_json(), TOKEN_ENCODING)
        except OSError as error:
            raise AuthError(AuthErrorReason.TOKEN_UNWRITABLE, self._detail(error)) from error

    def drop(self) -> None:
        """Удалить файл токена: единственное место удаления (токен ведёт не на тот аккаунт)."""
        try:
            self.token_file.unlink(missing_ok=True)
        except OSError as error:
            raise AuthError(AuthErrorReason.TOKEN_UNWRITABLE, self._detail(error)) from error
        LOGGER.info("token_dropped file=%s", self.token_file.name)

    def _log_in(self, allow_login: bool, on_login: Callable[[], None] | None) -> Credentials:
        """Вход через браузер — единственный путь к нему; запрет входа проверяется здесь же."""
        if not allow_login:
            LOGGER.info("login_not_allowed file=%s", self.token_file.name)
            raise AuthError(AuthErrorReason.LOGIN_REQUIRED, self.token_file.name)
        if on_login is not None:
            on_login()
        credentials: Credentials = self._run_flow()
        LOGGER.info("login_completed file=%s saved=%s", self.token_file.name, self.saves_new_login)
        if self.saves_new_login:
            self.save(credentials)
        return credentials

    def _load_token(self) -> Credentials | None:
        """Нет файла — None (пойдём в браузер); файл есть, но не читается — это ошибка."""
        if not self.token_file.is_file():
            return None
        try:
            return Credentials.from_authorized_user_file(str(self.token_file), scopes=list(self.scopes))
        except (OSError, ValueError, KeyError) as error:
            raise AuthError(AuthErrorReason.TOKEN_UNREADABLE, self._detail(error)) from error

    def _refresh(self, credentials: Credentials) -> Credentials | None:
        """None — токен отозван, нужен браузер; сетевой сбой — AuthError, браузер тут не поможет."""
        if not credentials.refresh_token:
            return None
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            LOGGER.warning("token_refresh_rejected file=%s reason=%s", self.token_file.name, error)
            return None
        except TransportError as error:
            raise AuthError(AuthErrorReason.REFRESH_FAILED, self._detail(error)) from error
        self.save(credentials)
        LOGGER.info("token_refreshed file=%s", self.token_file.name)
        return credentials

    def _run_flow(self) -> Credentials:
        """Браузер не дольше LOGIN_TIMEOUT_SEC.

        WSGITimeoutError наследует AttributeError — ловится отдельно, до общих сбоев.
        """
        try:
            flow: InstalledAppFlow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secret_file),
                scopes=list(self.scopes),
            )
            credentials: Credentials = flow.run_local_server(**self._flow_arguments())
        except WSGITimeoutError as error:
            raise AuthError(AuthErrorReason.LOGIN_TIMEOUT, f"no answer in {LOGIN_TIMEOUT_SEC} s") from error
        except (OSError, ValueError, RefreshError, TransportError) as error:
            raise AuthError(AuthErrorReason.FLOW_FAILED, self._detail(error, self.client_secret_file)) from error
        if credentials is None:
            raise AuthError(AuthErrorReason.FLOW_FAILED, "flow returned no credentials")
        return credentials

    def _flow_arguments(self) -> dict[str, Any]:
        """Параметры браузерного входа; подсказка аккаунта — только если она есть."""
        arguments: dict[str, Any] = {
            "port": LOCAL_SERVER_PORT,
            "access_type": ACCESS_TYPE,
            "prompt": PROMPT,
            "timeout_seconds": LOGIN_TIMEOUT_SEC,
            "authorization_prompt_message": msg.AUTH_OPEN_LINK,
            "success_message": msg.AUTH_BROWSER_DONE,
        }
        if self.login_hint is not None:
            arguments["login_hint"] = self.login_hint
        return arguments

    def _detail(self, error: Exception, file: Path | None = None) -> str:
        """Имя файла и причина без полного пути: у OSError путь лежит в filename, берётся только strerror."""
        if isinstance(error, OSError):
            problem: str = error.strerror or type(error).__name__
        else:
            problem = f"{type(error).__name__}: {error}"
        return DETAIL_TEMPLATE.format(file=(file or self.token_file).name, problem=problem)
