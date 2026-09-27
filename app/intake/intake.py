"""Прогон контура A одного запуска режима А (CLAUDE.md §3 шаги 2.3–2.6, §4, §10).

Таблица плана → ряды → источники (yt-dlp, язык, обложки) → merge → слоты → пакет plan_*.bcast в bcast\\.
Каждый шаг делает свой объект (`SheetsReader`, `SheetPlan`, `SourceCatalog`, `MergeStage`, `SlotBuilder`,
`SlotPackage`); `PlanIntake` только ведёт их по порядку и останавливается там, где дальше идти не с чем.
Итог — `IntakeResult`: что получилось на каждом шаге, где остановился прогон, исход (`RunOutcome`) и строки для
оператора. Код выхода по исходу решает app\\run.

Merge идёт, когда его часть режима готова (`IntakeRequest.with_merge`: нет --no-llm, ключ OpenAI в сейфе): тогда
у прогона есть нейросеть (`merge_backend`), и тексты слотов даёт стадия merge (`MergeResult.texts_of`) — тексты
модели или тексты видео. Иначе стадии merge нет, тексты слотов — из видео (`SlotGroup.source_texts`). Merge прогон не
останавливает: модель не выбрана или merge остановлен — ошибка запуска, а слоты и пакет идут дальше.
Сбой чтения таблицы — не исключение наружу, а итог с причиной. Сбой записи пакета на диск (OSError) — ошибка
программы, её ловит запуск.

В строках консоли нет ни значений сейфа, ни ссылки на форму, ни названий и описаний видео (§7.4): только
счётчики и причины человеческим текстом.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.config.loader import LivecraftSettings
from app.core.dates import require_aware
from app.google.auth import GoogleLogin
from app.intake.builder import SlotBuild, SlotBuilder, SlotGroup
from app.intake.merge_stage import MergeResult, MergeStage
from app.llm.backend import LlmBackend
from app.llm.backends.openai import OpenAiClient
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.packages.package import PackageResult, SlotPackage
from app.paths import LivecraftPaths
from app.run.exit_code import RunOutcome
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReader, SheetsReadError
from app.sheets.plan import PlanProblem, SheetPlan
from app.sheets.rows import PlannedRows
from app.slots.texts import SlotTexts
from app.sources.video import PreparedSources, SourceCatalog
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
    """Всё, что нужно прогону: корень, настройки, сейф, «сейчас» (со смещением), id пакета и идёт ли merge (часть
    «нейросеть» готова)."""

    paths: LivecraftPaths
    settings: LivecraftSettings
    vault: Vault
    now: datetime
    package_id: str
    with_merge: bool

    def __post_init__(self) -> None:
        require_aware(self.now)


@dataclass(frozen=True)
class IntakeResult:
    """Итог прогона: объект каждой пройденной стадии и шаг, на котором прогон остановился.

    Не пройденная стадия — None. Итог только опрашивает стадии: исход, строки консоли и лога — из их ответов.
    """

    sheets_error: SheetsReadError | None = None
    plan: SheetPlan | None = None
    rows: PlannedRows | None = None
    sources: PreparedSources | None = None
    merge: MergeResult | None = None
    build: SlotBuild | None = None
    package: PackageResult | None = None
    stopped_at: IntakeStage | None = None

    @property
    def plan_problem(self) -> PlanProblem | None:
        return self.plan.problem if self.plan is not None else None

    @property
    def has_future_rows(self) -> bool:
        return self.rows is not None and bool(self.rows.admitted)

    @property
    def has_errors(self) -> bool:
        """Негодный источник, merge без модели или остановленный до конца запуска, слот с проблемой или незаписанный
        пакет — ошибка запуска (§10)."""
        return any(stage.has_errors for stage in self._later_stages)

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
        """По строке на пройденную стадию; на остановке — строка о том, почему дальше не пошли."""
        if self.rows is None:
            return (self._table_problem,)
        lines: list[str] = [self.rows.console_line]
        if not self.has_future_rows:
            return (*lines, msg.INTAKE_NO_FUTURE_ROWS)
        lines.extend(self._stage_lines)
        if self.package is None:
            lines.append(msg.INTAKE_NO_SLOTS)
        return tuple(lines)

    @property
    def _later_stages(self) -> tuple[PreparedSources | MergeResult | SlotBuild | PackageResult, ...]:
        """Пройденные стадии после рядов по порядку: источники, merge, слоты, пакет."""
        return tuple(stage for stage in (self.sources, self.merge, self.build, self.package) if stage is not None)

    @property
    def _stage_lines(self) -> tuple[str, ...]:
        """Строки стадий после рядов: видео, merge (у него несколько строк), слоты, пакет."""
        sources: tuple[str, ...] = () if self.sources is None else (self.sources.console_line,)
        merge: tuple[str, ...] = () if self.merge is None else self.merge.console_lines
        later: tuple[str, ...] = tuple(stage.console_line for stage in (self.build, self.package) if stage is not None)
        return (*sources, *merge, *later)

    @property
    def _table_problem(self) -> str:
        """Почему таблица не дала рядов: сбой чтения либо проблема плана."""
        if self.sheets_error is not None:
            return self.sheets_error.human
        return self.plan.problem_text if self.plan is not None else ""

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Счётчики стадий, причина остановки и исход; без значений сейфа, ссылки формы и текстов видео."""
        return dict(
            stopped_at=self.stopped_at,
            sheets_error=None if self.sheets_error is None else self.sheets_error.reason,
            plan_problem=self.plan_problem,
            rows=None if self.rows is None else self.rows.total,
            admitted=None if self.rows is None else len(self.rows.admitted),
            sources=None if self.sources is None else len(self.sources.videos),
            ready=None if self.sources is None else self.sources.ready,
            merged=None if self.merge is None else self.merge.merged,
            slots=None if self.build is None else len(self.build.slots),
            refused=None if self.build is None else len(self.build.refused),
            package=None if self.package is None else self.package.is_written,
            outcome=self.outcome,
        )


