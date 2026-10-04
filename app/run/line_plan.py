"""Линии работы запуска: какие работают, что из них готово и что делает запуск (CLAUDE.md §10, §14 решения 37, 50, 51).

`LinePlan` — из включённых линий (раздел `lines` livecraft.json): вход запуска (`source`: таблица плана, если её линия
включена, иначе пакеты) и состояние каждой линии — выключена, работает или включена без опоры (какой выключенной линии
ей не хватает по опорам своего входа, `RunPart.requires_from`). Линия без опоры — не ошибка: её значение хранится и
вернётся, когда опору включат; сводка называет такие линии одной строкой на опору, а у пакета и эфиров без нейросети —
и причину: от таблицы они работают только с ней. Таблица плана выключена, а хоть одна линия работает — слоты всех линий
из пакетов, первой идёт чтение пакетов (`PACKAGES_IN`); форма ключей приходит в каждом пакете, а таблицы нет — эти
нужды удовлетворены сами (`needs_of`). `ModeReadiness` — готовность работающих частей по порядку работы: первая из них —
основа (таблица плана или чтение пакетов), без неё не делается ничего. Часть идёт в этом запуске (`runs`), когда она
работает, готова и идёт её опора. Что делает запуск (`ModeStep`) и каков исход готовности, решает сам
`ModeReadiness`, а не запуск; что идёт снаружи — одним значением `RunScope` (части и пробный ли запуск), откуда тексты
эфиров — `RunTexts`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.observability.log_event import LogEvent, LogValue
from app.run.exit_code import RunOutcome
from app.run.mode import LINE_ORDER, PACKAGES_MET_NEEDS, ModeStep, Need, PartReadiness, PartState, RunPart
from app.ui.messages import msg

# Линия в снимке запуска: включена ли, состояние, готова ли и каких нужд не хватает.
LINE_SNAPSHOT_TEMPLATE: Final[str] = "on={on};state={state};ready={ready};unmet={unmet}"
NEED_JOINER: Final[str] = "+"
# Строка сводки о линиях без опоры: без нейросети — с причиной (§14 решение 50); прочие опоры — общей строкой.
NO_SUPPORT_TEMPLATES: Final[dict[RunPart, str]] = {RunPart.MERGE: msg.LINES_NO_SUPPORT_MERGE}


class LineState(str, Enum):
    """Состояние линии. Значение — идентификатор для лога."""

    OFF = "off"                  # выключена
    WORKS = "works"              # включена, и её опора работает
    NO_SUPPORT = "no_support"    # включена, но линия, на которую она опирается, выключена


class LinePlanEvent(str, Enum):
    """События линий в логе."""

    READINESS = "mode_readiness"
    SNAPSHOT = "run_snapshot_lines"


@dataclass(frozen=True)
class LineStatus:
    """Одна линия: включена ли и какой выключенной линии ей не хватает (None — хватает всех)."""

    part: RunPart
    is_on: bool
    missing: RunPart | None

    @property
    def state(self) -> LineState:
        if not self.is_on:
            return LineState.OFF
        return LineState.WORKS if self.missing is None else LineState.NO_SUPPORT


@dataclass(frozen=True)
class LinePlan:
    """Включённые линии запуска и правила «работает ли линия»."""

    switched_on: frozenset[RunPart]

    @property
    def source(self) -> RunPart:
        """Вход запуска: таблица плана, если её линия включена, иначе чтение пакетов (§14 решение 51)."""
        return RunPart.PLAN if RunPart.PLAN in self.switched_on else RunPart.PACKAGES_IN

    def requires(self, part: RunPart) -> RunPart | None:
        """Опора части при входе этого запуска; своя опора не нужна — None."""
        return part.requires_from(self.source)

    def status(self, part: RunPart) -> LineStatus:
        """Линия и первая выключенная линия по цепочке её опор: у эфиров от таблицы без нейросети — нейросеть."""
        support: RunPart | None = self.requires(part)
        while support is not None and support in self.switched_on:
            support = self.requires(support)
        return LineStatus(part=part, is_on=part in self.switched_on, missing=support)

    @property
    def lines(self) -> tuple[LineStatus, ...]:
        """Все линии в порядке «Главной»."""
        return tuple(self.status(part) for part in LINE_ORDER)

    def works(self, part: RunPart) -> bool:
        """Линия работает; чтение пакетов — когда вход «Пакеты» и хоть одна линия работает: без них читать незачем."""
        if part is RunPart.PACKAGES_IN:
            return self.source is RunPart.PACKAGES_IN and any(self.works(line) for line in LINE_ORDER)
        return self.status(part).state is LineState.WORKS

    @property
    def working(self) -> tuple[RunPart, ...]:
        """Работающие части в порядке работы: первая — основа запуска."""
        return tuple(part for part in RunPart if self.works(part))

    @property
    def unsupported(self) -> tuple[LineStatus, ...]:
        return tuple(line for line in self.lines if line.state is LineState.NO_SUPPORT)

    def needs_of(self, part: RunPart) -> tuple[Need, ...]:
        """Что нужно части в этом запуске: при входе «Пакеты» форма ключей — у каждого пакета своя, а таблицы нет."""
        if self.source is RunPart.PLAN:
            return part.needs
        return tuple(need for need in part.needs if need not in PACKAGES_MET_NEEDS)

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Не работает ни одна линия — одна строка «включите линии»; иначе ничего: линии без опоры называет сводка."""
        return () if self.working else (msg.LINES_NONE_WORKING,)

    @property
    def summary_lines(self) -> tuple[str, ...]:
        """Строки сводки настроек: работающие линии в порядке «Главной» (ни одной — «нет»), затем выключенные, если
        они есть, затем по строке на опору, без которой не работают включённые линии."""
        working: str = msg.LIST_JOINER.join(self._labels(LineState.WORKS)) or msg.NONE_TEXT
        off: tuple[str, ...] = self._labels(LineState.OFF)
        lines: list[str] = [msg.READINESS_LINES_WORKING.format(lines=working)]
        if off:
            lines.append(msg.READINESS_LINES_OFF.format(lines=msg.LIST_JOINER.join(off)))
        return (*lines, *self._no_support_lines)

    @property
    def _no_support_lines(self) -> tuple[str, ...]:
        """«Не работают без «X»: A, B.» — по строке на выключенную опору, в порядке «Главной»; без нейросети — с
        причиной: от таблицы пакет и эфиры работают только с ней (§14 решение 50)."""
        missing: dict[RunPart, list[str]] = {}
        for line in self.unsupported:
            if line.missing is not None:
                missing.setdefault(line.missing, []).append(line.part.human_label)
        return tuple(
            NO_SUPPORT_TEMPLATES.get(support, msg.LINES_NO_SUPPORT).format(
                support=support.human_label, lines=msg.LIST_JOINER.join(labels)
            )
            for support, labels in missing.items()
        )

    def _labels(self, state: LineState) -> tuple[str, ...]:
        return tuple(line.part.human_label for line in self.lines if line.state is state)


