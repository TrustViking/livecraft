"""Чистые преобразования текста таблицы плана: дата и время ряда, имя колонки шапки, диапазон листа в нотации A1
и буквы колонки (CLAUDE.md §2 контур A, §5, §14 решение 26).

Ни одна функция не знает о рядах, плане и слотах — разрешённое §0 исключение «чистое преобразование без знания
о предметных объектах». Правила над рядами живут в `app\\sheets\\`; id видео в ячейке ссылки —
`app\\core\\youtube_video.py::YouTubeVideoId`.
"""
from __future__ import annotations

import re
import string
from datetime import datetime, timezone, tzinfo
from enum import Enum
from typing import ClassVar, Final
from zoneinfo import ZoneInfo

from app.core.alphabet import CYRILLIC_LOWER, LATIN_LOWER, YO_FOLD
from app.core.dates import require_aware

# Форматы ячеек, порядок важен: берётся первый подошедший.
SHEET_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",       # так пишет даты сама программа (§6 инвариант 4)
    "%d-%m-%y",
    "%Y-%m-%d",
    "%d%m%y",
    "%d%m%Y",
)
SHEET_TIME_FORMATS: Final[tuple[str, ...]] = (
    "%H:%M",
    "%H.%M",
    "%H%M",
    "%H:%M:%S",
    "%I:%M %p",
    "%I %p",
)
# Имя колонки для сравнения: после нижнего регистра и свёртки «ё → е» остаются только буквы обоих алфавитов
# (украинские і ї є ґ — тоже) и цифры.
HEADER_JUNK_PATTERN: Final[re.Pattern[str]] = re.compile(f"[^{LATIN_LOWER}{CYRILLIC_LOWER}0-9]+")
# Нотация A1: название листа — в одинарных кавычках (кавычка внутри удваивается), «!» отделяет его от ячеек;
# первая строка листа — «1:1». Колонки листа — латинские буквы: A…Z, затем AA, AB…
SHEET_TITLE_QUOTE: Final[str] = "'"
SHEET_CELLS_MARK: Final[str] = "!"
FIRST_ROW_CELLS: Final[str] = "1:1"
COLUMN_ALPHABET: Final[str] = string.ascii_uppercase


class SheetCellError(ValueError):
    """Ячейка даты или времени не подошла ни под один формат. Ряд с ней отсеивается, до человека ошибка не доходит."""

    TEXT: ClassVar[str] = "unsupported {cell} format: {raw!r}"

    def __init__(self, cell: SheetCell, raw: str) -> None:
        super().__init__(self.TEXT.format(cell=cell.value, raw=raw))


class SheetCell(str, Enum):
    """Ячейка ряда, у которой есть формат: дата или время."""

    DATE = "date"
    TIME = "time"

    @property
    def formats(self) -> tuple[str, ...]:
        return SHEET_DATE_FORMATS if self is SheetCell.DATE else SHEET_TIME_FORMATS

    def parse(self, raw: str) -> datetime:
        """Значение ячейки (края обрезаются) по первому подошедшему формату; не подошёл ни один — SheetCellError."""
        text: str = raw.strip()
        for pattern in self.formats:
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue
        raise SheetCellError(self, raw)


def parse_sheet_datetime(date_raw: str, time_raw: str, zone: ZoneInfo) -> datetime:
    """Дата и время ряда → момент в зоне `zone`; секунды отбрасываются; негодное — ValueError."""
    parsed_date: datetime = SheetCell.DATE.parse(date_raw)
    parsed_time: datetime = SheetCell.TIME.parse(time_raw)
    return datetime(
        year=parsed_date.year,
        month=parsed_date.month,
        day=parsed_date.day,
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        tzinfo=zone,
    )


def is_real_local_time(value: datetime) -> bool:
    """Существует ли такое местное время в зоне момента: в час перехода на летнее время его нет.

    Момент переводится в UTC и обратно; если часы и минуты не вернулись — местного времени не было.
    Повторяющийся час осени существует (берётся первое наступление, fold=0). Момент без пояса — ValueError.
    """
    zone: tzinfo | None = require_aware(value).tzinfo
    back: datetime = value.astimezone(timezone.utc).astimezone(zone)
    return back.replace(tzinfo=None, fold=0) == value.replace(tzinfo=None, fold=0)


def normalize_header_name(text: str) -> str:
    """Имя колонки шапки для сравнения: нижний регистр, «ё» как «е», только буквы латиницы и кириллицы и цифры."""
    return HEADER_JUNK_PATTERN.sub("", text.strip().lower().translate(YO_FOLD))


def quoted_sheet_title(title: str) -> str:
    """Название листа в нотации A1 — это и диапазон «весь лист»: «План 'А'» → «'План ''А'''»."""
    doubled: str = title.replace(SHEET_TITLE_QUOTE, SHEET_TITLE_QUOTE + SHEET_TITLE_QUOTE)
    return f"{SHEET_TITLE_QUOTE}{doubled}{SHEET_TITLE_QUOTE}"


def sheet_header_range(title: str) -> str:
    """Диапазон первой строки листа в нотации A1: «'План'!1:1»."""
    return f"{quoted_sheet_title(title)}{SHEET_CELLS_MARK}{FIRST_ROW_CELLS}"


def column_letters(index: int) -> str:
    """Номер колонки с 0 → её буквы в таблице: 0 → A, 25 → Z, 26 → AA."""
    letters: str = ""
    number: int = index + 1
    while number > 0:
        number, remainder = divmod(number - 1, len(COLUMN_ALPHABET))
        letters = COLUMN_ALPHABET[remainder] + letters
    return letters
