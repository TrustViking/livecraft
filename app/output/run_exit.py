"""Код выхода контура B и его причины — одно решение для консоли, отчёта и лога (CLAUDE.md §10).

Код 1 (`RunOutcome.FAILED`): ошибки по эфирам (ERROR, AMBIGUOUS, NO_STREAM), сбои без слота (канал, файл программы),
ключ, который должен был дойти до стримера и не дошёл, непрочитанный пакет bcast\\ (режим Б). Не допущенный объект —
не ошибка: на площадке по нему ничего не сделано, ключ стример не ждёт; не подтверждённый канал даёт код 1 своим сбоем,
а не своими объектами.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.output.run_totals import RunTotals
from app.run.exit_code import RunOutcome
from app.ui.messages import msg

REASON_LOG_TEMPLATE: Final[str] = "{kind}:{count}"   # причина в строке лога run_report


class ExitReasonKind(str, Enum):
    """Почему код выхода 1; значения — идентификаторы строки лога и ключи EXIT_REASON_TEXT."""

    ERRORS = "errors"                    # ошибки по эфирам
    FAILURES = "failures"                # сбой канала или файла программы (без слота)
    KEY_UNDELIVERED = "key_undelivered"  # ключ должен был уйти в форму и не ушёл
    PACKAGES = "packages"                # пакет не прочитан


@dataclass(frozen=True)
class ExitReason:
    kind: ExitReasonKind
    count: int

    @property
    def text(self) -> str:
        return msg.EXIT_REASON_TEXT[self.kind.value].format(count=self.count)

    @property
    def log_text(self) -> str:
        return REASON_LOG_TEMPLATE.format(kind=self.kind.value, count=self.count)


@dataclass(frozen=True)
class RunExit:
    """Причины кода выхода; нет причин — сделано всё, что можно."""

    reasons: tuple[ExitReason, ...] = ()

    @classmethod
    def of(cls, totals: RunTotals) -> RunExit:
        counts: dict[ExitReasonKind, int] = {
            ExitReasonKind.ERRORS: totals.errors,
            ExitReasonKind.FAILURES: totals.failures,
            ExitReasonKind.KEY_UNDELIVERED: totals.undelivered,
            ExitReasonKind.PACKAGES: totals.unreadable_packages,
        }
        return cls(tuple(ExitReason(kind, count) for kind, count in counts.items() if count > 0))

    @property
    def outcome(self) -> RunOutcome:
        return RunOutcome.FAILED if self.reasons else RunOutcome.DONE

    @property
    def log_reasons(self) -> tuple[str, ...]:
        return tuple(reason.log_text for reason in self.reasons)

    @property
    def line(self) -> str | None:
        """Строка «Код выхода …» — только при причинах: при коде 0 сказать нечего."""
        if not self.reasons:
            return None
        reasons: str = msg.LIST_JOINER.join(reason.text for reason in self.reasons)
        return msg.SUMMARY_EXIT_FAILED.format(code=self.outcome.exit_code.value, reasons=reasons)
