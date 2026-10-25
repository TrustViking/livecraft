"""День объявлений (app\\publish\\day.py, CLAUDE.md §13 задача 4.5, §14 решение 51): группировка слотов по дате и форме —
общая для документа и Telegram — и время дня для стримеров: первый эфир по CET/CEST, Киеву и GMT зимой, летом и в ночь перевода часов,
срок ключей — за час по ходу времени."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.config.files import ShippedSettings
from app.config.settings import FormSettings
from app.packages.package_slot import PackageSlot
from app.publish.day import DayTimes, PublishDay
from app.slots.slot import StreamSlot
from app.tests.fixtures.announce import KYIV, stream_slot

FORM: FormSettings = ShippedSettings().settings.form
OTHER_FORM: FormSettings = FormSettings(
    url="https://docs.google.com/forms/d/e/OTHER/viewform", fields=FORM.fields, values=FORM.values,
    date_format=FORM.date_format,
)


def _days(*slots: StreamSlot) -> tuple[PublishDay, ...]:
    """Дни слотов одной формы — как у входа «Таблица»."""
    return PublishDay.days(PackageSlot.with_form(slots, FORM))


def test_slots_are_grouped_by_date_in_slot_order() -> None:
    later: StreamSlot = stream_slot(datetime(2026, 9, 29, 19, 0, tzinfo=KYIV))
    evening: StreamSlot = stream_slot(datetime(2026, 9, 28, 21, 0, tzinfo=KYIV), "en")
    early: StreamSlot = stream_slot(datetime(2026, 9, 28, 20, 0, tzinfo=KYIV))
    days: tuple[PublishDay, ...] = _days(early, later, evening)
    assert [day.date for day in days] == ["28-09-2026", "29-09-2026"]
    assert days[0].slots == (early, evening) and days[1].slots == (later,)
    assert days[0].first_start == datetime(2026, 9, 28, 20, 0, tzinfo=KYIV)
    assert days[0].human_date == "28.09.2026"


def test_no_slots_give_no_days() -> None:
    assert _days() == ()


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        # Зима: Киев UTC+2, Берлин UTC+1 (CET); ключи — за час.
        (datetime(2027, 3, 17, 19, 0, tzinfo=KYIV), DayTimes("17.03.2027", "18:00", "19:00", "17:00", "18:00", "16:00")),
        # Лето (с 28-03-2027): Киев UTC+3, Берлин UTC+2 (CEST).
        (datetime(2027, 3, 29, 19, 0, tzinfo=KYIV), DayTimes("29.03.2027", "18:00", "19:00", "16:00", "18:00", "15:00")),
        # Ночь перевода часов: 04:30 уже летнего Киева — 01:30 GMT; за час до него по ходу времени — 00:30 GMT, то
        # есть 02:30 ещё зимнего Киева (по циферблату было бы 03:30 — такого времени в эту ночь нет).
        (datetime(2027, 3, 28, 4, 30, tzinfo=KYIV), DayTimes("28.03.2027", "03:30", "04:30", "01:30", "02:30", "00:30")),
    ],
)
def test_the_day_times_follow_summer_time(start: datetime, expected: DayTimes) -> None:
    assert _days(stream_slot(start))[0].times == expected


def test_the_times_follow_the_first_start_of_the_date_not_the_first_slot() -> None:
    """Срок ключей — от самого раннего эфира даты, в каком бы порядке ни шли слоты."""
    late: StreamSlot = stream_slot(datetime(2026, 10, 16, 21, 0, tzinfo=KYIV), "en")
    first: StreamSlot = stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV))
    [day] = _days(late, first)
    assert (day.times.time_local, day.times.keys_local) == ("19:00", "18:00")


def test_the_values_are_the_template_names_of_the_header() -> None:
    times: DayTimes = DayTimes("16.10.2026", "18:00", "19:00", "16:00", "18:00", "15:00")
    assert times.values == {
        "date": "16.10.2026", "time_cet": "18:00", "time_local": "19:00", "time_gmt": "16:00", "keys_local": "18:00",
        "keys_gmt": "15:00",
    }


def test_one_date_with_two_forms_is_two_days_numbered_within_the_date() -> None:
    """Слоты одной даты из пакетов двух форм — два дня (свой документ и своё объявление), номер — место среди дней
    даты; следующая дата снова с 1."""
    first: StreamSlot = stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV))
    second: StreamSlot = stream_slot(datetime(2026, 10, 16, 20, 0, tzinfo=KYIV), "en")
    third: StreamSlot = stream_slot(datetime(2026, 10, 16, 21, 0, tzinfo=KYIV), "ru")
    next_day: StreamSlot = stream_slot(datetime(2026, 10, 17, 19, 0, tzinfo=KYIV))
    days: tuple[PublishDay, ...] = PublishDay.days((
        PackageSlot(first, FORM), PackageSlot(second, OTHER_FORM), PackageSlot(third, FORM),
        PackageSlot(next_day, OTHER_FORM),
    ))
    assert [(day.date, day.form.url, day.number) for day in days] == [
        ("16-10-2026", FORM.url, 1), ("16-10-2026", OTHER_FORM.url, 2), ("17-10-2026", OTHER_FORM.url, 1)
    ]
    assert days[0].slots == (first, third) and days[1].slots == (second,)
    assert days[0].is_same(days[0]) and not days[0].is_same(days[1])