@dataclass(frozen=True)
class PlanIntake:
    """Прогон контура A: зависимости — полями, в тестах свои (читатель таблицы, источники, сборщик слотов, нейросеть).

    `merge_backend` None — merge в этом прогоне нет: тексты слотов из видео, к нейросети ни одного обращения.
    """

    request: IntakeRequest
    reader_factory: Callable[[], SheetsReader]
    catalog: SourceCatalog
    builder: SlotBuilder
    merge_backend: LlmBackend | None

    @classmethod
    def of(cls, request: IntakeRequest, on_login: Callable[[], None] | None = None) -> PlanIntake:
        """Боевые зависимости: вход оператора и Sheets, yt-dlp корня, сборщик в зоне программы, OpenAI — когда идёт
        merge (ключ в сейфе: без него часть «нейросеть» не готова).

        Читатель открывается только в `run`: вход в Google (а с ним, может быть, браузер) — часть прогона. Клиент
        OpenAI к сети не обращается, пока его не спросят.
        """
        login: GoogleLogin = GoogleLogin.operator(request.paths)
        backend: LlmBackend | None = None
        if request.with_merge:
            backend = OpenAiClient.from_vault(request.vault, request.settings.llm)
        return cls(
            request=request,
            reader_factory=lambda: SheetsReader.open(login, allow_login=True, on_login=on_login),
            catalog=SourceCatalog.from_paths(request.paths),
            builder=SlotBuilder(request.settings.zone),
            merge_backend=backend,
        )

    def run(self) -> IntakeResult:
        """Таблица → ряды → источники → merge → слоты → пакет; остановка там, где дальше идти не с чем."""
        try:
            plan: SheetPlan = self.reader_factory().read_plan(self.request.vault)
        except SheetsReadError as error:
            return self._finish(IntakeResult(sheets_error=error, stopped_at=IntakeStage.TABLE))
        if plan.problem is not None:
            return self._finish(IntakeResult(plan=plan, stopped_at=IntakeStage.TABLE))
        rows: PlannedRows = plan.plan_rows(self.request.settings.zone, self.request.now)
        if not rows.admitted:
            return self._finish(IntakeResult(plan=plan, rows=rows, stopped_at=IntakeStage.TABLE))
        return self._finish(self._after_rows(plan, rows))

    def _after_rows(self, plan: SheetPlan, rows: PlannedRows) -> IntakeResult:
        """Источники → merge → слоты → пакет по рядам с будущими эфирами; остановка там, где дальше идти не с чем."""
        sources: PreparedSources = self.catalog.prepare(rows)
        if not sources.has_ready:
            return IntakeResult(plan=plan, rows=rows, sources=sources, stopped_at=IntakeStage.SOURCES)
        groups: tuple[SlotGroup, ...] = self.builder.groups(sources.videos)
        merge: MergeResult | None = self._merge(groups)
        build: SlotBuild = SlotBuild.of([group.slot(self._texts(group, merge)) for group in groups])
        if not build.slots:
            return IntakeResult(
                plan=plan, rows=rows, sources=sources, merge=merge, build=build, stopped_at=IntakeStage.SLOTS
            )
        package: PackageResult = self._package(build).write(self.request.paths.bcast_dir)
        stopped_at: IntakeStage | None = None if package.is_written else IntakeStage.PACKAGE
        return IntakeResult(
            plan=plan, rows=rows, sources=sources, merge=merge, build=build, package=package, stopped_at=stopped_at
        )

    def _merge(self, groups: tuple[SlotGroup, ...]) -> MergeResult | None:
        """Стадия merge на нейросети прогона и видео этого запуска; нейросети нет — стадии нет."""
        if self.merge_backend is None:
            return None
        return MergeStage(self.merge_backend, self.request.settings.llm, self.catalog).run(groups)

    def _texts(self, group: SlotGroup, merge: MergeResult | None) -> SlotTexts:
        """Окончательные тексты слота: от стадии merge, а без неё — тексты видео по правилам YouTube."""
        return group.source_texts if merge is None else merge.texts_of(group)

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
