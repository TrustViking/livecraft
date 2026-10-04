"""Слоты запуска с формой ключей каждого — то, с чем идут вывод и эфиры от любого входа (CLAUDE.md §4, §14 решения 13,
50, 51).

Вход даёт слоты с формой ключей: «Таблица» — все годные слоты сборки с формой настроек (`of_table`); «Пакеты» — будущие
слоты полки с формой своего пакета (`of_shelf`: прошедшие отпали, из повторов остался слот новейшего пакета — правила
полки); форма пакета главнее формы настроек. Слоты одной формы — `FormSlots`: по пакету на форму пишет `packages`
(«Пакеты → Пакет» — актуализация полки), по формам делят даты документ и Telegram. В пакет и на YouTube идут только
слоты для YouTube (`for_youtube`, §14 решение 32).
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.config.settings import FormSettings, LivecraftSettings
from app.packages.package import SlotPackage
from app.packages.package_shelf import PackageShelf
from app.packages.package_slot import FormSlots, PackageSlot
from app.slots.slot import StreamSlot


@dataclass(frozen=True)
class RunSlots:
    """Слоты запуска с формой каждого, в порядке слотов входа."""

    items: tuple[PackageSlot, ...]

    @classmethod
    def of_table(cls, slots: Sequence[StreamSlot], form: FormSettings) -> RunSlots:
        """Вход «Таблица»: годные слоты сборки — со слотами «по номерам» — и форма настроек у всех."""
        return cls(PackageSlot.with_form(slots, form))

    @classmethod
    def of_shelf(cls, shelf: PackageShelf) -> RunSlots:
        """Вход «Пакеты»: будущие слоты полки с формой своего пакета."""
        return cls(shelf.slots)

    @property
    def slots(self) -> tuple[StreamSlot, ...]:
        return tuple(item.slot for item in self.items)

    @property
    def for_youtube(self) -> RunSlots:
        """Слоты, которые идут в пакет и на YouTube: тексты «по номерам» — только для людей."""
        return RunSlots(tuple(item for item in self.items if item.slot.is_for_youtube))

    @property
    def by_form(self) -> tuple[FormSlots, ...]:
        """Слоты по формам: формы — в порядке их первого слота, слоты формы — в порядке запуска."""
        forms: list[FormSettings] = []
        for item in self.items:
            if item.form not in forms:
                forms.append(item.form)
        return tuple(
            FormSlots(form, tuple(item.slot for item in self.items if item.form == form)) for form in forms
        )

    def packages(
        self, settings: LivecraftSettings, generated_at: datetime, new_id: Callable[[], str]
    ) -> tuple[SlotPackage, ...]:
        """Пакеты запуска из слотов для YouTube — по пакету на форму, у каждого свой id; место пакета среди них —
        в имени файла (`SlotPackage.order`): пакеты одного периода и одной минуты сборки не затирают друг друга."""
        return tuple(
            dataclasses.replace(SlotPackage.of(group, settings, generated_at, new_id()), order=place)
            for place, group in enumerate(self.for_youtube.by_form)
        )
