"""Коды выхода и исход части запуска (CLAUDE.md §10).

Часть запуска — прогон таблицы, готовность режима, окно настройщика — говорит исходом (`RunOutcome`), а не числом:
числа кодов знает только этот модуль. Код всего запуска — самый важный из кодов его частей (`ExitCode.combined`):
ошибка конфигурации важнее «нет будущих слотов», «нет будущих слотов» — важнее ошибок, ошибки — важнее «всё сделано».
"""
from __future__ import annotations

from enum import Enum, IntEnum
from typing import Final


class ExitCode(IntEnum):
    """Коды выхода (CLAUDE.md §10)."""

    OK = 0                 # сделано всё, что можно
    ERRORS = 1             # есть ошибки
    CONFIG = 2             # ошибка конфигурации, сейфа или авторизации — ничего не делалось
    NO_FUTURE_SLOTS = 3    # нет будущих слотов — к каналам не обращались

    @property
    def weight(self) -> int:
        """Важность кода при сведении: чем больше, тем важнее."""
        return EXIT_CODE_IMPORTANCE.index(self)

    def combined(self, other: ExitCode) -> ExitCode:
        """Общий код двух итогов одного запуска — более важный из двух."""
        return other if other.weight > self.weight else self


# Коды по возрастанию важности: всё сделано < ошибки < нет будущих слотов < конфигурация.
EXIT_CODE_IMPORTANCE: Final[tuple[ExitCode, ...]] = (
    ExitCode.OK,
    ExitCode.ERRORS,
    ExitCode.NO_FUTURE_SLOTS,
    ExitCode.CONFIG,
)


class RunOutcome(str, Enum):
    """Чем кончилась часть запуска. Значение — идентификатор для лога."""

    DONE = "done"                          # сделано всё, что можно
    FAILED = "failed"                      # есть ошибки
    NOT_CONFIGURED = "not_configured"      # не хватает настройки, сейфа или входа — ничего не делалось
    NOTHING_PLANNED = "nothing_planned"    # будущих слотов нет — делать нечего

    @property
    def exit_code(self) -> ExitCode:
        return OUTCOME_EXIT_CODES[self]


OUTCOME_EXIT_CODES: Final[dict[RunOutcome, ExitCode]] = {
    RunOutcome.DONE: ExitCode.OK,
    RunOutcome.FAILED: ExitCode.ERRORS,
    RunOutcome.NOT_CONFIGURED: ExitCode.CONFIG,
    RunOutcome.NOTHING_PLANNED: ExitCode.NO_FUTURE_SLOTS,
}
