"""Часть «эфиры» одного запуска (CLAUDE.md §3 шаги 7–12, §10; §14 решения 18, 32) и сверка --status.

Слоты части — `BroadcastSlots`: в режиме А — слоты прогона таблицы для YouTube с формой настроек (слот «по номерам» на
YouTube не идёт), в режиме Б — будущие слоты полки bcast\\ с формой своего пакета, прошедшие слоты и строки пакетов.
Нет слотов для YouTube — к YouTube не обращаемся. Иначе: проверка каналов без браузера → прогон
(app\\broadcasts\\run.py) → «Запись отчёта» → чистка памяти (полный запуск) → итог эфиров в лог. --status — без слотов:
проверка без браузера, входы всех каналов, эфиры с меткой программы, keys.txt и итог (app\\broadcasts\\status.py).
Память открывается на прогон — в --dry-run и --status только на чтение — и закрывается всегда, в том числе при обрыве и
падении. После итога полного запуска с включённой повторной передачей ключей — `KeyResend` (§14 решение 36): все ключи
дошли — переключатель выключается. Код части — единственное правило кода контура B (`RunReport.exit`), плюс ошибка
записи переключателя; консоль — `RunConsole`, строка расхода YouTube и строка повторной передачи. Часть отчёта
запуска — `part_report` (`ReportText`); файл отчёта и подвал путей пишет запуск (app\\run\\run_report.py).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.broadcasts.key_resend import KeyResend, KeysResent
from app.broadcasts.record_keeper import RecordKeeper
from app.broadcasts.run import BroadcastRun, BroadcastSlots
from app.broadcasts.services import BroadcastServices
from app.broadcasts.status import StatusRun
from app.config.channel import ConfiguredChannels
from app.config.files import SettingsFile
from app.observability.log_event import LogArea, get_logger
from app.output.console import RunConsole
from app.output.report import ReportKind, RunReport
from app.output.report_text import ReportText
from app.paths import FileName
from app.records.record_store import RecordStore
from app.run.exit_code import RunOutcome
from app.run.mode import RunPart
from app.run.report_section import PartReport
from app.run.request import RunRequest
from app.ui.messages import msg

LOGGER = get_logger(LogArea.BROADCASTS)

ReportMaker = Callable[[RecordKeeper, ConfiguredChannels], RunReport]


@dataclass(frozen=True)
class BroadcastPartResult:
    """Итог части: отчёт (нет слотов для YouTube — None), строка расхода YouTube и итог повторной передачи ключей
    (None — её не было)."""

    report: RunReport | None = None
    usage_line: str | None = None
    resend: KeysResent | None = None

    @property
    def outcome(self) -> RunOutcome:
        """Исход по отчёту; переключатель повторной передачи не выключился — ошибка части."""
        outcome: RunOutcome = RunOutcome.DONE if self.report is None else self.report.exit.outcome
        failed: bool = self.resend is not None and self.resend.has_errors
        return RunOutcome.FAILED if failed and outcome is RunOutcome.DONE else outcome

    @property
    def console_lines(self) -> tuple[str, ...]:
        """После строк по ходу работы — пустая строка, «Итог», блоки, расход YouTube и повторная передача ключей."""
        if self.report is None:
            return (msg.BROADCASTS_NO_SLOTS,)
        return ("", *RunConsole(self.report).lines, *self._tail)

    @property
    def part_report(self) -> PartReport:
        """Часть «Эфиры YouTube» отчёта запуска: итог, файл ключей, расход и повторная передача, затем разделы."""
        if self.report is None:
            return PartReport(RunPart.BROADCAST.human_label, (msg.BROADCASTS_NO_SLOTS,))
        return ReportText(self.report).part(self._tail)

    @property
    def _tail(self) -> tuple[str, ...]:
        usage: tuple[str, ...] = () if self.usage_line is None else (self.usage_line,)
        resend: tuple[str, ...] = () if self.resend is None else (self.resend.line,)
        return (*usage, *resend)


@dataclass(frozen=True)
class BroadcastStage:
    """Зависимости запуска, прочитанные каналы, запрос запуска и его начало (штамп итога, тот же, что у лога)."""

    services: BroadcastServices
    channels: ConfiguredChannels
    request: RunRequest
    started: datetime

    def run(self, slots: BroadcastSlots, to_form: bool) -> BroadcastPartResult:
        """Эфиры по слотам для YouTube; прочие слоты плана — известные для сверки; ключи в форму — если идёт их линия
        (`to_form`, §14 решение 37)."""
        if not slots.slots:
            return BroadcastPartResult()
        kind: ReportKind = ReportKind.of(self.request)

        def report(keeper: RecordKeeper, channels: ConfiguredChannels) -> RunReport:
            return BroadcastRun(self.services, keeper, channels, kind, self.started, to_form).run(slots)

        return self._reported(kind, report)

    def status(self) -> BroadcastPartResult:
        """--status: эфиры с меткой программы на всех каналах и keys.txt; память — только на чтение."""

        def report(keeper: RecordKeeper, channels: ConfiguredChannels) -> RunReport:
            return StatusRun(self.services, keeper, channels, self.started).run()

        return self._reported(ReportKind.STATUS, report)

    def _reported(self, kind: ReportKind, make: ReportMaker) -> BroadcastPartResult:
        """Проверка каналов без браузера → отчёт прогона → «Запись отчёта» → чистка памяти (полный запуск) → итог в
        лог → повторная передача ключей (полный запуск); память закрывается всегда."""
        channels: ConfiguredChannels = self.services.book.check_without_login(self.channels)
        path: Path = self.services.paths.file(FileName.RECORDS)
        store: RecordStore = RecordStore.open(path, kind is not ReportKind.FULL, self.services.clock)
        try:
            keeper: RecordKeeper = RecordKeeper(store, self.services.clock)
            report: RunReport = make(keeper, channels)
            self.services.progress.report_started()
            if kind is ReportKind.FULL:
                keeper.clean(self.services.settings.keep_days)
        finally:
            store.close()
        ReportText(report).event.emit(LOGGER)
        resend: KeyResend = KeyResend(SettingsFile.of(self.services.paths), self.services.settings.broadcasts)
        return BroadcastPartResult(report, self.services.usage.line, resend.after(report))
