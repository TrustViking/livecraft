"""Прогон контура A одного запуска от входа «Таблица» (CLAUDE.md §3 шаги 2.3–2.6, §4, §10).

Таблица плана → ряды → источники (yt-dlp, язык, обложки) → превью (копии в папке превью и на Google Диске) → запись в
таблицу (язык видео и ссылка на копию превью в строке видео) → merge → слоты. Какие из этих шагов идут, решают линии
работы (`IntakeRequest.scope`, §14 решение 37): превью — по своим линиям (ни одна не идёт — шага нет, превью в памяти
для вывода остаются), ссылки на превью в таблицу — только с копиями на Диске. Каждый шаг делает свой объект
(`SheetsReader`, `SheetPlan`, `SourceCatalog`, `PreviewStage`, `TableStage`, `MergeStage`, `SlotBuilder`); `PlanIntake`
только ведёт их по порядку и останавливается там, где дальше идти не с чем. Превью и запись в таблицу прогон не
останавливают: сбой Диска или записи — ошибка запуска, merge и слоты идут дальше. Всё, что знает таблицу, — здесь;
вывод (пакет, документ, Telegram) и эфиры идут от слотов прогона тем же путём, что от слотов пакетов (app\\main.py).
Итог — `IntakeResult`: что получилось на каждом шаге, где остановился прогон, исход (`RunOutcome`) и строки для
оператора; часть отчёта запуска — `IntakeReport` (app\\intake\\intake_report.py). Код выхода по исходу решает
app\\run. Допущенный ряд таблицы — строкой лога сразу после разбора рядов (§14 решение 38). Долгие шаги (видео,
копии на Диск, обращения к модели) говорят в консоль строкой хода перед каждым шагом (`IntakeRequest.progress`,
app\\run\\progress.py): итоговые строки стадий готовы только после всего прогона.

Тексты слотов — строго по линиям (§14 решения 32, 50): идёт линия «Нейросеть» (включена, ключ OpenAI в сейфе) — у
прогона есть нейросеть (`merge_backend`), и тексты слотов даёт стадия merge (`MergeResult.texts_of`) по правилу «умного
merge»: тексты модели, тексты видео, а когда merge не удался — «по номерам», не для YouTube, ошибка запуска. Нейросеть не
идёт — стадии merge нет, тексты — по правилу группы без нейросети (`SlotGroup.people_texts`): одно видео — его тексты,
несколько — «по номерам»; это не ошибка, а настройка: такие слоты только для людей, пакет и эфиры от таблицы без
нейросети не работают. Merge прогон не останавливает: модель не выбрана или merge остановлен — ошибка запуска, а слоты
идут дальше. Сбой чтения таблицы и сбой входа оператора — не исключение наружу, а итог с причиной. Таблицу прогон
читает по правилу входа оператора (`OperatorSheets`, app\\sheets\\operator.py): после нового входа — строка с почтой
аккаунта, а когда аккаунту таблица не открыта — повторный вход в том же запуске.

В строках консоли нет ни значений сейфа, ни ссылки на форму, ни названий и описаний видео (§7.4): только
счётчики и причины человеческим текстом.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.config.loader import LivecraftSettings
from app.core.dates import require_aware
from app.google.auth import GoogleLogin
from app.intake.builder import SlotBuild, SlotBuilder, SlotGroup
from app.intake.preview_stage import PreviewCopies, PreviewMode, PreviewResult, PreviewStage
from app.intake.merge_stage import MergeResult, MergeStage
from app.intake.table_stage import TableResult, TableStage
from app.llm.backend import LlmBackend
from app.llm.backends.openai import OpenAiClient
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths
from app.run.exit_code import RunOutcome
from app.run.line_plan import RunScope
from app.run.mode import RunPart
from app.run.progress import SILENT_PROGRESS, StageProgress
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReader, SheetsReadError
from app.sheets.operator import OperatorDoor, OperatorPlan, OperatorSheets
from app.sheets.plan import PlanProblem, SheetPlan
from app.sheets.rows import PlannedRows
from app.slots.slot import StreamSlot
from app.slots.texts import SlotTexts
from app.sources.video import PreparedSources, SourceCatalog
from app.ui.messages import msg

LOGGER = get_logger(LogArea.INTAKE)


class IntakeStage(str, Enum):
    """Шаг, на котором прогон остановился. Значение — идентификатор для лога."""

    TABLE = "table"        # таблица не прочиталась, шапка не распознана или будущих рядов нет
    SOURCES = "sources"    # годных источников нет
    SLOTS = "slots"        # годных слотов нет


class IntakeEvent(str, Enum):
    """События прогона контура A в логе."""

    TABLE_FAILED = "intake_table_failed"
    FINISHED = "intake_finished"


@dataclass(frozen=True)
class IntakeRequest:
    """Всё, что нужно прогону: корень, настройки, сейф, «сейчас» (со смещением), что идёт в запуске (`scope`: части
    по линиям работы и пробный ли запуск — копии превью только в папке превью, к записи в таблицу прогон не
    обращается) и строки хода долгих шагов в консоль (`progress`; без консоли — молчит)."""

    paths: LivecraftPaths
    settings: LivecraftSettings
    vault: Vault
    now: datetime
    scope: RunScope
    progress: StageProgress = SILENT_PROGRESS

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
    previews: PreviewResult | None = None
    table: TableResult | None = None
    merge: MergeResult | None = None
    build: SlotBuild | None = None
    stopped_at: IntakeStage | None = None

    @property
    def plan_problem(self) -> PlanProblem | None:
        return self.plan.problem if self.plan is not None else None

    @property
    def slots(self) -> tuple[StreamSlot, ...]:
        """Годные слоты прогона — со слотами «по номерам» (§14 решение 32); слотов нет — пусто. По ним идут вывод и
        эфиры (эфиры и пакет — только по слотам для YouTube)."""
        return () if self.build is None else self.build.slots

    @property
    def has_future_rows(self) -> bool:
        return self.rows is not None and bool(self.rows.admitted)

    @property
    def outcome(self) -> RunOutcome:
        """Исход по §10: сбой таблицы по настройке или входу — не настроено, прочий сбой и шапка — ошибка; будущих
        рядов нет — нечего делать; негодный источник, сбой Диска или записи в таблицу, merge без модели или
        остановленный до конца запуска, слот с проблемой или слот, которому не удался merge, — ошибка; слотов нет без
        отказов — нечего делать.
        """
        if self.sheets_error is not None:
            return RunOutcome.NOT_CONFIGURED if self.sheets_error.reason.is_configuration else RunOutcome.FAILED
        if self.plan_problem is not None:
            return RunOutcome.FAILED
        if not self.has_future_rows:
            return RunOutcome.NOTHING_PLANNED
        if any(stage.has_errors for stage in self._later_stages):
            return RunOutcome.FAILED
        if not self.slots:
            return RunOutcome.NOTHING_PLANNED
        return RunOutcome.DONE

    @property
    def console_lines(self) -> tuple[str, ...]:
        """По строке на пройденную стадию; на остановке — строка о том, почему дальше не пошли. Таблица не дала
        рядов — сбой чтения либо проблема плана."""
        if self.sheets_error is not None:
            return (self.sheets_error.human,)
        if self.rows is None:
            return (self.plan.problem_text if self.plan is not None else "",)
        lines: list[str] = [self.rows.console_line]
        if not self.has_future_rows:
            return (*lines, msg.INTAKE_NO_FUTURE_ROWS)
        lines.extend(self._stage_lines)
        if not self.slots:      # дальше идти не с чем: ни вывода, ни эфиров
            lines.append(msg.INTAKE_NO_SLOTS)
        return tuple(lines)

    @property
    def _later_stages(self) -> tuple[PreparedSources | PreviewResult | TableResult | MergeResult | SlotBuild, ...]:
        """Пройденные стадии после рядов по порядку: источники, превью, запись в таблицу, merge, слоты."""
        return tuple(
            stage
            for stage in (self.sources, self.previews, self.table, self.merge, self.build)
            if stage is not None
        )

    @property
    def _stage_lines(self) -> tuple[str, ...]:
        """Строки стадий после рядов: видео, затем превью, запись в таблицу, merge и слоты — у них по несколько
        строк."""
        sources: tuple[str, ...] = () if self.sources is None else (self.sources.console_line,)
        stages: tuple[PreviewResult | TableResult | MergeResult | SlotBuild, ...] = tuple(
            stage for stage in (self.previews, self.table, self.merge, self.build) if stage is not None
        )
        return (*sources, *(line for stage in stages for line in stage.console_lines))

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
            previews=None if self.previews is None else self.previews.mode,
            table_error=None if self.table is None or self.table.error is None else self.table.error.reason,
            merged=None if self.merge is None else self.merge.merged,
            slots=None if self.build is None else len(self.build.slots),
            refused=None if self.build is None else len(self.build.refused),
            outcome=self.outcome,
        )


@dataclass(frozen=True)
class PlanIntake:
    """Прогон контура A: зависимости — полями, в тестах свои (таблица на входе оператора, источники, этап превью,
    запись в таблицу, сборщик слотов, нейросеть).

    `sheets` — таблица плана по правилу входа оператора (app\\sheets\\operator.py): каким аккаунтом вошли и повторный
    вход, когда аккаунту таблица не открыта;
    `merge_backend` None — merge в этом прогоне нет: тексты слотов — по правилу без нейросети, к ней ни одного
    обращения;
    `previews` None — ни одна линия превью не идёт.
    """

    request: IntakeRequest
    sheets: OperatorSheets
    catalog: SourceCatalog
    previews: PreviewStage | None
    table: TableStage
    builder: SlotBuilder
    merge_backend: LlmBackend | None

    @classmethod
    def of(cls, request: IntakeRequest) -> PlanIntake:
        """Боевые зависимости: вход оператора и Sheets, yt-dlp корня, сборщик в зоне программы, OpenAI — когда идёт
        merge (ключ в сейфе: без него часть «нейросеть» не готова).

        Читатель открывается только в `run`: вход в Google (а с ним, может быть, браузер) — часть прогона; строки
        входа оператора и повторов чтения — на консоль запроса (`request.progress`). Клиент OpenAI к сети не
        обращается, пока его не спросят.
        """
        door: OperatorDoor = OperatorDoor(GoogleLogin.operator(request.paths), request.progress)
        backend: LlmBackend | None = None
        if request.scope.runs(RunPart.MERGE):
            backend = OpenAiClient.from_vault(request.vault, request.settings.llm)
        mode: PreviewMode | None = PreviewMode.of(request.scope)
        return cls(
            request=request,
            sheets=OperatorSheets.for_console(door, request.progress.operator_note),
            catalog=SourceCatalog.from_paths(request.paths),
            previews=None if mode is None else PreviewStage.of(request.paths, request.settings, request.vault, mode),
            table=TableStage(request.vault, request.scope.dry_run),
            builder=SlotBuilder(request.settings.zone),
            merge_backend=backend,
        )

    def run(self) -> IntakeResult:
        """Таблица → ряды → источники → превью → запись в таблицу → merge → слоты; остановка там, где дальше идти не
        с чем."""
        try:
            read: OperatorPlan = self.sheets.read_plan(self.request.vault)
        except SheetsReadError as error:
            return self._finish(IntakeResult(sheets_error=error, stopped_at=IntakeStage.TABLE))
        plan: SheetPlan = read.plan
        if plan.problem is not None:
            return self._finish(IntakeResult(plan=plan, stopped_at=IntakeStage.TABLE))
        rows: PlannedRows = plan.plan_rows(self.request.settings.zone, self.request.now)
        for admitted in rows.admitted:
            admitted.event.emit(LOGGER)
        if not rows.admitted:
            return self._finish(IntakeResult(plan=plan, rows=rows, stopped_at=IntakeStage.TABLE))
        return self._finish(self._after_rows(plan, rows, read.reader))

    def _after_rows(self, plan: SheetPlan, rows: PlannedRows, reader: SheetsReader) -> IntakeResult:
        """Источники → превью → запись в таблицу → merge → слоты по рядам с будущими эфирами; остановка там, где
        дальше идти не с чем."""
        progress: StageProgress = self.request.progress
        sources: PreparedSources = self.catalog.prepare(rows, progress)
        if not sources.has_ready:
            return IntakeResult(plan=plan, rows=rows, sources=sources, stopped_at=IntakeStage.SOURCES)
        previews: PreviewResult | None = None
        if self.previews is not None:
            previews = self.previews.run(PreviewCopies.of(sources.videos, self.request.settings.zone), progress)
        table: TableResult = self.table.run(plan, sources, previews, reader)
        groups: tuple[SlotGroup, ...] = self.builder.groups(sources.videos)
        merge: MergeResult | None = self._merge(groups)
        build: SlotBuild = SlotBuild.of([group.slot(self._texts(group, merge)) for group in groups], merge is not None)
        return IntakeResult(
            plan=plan, rows=rows, sources=sources, previews=previews, table=table, merge=merge, build=build,
            stopped_at=None if build.slots else IntakeStage.SLOTS,
        )

    def _merge(self, groups: tuple[SlotGroup, ...]) -> MergeResult | None:
        """Стадия merge на нейросети прогона и видео этого запуска; нейросети нет или групп нет — стадии нет."""
        if self.merge_backend is None or not groups:
            return None
        stage: MergeStage = MergeStage(self.merge_backend, self.request.settings.llm, self.catalog)
        return stage.run(groups, self.request.progress)

    def _texts(self, group: SlotGroup, merge: MergeResult | None) -> SlotTexts:
        """Окончательные тексты слота: от стадии merge, а без неё — по правилу группы без нейросети."""
        return group.people_texts if merge is None else merge.texts_of(group)

    def _finish(self, result: IntakeResult) -> IntakeResult:
        """Итог — строкой в лог; сбой таблицы — её ярлыком, причиной и кодом ответа."""
        error: SheetsReadError | None = result.sheets_error
        if error is not None:
            failed: LogEvent = LogEvent.of(IntakeEvent.TABLE_FAILED, reason=error.reason, sheet=error.label)
            failed.extended(status=error.status).emit(LOGGER, logging.ERROR)
        LogEvent.of(IntakeEvent.FINISHED, **result.log_fields).emit(LOGGER)
        return result
