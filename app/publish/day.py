"""День объявлений: дата эфиров, форма ключей и их слоты — общий день документа и Telegram (CLAUDE.md §3 шаг 6a, §13
задача 4.5, §14 решение 51).

`PublishDay` — дата эфиров (DD-MM-YYYY, инвариант 4), форма ключей её слотов и сами слоты в порядке слотов запуска;
`days` — единственная группировка слотов запуска по дате и форме: по ней идут и документ объявлений (`DocDay`), и
объявления в Telegram (`AnnounceDay`). У слотов одной даты разные формы (пакеты разных операторов) — отдельный день на
каждую форму: свой документ и своё объявление; номер дня среди дней той же даты (`number`) различает их имена.
`DayTimes` — время дня для стримеров: дата для людей DD.MM.YYYY (§14 решение 31), время первого эфира дня по CET/CEST,
по поясу программы и по GMT и срок сдачи ключей — за час до первого эфира.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final
from zoneinfo import ZoneInfo

from app.config.settings import FormSettings
from app.core.dates import format_time
from app.packages.package_slot import PackageSlot
from app.slots.slot import StreamSlot

# Центральноевропейское время шапки: Берлин сам переходит между CET и CEST.
CET_ZONE: Final[ZoneInfo] = ZoneInfo("Europe/Berlin")
# Ключи потоков стримеры сдают за час до первого эфира даты.
KEYS_LEAD: Final[timedelta] = timedelta(hours=1)


@dataclass(frozen=True)
class DayTimes:
    """Время дня для шапки: дата DD.MM.YYYY, первый эфир по CET/CEST, поясу программы и GMT, срок ключей по поясу
    программы и GMT (HH:MM)."""

    date: str
    time_cet: str
    time_local: str
    time_gmt: str
    keys_local: str
    keys_gmt: str

    @classmethod
    def of(cls, human_date: str, first: datetime) -> DayTimes:
        """Время по моменту первого эфира в поясе программы. Срок ключей — час по ходу времени, а не по циферблату:
        в ночь перевода часов они расходятся."""
        keys: datetime = (first.astimezone(timezone.utc) - KEYS_LEAD).astimezone(first.tzinfo)
        return cls(
            date=human_date,
            time_cet=format_time(first.astimezone(CET_ZONE).time()),
            time_local=format_time(first.time()),
            time_gmt=format_time(first.astimezone(timezone.utc).time()),
            keys_local=format_time(keys.time()),
            keys_gmt=format_time(keys.astimezone(timezone.utc).time()),
        )

    @property
    def values(self) -> Mapping[str, str]:
        """Подстановки шаблонов шапки по именам полей."""
        return dict(vars(self))


@dataclass(frozen=True)
class PublishDay:
    """Дата эфиров DD-MM-YYYY, форма ключей и их слоты в порядке слотов запуска; `number` — место дня среди дней той же
    даты (с 1)."""

    date: str
    form: FormSettings
    slots: tuple[StreamSlot, ...]
    number: int

    @classmethod
    def days(cls, items: Sequence[PackageSlot]) -> tuple[PublishDay, ...]:
        """Слоты по дате и форме: дни — в порядке их первого слота, слоты дня — в порядке запуска."""
        days: list[PublishDay] = []
        for item in items:
            found: PublishDay | None = next(
                (day for day in days if day.date == item.slot.date and day.form == item.form), None
            )
            if found is None:
                number: int = sum(1 for day in days if day.date == item.slot.date) + 1
                days.append(cls(item.slot.date, item.form, (item.slot,), number))
            else:
                days[days.index(found)] = cls(found.date, found.form, (*found.slots, item.slot), found.number)
        return tuple(days)

    def is_same(self, other: PublishDay) -> bool:
        """Тот же день: та же дата и то же место среди дней даты."""
        return self.date == other.date and self.number == other.number

    @property
    def human_date(self) -> str:
        """Дата эфиров DD.MM.YYYY — для текстов людям (§14 решение 31)."""
        return self.slots[0].human_date

    @property
    def first_start(self) -> datetime:
        """Момент первого эфира даты в поясе программы."""
        return min(slot.start for slot in self.slots)

    @property
    def times(self) -> DayTimes:
        return DayTimes.of(self.human_date, self.first_start)
