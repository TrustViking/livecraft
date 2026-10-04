"""Пробник чтения таблицы плана: вход оператора → выбор листа и чтение его → разбор рядов (CLAUDE.md §5 tools\\).

Запуск из корня репо: `python -m app.tools.sheets_probe [--relogin]`. В поставку не идёт. Сети в тестах
нет — читатель подменяется; боевую проверку делают вручную на настоящих данных.

`--relogin` — вход в браузере заново, без чтения прежнего токена: так исправляется вход не тем аккаунтом.
Новый токен заменяет прежний только после успешного входа (это правило `GoogleLogin`). Отказ в доступе к
таблице пробник сопровождает подсказкой про `--relogin`.

Печатает только то, что не секретно: лист плана, заголовки и буквы распознанных колонок, сколько рядов прочитано,
допущено и отсеяно по каждой причине, проблему плана. Ни id таблицы, ни ссылок рядов (§7.4).
Фильтр секретов в логах ставится сразу после чтения сейфа, до первого обращения к Google.
Коды — по правилу запуска (§10): 0 — прочитано; 1 — Google не дал прочитать; 2 — сейф или настройки не готовы
или вход в Google не удался (`SheetsReadReason.is_configuration`).
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.files import SettingsFile
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings
from app.core.counts import CountItem
from app.google.auth import AuthError, GoogleLogin
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.run.exit_code import ExitCode
from app.run.flag import ArgAction
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.field import SecretField
from app.sheets.client import SheetsReader, SheetsReadError, SheetsReadReason, SheetsTarget
from app.sheets.plan import PlanColumn, SheetColumns, SheetPlan
from app.sheets.rows import PlannedRows, RowSkipReason
from app.tools.probe import ProbeConsole, ProbeLauncher, ProbeSession
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SHEETS_PROBE)
PROG: Final[str] = "python -m app.tools.sheets_probe"
RELOGIN_FLAG: Final[str] = "--relogin"


class SheetsProbeEvent(str, Enum):
    """События пробника таблицы в логе."""

    FAILED = "sheets_probe_failed"
    RELOGIN_FAILED = "sheets_probe_relogin_failed"


@dataclass(frozen=True)
class SheetsProbeReport:
    """Что показать человеку о прочитанном плане: колонки, счётчики, проблема. Ни одного значения ряда."""

    plan: SheetPlan
    rows: PlannedRows

    @property
    def lines(self) -> tuple[str, ...]:
        """Проблема плана — одной строкой; иначе колонки, счётчики рядов и отсеянные по причинам."""
        columns: SheetColumns | None = self.plan.columns
        if columns is None:
            return (self.plan.problem_text,)
        return (self._columns_line(columns), self._rows_line, *self._skip_lines)

    def _columns_line(self, columns: SheetColumns) -> str:
        return msg.SHEETS_PROBE_COLUMNS.format(
            sheet=self.plan.sheet_title,
            link=self._column(columns, PlanColumn.LINK),
            date=self._column(columns, PlanColumn.DATE),
            time=self._column(columns, PlanColumn.TIME),
        )

    def _column(self, columns: SheetColumns, column: PlanColumn) -> str:
        """Заголовок колонки и её буквы на листе."""
        return msg.SHEETS_PROBE_COLUMN.format(
            name=self.plan.header.names[columns.index(column)], letters=columns.letters(column)
        )

    @property
    def _rows_line(self) -> str:
        rows: PlannedRows = self.rows
        return msg.SHEETS_PROBE_ROWS.format(rows=rows.total, admitted=len(rows.admitted), skipped=len(rows.skipped))

    @property
    def _skip_lines(self) -> tuple[str, ...]:
        """По строке на причину отсева в порядке проверок."""
        items: tuple[CountItem[RowSkipReason], ...] = self.rows.counts.items
        return tuple(item.text(msg.SHEETS_PROBE_SKIP_LINE, lambda reason: reason.human) for item in items)


@dataclass(frozen=True)
class SheetsProbe:
    """Один прогон пробника в сессии запуска; `relogin` — войти в браузере заново до чтения таблицы."""

    session: ProbeSession
    relogin: bool = False

    def run(self) -> int:
        console: ProbeConsole = self.session.console
        console.say(msg.SHEETS_PROBE_TITLE)
        try:
            loaded: VaultLoad = VaultStore.open(self.session.paths).load()
            settings: LivecraftSettings = SettingsFile.of(self.session.paths).load()
        except (VaultFormatError, ConfigError) as error:
            return console.refuse(error.human)
        self.session.log.protect(loaded.vault.log_filter())      # до первого обращения к Google (§7.4)
        console.say_lines(loaded.warnings)
        try:
            SheetsTarget.from_vault(loaded.vault)
            plan: SheetPlan = self._read(loaded)
        except SheetsReadError as error:
            return self._fail(error)
        rows: PlannedRows = plan.plan_rows(settings.zone, self.session.started.astimezone(settings.zone))
        console.say_lines(SheetsProbeReport(plan=plan, rows=rows).lines)
        return int(ExitCode.OK)

    def _read(self, loaded: VaultLoad) -> SheetPlan:
        login: GoogleLogin = GoogleLogin.operator(self.session.paths)
        if self.relogin:
            self._log_in_again(login)
        reader: SheetsReader = SheetsReader.open(login, on_login=self._announce_login)
        return reader.read_plan(loaded.vault)

    def _log_in_again(self, login: GoogleLogin) -> None:
        """Вход в браузере без чтения прежнего токена; новый токен пишет сам вход, только после успеха.

        Отказ входа — та же ошибка чтения, что отдал бы `SheetsReader.open`: ярлык таблицы и причина входа.
        """
        try:
            login.credentials(force_reauth=True, on_login=self._announce_login)
        except AuthError as error:
            failed: LogEvent = LogEvent.of(SheetsProbeEvent.RELOGIN_FAILED, reason=error.reason, detail=error.detail)
            failed.emit(LOGGER, logging.WARNING)
            raise SheetsReadError(
                SheetsReadReason.AUTH, SecretField.SHEETS_ID.log_label, detail=error.human
            ) from error

    def _announce_login(self) -> None:
        self.session.console.say(msg.SHEETS_PROBE_LOGIN)

    def _fail(self, error: SheetsReadError) -> int:
        """Не настроено — код 2 и совет про настройщик; вход не удался — код 2; прочее — код 1 (§10)."""
        failed: LogEvent = LogEvent.of(SheetsProbeEvent.FAILED, reason=error.reason, sheet=error.label)
        failed.extended(status=error.status).emit(LOGGER, logging.ERROR)
        if error.reason is SheetsReadReason.NOT_CONFIGURED:
            return self.session.console.refuse(error.human)
        self.session.console.say(error.human)
        if error.reason is SheetsReadReason.NO_ACCESS:
            self.session.console.say(msg.SHEETS_PROBE_RELOGIN_HINT)
        return int(ExitCode.CONFIG if error.reason.is_configuration else ExitCode.ERRORS)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа пробника: ключи; корень, папки и лог — у `ProbeLauncher`; дальше — `SheetsProbe`."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument(RELOGIN_FLAG, action=ArgAction.STORE_TRUE.value, help=msg.SHEETS_PROBE_RELOGIN_HELP)
    relogin: bool = bool(parser.parse_args(argv).relogin)
    return ProbeLauncher.system().run(lambda session: SheetsProbe(session=session, relogin=relogin).run())


if __name__ == "__main__":
    sys.exit(main())
