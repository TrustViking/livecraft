"""Решение по объекту запланированного эфира (CLAUDE.md §6 инварианты 1, 8).

Решения «создать заново» нет: эфира на площадке нет — всегда CREATE, различать «впервые» и «заново» программе нечем
и незачем. Эфиры не удаляются: несколько эфиров без метки на минуту старта — AMBIGUOUS, программа не выбирает.
"""
from __future__ import annotations

from enum import Enum


class Decision(str, Enum):
    CREATE = "create"               # эфира нет
    MATCH = "match"                 # есть, все исправимые поля совпадают
    UPDATE = "update"               # есть, исправимое поле отличается — привести к плану
    NO_STREAM = "no_stream"         # эфир есть, привязанного потока нет — ключ взять неоткуда
    TOO_LATE = "too_late"           # до старта меньше min_lead_minutes — эфир не трогаем
    AMBIGUOUS = "ambiguous"         # несколько эфиров без метки на эту минуту
    ERROR = "error"                 # площадка не ответила по каналу
    NOT_ADMITTED = "not_admitted"   # не допущен к публикации: канал не подтверждён или форма его не примет

    @property
    def publishes(self) -> bool:
        """Запуск ставит эфир на YouTube — создаёт его или даёт ему поток — и берёт его ключ с площадки."""
        return self is Decision.CREATE or self is Decision.NO_STREAM

    @property
    def acts_on_platform(self) -> bool:
        """Полный запуск действует на площадке: ставит эфир или исправляет найденный."""
        return self.publishes or self is Decision.UPDATE
