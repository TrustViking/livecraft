"""Режим запуска, его части и их нужды (CLAUDE.md §10, §14 решения 17, 18).

Режим — всё, что запросил ярлык, одним полем. Режим А из таблицы: «объявления» (--announce), «эфиры» (--broadcast),
«всё» (без ключа); режим Б «эфиры из пакетов» (--from-package). Служебные запуски — настройщик (--setup), проверка
каналов (--check), вход (--auth), сверка (--status): частей работы у них нет.

Режим работы — упорядоченный набор частей; готовность считается по частям: не готова часть — остальное делается.
Часть знает себя: своё имя для людей, реализована ли она в этой версии, на каком этапе появится и что ей нужно
(`RunPart.needs`). Удовлетворена ли нужда и что сделать, если нет, решает `Readiness.gap` (app\\setup\\readiness.py):
там прочитанные сейф и конфиги. Итог — `PartReadiness` на каждую часть и `ModeReadiness` на режим: одна строка
на каждую нужду, которой не хватает, с перечнем частей, которым она нужна. Что делает запуск режима (`ModeStep`)
и каков исход готовности, решает сам `ModeReadiness`, а не запуск.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.observability.log_event import LogEvent
from app.run.exit_code import RunOutcome
from app.run.flag import CliFlag
from app.ui import messages_ru as msg


class Need(str, Enum):
    """Что нужно части запуска, чтобы работать. Значение — английский идентификатор для лога."""

    SHEETS_VAULT = "sheets_vault"        # id и диапазон таблицы плана в сейфе
    OPENAI_VAULT = "openai_vault"        # ключ OpenAI в сейфе
    SETTINGS = "settings"                # livecraft.json прочитан
    FORM = "form"                        # ссылка на форму ключей задана
    CHANNELS = "channels"                # channels.json прочитан
    CLIENT_SECRET = "client_secret"      # client_secret.json рядом с программой (§9)


class RunPart(str, Enum):
    """Часть работы одного запуска. Значение — английский идентификатор для лога."""

    PLAN = "plan"                  # чтение таблицы плана, источники, слоты
    MERGE = "merge"                # одно название и одно описание на слот нейросетью
    PACKAGE = "package"            # пакет plan_*.bcast в bcast\
    ANNOUNCE = "announce"          # Google Doc и Telegram — этап «Публикация»
    BROADCAST = "broadcast"        # эфиры на YouTube, ключи, форма
    PACKAGES_IN = "packages_in"    # чтение пакетов из bcast\ — режим Б

    @property
    def human_label(self) -> str:
        return msg.RUN_PART_LABELS[self.value]

    @property
    def is_built(self) -> bool:
        """Реализована ли часть в этой версии программы."""
        return self not in NOT_BUILT_PARTS

    @property
    def needs(self) -> tuple[Need, ...]:
        """Что нужно части — в том порядке, в каком об этом говорить человеку."""
        return PART_NEEDS[self]

    @property
    def not_built_line(self) -> str:
        """Одна строка о части, которой в этой версии нет: когда появится."""
        template: str = msg.RUN_PART_NOT_BUILT_TEXTS.get(self.value, msg.RUN_PART_NOT_BUILT)
        return template.format(part=self.human_label, stage=msg.RUN_PART_STAGES[self.value])


# Части, которых в этой версии ещё нет: их неготовность — не ошибка настройки, а «появится позже».
# Без нейросети режим А идёт как с --no-llm: тексты слотов — из видео (SlotTexts.from_sources).
NOT_BUILT_PARTS: Final[frozenset[RunPart]] = frozenset(
    {RunPart.MERGE, RunPart.ANNOUNCE, RunPart.BROADCAST, RunPart.PACKAGES_IN}
)
# Что нужно каждой части (§7.5, §9): таблице — сейф таблицы, настройки и вход в Google; нейросети — ключ OpenAI;
# пакету — настройки и форма; эфирам — каналы, настройки и форма. Объявлениям и чтению пакетов — появится с ними.
PART_NEEDS: Final[dict[RunPart, tuple[Need, ...]]] = {
    RunPart.PLAN: (Need.SHEETS_VAULT, Need.SETTINGS, Need.CLIENT_SECRET),
    RunPart.MERGE: (Need.OPENAI_VAULT,),
    RunPart.PACKAGE: (Need.SETTINGS, Need.FORM),
    RunPart.ANNOUNCE: (),
    RunPart.BROADCAST: (Need.CHANNELS, Need.SETTINGS, Need.FORM),
    RunPart.PACKAGES_IN: (),
}


class RunMode(str, Enum):
    """Что запросил ярлык. Значение — английский идентификатор для лога."""

    ANNOUNCE = "announce"            # А: таблица → merge → пакет → объявления
    BROADCAST = "broadcast"          # А: таблица → merge → пакет → эфиры
    ALL = "all"                      # А: объявления, затем эфиры; ключа нет
    FROM_PACKAGE = "from_package"    # Б: пакеты из bcast\ → эфиры
    SETUP = "setup"                  # окно настройщика
    CHECK = "check"                  # проверка каналов
    AUTH = "auth"                    # вход в канал заново
    STATUS = "status"                # сверка эфиров без таблицы и нейросети

    @property
    def is_from_table(self) -> bool:
        """Режим А: слоты собираются из таблицы плана."""
        return self in MODE_OUTPUTS

    @property
    def is_service(self) -> bool:
        """Служебный запуск, а не работа режима: частей работы у него нет."""
        return self in SERVICE_MODES

    @property
    def flag(self) -> CliFlag | None:
        """Ключ командной строки режима; у режима «всё» ключа нет."""
        return MODE_FLAGS.get(self)

    def parts(self, no_llm: bool) -> tuple[RunPart, ...]:
        """Части режима по порядку работы. --no-llm убирает merge; в режиме Б нейросети нет вовсе."""
        if self.is_service:
            return ()
        if not self.is_from_table:
            return (RunPart.PACKAGES_IN, RunPart.BROADCAST)
        table: tuple[RunPart, ...] = (RunPart.PLAN,) if no_llm else (RunPart.PLAN, RunPart.MERGE)
        return (*table, RunPart.PACKAGE, *MODE_OUTPUTS[self])


# Выводы режима А после пакета: что делается из слотов в памяти (§14 решение 17).
MODE_OUTPUTS: Final[dict[RunMode, tuple[RunPart, ...]]] = {
    RunMode.ANNOUNCE: (RunPart.ANNOUNCE,),
    RunMode.BROADCAST: (RunPart.BROADCAST,),
    RunMode.ALL: (RunPart.ANNOUNCE, RunPart.BROADCAST),
}
SERVICE_MODES: Final[frozenset[RunMode]] = frozenset({RunMode.SETUP, RunMode.CHECK, RunMode.AUTH, RunMode.STATUS})
MODE_FLAGS: Final[dict[RunMode, CliFlag]] = {
    RunMode.ANNOUNCE: CliFlag.ANNOUNCE,
    RunMode.BROADCAST: CliFlag.BROADCAST,
    RunMode.FROM_PACKAGE: CliFlag.FROM_PACKAGE,
    RunMode.SETUP: CliFlag.SETUP,
    RunMode.CHECK: CliFlag.CHECK,
    RunMode.AUTH: CliFlag.AUTH,
    RunMode.STATUS: CliFlag.STATUS,
}


class ModeEvent(str, Enum):
    """События режима в логе."""

    READINESS = "mode_readiness"


class ModeStep(str, Enum):
    """Что делает запуск режима по его готовности. Значение — идентификатор для лога."""

    REFUSE = "refuse"            # не готово ничего, и окно не поможет: строки проблем, код 2
    OPEN_SETUP = "open_setup"    # не готово ничего: строки нужд, окно настройщика, код 2
    REPORT = "report"            # таблица плана режиму не нужна: сводка и строки нужд
    RUN_PLAN = "run_plan"        # таблица готова: сводка, строки нужд, прогон контура A


class PartState(str, Enum):
    """Состояние части режима. Значение — идентификатор для лога."""

    READY = "ready"              # реализована, и всё нужное есть
    BLOCKED = "blocked"          # реализована, но чего-то не хватает
    NOT_BUILT = "not_built"      # в этой версии её ещё нет


@dataclass(frozen=True)
class NeedGap:
    """Нужда, которой не хватает, и одна строка для человека: что задать и где (§7.4: без значений)."""

    need: Need
    text: str


@dataclass(frozen=True)
class PartReadiness:
    """Готовность одной части режима: чего ей не хватает (`unmet`) и что из этого следует (`state`)."""

    part: RunPart
    unmet: tuple[NeedGap, ...]

    @property
    def state(self) -> PartState:
        if not self.part.is_built:
            return PartState.NOT_BUILT
        return PartState.BLOCKED if self.unmet else PartState.READY

    def lacks(self, need: Need) -> bool:
        """Не готова ли часть из-за этой нужды."""
        return self.state is PartState.BLOCKED and any(gap.need is need for gap in self.unmet)


@dataclass(frozen=True)
class ModeReadiness:
    """Готовность выбранного режима по частям — в порядке работы режима.

    Первая часть режима — его основа: в режиме А из таблицы берутся все слоты, и без чтения таблицы не
    делается ничего. Поэтому не готовая основа — это «не готово ничего», даже если у остальных частей
    всё настроено. `is_fixable_in_setup` — ложь, когда повреждён файл ключей и ссылок, пришедший с программой:
    его заменяет только установка, и окно открывать незачем. Повреждённый личный файл окно заменяет первым
    сохранением — тогда истина.
    """

    mode: RunMode
    parts: tuple[PartReadiness, ...]
    is_fixable_in_setup: bool

    def in_state(self, state: PartState) -> tuple[PartReadiness, ...]:
        """Части режима в этом состоянии, по порядку работы."""
        return tuple(part for part in self.parts if part.state is state)

    @property
    def is_nothing_ready(self) -> bool:
        """Есть реализованные части, и ни одна не готова, либо не готова основа режима.

        Режим, в котором реализованных частей ещё нет (режим Б этой версии), настройкой не лечится: окно
        для него не открывается, строки «пока нет» говорят сами за себя.
        """
        if self.parts and self.parts[0].state is PartState.BLOCKED:
            return True
        has_built: bool = any(part.state is not PartState.NOT_BUILT for part in self.parts)
        return has_built and not self.in_state(PartState.READY)

    def is_part_ready(self, part: RunPart) -> bool:
        """Часть есть в режиме, реализована и готова."""
        return any(ready.part is part for ready in self.in_state(PartState.READY))

    @property
    def step(self) -> ModeStep:
        """Что делает запуск: не готово ничего — отказ или окно; готова таблица плана — её прогон; иначе — сводка."""
        if self.is_nothing_ready:
            return ModeStep.OPEN_SETUP if self.is_fixable_in_setup else ModeStep.REFUSE
        return ModeStep.RUN_PLAN if self.is_part_ready(RunPart.PLAN) else ModeStep.REPORT

    @property
    def outcome(self) -> RunOutcome:
        """Исход готовности режима: есть реализованная, но не настроенная часть — ошибка (§10, код 1)."""
        return RunOutcome.FAILED if self.in_state(PartState.BLOCKED) else RunOutcome.DONE

    @property
    def lines(self) -> tuple[str, ...]:
        """Строки для консоли по порядку работы: нереализованная часть — своя строка; нехватка — одна строка
        на нужду с перечнем частей, которым её не хватает, на месте первой такой части."""
        lines: list[str] = []
        said: set[Need] = set()
        for part in self.parts:
            if part.state is PartState.NOT_BUILT:
                lines.append(part.part.not_built_line)
            for gap in part.unmet if part.state is PartState.BLOCKED else ():
                if gap.need not in said:
                    said.add(gap.need)
                    lines.append(self._need_line(gap))
        return tuple(lines)

    @property
    def event(self) -> LogEvent:
        """Строка лога: режим и части по состоянию."""
        return LogEvent.of(
            ModeEvent.READINESS,
            mode=self.mode,
            ready=self._part_ids(PartState.READY),
            blocked=self._part_ids(PartState.BLOCKED),
            not_built=self._part_ids(PartState.NOT_BUILT),
        )

    def _need_line(self, gap: NeedGap) -> str:
        """Нужда и все части режима, которым её не хватает."""
        labels: tuple[str, ...] = tuple(part.part.human_label for part in self.parts if part.lacks(gap.need))
        return msg.RUN_NEED_BLOCKED.format(parts=msg.LIST_JOINER.join(labels), gap=gap.text)

    def _part_ids(self, state: PartState) -> tuple[RunPart, ...]:
        return tuple(part.part for part in self.in_state(state))
