"""Прогон контура A одного запуска режима А (CLAUDE.md §3 шаги 2.3–2.6, §4, §10).

Таблица плана → ряды → источники (yt-dlp, язык, обложки) → слоты → пакет plan_*.bcast в bcast\\.
Каждый шаг делает свой объект (`SheetsReader`, `SheetPlan`, `SourceCatalog`, `SlotBuilder`, `SlotPackage`);
`PlanIntake` только ведёт их по порядку, выбирает тексты слотов и останавливается там, где дальше идти не с чем.
Итог — `IntakeResult`: что получилось на каждом шаге, где остановился прогон, исход (`RunOutcome`) и строки для
оператора. Код выхода по исходу решает app\\run.

Нейросети в прогоне пока нет: тексты слотов — из источников (`SlotGroup.source_texts`, этап 3.15 подключит merge).
Сбой чтения таблицы — не исключение наружу, а итог с причиной. Сбой записи пакета на диск (OSError) — ошибка
программы, её ловит запуск.

В строках консоли нет ни значений сейфа, ни ссылки на форму, ни названий и описаний видео (§7.4): только
счётчики и причины человеческим текстом.
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.config.loader import LivecraftSettings
from app.core.dates import require_aware
from app.google.auth import GoogleLogin
from app.intake.builder import SlotBuild, SlotBuilder, SlotGroup
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.packages.package import PackageResult, SlotPackage
from app.paths import LivecraftPaths
from app.run.exit_code import RunOutcome
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReader, SheetsReadError
from app.sheets.plan import SheetPlan
from app.sheets.rows import PlanRow, RowSkipReason
from app.slots.texts import SlotTexts
from app.sources.video import SourceCatalog, SourceTally, SourceVideo
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.INTAKE)


class IntakeStage(str, Enum):
    """Шаг, на котором прогон остановился. Значение — идентификатор для лога."""

    TABLE = "table"        # таблица не прочиталась, шапка не распознана или будущих рядов нет
    SOURCES = "sources"    # годных источников нет
    SLOTS = "slots"        # годных слотов нет
    PACKAGE = "package"    # пакет не записан


class IntakeEvent(str, Enum):
    """События прогона контура A в логе."""

    TABLE_FAILED = "intake_table_failed"
    FINISHED = "intake_finished"


@dataclass(frozen=True)
class IntakeRequest:
    """Всё, что нужно прогону: корень, настройки, сейф, «сейчас» (со смещением) и id пакета."""

    paths: LivecraftPaths
    settings: LivecraftSettings
    vault: Vault
    now: datetime
    package_id: str

    def __post_init__(self) -> None:
        require_aware(self.now)


@dataclass(frozen=True)
class RowTally:
    """Итог разбора рядов таблицы: сколько прочитано, допущено и отсеяно по причинам (порядок — порядок проверок)."""

    rows: tuple[PlanRow, ...]

    @property
    def admitted(self) -> int:
        return sum(1 for row in self.rows if row.is_admitted)

    @property
    def skipped(self) -> Counter[RowSkipReason]:
        counts: Counter[RowSkipReason] = Counter(row.skip for row in self.rows if row.skip is not None)
        return Counter({reason: counts[reason] for reason in RowSkipReason if counts[reason]})

    @property
    def console_line(self) -> str:
        skipped: Counter[RowSkipReason] = self.skipped
        reasons: str = ""
        if skipped:
            items: str = msg.ITEM_JOINER.join(
                msg.INTAKE_COUNT_ITEM.format(name=reason.human, count=count) for reason, count in skipped.items()
            )
            reasons = msg.INTAKE_TABLE_REASONS.format(items=items)
        return msg.INTAKE_TABLE_LINE.format(
            rows=len(self.rows), admitted=self.admitted, skipped=sum(skipped.values()), reasons=reasons
        )


@dataclass(frozen=True)
class IntakeResult:
    """Итог прогона: ряды, источники, слоты, пакет и причина остановки — и правила исхода и строк."""

    rows: tuple[PlanRow, ...]
    videos: tuple[SourceVideo, ...]
    build: SlotBuild | None
    package: PackageResult | None
    sheets_error: SheetsReadError | None
    plan_problem: str | None
    stopped_at: IntakeStage | None

    @classmethod
    def table_failed(cls, error: SheetsReadError) -> IntakeResult:
        return cls(
            rows=(), videos=(), build=None, package=None, sheets_error=error, plan_problem=None,
            stopped_at=IntakeStage.TABLE,
        )

    @classmethod
    def plan_failed(cls, problem: str) -> IntakeResult:
        return cls(
            rows=(), videos=(), build=None, package=None, sheets_error=None, plan_problem=problem,
            stopped_at=IntakeStage.TABLE,
        )

    @classmethod
    def stopped(
        cls,
        rows: tuple[PlanRow, ...],
        stage: IntakeStage,
        videos: tuple[SourceVideo, ...] = (),
        build: SlotBuild | None = None,
    ) -> IntakeResult:
        """Прогон остановился после разбора рядов: дальше идти не с чем, пакета нет."""
        return cls(
            rows=rows, videos=videos, build=build, package=None, sheets_error=None, plan_problem=None,
            stopped_at=stage,
        )

    @property
    def has_future_rows(self) -> bool:
        return RowTally(self.rows).admitted > 0

    @property
    def has_errors(self) -> bool:
        """Отказ источника, слот с проблемой или незаписанный пакет — ошибка запуска (§10)."""
        if SourceTally(self.videos).failures:
            return True
        if self.build is not None and self.build.refused:
            return True
        return self.package is not None and not self.package.is_written

    @property
    def outcome(self) -> RunOutcome:
        """Исход по §10: сбой таблицы по настройке или входу — не настроено, прочий сбой и шапка — ошибка; будущих
        рядов нет — нечего делать; ошибки источников, слотов и пакета — ошибка; слотов нет без отказов — нечего делать.
        """
        if self.sheets_error is not None:
            return RunOutcome.NOT_CONFIGURED if self.sheets_error.reason.is_configuration else RunOutcome.FAILED
        if self.plan_problem is not None:
            return RunOutcome.FAILED
        if not self.has_future_rows:
            return RunOutcome.NOTHING_PLANNED
        if self.has_errors:
            return RunOutcome.FAILED
        if self.build is None or not self.build.slots:
            return RunOutcome.NOTHING_PLANNED
        return RunOutcome.DONE

    @property
    def console_lines(self) -> tuple[str, ...]:
        """По строке на пройденный шаг; на остановке — строка о том, почему дальше не пошли."""
        if self.sheets_error is not None:
            return (self.sheets_error.human,)
        if self.plan_problem is not None:
            return (self.plan_problem,)
        lines: list[str] = [RowTally(self.rows).console_line]
        if not self.has_future_rows:
            return (*lines, msg.INTAKE_NO_FUTURE_ROWS)
        lines.append(self._sources_line)
        if self.build is not None:
            lines.append(self._slots_line(self.build))
        if self.package is not None:
            lines.append(self.package.console_line)
        elif self.stopped_at in (IntakeStage.SOURCES, IntakeStage.SLOTS):
            lines.append(msg.INTAKE_NO_SLOTS)
        return tuple(lines)

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Счётчики, причина остановки и исход; без значений сейфа, ссылки формы и текстов видео."""
        return dict(
            stopped_at=self.stopped_at,
            sheets_error=None if self.sheets_error is None else self.sheets_error.reason,
            plan_problem=self.plan_problem is not None,
            rows=len(self.rows),
            admitted=RowTally(self.rows).admitted,
            sources=len(self.videos),
            ready=SourceTally(self.videos).ready,
            slots=None if self.build is None else len(self.build.slots),
            refused=None if self.build is None else len(self.build.refused),
            package=None if self.package is None else self.package.log_line,
            outcome=self.outcome,
        )

    @property
    def _sources_line(self) -> str:
        tally: SourceTally = SourceTally(self.videos)
        failures: str = ""
        if tally.failures:
            items: str = msg.ITEM_JOINER.join(
                msg.INTAKE_COUNT_ITEM.format(name=reason.human, count=count)
                for reason, count in tally.failures.items()
            )
            failures = msg.INTAKE_SOURCES_FAILURES.format(items=items)
        return msg.INTAKE_SOURCES_LINE.format(
            ready=tally.ready, total=len(self.videos), no_preview=tally.no_preview, failures=failures
        )

    def _slots_line(self, build: SlotBuild) -> str:
        languages: str = ""
        if build.languages:
            items: str = msg.LIST_JOINER.join(
                msg.INTAKE_COUNT_ITEM.format(name=code, count=count) for code, count in build.languages.items()
            )
            languages = msg.INTAKE_SLOTS_LANGUAGES.format(items=items)
        refused: str = msg.INTAKE_SLOTS_REFUSED.format(count=len(build.refused)) if build.refused else ""
        return msg.INTAKE_SLOTS_LINE.format(count=len(build.slots), languages=languages, refused=refused)