@dataclass(frozen=True)
class RunScope:
    """Что делает запуск снаружи: части, которые в нём идут, и пробный ли он (--dry-run)."""

    parts: frozenset[RunPart]
    dry_run: bool = False

    def runs(self, part: RunPart) -> bool:
        return part in self.parts


class RunTextSource(str, Enum):
    """Откуда тексты эфиров запуска. Значение — идентификатор для лога и ключ текста каталога."""

    LLM = "llm"              # нейросеть пишет тексты слотам таблицы
    VIDEOS = "videos"        # таблица без нейросети: тексты видео, у слота из нескольких видео — «по номерам»
    PACKAGES = "packages"    # вход «Пакеты»: тексты пакетов

    @property
    def human(self) -> str:
        return msg.RUN_TEXT_SOURCES[self.value]


@dataclass(frozen=True)
class RunTexts:
    """Откуда тексты эфиров запуска — строго по линиям, которые в нём идут (§14 решение 50): вход «Пакеты» — из пакетов;
    таблица с нейросетью — от неё; без неё — тексты видео, а у слота из нескольких видео — «по номерам», только для
    людей. Одно правило для сводки настроек запуска."""

    scope: RunScope

    @property
    def source(self) -> RunTextSource:
        if self.scope.runs(RunPart.PACKAGES_IN):
            return RunTextSource.PACKAGES
        return RunTextSource.LLM if self.scope.runs(RunPart.MERGE) else RunTextSource.VIDEOS


