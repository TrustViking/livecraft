"""Отчёт запуска контура B (CLAUDE.md §3 шаг 12, §10): итоги эфиров, сбои, пропуски, предупреждения, расхождения.

Отчёт строится одним правилом из входов прогона (`ReportRequest` → `RunReport.of`); счётчики — один раз
(`RunTotals`), код выхода контура B — одно решение (`RunReport.exit`). Часть «Эфиры YouTube» отчёта запуска —
`ReportText`, консоль — `RunConsole`: у каждой поверхности свой читатель, числа у них общие.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from enum import Enum
from pathlib import Path

from app.config.channel import ChannelConfig
from app.config.settings import LivecraftSettings
from app.output.result import BroadcastResult
from app.output.run_exit import RunExit
from app.output.run_failure import RunFailure
from app.output.run_lines import FactsCheck, OrphanLine, RunNotes
from app.output.run_totals import RunTotals
from app.output.skipped import SkippedSlots
from app.packages.package_line import PackageLines
from app.paths import LivecraftPaths
from app.pipeline.orphan import MarkedScan, OrphanBroadcast
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.selection import Selection
from app.platforms.limits import PlatformLimits
from app.platforms.notice import PlatformNotice
from app.run.mode import RunMode
from app.run.request import RunRequest
from app.slots.slot import SlotEntry
from app.ui.messages import msg


class ReportKind(str, Enum):
    """Вид запуска для вывода: обычный, без действий (--dry-run), сверка эфиров программы (--status)."""

    FULL = "full"
    DRY_RUN = "dry_run"
    STATUS = "status"

    @classmethod
    def of(cls, request: RunRequest) -> ReportKind:
        if request.mode is RunMode.STATUS:
            return cls.STATUS
        return cls.DRY_RUN if request.dry_run else cls.FULL

    @property
    def summary_template(self) -> str:
        """Первая строка «Итога»: в dry-run — о намерениях, в --status — только что стоит и ошибки."""
        templates: dict[ReportKind, str] = {
            ReportKind.FULL: msg.SUMMARY_BROADCASTS,
            ReportKind.DRY_RUN: msg.SUMMARY_BROADCASTS_DRY_RUN,
            ReportKind.STATUS: msg.SUMMARY_BROADCASTS_STATUS,
        }
        return templates[self]


@dataclass(frozen=True)
class ReportRequest:
    """Входы прогона для отчёта. `selection` — объекты эфиров и слоты без канала (в --status пустой); `past_slots` —
    прошедшие слоты плана (режим Б); `packages` — строки пакетов полки bcast\\ (режим Б); `orphans` — сироты и
    перенесённые сверки; `scan` — эфиры с меткой программы (--status); `notices` — замечания площадки; `warnings` —
    строки предупреждений запуска (сверка каналов, память); `channels` — каналы запуска со значениями после фазы входов,
    в порядке channels.json; `keys_file` — итог записи keys.txt.
    """

    kind: ReportKind
    started: datetime
    selection: Selection
    settings: LivecraftSettings
    limits: PlatformLimits
    channels: tuple[ChannelConfig, ...]
    paths: LivecraftPaths
    past_slots: tuple[SlotEntry, ...] = ()
    packages: PackageLines = field(default_factory=PackageLines)
    orphans: tuple[OrphanBroadcast, ...] = ()
    scan: MarkedScan | None = None
    notices: tuple[PlatformNotice, ...] = ()
    warnings: tuple[str, ...] = ()
    keys_file: Path | RunFailure | None = None

    @property
    def results(self) -> tuple[BroadcastResult, ...]:
        """Итоги объектов эфиров (слоты внутри min_lead_minutes — в «Пропущено») и эфиров с меткой из --status."""
        is_dry_run: bool = self.kind is ReportKind.DRY_RUN
        planned: tuple[BroadcastResult, ...] = tuple(
            BroadcastResult.of_planned(item, is_dry_run=is_dry_run)
            for item in self.selection.planned
            if not item.is_too_late
        )
        marked: tuple[BroadcastResult, ...] = () if self.scan is None else tuple(
            BroadcastResult.of_marked(broadcast) for broadcast in self.scan.broadcasts
        )
        return planned + marked

    @property
    def failures(self) -> tuple[RunFailure, ...]:
        """Отказы каналов объектов, каналы, не ответившие в --status, и сбой записи keys.txt."""
        found: list[RunFailure] = list(RunFailure.channel_refusals(self.selection.planned))
        if self.scan is not None:
            found.extend(RunFailure.of_channel(failure.channel, failure.error) for failure in self.scan.failures)
        if isinstance(self.keys_file, RunFailure):
            found.append(self.keys_file)
        return tuple(found)

    @property
    def skipped(self) -> SkippedSlots:
        """Прошедшие — только языков каналов запуска."""
        languages: frozenset[str] = frozenset(language for channel in self.channels for language in channel.languages)
        minutes: int = self.settings.min_lead_minutes
        return SkippedSlots.of(self.selection, self.past_slots, languages, minutes)

    @property
    def keys_shown(self) -> str | None:
        """Путь keys.txt для людей; файл не записан или запуск его не пишет — None."""
        return self.paths.shown(self.keys_file) if isinstance(self.keys_file, Path) else None

    @property
    def notes(self) -> RunNotes:
        return RunNotes(self.selection.planned, self.notices, self.warnings, self.paths)


@dataclass(frozen=True)
class RunReport:
    """Отчёт запуска. `orphans`, `warnings`, `notes` (особенности площадки) и `mismatches` — готовые строки;
    `keys_file` — путь keys.txt для людей; `has_kept_keys` — ключ совпавшего эфира форма подтверждала раньше и
    повторно он не отправлялся; `channel_order` — ключи каналов в порядке channels.json; `packages` — строки пакетов
    (режим Б).
    """

    kind: ReportKind
    started: datetime
    results: tuple[BroadcastResult, ...] = ()
    failures: tuple[RunFailure, ...] = ()
    orphans: tuple[str, ...] = ()
    skipped: SkippedSlots = field(default_factory=SkippedSlots)
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    mismatches: tuple[str, ...] = ()
    keys_file: str | None = None
    has_kept_keys: bool = False
    channel_order: tuple[str, ...] = ()
    packages: PackageLines = field(default_factory=PackageLines)

    @classmethod
    def of(cls, request: ReportRequest) -> RunReport:
        zone: tzinfo = request.settings.zone
        notes: RunNotes = request.notes
        planned: tuple[PlannedBroadcast, ...] = request.selection.planned
        return cls(
            kind=request.kind,
            started=request.started,
            results=request.results,
            failures=request.failures,
            orphans=tuple(OrphanLine(orphan, zone).text for orphan in request.orphans),
            skipped=request.skipped,
            warnings=notes.run_warnings,
            notes=notes.platform_notes,
            mismatches=tuple(line for item in planned for line in FactsCheck(item, request.limits, zone).lines),
            keys_file=request.keys_shown,
            has_kept_keys=any(item.has_kept_key for item in planned),
            channel_order=tuple(channel.key for channel in request.channels),
            packages=request.packages,
        )

    @property
    def totals(self) -> RunTotals:
        counted: RunTotals = RunTotals.count(
            self.results, len(self.failures), len(self.orphans), len(self.skipped.lines)
        )
        return counted.with_packages(len(self.packages.unreadable))

    @property
    def exit(self) -> RunExit:
        """Единственное правило кода выхода контура B."""
        return RunExit.of(self.totals)

    @property
    def is_dry_run(self) -> bool:
        return self.kind is ReportKind.DRY_RUN

    @property
    def summary_lines(self) -> tuple[str, ...]:
        """«Итог» — одинаково в консоли и отчёте: эфиры, слоты вне работы и код выхода, если есть причины."""
        totals: RunTotals = self.totals
        broadcasts: str = self.kind.summary_template.format(
            total=totals.broadcasts,
            created=totals.created,
            fixed=totals.fixed,
            matched=totals.matched,
            not_admitted=totals.not_admitted,
            errors=totals.errors,
        )
        lines: tuple[str | None, ...] = (broadcasts, self.skipped.summary_line, self.exit.line)
        return tuple(line for line in lines if line is not None)
