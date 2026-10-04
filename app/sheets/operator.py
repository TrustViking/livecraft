"""Таблица плана на входе оператора: каким аккаунтом вошли и что делать, когда ему таблица не открыта (CLAUDE.md §9,
§13 задача 9.6).

Google при входе предлагает последний аккаунт браузера — часто это аккаунт канала YouTube, которому таблица плана не
открыта. Поэтому правило входа оператора — одно на запуск и на проверку таблицы в окне настройки (`OperatorSheets`):
перед браузером человеку говорят, каким аккаунтом входить (`on_login`); после нового входа — строка с почтой аккаунта
(её называет Google Диск: скоуп `drive` у оператора уже есть); таблица ответила 401 / 403 — строка с почтой, один
повторный вход в браузере мимо токена (прежний токен заменяет только удачный вход) и повтор чтения; снова 401 / 403 —
ошибка чтения `ACCOUNT_REFUSED` с почтой и действием. Файл токена человек руками не удаляет.

`OperatorDoor` — вход оператора этой установки: читатель таблицы и аккаунт входа; в тестах — подделка с теми же
`reader` и `account`. Строки правила уходят тому, кого назвал вызывающий (`say`): в запуске — на консоль, в окне — в
итог проверки. Почта аккаунта — не значение сейфа: она идёт и в строки, и в лог.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.google.auth import GoogleLogin
from app.google.drive import DriveClient, DriveError
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.run.progress import SILENT_PROGRESS, StageProgress
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReader, SheetsReadError, SheetsReadReason
from app.sheets.plan import SheetPlan
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SHEETS)


class OperatorEvent(str, Enum):
    """События входа оператора в логе."""

    LOGGED_IN = "operator_logged_in"
    ACCESS_REFUSED = "operator_access_refused"


@dataclass(frozen=True)
class OperatorAccount:
    """Аккаунт Google, под которым открыт вход оператора: почта; None — Google Диск её не назвал."""

    email: str | None

    @property
    def shown(self) -> str:
        """Почта для людей; не названа — так и сказать."""
        return self.email or msg.OPERATOR_ACCOUNT_UNKNOWN


@dataclass(frozen=True)
class OperatorDoor:
    """Вход оператора этой установки: читатель таблицы плана и аккаунт, под которым вошли. `progress` — строки хода
    повторов чтения (без консоли молчит)."""

    login: GoogleLogin
    progress: StageProgress = SILENT_PROGRESS

    def reader(self, on_login: Callable[[], None], again: bool = False) -> SheetsReader:
        """Читатель таблицы на входе оператора; нужен браузер — перед ним `on_login`. `again` — вход в браузере
        заново, мимо токена. Вход не удался — SheetsReadError(AUTH)."""
        return SheetsReader.open(self.login, on_login=on_login, force_reauth=again).reporting(self.progress)

    def account(self) -> OperatorAccount:
        """Аккаунт входа, как его называет Google Диск; Диск не ответил — аккаунт без почты и строка лога."""
        try:
            return OperatorAccount(DriveClient.open(self.login).account_email())
        except DriveError as error:
            error.event.emit(LOGGER, logging.WARNING)
            return OperatorAccount(None)


@dataclass
class BrowserVisit:
    """Открывался ли браузер входа: зовётся ровно перед ним и зовёт того, кто говорит об этом человеку."""

    on_login: Callable[[], None]
    is_opened: bool = False

    def __call__(self) -> None:
        self.is_opened = True
        self.on_login()


@dataclass(frozen=True)
class OperatorPlan:
    """План и читатель, который его прочитал: им же прогон пишет в таблицу язык видео и ссылки на превью."""

    plan: SheetPlan
    reader: SheetsReader


@dataclass(frozen=True)
class OperatorSheets:
    """Чтение таблицы плана по правилу входа оператора. `on_login` — ровно перед браузером (первый вход и
    повторный); `say` — строки правила: каким аккаунтом вошли, аккаунту таблица не открыта."""

    door: OperatorDoor
    on_login: Callable[[], None]
    say: Callable[[str], None]

    @classmethod
    def for_console(cls, door: OperatorDoor, say: Callable[[str], None]) -> OperatorSheets:
        """Правило запуска: и строка перед браузером (каким аккаунтом входить), и строки правила — в `say`."""
        return cls(door, lambda: say(msg.SHEETS_LOGIN_BROWSER), say)

    def read_plan(self, vault: Vault) -> OperatorPlan:
        """План таблицы, которую называет сейф. Аккаунту входа таблица не открыта — строка с его почтой, один
        повторный вход и повтор чтения; не открыта и новому — SheetsReadError(ACCOUNT_REFUSED) с почтой. Прочий
        сбой входа или чтения — SheetsReadError как есть."""
        first: OperatorPlan | SheetsReadError = self._attempt(vault, again=False)
        if isinstance(first, OperatorPlan):
            return first
        self.say(msg.OPERATOR_ACCESS_REFUSED.format(account=self._refused(first, will_relogin=True).shown))
        second: OperatorPlan | SheetsReadError = self._attempt(vault, again=True)
        if isinstance(second, OperatorPlan):
            return second
        account: OperatorAccount = self._refused(second, will_relogin=False)
        raise SheetsReadError(
            SheetsReadReason.ACCOUNT_REFUSED, second.label, second.status, account.shown
        ) from second

    def _refused(self, error: SheetsReadError, will_relogin: bool) -> OperatorAccount:
        """Аккаунт входа, которому таблица не открыта, и строка лога: будет ли повторный вход."""
        account: OperatorAccount = self.door.account()
        refused: LogEvent = LogEvent.of(OperatorEvent.ACCESS_REFUSED, account=account.email, status=error.status)
        refused.extended(relogin=will_relogin).emit(LOGGER, logging.WARNING if will_relogin else logging.ERROR)
        return account

    def _attempt(self, vault: Vault, again: bool) -> OperatorPlan | SheetsReadError:
        """Вход (при `again` — заново в браузере) и чтение. Отказ доступа — значением: что с ним делать, решает
        правило; прочий сбой — исключением."""
        reader: SheetsReader = self._entered(again)
        try:
            return OperatorPlan(reader.read_plan(vault), reader)
        except SheetsReadError as error:
            if error.reason is not SheetsReadReason.NO_ACCESS:
                raise
            return error

    def _entered(self, again: bool) -> SheetsReader:
        """Читатель на входе оператора; вход был новый (открывался браузер) — строка и лог: каким аккаунтом вошли."""
        visit: BrowserVisit = BrowserVisit(self.on_login)
        reader: SheetsReader = self.door.reader(visit, again)
        if visit.is_opened:
            account: OperatorAccount = self.door.account()
            LogEvent.of(OperatorEvent.LOGGED_IN, account=account.email).emit(LOGGER)
            self.say(msg.OPERATOR_LOGGED_IN.format(account=account.shown))
        return reader
