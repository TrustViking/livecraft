"""Отчёт замка: по строке на правило — сейчас, в реестре, исключений, цель (REFACTORING_STANDARD.md §6).

«Сейчас» — всё, что правило находит в коде, вместе с исключениями; «в реестре» — долги, «исключений» —
постоянные исключения. Под строкой правила с признаками — разбивка по признакам.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.tools.code_standard.exemptions import Exceptions
from app.tools.code_standard.ledger import Ledger, LedgerDiff
from app.tools.code_standard.measurement import Measurement, Measurements
from app.tools.code_standard.rule import Rule
from app.ui import messages_ru as msg


class ReportColumn(str, Enum):
    """Колонки строки отчёта: имена полей шаблона `CODE_STANDARD_REPORT_ROW` и ключи его заголовков."""

    RULE = "rule"
    LABEL = "label"
    NOW = "now"
    LEDGER = "ledger"
    EXEMPT = "exempt"
    GOAL = "goal"


@dataclass(frozen=True)
class StandardReport:
    """Замеры кода (с исключениями), исключения и реестр; реестра может не быть."""

    measurements: Measurements
    exceptions: Exceptions
    ledger: Ledger | None

    def lines(self) -> tuple[str, ...]:
        header: str = msg.CODE_STANDARD_REPORT_ROW.format(**msg.CODE_STANDARD_REPORT_COLUMNS)
        rows: list[str] = [msg.CODE_STANDARD_REPORT_TITLE, header]
        for rule in self.measurements.rules:
            rows.extend(self._rule_lines(self.measurements.of(rule)))
        rows.append(self._not_measured())
        rows.extend(self._state_lines())
        rows.extend(self.exceptions.problems(self.measurements))
        return tuple(rows)

    @property
    def debts(self) -> Ledger:
        """Долги кода: замеры без постоянных исключений."""
        return Ledger.of(self.measurements.without(self.exceptions.keys))

    def _rule_lines(self, measurement: Measurement) -> tuple[str, ...]:
        rule: Rule = measurement.rule
        registered: object = len(self.ledger.section(rule)) if self.ledger is not None else msg.CODE_STANDARD_REPORT_NO_VALUE
        row: str = msg.CODE_STANDARD_REPORT_ROW.format(**{
            ReportColumn.RULE.value: rule.value,
            ReportColumn.LABEL.value: rule.label,
            ReportColumn.NOW.value: measurement.count,
            ReportColumn.LEDGER.value: registered,
            ReportColumn.EXEMPT.value: self.exceptions.count(rule),
            ReportColumn.GOAL.value: 0,
        })
        signs: str = msg.CODE_STANDARD_REPORT_SIGN_JOINER.join(
            msg.CODE_STANDARD_REPORT_SIGN.format(label=sign.label, count=count)
            for sign, count in measurement.sign_counts().items()
        )
        return (row, msg.CODE_STANDARD_REPORT_SIGNS.format(signs=signs)) if signs else (row,)

    def _not_measured(self) -> str:
        waiting: list[str] = [rule.value for rule in Rule if rule not in self.measurements.rules]
        return msg.CODE_STANDARD_REPORT_NOT_MEASURED.format(rules=msg.CODE_STANDARD_REPORT_RULE_JOINER.join(waiting))

    def _state_lines(self) -> tuple[str, ...]:
        """Разница реестра и кода: итог и по строке на изменение."""
        if self.ledger is None:
            return (msg.CODE_STANDARD_REPORT_NO_LEDGER,)
        diff: LedgerDiff = self.ledger.diff(self.debts)
        total: str = msg.CODE_STANDARD_REPORT_STATE.format(
            new=len(diff.new), grown=len(diff.grown), shrunk=len(diff.shrunk), gone=len(diff.gone)
        )
        return (total,) + tuple(change.line for change in diff.changes)
