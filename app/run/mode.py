"""Режим запуска и его части (CLAUDE.md §10, §14 решения 17, 18).

Режим — всё, что запросил ярлык, одним полем. Режим А из таблицы: «объявления» (--announce), «эфиры» (--broadcast),
«всё» (без ключа); режим Б «эфиры из пакетов» (--from-package). Служебные запуски — настройщик (--setup), проверка
каналов (--check), вход (--auth), сверка (--status): частей работы у них нет.

Режим работы — упорядоченный набор частей; готовность считается по частям: не готова часть — остальное делается,
по ней одна строка. Часть знает только себя: своё имя для людей, реализована ли она в этой версии и на каком этапе
появится. Что нужно части для готовности, решает Readiness (app\\setup\\readiness.py): там прочитанные сейф и конфиги.
Итог — `PartReadiness` на каждую часть и `ModeReadiness` на режим; что делает запуск режима (`ModeStep`) и каков
исход готовности, решает сам `ModeReadiness`, а не запуск.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.observability.log_event import LogEvent
from app.run.exit_code import RunOutcome
from app.run.flag import CliFlag
from app.ui import messages_ru as msg


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
    def not_built_line(self) -> str | None:
        """Одна строка о нереализованной части: когда появится. Реализованная — None."""
        if self.is_built:
            return None
        template: str = msg.RUN_PART_NOT_BUILT_TEXTS.get(self.value, msg.RUN_PART_NOT_BUILT)
        return template.format(part=self.human_label, stage=msg.RUN_PART_STAGES[self.value])


# Части, которых в этой версии ещё нет: их неготовность — не ошибка настройки, а «появится позже».
# Без нейросети режим А идёт как с --no-llm: тексты слотов — из видео (SlotTexts.from_sources).
NOT_BUILT_PARTS: Final[frozenset[RunPart]] = frozenset(
    {RunPart.MERGE, RunPart.ANNOUNCE, RunPart.BROADCAST, RunPart.PACKAGES_IN}
)


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
    OPEN_SETUP = "open_setup"    # не готово ничего: строки частей, окно настройщика, код 2
    REPORT = "report"            # таблица плана режиму не нужна: сводка и строки частей
    RUN_PLAN = "run_plan"        # таблица готова: сводка, строки частей, прогон контура A


@dataclass(frozen=True)
class PartReadiness:
    """Готовность одной части режима: готова ли, реализована ли в этой версии и что сделать, если нет.

    `action` — одна строка для оператора: у не готовой части — что задать и где, у нереализованной — когда
    появится; у готовой — None. Ни значений, ни путей к файлам ключей в строке нет (§7.4).
    """

    part: RunPart
    is_ready: bool
    is_built: bool
    action: str | None

    @property
    def is_blocked(self) -> bool:
        """Часть есть в этой версии, но не настроена."""
        return self.is_built and not self.is_ready


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

    @property
    def ready(self) -> tuple[PartReadiness, ...]:
        return tuple(part for part in self.parts if part.is_built and part.is_ready)

    @property
    def blocked(self) -> tuple[PartReadiness, ...]:
        return tuple(part for part in self.parts if part.is_blocked)

    @property
    def not_built(self) -> tuple[PartReadiness, ...]:
        return tuple(part for part in self.parts if not part.is_built)

    @property
    def is_nothing_ready(self) -> bool:
        """Есть реализованные части, и ни одна не готова, либо не готова основа режима.

        Режим, в котором реализованных частей ещё нет (режим Б этой версии), настройкой не лечится: окно
        для него не открывается, строки «пока нет» говорят сами за себя.
        """
        base: PartReadiness | None = self.parts[0] if self.parts else None
        if base is not None and base.is_blocked:
            return True
        has_built: bool = any(part.is_built for part in self.parts)
        return has_built and not self.ready

    def is_part_ready(self, part: RunPart) -> bool:
        """Часть есть в режиме, реализована и готова."""
        return any(ready.part is part for ready in self.ready)

    @property
    def step(self) -> ModeStep:
        """Что делает запуск: не готово ничего — отказ или окно; готова таблица плана — её прогон; иначе — сводка."""
        if self.is_nothing_ready:
            return ModeStep.OPEN_SETUP if self.is_fixable_in_setup else ModeStep.REFUSE
        return ModeStep.RUN_PLAN if self.is_part_ready(RunPart.PLAN) else ModeStep.REPORT

    @property
    def outcome(self) -> RunOutcome:
        """Исход готовности режима: есть реализованная, но не настроенная часть — ошибка (§10, код 1)."""
        return RunOutcome.FAILED if self.blocked else RunOutcome.DONE

    @property
    def lines(self) -> tuple[str, ...]:
        """Строки для консоли: по одной на каждую не готовую и каждую нереализованную часть, по порядку работы."""
        return tuple(part.action for part in self.parts if part.action is not None)

    @property
    def event(self) -> LogEvent:
        """Строка лога: режим и части по состоянию."""
        return LogEvent.of(
            ModeEvent.READINESS,
            mode=self.mode,
            ready=self._part_ids(self.ready),
            blocked=self._part_ids(self.blocked),
            not_built=self._part_ids(self.not_built),
        )

    def _part_ids(self, parts: tuple[PartReadiness, ...]) -> tuple[RunPart, ...]:
        return tuple(part.part for part in parts)