@dataclass(frozen=True)
class PlanIntake:
    """Прогон контура A: зависимости — полями, в тестах свои (читатель таблицы, источники, сборщик слотов)."""

    request: IntakeRequest
    reader_factory: Callable[[], SheetsReader]
    catalog: SourceCatalog
    builder: SlotBuilder

    @classmethod
    def of(cls, request: IntakeRequest, on_login: Callable[[], None] | None = None) -> PlanIntake:
        """Боевые зависимости: вход оператора и Sheets, yt-dlp корня, сборщик в зоне программы.

        Читатель открывается только в `run`: вход в Google (а с ним, может быть, браузер) — часть прогона.
        """
        login: GoogleLogin = GoogleLogin.operator(request.paths)
        return cls(
            request=request,
            reader_factory=lambda: SheetsReader.open(login, allow_login=True, on_login=on_login),
            catalog=SourceCatalog.from_paths(request.paths),
            builder=SlotBuilder(request.settings.zone),
        )

    def run(self) -> IntakeResult:
        """Таблица → ряды → источники → слоты → пакет; остановка там, где дальше идти не с чем."""
        try:
            plan: SheetPlan = self.reader_factory().read_plan(self.request.vault)
        except SheetsReadError as error:
            return self._finish(IntakeResult.table_failed(error))
        if plan.problem is not None:
            return self._finish(IntakeResult.plan_failed(plan.problem))
        rows: tuple[PlanRow, ...] = plan.plan_rows(self.request.settings.zone, self.request.now)
        if not RowTally(rows).admitted:
            return self._finish(IntakeResult.stopped(rows, IntakeStage.TABLE))
        videos: tuple[SourceVideo, ...] = self.catalog.prepare(rows)
        if not SourceTally(videos).ready:
            return self._finish(IntakeResult.stopped(rows, IntakeStage.SOURCES, videos))
        build: SlotBuild = SlotBuild.of([group.slot(self._texts(group)) for group in self.builder.groups(videos)])
        if not build.slots:
            return self._finish(IntakeResult.stopped(rows, IntakeStage.SLOTS, videos, build))
        package: PackageResult = self._package(build).write(self.request.paths.bcast_dir)
        stopped_at: IntakeStage | None = None if package.is_written else IntakeStage.PACKAGE
        return self._finish(
            IntakeResult(
                rows=rows, videos=videos, build=build, package=package, sheets_error=None, plan_problem=None,
                stopped_at=stopped_at,
            )
        )

    def _texts(self, group: SlotGroup) -> SlotTexts:
        """Окончательные тексты слота. Нейросети в прогоне пока нет: тексты источников по правилам YouTube."""
        return group.source_texts

    def _package(self, build: SlotBuild) -> SlotPackage:
        return SlotPackage.of(build.slots, self.request.settings, self.request.now, self.request.package_id)

    def _finish(self, result: IntakeResult) -> IntakeResult:
        """Итог — строкой в лог; сбой таблицы — её ярлыком, причиной и кодом ответа."""
        error: SheetsReadError | None = result.sheets_error
        if error is not None:
            failed: LogEvent = LogEvent.of(IntakeEvent.TABLE_FAILED, package_id=self.request.package_id)
            failed.extended(reason=error.reason, sheet=error.label, status=error.status).emit(LOGGER, logging.ERROR)
        LogEvent.of(IntakeEvent.FINISHED, package_id=self.request.package_id, **result.log_fields).emit(LOGGER)
        return result
