"""Пробник чтения таблицы плана: вход оператора → чтение диапазона → разбор рядов (CLAUDE.md §5 tools\\).

Запуск из корня репо: `python -m app.tools.sheets_probe [--relogin]`. В поставку не идёт. Сети в тестах
нет — читатель подменяется; боевой прогон делает Артур.

`--relogin` — вход в браузере заново, без чтения прежнего токена: так исправляется вход не тем аккаунтом.
Новый токен заменяет прежний только после успешного входа (это правило `GoogleLogin`). Отказ в доступе к
таблице пробник сопровождает подсказкой про `--relogin`.

Печатает только то, что не секретно: заголовки распознанных колонок, сколько рядов прочитано, допущено
и отсеяно по каждой причине, проблему плана. Ни id таблицы, ни диапазона, ни ссылок рядов (§7.4).
Фильтр секретов в логах ставится сразу после чтения сейфа, до первого обращения к Google.
Коды: 0 — прочитано; 1 — Google или вход не дали прочитать; 2 — сейф или настройки не готовы.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Final

from app.config.loader import ConfigError, LivecraftSettings, load_settings
from app.google.auth import AuthError, GoogleLogin
from app.observability.logging_setup import close_logging, get_logger, install_secret_filter, setup_logging
from app.paths import LivecraftPaths, build_paths, ensure_dirs, resolve_root
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.value import SecretField
from app.sheets.client import SheetsReader, SheetsReadError, SheetsReadReason, SheetsTarget
from app.sheets.plan import SheetColumns, SheetPlan
from app.sheets.rows import PlanRow, RowSkipReason
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "tools.sheets_probe"
LOGGER = get_logger(LOGGER_NAME)
RELOGIN_FLAG: Final[str] = "--relogin"


class ProbeExit(IntEnum):
    OK = 0          # таблица прочитана и разобрана
    ERRORS = 1      # вход или Google не дали прочитать
    CONFIG = 2      # сейф или настройки не готовы — к Google не обращались


@dataclass(frozen=True)
class SheetsProbeReport:
    """Что показать человеку о прочитанном плане: колонки, счётчики, проблема. Ни одного значения ряда."""

    plan: SheetPlan
    rows: tuple[PlanRow, ...]

    @property
    def lines(self) -> tuple[str, ...]:
        problem: str | None = self.plan.problem
        columns: SheetColumns | None = self.plan.columns
        if problem is not None or columns is None:
            return (problem,) if problem is not None else ()
        return (self._columns_line(columns), self._rows_line, *self._skip_lines)

    def _columns_line(self, columns: SheetColumns) -> str:
        return msg.SHEETS_PROBE_COLUMNS.format(
            link=self._column(columns.link), date=self._column(columns.date), time=self._column(columns.time)
        )

    def _column(self, index: int) -> str:
        """Заголовок колонки и её номер в диапазоне (с 1): буквы листа без значения диапазона не восстановить."""
        return msg.SHEETS_PROBE_COLUMN.format(name=self.plan.header[index], number=index + 1)

    @property
    def _rows_line(self) -> str:
        admitted: int = sum(1 for row in self.rows if row.is_admitted)
        return msg.SHEETS_PROBE_ROWS.format(rows=len(self.rows), admitted=admitted, skipped=len(self.rows) - admitted)

    @property
    def _skip_lines(self) -> tuple[str, ...]:
        counts: Counter[RowSkipReason] = Counter(row.skip for row in self.rows if row.skip is not None)
        return tuple(
            msg.SHEETS_PROBE_SKIP_LINE.format(reason=reason.human, count=counts[reason])
            for reason in RowSkipReason
            if counts[reason]
        )


@dataclass(frozen=True)
class SheetsProbe:
    """Один прогон пробника на корне `paths`; `now` и вывод `say` — параметрами, в тестах свои.

    `relogin` — войти в браузере заново до чтения таблицы (ключ `--relogin`).
    """

    paths: LivecraftPaths
    now: datetime
    say: Callable[[str], None]
    relogin: bool = False

    def run(self) -> int:
        self.say(msg.SHEETS_PROBE_TITLE)
        try:
            loaded: VaultLoad = VaultStore.open(self.paths).load()
            settings: LivecraftSettings = load_settings(self.paths.config_file)
        except VaultFormatError as error:
            return self._refuse(msg.VAULT_FILE_BROKEN.format(error=error))
        except ConfigError as error:
            return self._refuse(str(error))
        install_secret_filter(loaded.vault)          # до первого обращения к Google (§7.4)
        if loaded.is_local_unreadable:
            self.say(msg.VAULT_LOCAL_UNREADABLE)
        try:
            SheetsTarget.from_vault(loaded.vault)
            plan: SheetPlan = self._read(loaded)
        except SheetsReadError as error:
            return self._fail(error)
        rows: tuple[PlanRow, ...] = plan.plan_rows(settings.zone, self.now.astimezone(settings.zone))
        for line in SheetsProbeReport(plan=plan, rows=rows).lines:
            self.say(line)
        return int(ProbeExit.OK)

    def _read(self, loaded: VaultLoad) -> SheetPlan:
        login: GoogleLogin = GoogleLogin.operator(self.paths)
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
            LOGGER.warning("sheets_probe_relogin_failed reason=%s detail=%s", error.reason.value, error.detail)
            raise SheetsReadError(
                SheetsReadReason.AUTH, SecretField.SHEETS_ID.log_label, detail=error.human
            ) from error

    def _announce_login(self) -> None:
        self.say(msg.SHEETS_PROBE_LOGIN)

    def _fail(self, error: SheetsReadError) -> int:
        """Не настроено — код 2 и совет про настройщик; прочее — код 1."""
        LOGGER.error("sheets_probe_failed %s", error.log_line)
        if error.reason is SheetsReadReason.NOT_CONFIGURED:
            return self._refuse(error.human)
        self.say(error.human)
        if error.reason is SheetsReadReason.NO_ACCESS:
            self.say(msg.SHEETS_PROBE_RELOGIN_HINT)
        return int(ProbeExit.ERRORS)

    def _refuse(self, text: str) -> int:
        self.say(text)
        self.say(msg.SETUP_REQUIRED)
        return int(ProbeExit.CONFIG)


def _say(text: str) -> None:
    print(text, flush=True)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(prog="python -m app.tools.sheets_probe")
    parser.add_argument(RELOGIN_FLAG, action="store_true", help=msg.SHEETS_PROBE_RELOGIN_HELP)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Точка входа пробника: ключи, корень, папки, логи; дальше — `SheetsProbe`."""
    relogin: bool = bool(_parse_args(argv).relogin)
    paths: LivecraftPaths = build_paths(resolve_root())
    ensure_dirs(paths)
    setup_logging(paths.logs_dir, debug=False)
    try:
        return SheetsProbe(paths=paths, now=datetime.now(timezone.utc), say=_say, relogin=relogin).run()
    finally:
        close_logging()


if __name__ == "__main__":
    sys.exit(main())
