"""Часы livecraft — единственное «сейчас» программы (CLAUDE.md §11, правило E17).

Отметки времени в файлах, именах и строках лога ставятся по поясу программы (CLAUDE.md §6, инвариант 4),
а не по поясу машины: оператор и отчёт живут по Киеву, где бы ни стояла машина. Поэтому «сейчас» берётся
только у объекта `Clock` с полем `zone`; тесты подменяют часы своим объектом с остановленным временем.
Длительность — разность двух моментов `now()`, секунды эпохи — `now().timestamp()`: у часов один источник
времени, и остановленные часы тестов останавливают всё сразу.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo


@dataclass(frozen=True)
class Clock:
    """Часы в поясе `zone`."""

    zone: tzinfo

    @classmethod
    def utc(cls) -> Clock:
        """Часы для замеров, где пояс не участвует: длительность обращения, секунды эпохи."""
        return cls(timezone.utc)

    def now(self) -> datetime:
        """Текущий момент в поясе часов."""
        return datetime.now(self.zone)

    def local_time(self, epoch_seconds: float) -> time.struct_time:
        """Секунды эпохи → календарное время в поясе часов: так время записей лога пишется по поясу программы."""
        return datetime.fromtimestamp(epoch_seconds, self.zone).timetuple()
