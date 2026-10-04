"""Читатель таблицы плана без Google: отдаёт план с листа из заданных значений или падает заданной ошибкой. Он же —
вход оператора без Google (`reader`, `account`, как у `OperatorDoor`): правило входа оператора идёт на нём."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReader, SheetsReadError
from app.sheets.operator import OperatorAccount
from app.sheets.plan import SheetPlan

PLAN_SHEET: str = "План стримов"
OPERATOR_EMAIL: str = "operator@example.com"


@dataclass
class FakeSheetsReader:
    """План с листа `sheet_title` по значениям `values` или сбой `error`; сейфы, с которыми его звали, и сколько раз
    для входа «открывался браузер» (`login_announced`) — в запись.

    Как вход оператора: первый вход открывает «браузер», если задано `announce_login`, повторный (`again`) — всегда;
    после повторного входа таблицу читает `relogin` (None — этот же читатель: вошли тем же аккаунтом). Почта аккаунта
    входа — `account_email` того читателя, которого вход отдал последним (None — Диск её не назвал)."""

    values: list[list[str]] = field(default_factory=list)
    error: SheetsReadError | None = None
    sheet_title: str = PLAN_SHEET
    announce_login: bool = False
    account_email: str | None = OPERATOR_EMAIL
    relogin: FakeSheetsReader | None = None
    vaults: list[Vault] = field(default_factory=list)
    login_announced: int = 0
    entered: list[FakeSheetsReader] = field(default_factory=list)

    def read_plan(self, vault: Vault) -> SheetPlan:
        self.vaults.append(vault)
        if self.error is not None:
            raise self.error
        return SheetPlan.from_values(self.sheet_title, 0, self.values)

    def reader(self, on_login: Callable[[], None], again: bool = False) -> SheetsReader:
        """Вход без браузера: сообщает «открылся браузер», как настоящий новый вход, и отдаёт читателя входа."""
        if again or self.announce_login:
            self.login_announced += 1
            on_login()
        self.entered.append(self.relogin if again and self.relogin is not None else self)
        return self.entered[-1]  # type: ignore[return-value]

    def account(self) -> OperatorAccount:
        """Аккаунт последнего входа."""
        return OperatorAccount(self.entered[-1].account_email)
