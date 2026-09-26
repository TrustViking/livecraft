"""Форматы дат и времени livecraft — единственный источник (CLAUDE.md §6, инвариант 4).

Даты `DD-MM-YYYY`, время `HH:MM` — во всех файлах, именах и отчётах. Исключение — `parse_iso_start`:
`start` слота и `slot_start_utc` в памяти пишутся ISO-8601 со смещением, только для сравнения моментов.
Здесь только чистые преобразования без знания о предметных объектах — разрешённое §0 исключение.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import ClassVar, Final

DATE_FORMAT: Final[str] = "%d-%m-%Y"
TIME_FORMAT: Final[str] = "%H:%M"
DATETIME_FORMAT: Final[str] = f"{DATE_FORMAT} {TIME_FORMAT}"
TIMESTAMP_FORMAT: Final[str] = f"{DATETIME_FORMAT}:%S"   # отметка журнала: дата и время с секундами
ISO_TIMESPEC: Final[str] = "seconds"                     # ISO-8601 моментов — до секунд
SECONDS_PER_MINUTE: Final[int] = 60
MINUTES_PER_HOUR: Final[int] = 60
FILE_STAMP_FORMAT: Final[str] = "%d-%m-%Y_%H%M%S"   # имя файла: дата_время_наименование
SLOT_TIME_FORMAT: Final[str] = "%H%M"
SLOT_ID_TEMPLATE: Final[str] = "{date}_{time}_{language}"


def parse_date(text: str) -> date:
    return datetime.strptime(text, DATE_FORMAT).date()


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def parse_time(text: str) -> time:
    return datetime.strptime(text, TIME_FORMAT).time()


def format_time(value: time) -> str:
    return value.strftime(TIME_FORMAT)


def format_datetime_text(value: datetime) -> str:
    return value.strftime(DATETIME_FORMAT)


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


def build_slot_id(date_text: str, time_text: str, language: str) -> str:
    """slot_id = {DD-MM-YYYY}_{HHMM}_{lang} (CLAUDE.md §4); неверные дата или время — ValueError."""
    return SLOT_ID_TEMPLATE.format(
        date=format_date(parse_date(date_text)),
        time=parse_time(time_text).strftime(SLOT_TIME_FORMAT),
        language=language,
    )