@dataclass(frozen=True)
class ModeReadiness:
    """Готовность работающих частей — в порядке работы.

    Первая работающая часть — основа: в режиме А из таблицы берутся все слоты, в режиме Б — из пакетов, и без неё
    не делается ничего. Поэтому не готовая основа — это «не готово ничего», даже если у остальных частей всё
    настроено. Всё, чего может не хватать, задаётся в окне настройщика: повреждённый личный файл ключей и ссылок заменит
    сохранение, файл токена — загрузка токена.
    """

    plan: LinePlan
    parts: tuple[PartReadiness, ...]

    def in_state(self, state: PartState) -> tuple[PartReadiness, ...]:
        """Работающие части в этом состоянии, по порядку работы."""
        return tuple(part for part in self.parts if part.state is state)

    @property
    def is_ready(self) -> bool:
        """Всё, что работает, готово: хоть одна линия работает, и ни одна работающая часть не заблокирована."""
        return bool(self.parts) and not self.in_state(PartState.BLOCKED)

    @property
    def is_nothing_ready(self) -> bool:
        """Не работает ни одна часть или не готова основа: без неё слотов нет ни у одной другой части."""
        return not self.parts or self.parts[0].state is PartState.BLOCKED

    def runs(self, part: RunPart) -> bool:
        """Часть идёт в этом запуске: основа готова, часть работает и готова, и идёт её опора."""
        if self.is_nothing_ready or part not in (ready.part for ready in self.in_state(PartState.READY)):
            return False
        support: RunPart | None = self.plan.requires(part)
        return support is None or self.runs(support)

    def scope(self, dry_run: bool) -> RunScope:
        """Части, которые идут в этом запуске, и пробный ли он — одним значением для частей запуска."""
        return RunScope(parts=frozenset(part for part in RunPart if self.runs(part)), dry_run=dry_run)

    @property
    def step(self) -> ModeStep:
        """Что делает запуск: не работает ни одна линия или не готова основа — окно; иначе прогон основы — таблицы плана
        (режим А) или пакетов (режим Б)."""
        if self.is_nothing_ready:
            return ModeStep.OPEN_SETUP
        return ModeStep.RUN_PLAN if self.parts[0].part is RunPart.PLAN else ModeStep.RUN_PACKAGES

    @property
    def outcome(self) -> RunOutcome:
        """Исход готовности: есть не настроенная работающая часть — ошибка (§10, код 1). Линия без опоры — не ошибка
        (§14 решение 37): она не работает и ничего не требует."""
        return RunOutcome.FAILED if self.in_state(PartState.BLOCKED) else RunOutcome.DONE

    @property
    def lines(self) -> tuple[str, ...]:
        """Строки для консоли: «включите линии», если не работает ни одна, затем по строке на текст нужды с перечнем
        частей, которым её не хватает, на месте первой такой части. Разные нужды с одним текстом — одна строка."""
        lines: list[str] = list(self.plan.console_lines)
        said: set[str] = set()
        for part in self.parts:
            for gap in part.unmet:
                if gap.text not in said:
                    said.add(gap.text)
                    lines.append(self._need_line(gap.text))
        return tuple(lines)

    @property
    def event(self) -> LogEvent:
        """Строка лога: работающие части по состоянию, идущие и линии без опоры."""
        return LogEvent.of(
            LinePlanEvent.READINESS,
            ready=self._part_ids(PartState.READY),
            blocked=self._part_ids(PartState.BLOCKED),
            runs=tuple(part for part in RunPart if self.runs(part)),
            no_support=tuple(line.part for line in self.plan.unsupported),
        )

    @property
    def snapshot(self) -> LogEvent:
        """Снимок линий запуска (§14 решение 38): по полю на линию — включена, состояние, идёт ли, чего не хватает."""
        fields: dict[str, str] = {}
        for line in self.plan.lines:
            found: PartReadiness | None = next((part for part in self.parts if part.part is line.part), None)
            unmet: str = NEED_JOINER.join(gap.need.value for gap in found.unmet) if found else ""
            fields[line.part.value] = LINE_SNAPSHOT_TEMPLATE.format(
                on=self._yes_no(line.is_on), state=line.state.value, ready=self._yes_no(self.runs(line.part)),
                unmet=unmet or LogValue.EMPTY.value,
            )
        return LogEvent.of(LinePlanEvent.SNAPSHOT, **fields)

    def _yes_no(self, value: bool) -> str:
        return LogValue.YES.value if value else LogValue.NO.value

    def _need_line(self, text: str) -> str:
        """Текст нужды и все работающие части, которым не хватает нужды с этим текстом."""
        labels: tuple[str, ...] = tuple(part.part.human_label for part in self.parts if part.lacks(text))
        return msg.RUN_NEED_BLOCKED.format(parts=msg.LIST_JOINER.join(labels), gap=text)

    def _part_ids(self, state: PartState) -> tuple[RunPart, ...]:
        return tuple(part.part for part in self.in_state(state))
