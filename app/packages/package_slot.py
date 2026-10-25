"""Слот эфира и форма, куда уйдёт его ключ; слоты одной формы (CLAUDE.md §4, §6 инвариант 2, §14 решения 13, 18, 51).

Форма ключей — у каждого слота своя: при входе «Пакеты» — форма его пакета (у пакетов разных операторов формы разные),
при входе «Таблица» — форма настроек у всех слотов. Отбор (app\\pipeline\\selection.py) отдаёт форму слота каждому
объекту эфира; по формам пишутся пакеты запуска и делятся даты документа и Telegram (`FormSlots`).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.config.settings import FormSettings
from app.slots.slot import StreamSlot


@dataclass(frozen=True)
class PackageSlot:
    """Слот и форма ключей его пакета."""

    slot: StreamSlot
    form: FormSettings

    @classmethod
    def with_form(cls, slots: Sequence[StreamSlot], form: FormSettings) -> tuple[PackageSlot, ...]:
        """Слоты с одной формой на всех — вход «Таблица»: форма настроек."""
        return tuple(cls(slot, form) for slot in slots)


@dataclass(frozen=True)
class FormSlots:
    """Форма ключей и её слоты в порядке слотов запуска."""

    form: FormSettings
    slots: tuple[StreamSlot, ...]
