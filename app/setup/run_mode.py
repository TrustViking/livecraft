"""Режим запуска и его части (CLAUDE.md §10, §14 решения 17, 18).

Режим задаёт ярлык: «объявления» (--announce), «эфиры» (--broadcast), «всё» (без флага) — режим А из таблицы;
«эфиры из пакетов» (--from-package) — режим Б. Каждый режим — упорядоченный набор частей работы; готовность
считается по частям (app\\setup\\readiness.py): не готова часть — остальное делается, по ней одна строка.

Часть знает только себя: своё имя для людей, реализована ли она в этой версии и на каком этапе появится.
Что нужно части для готовности, решает Readiness — там лежат прочитанные сейф и конфиги.
"""
from __future__ import annotations

from enum import Enum
from typing import Final

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
        return msg.RUN_PART_NOT_BUILT.format(part=self.human_label, stage=msg.RUN_PART_STAGES[self.value])


# Части, которых в этой версии ещё нет: их неготовность — не ошибка настройки, а «появится позже».
NOT_BUILT_PARTS: Final[frozenset[RunPart]] = frozenset({RunPart.ANNOUNCE, RunPart.PACKAGES_IN})


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
