"""Форматы дат и времени livecraft — единственный источник (CLAUDE.md §6, инвариант 4).

Даты `DD-MM-YYYY`, время `HH:MM` — в файлах, именах, `slot_id`, пакете и логе. В текстах для людей (документ
объявлений, Telegram, консоль, окно, отчёт) дата — `DD.MM.YYYY` (§14 решение 31: `format_human_date`,
`format_human_datetime`). Исключение — `parse_iso_start`: `start` слота и `slot_start_utc` в памяти пишутся ISO-8601
со смещением, только для сравнения моментов.
Здесь только чистые преобразования без знания о предметных объектах — разрешённое §0 исключение.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone, tzinfo
from typing import ClassVar, Final

DATE_FORMAT: Final[str] = "%d-%m-%Y"
TIME_FORMAT: Final[str] = "%H:%M"
DATETIME_FORMAT: Final[str] = f"{DATE_FORMAT} {TIME_FORMAT}"
HUMAN_DATE_FORMAT: Final[str] = "%d.%m.%Y"                  # дата в текстах для людей: 17.03.2027
HUMAN_DATETIME_FORMAT: Final[str] = f"{HUMAN_DATE_FORMAT} {TIME_FORMAT}"
TIMESTAMP_FORMAT: Final[str] = f"{DATETIME_FORMAT}:%S"   # отметка журнала: дата и время с секундами
ISO_TIMESPEC: Final[str] = "seconds"                     # ISO-8601 моментов — до секунд
SECONDS_PER_MINUTE: Final[int] = 60
MINUTES_PER_HOUR: Final[int] = 60
FILE_STAMP_FORMAT: Final[str] = "%d-%m-%Y_%H%M%S"   # имя файла: дата_время_наименование
SLOT_TIME_FORMAT: Final[str] = "%H%M"                # время старта в `slot_id` и в имени пакета


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def format_time(value: time) -> str:
    return value.strftime(TIME_FORMAT)


def format_datetime_text(value: datetime) -> str:
    return value.strftime(DATETIME_FORMAT)


def parse_datetime_text(text: str, zone: tzinfo) -> datetime:
    """`DD-MM-YYYY HH:MM` по поясу `zone` → момент с поясом; не тот формат — ValueError.

    Пояс — программы, а не машины (инвариант 4): иначе на машине в другом поясе момент сдвинулся бы.
    """
    return datetime.strptime(text, DATETIME_FORMAT).replace(tzinfo=zone)


def format_human_date(value: date) -> str:
    """Дата для людей `DD.MM.YYYY`."""
    return value.strftime(HUMAN_DATE_FORMAT)


def format_human_datetime(value: datetime) -> str:
    """Дата и время для людей `DD.MM.YYYY HH:MM`."""
    return value.strftime(HUMAN_DATETIME_FORMAT)


def format_timestamp(value: datetime) -> str:
    """Отметка журнала `DD-MM-YYYY HH:MM:SS`: два события одной минуты различимы."""
    return value.strftime(TIMESTAMP_FORMAT)


class NaiveMomentError(ValueError):
    """Момент без пояса: его нельзя сравнить ни с минутой старта на YouTube, ни с «сейчас». Ошибка программы."""

    TEXT: ClassVar[str] = "moment without UTC offset: {value!r}"

    def __init__(self, value: object) -> None:
        super().__init__(self.TEXT.format(value=value))


def require_aware(value: datetime) -> datetime:
    """Момент с поясом как есть; без пояса — NaiveMomentError. Единственная проверка «время с поясом»."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise NaiveMomentError(value)
    return value


def parse_iso_start(text: str) -> datetime:
    """`start` слота: ISO-8601 со смещением; без смещения — NaiveMomentError (CLAUDE.md §4)."""
    return require_aware(datetime.fromisoformat(text))



def to_minute(value: datetime) -> datetime:
    """Момент с точностью до минуты в UTC — единственный способ сравнивать время старта слота и эфира на площадке."""
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)
