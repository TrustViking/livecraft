"""Часть «Эфиры YouTube» отчёта запуска (CLAUDE.md §3 шаг 12, §5): итог эфиров и разделы уровнем «###».

Сначала итог и то, ради чего отчёт открывают (ключ не дошёл, два ключа, не допущено, ошибки, предупреждения,
расхождения), потом справка (создано, исправлено, совпало, сироты, пропуски, пакеты режима Б, особенности
площадки); --status — сбои каналов, эфиры программы на каналах и особенности площадки. Пустой раздел не печатается:
нули видны в итоге. Файл отчёта пишет запуск (app\\run\\run_report.py) — по всем частям, которые работали.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from app.observability.log_event import LogEvent
from app.output.event import OutputEvent
from app.output.report import ReportKind, RunReport
from app.output.result import ERROR_KINDS, KeyState, OutcomeKind
from app.output.result_text import ResultText
from app.output.run_exit import RunExit
from app.output.run_totals import RunTotals
from app.pipeline.memory import ReplacedBroadcast
from app.run.mode import RunPart
from app.run.report_section import PartReport, ReportSection
from app.ui.messages import msg


@dataclass(frozen=True)
class ReportText:
    """Отчёт эфиров как часть отчёта запуска."""

    report: RunReport

    def part(self, tail: tuple[str, ...]) -> PartReport:
        """Часть «Эфиры YouTube»: итог, файл ключей и строки `tail` (расход YouTube, повторная передача ключей), затем
        разделы; путь keys.txt — для подвала запуска."""
        report: RunReport = self.report
        keys: tuple[str, ...] = () if report.keys_file is None else (
            msg.REPORT_TOTAL_KEYS_FILE.format(path=report.keys_file),
        )
        sections: tuple[ReportSection, ...] = (
            self._status_sections if report.kind is ReportKind.STATUS else self._run_sections
        )
        body: tuple[str, ...] = (*report.summary_lines, *keys, *tail)
        return PartReport(RunPart.BROADCAST.human_label, body, sections, report.keys_file)

    @property
    def event(self) -> LogEvent:
        """Итог эфиров в лог: вид запуска, итоги, сбои, код выхода контура B и его причины."""
        run_exit: RunExit = self.report.exit
        event: LogEvent = LogEvent.of(OutputEvent.BROADCASTS_REPORT, kind=self.report.kind)
        event = event.extended(results=len(self.report.results), failures=len(self.report.failures))
        return event.extended(exit_code=run_exit.outcome.exit_code.value, reason=run_exit.log_reasons)

    @property
    def _run_sections(self) -> tuple[ReportSection, ...]:
        report: RunReport = self.report
        totals: RunTotals = report.totals
        errors: list[str] = [*self._texts(ERROR_KINDS), *(failure.text for failure in report.failures)]
        created: list[str] = [*self._texts({OutcomeKind.CREATED}), *self._texts({OutcomeKind.STREAM_ATTACHED})]
        matched_lead: str | None = msg.WARNING_KEPT_KEY if report.has_kept_keys else None
        two_keys: list[str] = self._two_keys
        return (
            ReportSection(msg.REPORT_SECTION_NOT_DELIVERED, self._not_delivered),
            ReportSection(msg.REPORT_SECTION_TWO_KEYS.format(count=len(two_keys)), two_keys),
            ReportSection(
                msg.REPORT_SECTION_NOT_ADMITTED.format(count=totals.not_admitted), self._texts({OutcomeKind.NOT_ADMITTED})
            ),
            ReportSection(msg.REPORT_SECTION_ERRORS, errors),
            ReportSection(msg.REPORT_SECTION_WARNINGS, report.warnings),
            ReportSection(msg.REPORT_SECTION_MISMATCHES, report.mismatches),
            ReportSection(msg.REPORT_SECTION_CREATED.format(count=totals.created), created),
            ReportSection(msg.REPORT_SECTION_FIXED.format(count=totals.fixed), self._texts({OutcomeKind.FIXED})),
            ReportSection(
                msg.REPORT_SECTION_MATCHED.format(count=totals.matched), self._texts({OutcomeKind.MATCHED}), matched_lead
            ),
            ReportSection(msg.REPORT_SECTION_ORPHANS.format(count=totals.orphans), report.orphans),
            ReportSection(msg.REPORT_SECTION_SKIPPED, [line.text for line in report.skipped.lines]),
            ReportSection(msg.REPORT_SECTION_PACKAGES, [line.text for line in report.packages.lines]),
            ReportSection(msg.REPORT_SECTION_NOTES, report.notes),
        )

    @property
    def _status_sections(self) -> tuple[ReportSection, ...]:
        """--status: сбои каналов, эфиры программы на каналах, особенности площадки."""
        report: RunReport = self.report
        return (
            ReportSection(msg.REPORT_SECTION_ERRORS, [failure.text for failure in report.failures]),
            ReportSection(
                msg.REPORT_SECTION_SCHEDULED.format(count=report.totals.matched), self._texts({OutcomeKind.MATCHED})
            ),
            ReportSection(msg.REPORT_SECTION_NOTES, report.notes),
        )

    def _texts(self, kinds: Collection[OutcomeKind]) -> list[str]:
        """Строки итогов этих видов в порядке итогов."""
        return [ResultText(result, self.report.is_dry_run).line for result in self.report.results if result.kind in kinds]

    @property
    def _not_delivered(self) -> list[str]:
        """Новый ключ, который форма не подтвердила: эфир стоит, а стример ключа не получил. Счётчики прежние."""
        return [ResultText(result).not_delivered for result in self.report.results if result.key_state is KeyState.FAILED]

    @property
    def _two_keys(self) -> list[str]:
        lines: list[str] = []
        for result in self.report.results:
            replaced: ReplacedBroadcast | None = result.replaced
            if replaced is not None:
                lines.append(ResultText(result).two_keys(replaced))
        return lines
