"""Режим запуска и его части (CLAUDE.md §10, §14 решения 17, 18).

Режим задаёт ярлык: «объявления» (--announce), «эфиры» (--broadcast), «всё» (без флага) — режим А из таблицы;
«эфиры из пакетов» (--from-package) — режим Б. Каждый режим — упорядоченный набор частей работы; готовность
считается по частям (app\\setup\\readiness.py): не готова часть — остальное делается, по ней одна строка.

Часть знает только себя: своё имя для людей, реализована ли она в этой версии и на каком этапе появится.
Что нужно части для готовности, решает Readiness — там лежат прочитанные сейф и конфиги.

Здесь же коды выхода (§10): их выбирают и main, и прогон режима (app\\slots\\intake.py), а прогон main не
импортирует. Появится runner.decide_exit → RunExit — переедут туда, как в planers.
"""
from __future__ import annotations

from enum import Enum, IntEnum
from typing import Final

from app.ui import messages_ru as msg


class ExitCode(IntEnum):
    """Коды выхода (CLAUDE.md §10)."""

    OK = 0                 # сделано всё, что можно
    ERRORS = 1             # есть ошибки
    CONFIG = 2             # ошибка конфигурации, сейфа или авторизации — ничего не делалось
    NO_FUTURE_SLOTS = 3    # в таблице нет будущих слотов — к каналам не обращались

    def combined(self, other: ExitCode) -> ExitCode:
        """Общий код двух итогов одного запуска: 2 важнее 3, 3 важнее 1, 1 важнее 0 (§10)."""
        return max(self, other, key=lambda code: EXIT_CODE_WEIGHT[code])


# Порядок важности кодов при сведении: конфигурация > нет будущих слотов > ошибки > всё сделано.
EXIT_CODE_WEIGHT: Final[dict[ExitCode, int]] = {
    ExitCode.OK: 0,
    ExitCode.ERRORS: 1,
    ExitCode.NO_FUTURE_SLOTS: 2,
    ExitCode.CONFIG: 3,
}


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
    """Режим запуска по ярлыку. Значение — английский идентификатор для лога."""

    ANNOUNCE = "announce"            # А: таблица → merge → пакет → объявления
    BROADCAST = "broadcast"          # А: таблица → merge → пакет → эфиры
    ALL = "all"                      # А: объявления, затем эфиры
    FROM_PACKAGE = "from_package"    # Б: пакеты из bcast\ → эфиры

    @classmethod
    def of(cls, *, announce: bool, broadcast: bool, from_package: bool) -> RunMode:
        """Флаги командной строки → режим; без флага — «всё». Взаимоисключаемость держит argparse."""
        if announce:
            return cls.ANNOUNCE
        if broadcast:
            return cls.BROADCAST
        if from_package:
            return cls.FROM_PACKAGE
        return cls.ALL

    @property
    def is_from_table(self) -> bool:
        """Режим А: слоты собираются из таблицы плана."""
        return self is not RunMode.FROM_PACKAGE

    def parts(self, no_llm: bool) -> tuple[RunPart, ...]:
        """Части режима по порядку работы. --no-llm убирает merge; в режиме Б нейросети нет вовсе."""
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
