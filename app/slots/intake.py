"""Прогон контура A одного запуска режима А (CLAUDE.md §3 шаги 2.3–2.6, §4, §10).

Таблица плана → ряды → источники (yt-dlp, язык, обложки) → слоты → пакет plan_*.bcast в bcast\\.
Каждый шаг делает свой объект (`SheetsReader`, `SheetPlan`, `SourceCatalog`, `SlotBuilder`, `SlotPackage`);
`PlanIntake` только ведёт их по порядку и останавливается там, где дальше идти не с чем. Итог — `IntakeResult`:
что получилось на каждом шаге, где остановился прогон, код выхода по §10 и строки для оператора.

Нейросети пока нет: тексты слотов — из источников (`SlotTexts.from_sources`, этап 3.5).
Сбой чтения таблицы — не исключение наружу, а итог с причиной: его печатает main. Сбой записи пакета на диск
(OSError) — ошибка программы, её ловит main.run_cli.

В строках консоли нет ни значений сейфа, ни ссылки на форму, ни названий и описаний видео (§7.4): только
счётчики и причины человеческим текстом.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final

from app.config.loader import LivecraftSettings
from app.google.auth import GoogleLogin
from app.observability.logging_setup import get_logger
from app.packages.package import PackageResult, SlotPackage
from app.paths import LivecraftPaths
from app.secretsafe.vault import Vault
from app.setup.run_mode import ExitCode
from app.sheets.client import SheetsReader, SheetsReadError, SheetsReadReason
from app.sheets.plan import SheetPlan
from app.sheets.rows import PlanRow, RowSkipReason
from app.slots.builder import SlotBuild, SlotBuilder
from app.sources.video import SourceCatalog, SourceTally, SourceVideo
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "intake"
LOGGER = get_logger(LOGGER_NAME)

NO_VALUE: Final[str] = "-"
# Сбой таблицы, который лечится настройкой или входом, — ошибка конфигурации или авторизации (§10, код 2).
CONFIG_SHEETS_REASONS: Final[frozenset[SheetsReadReason]] = frozenset(
    {SheetsReadReason.NOT_CONFIGURED, SheetsReadReason.AUTH}
)


class IntakeStage(str, Enum):
    """Шаг, на котором прогон остановился. Значение — идентификатор для лога."""

    TABLE = "table"        # таблица не прочиталась, шапка не распознана или будущих рядов нет
    SOURCES = "sources"    # годных источников нет
    SLOTS = "slots"        # годных слотов нет
    PACKAGE = "package"    # пакет не записан


@dataclass(frozen=True)
class IntakeRequest:
    """Всё, что нужно прогону: корень, настройки, сейф, «сейчас» (со смещением) и id пакета."""

    paths: LivecraftPaths
    settings: LivecraftSettings
    vault: Vault
    now: datetime
    package_id: str

    def __post_init__(self) -> None:
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")


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
            items: str = msg.INTAKE_ITEM_JOINER.join(
                msg.INTAKE_COUNT_ITEM.format(name=reason.human, count=count) for reason, count in skipped.items()
            )
            reasons = msg.INTAKE_TABLE_REASONS.format(items=items)
        return msg.INTAKE_TABLE_LINE.format(
            rows=len(self.rows), admitted=self.admitted, skipped=sum(skipped.values()), reasons=reasons
        )


@dataclass(frozen=True)
class IntakeResult:
    """Итог прогона: ряды, источники, слоты, пакет и причина остановки — и правила кода выхода и строк."""

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
        """Отказ источника, слот с проблемой или незаписанный пакет — ошибка запуска (§10, код 1)."""
        if SourceTally(self.videos).failures:
            return True
        if self.build is not None and self.build.refused:
            return True
        return self.package is not None and not self.package.is_written

    @property
    def exit_code(self) -> ExitCode:
        """Код по §10: таблица — 2 на настройке и входе, 1 на прочем сбое и шапке; будущих рядов нет — 3;
        ошибки источников, слотов и пакета — 1; иначе 0. Слотов нет из-за отказов — это ошибки, а не «нет рядов».
        """
        if self.sheets_error is not None:
            return ExitCode.CONFIG if self.sheets_error.reason in CONFIG_SHEETS_REASONS else ExitCode.ERRORS
        if self.plan_problem is not None:
            return ExitCode.ERRORS
        if not self.has_future_rows:
            return ExitCode.NO_FUTURE_SLOTS
        if self.has_errors:
            return ExitCode.ERRORS
        if self.build is None or not self.build.slots:
            return ExitCode.NO_FUTURE_SLOTS
        return ExitCode.OK

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
    def log_line(self) -> str:
        """Счётчики и причина остановки key=value; без значений сейфа, ссылки формы и текстов видео."""
        rows: RowTally = RowTally(self.rows)
        sources: SourceTally = SourceTally(self.videos)
        slots: str = NO_VALUE if self.build is None else str(len(self.build.slots))
        refused: str = NO_VALUE if self.build is None else str(len(self.build.refused))
        package: str = NO_VALUE if self.package is None else self.package.log_line
        sheets: str = NO_VALUE if self.sheets_error is None else self.sheets_error.reason.value
        stopped: str = NO_VALUE if self.stopped_at is None else self.stopped_at.value
        return (
            f"stopped_at={stopped} sheets_error={sheets} plan_problem={self.plan_problem is not None} "
            f"rows={len(self.rows)} admitted={rows.admitted} sources={len(self.videos)} ready={sources.ready} "
            f"slots={slots} refused={refused} package=[{package}] exit_code={int(self.exit_code)}"
        )

    @property
    def _sources_line(self) -> str:
        tally: SourceTally = SourceTally(self.videos)
        failures: str = ""
        if tally.failures:
            items: str = msg.INTAKE_ITEM_JOINER.join(
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
            items: str = msg.INTAKE_LANGUAGE_JOINER.join(
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
        build: SlotBuild = self.builder.build(videos)
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

    def _package(self, build: SlotBuild) -> SlotPackage:
        return SlotPackage.of(build.slots, self.request.settings, self.request.now, self.request.package_id)

    def _finish(self, result: IntakeResult) -> IntakeResult:
        """Итог — строкой в лог; сбой таблицы — её ярлыком и причиной (SheetsReadError.log_line)."""
        if result.sheets_error is not None:
            LOGGER.error("intake_table_failed package_id=%s %s", self.request.package_id, result.sheets_error.log_line)
        LOGGER.info("intake_finished package_id=%s %s", self.request.package_id, result.log_line)
        return result
