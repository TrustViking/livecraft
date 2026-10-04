"""Вывод запуска от слотов любого входа: превью, пакет, документ объявлений, объявления в Telegram (CLAUDE.md §3 шаги
2.4, 2.6, 6a; §14 решения 13, 14, 33, 50, 51).

Один путь для обоих входов: слоты запуска с формой каждого (`RunSlots`) → части, которые идут в запуске, по порядку.
Превью — только от входа «Пакеты»: у входа «Таблица» их уже сделал прогон таблицы (копии идут по видео и нужны записи в
таблицу), и сюда приходит его итог. Пакет — по пакету на форму из слотов для YouTube (от таблицы — только с нейросетью:
иначе линия не идёт, решение 50); в пробном запуске он тоже пишется. Документ и объявления — по дням (`PublishDay.days`:
дата и форма), обложки документа — копии превью на Диске этого запуска (`PreviewResult.covers`), в Telegram после дней
уходят все записанные пакеты. Строки каждой части — сразу в консоль и её часть — в отчёт запуска (`RunJournal`); пока
часть идёт, её долгие шаги (копии на Диск, документы, объявления, пакет в Telegram) говорят строкой хода в ту же
консоль (app\\run\\progress.py). Код — важнейший из исходов частей. Сбой записи пакета на диск (OSError) — ошибка программы, её ловит запуск.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.intake.preview_stage import PreviewCopies, PreviewMode, PreviewResult, PreviewStage
from app.packages.package import PackageResult
from app.packages.run_slots import RunSlots
from app.paths import LivecraftPaths
from app.publish.announce_stage import AnnounceResult, AnnounceStage
from app.publish.day import PublishDay
from app.publish.doc_stage import DocResult, DocStage
from app.run.exit_code import ExitCode, RunOutcome
from app.run.line_plan import RunScope
from app.run.mode import RunPart
from app.run.progress import StageProgress
from app.run.report_section import PartReport
from app.run.run_report import RunJournal
from app.secretsafe.vault import Vault
from app.ui.messages import msg


@dataclass(frozen=True)
class PackageOutput:
    """Итог части «пакет»: записанные пакеты или почему они не записаны; слотов для YouTube нет — ни одного итога."""

    results: tuple[PackageResult, ...]

    @property
    def has_errors(self) -> bool:
        """Незаписанный пакет — ошибка запуска (§10)."""
        return any(result.has_errors for result in self.results)

    @property
    def console_lines(self) -> tuple[str, ...]:
        """По строке на пакет; слотов для YouTube нет — строка об этом: пакет не записан."""
        return tuple(result.console_line for result in self.results) or (msg.PACKAGE_NO_YOUTUBE_SLOTS,)

    @property
    def part_report(self) -> PartReport:
        return PartReport(RunPart.PACKAGE.human_label, self.console_lines)


@dataclass(frozen=True)
class RunOutput:
    """Вывод одного запуска: пути, настройки, сейф (папка Диска, бот), что идёт в запуске, журнал запуска и источник id
    пакетов (новый на каждый пакет)."""

    paths: LivecraftPaths
    settings: LivecraftSettings
    vault: Vault
    scope: RunScope
    journal: RunJournal
    new_id: Callable[[], str] = lambda: uuid4().hex

    def run(self, slots: RunSlots, previews: PreviewResult | None) -> ExitCode:
        """Превью (вход «Пакеты»), пакет, документ, Telegram — те части, что идут; `previews` — итог превью прогона
        таблицы (вход «Таблица»)."""
        if self.scope.runs(RunPart.PACKAGES_IN):
            previews = self._previews(slots)
        packages: PackageOutput = self._packages(slots)
        code: ExitCode = self._code(previews is not None and previews.has_errors).combined(
            self._code(packages.has_errors)
        )
        days: tuple[PublishDay, ...] = PublishDay.days(slots.items)
        doc: DocResult | None = None
        if self.scope.runs(RunPart.DOC):
            docs: DocStage = DocStage.of(self.paths, self.settings, self.vault, self.scope)
            doc = docs.run(days, self._covers(previews), self.progress)
            self.journal.part(doc.console_lines, doc.part_report)
            code = code.combined(doc.outcome.exit_code)
        if not self.scope.runs(RunPart.ANNOUNCE):
            return code
        stage: AnnounceStage = AnnounceStage.of(self.paths, self.settings, self.vault, self.scope.dry_run)
        announce: AnnounceResult = stage.run(days, doc, packages.results, self.progress)
        self.journal.part(announce.console_lines, announce.part_report)
        return code.combined(announce.outcome.exit_code)

    @property
    def progress(self) -> StageProgress:
        """Строки хода долгих шагов — на консоль журнала запуска: туда же, куда идут строки частей; в отчёт — нет."""
        return StageProgress(self.journal.console)

    def _previews(self, slots: RunSlots) -> PreviewResult | None:
        """Копии превью слотов пакетов — по линиям превью, которые идут; ни одна не идёт — None."""
        mode: PreviewMode | None = PreviewMode.of(self.scope)
        if mode is None:
            return None
        result: PreviewResult = PreviewStage.of(self.paths, self.settings, self.vault, mode).run(
            PreviewCopies.of_slots(slots.slots), self.progress
        )
        self.journal.part(result.console_lines, PartReport(msg.REPORT_PART_PREVIEWS, result.console_lines))
        return result

    def _packages(self, slots: RunSlots) -> PackageOutput:
        """Пакеты — по пакету на форму из слотов для YouTube, когда идёт линия «Пакет»; иначе ни одного."""
        if not self.scope.runs(RunPart.PACKAGE):
            return PackageOutput(())
        now: datetime = Clock(self.settings.zone).now()
        output: PackageOutput = PackageOutput(
            tuple(package.write(self.paths.bcast_dir) for package in slots.packages(self.settings, now, self.new_id))
        )
        self.journal.part(output.console_lines, output.part_report)
        return output

    def _covers(self, previews: PreviewResult | None) -> dict[str, str]:
        return {} if previews is None else previews.covers

    def _code(self, has_errors: bool) -> ExitCode:
        return (RunOutcome.FAILED if has_errors else RunOutcome.DONE).exit_code
