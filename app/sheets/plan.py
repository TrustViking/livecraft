"""План стримов с листа Google-таблицы (CLAUDE.md §2 контур A, §3 шаг 2.3, §14 решение 26).

Вход — название и id листа и его значения, как их отдаёт `values.get` по всему листу: первая строка — шапка, ряды
данных нумеруются с 2, колонки — с A (как в самой таблице). Сети здесь нет: чтение таблицы — `sheets\\client.py`,
выбор листа — `sheets\\book.py`.

Объекты:
- `PlanColumn` — колонка, которую читает план: ссылка, дата или время; её названия — ресурсы;
- `SheetHeader` — первая строка листа; сама находит колонку по названиям и называет, каких колонок в ней нет;
- `SheetColumns` — где на листе колонки ссылки, даты и времени; строит ряды `SheetRow` (app\\sheets\\rows.py);
- `SheetPlan` — лист, шапка, ряды и прочитанные значения; сам называет свою проблему (`problem`) и разбирает ряды
  (`plan_rows` → `PlannedRows`).

Программа пишет в строку видео только язык видео и ссылку на копию превью (§6 инвариант 3): колонки и запись —
`sheets\\preview.py`, по значениям плана.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final
from zoneinfo import ZoneInfo

from app.core.sheet_text import column_letters, normalize_header_name
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.resources.loader import TextResource
from app.sheets.rows import PlannedRows, SheetRow
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SHEETS)

FIRST_DATA_ROW_NUMBER: Final[int] = 2        # строка 1 листа — шапка
HEADER_ITEM_TEMPLATE: Final[str] = "«{name}»"


class PlanColumn(str, Enum):
    """Колонка, которую план читает с листа. Значение — английский идентификатор, название для человека — `human`."""

    LINK = "link"
    DATE = "date"
    TIME = "time"

    @property
    def aliases(self) -> tuple[str, ...]:
        """Названия колонки из ресурса — от точных к общим: по части заголовка решает порядок названий."""
        return TextResource(ALIAS_RESOURCES[self]).lines

    @property
    def human(self) -> str:
        return msg.SHEET_PLAN_COLUMN_NAMES[self.value]


# Названия колонок шапки — ресурсы: сначала точное совпадение имени, затем вхождение названия в имя.
ALIAS_RESOURCES: Final[dict[PlanColumn, str]] = {
    PlanColumn.LINK: "sheet_header_link.txt",
    PlanColumn.DATE: "sheet_header_date.txt",
    PlanColumn.TIME: "sheet_header_time.txt",
}


class PlanProblem(str, Enum):
    """Почему по плану нельзя работать."""

    EMPTY = "empty"                     # на листе плана под шапкой нет ни одной строки
    HEADER_UNKNOWN = "header_unknown"   # ни на одном листе в первой строке нет колонок ссылки, даты и времени


class PlanEvent(str, Enum):
    """События плана в логе."""

    PROBLEM = "sheet_plan_problem"


@dataclass(frozen=True)
class SheetHeader:
    """Первая строка листа: заголовки колонок как в таблице, без краёв."""

    names: tuple[str, ...]

    @classmethod
    def of(cls, cells: Sequence[object]) -> SheetHeader:
        return cls(tuple(str(cell).strip() for cell in cells))

    @property
    def keys(self) -> tuple[str, ...]:
        """Заголовки в виде для сравнения с названиями колонок (`normalize_header_name`)."""
        return tuple(normalize_header_name(name) for name in self.names)

    def exact_index_of(self, aliases: tuple[str, ...]) -> int | None:
        """Первая колонка, заголовок которой целиком совпадает с одним из названий; нет такой — None."""
        wanted: tuple[str, ...] = self._wanted(aliases)
        return next((index for index, key in enumerate(self.keys) if key in wanted), None)

    def index_of(self, aliases: tuple[str, ...]) -> int | None:
        """Колонка по названиям; не нашлась — None.

        Сначала точное совпадение заголовка с любым названием; затем — по порядку названий: для каждого названия
        первая колонка, в заголовке которой оно есть. Так общее название («час») не перебивает точное («время»),
        даже если его колонка левее.
        """
        exact: int | None = self.exact_index_of(aliases)
        if exact is not None:
            return exact
        keys: tuple[str, ...] = self.keys
        found: tuple[int, ...] = tuple(
            index for alias in self._wanted(aliases) for index, key in enumerate(keys) if alias in key
        )
        return found[0] if found else None

    def _wanted(self, aliases: tuple[str, ...]) -> tuple[str, ...]:
        """Названия в виде для сравнения с заголовками; пустые после приведения не в счёт."""
        return tuple(key for key in (normalize_header_name(alias) for alias in aliases) if key)

    def column(self, column: PlanColumn) -> int | None:
        """Где в шапке колонка плана; нет её — None."""
        return self.index_of(column.aliases)

    @property
    def missing(self) -> tuple[PlanColumn, ...]:
        """Колонки плана, которых в шапке нет, — в порядке `PlanColumn`."""
        return tuple(column for column in PlanColumn if self.column(column) is None)

    @property
    def text(self) -> str:
        """Непустые заголовки для человека: «a», «b»; ни одного — «нет ни одного»."""
        names: list[str] = [HEADER_ITEM_TEMPLATE.format(name=name) for name in self.names if name]
        return msg.LIST_JOINER.join(names) if names else msg.SHEET_PLAN_HEADER_NONE


@dataclass(frozen=True)
class SheetColumns:
    """Индексы (с 0, колонка A — 0) колонок ссылки, даты и времени на листе."""

    link: int
    date: int
    time: int

    @classmethod
    def from_header(cls, header: SheetHeader) -> SheetColumns | None:
        """Колонки по шапке; не нашлась хотя бы одна — None."""
        link: int | None = header.column(PlanColumn.LINK)
        date: int | None = header.column(PlanColumn.DATE)
        time: int | None = header.column(PlanColumn.TIME)
        if link is None or date is None or time is None:
            return None
        return cls(link=link, date=date, time=time)

    def index(self, column: PlanColumn) -> int:
        return {PlanColumn.LINK: self.link, PlanColumn.DATE: self.date, PlanColumn.TIME: self.time}[column]

    @property
    def indexes(self) -> frozenset[int]:
        """Колонки, которые читает план: в них программа не пишет никогда."""
        return frozenset(self.index(column) for column in PlanColumn)

    def letters(self, column: PlanColumn) -> str:
        """Буквы колонки в таблице: так человек найдёт её на листе."""
        return column_letters(self.index(column))

    def row(self, row_number: int, values: Sequence[str]) -> SheetRow:
        """Ряд из значений строки таблицы; ячейки, которых нет (короткий ряд), — пустые."""
        return SheetRow(
            row_number=row_number,
            link=self._cell(values, self.link),
            date_raw=self._cell(values, self.date),
            time_raw=self._cell(values, self.time),
        )

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Колонки для строки лога — буквами листа."""
        return dict(
            link_column=self.letters(PlanColumn.LINK),
            date_column=self.letters(PlanColumn.DATE),
            time_column=self.letters(PlanColumn.TIME),
        )

    def _cell(self, values: Sequence[str], index: int) -> str:
        return str(values[index]).strip() if index < len(values) else ""


@dataclass(frozen=True)
class SheetPlan:
    """План с листа `sheet_title` (id листа `sheet_id`): шапка, распознанные колонки, ряды данных и все прочитанные
    значения листа строками (`values`, первая — шапка): по ним находятся колонки языка и превью (`sheets\\preview.py`).

    Шапка не распознана — `columns` None и рядов нет: план не падает, а называет проблему (`problem`). Так же
    выглядит план таблицы, где подходящего листа нет вовсе: лист — ближайший кандидат (`app\\sheets\\book.py`).
    """

    sheet_title: str
    sheet_id: int
    header: SheetHeader
    columns: SheetColumns | None
    rows: tuple[SheetRow, ...]
    values: tuple[tuple[str, ...], ...]

    @classmethod
    def from_values(cls, sheet_title: str, sheet_id: int, values: Sequence[Sequence[object]]) -> SheetPlan:
        """План по значениям листа: первая строка — шапка, остальные — ряды."""
        cells: tuple[tuple[str, ...], ...] = tuple(tuple(str(cell) for cell in row) for row in values)
        header: SheetHeader = SheetHeader.of(cells[0] if cells else ())
        columns: SheetColumns | None = SheetColumns.from_header(header)
        rows: tuple[SheetRow, ...] = ()
        if columns is not None:
            rows = tuple(
                columns.row(row_number, row_values)
                for row_number, row_values in enumerate(cells[1:], start=FIRST_DATA_ROW_NUMBER)
            )
        return cls(sheet_title=sheet_title, sheet_id=sheet_id, header=header, columns=columns, rows=rows, values=cells)

    @property
    def problem(self) -> PlanProblem | None:
        """Почему по этому плану нельзя работать; годному плану — None."""
        if self.columns is None:
            return PlanProblem.HEADER_UNKNOWN
        if not self.rows:
            return PlanProblem.EMPTY
        return None

    @property
    def problem_text(self) -> str:
        """Проблема плана для человека: лист, а у нераспознанной шапки — чего не хватает и какие заголовки есть."""
        if self.problem is PlanProblem.EMPTY:
            return msg.SHEET_PLAN_EMPTY.format(sheet=self.sheet_title)
        if self.problem is PlanProblem.HEADER_UNKNOWN:
            missing: str = msg.LIST_JOINER.join(column.human for column in self.header.missing)
            return msg.SHEET_PLAN_HEADER_UNKNOWN.format(
                sheet=self.sheet_title, missing=missing, headers=self.header.text
            )
        return ""

    def plan_rows(self, zone: ZoneInfo, now: datetime) -> PlannedRows:
        """Разбор рядов с отсевом повторов; отсеянные ряды и итог — строками лога."""
        planned: PlannedRows = PlannedRows.of(self.rows, zone, now)
        if self.columns is None:
            problem: LogEvent = LogEvent.of(PlanEvent.PROBLEM, problem=self.problem, sheet=self.sheet_title)
            problem.extended(header=self.header.names).emit(LOGGER, logging.WARNING)
            return planned
        for row in planned.skipped:
            row.event.emit(LOGGER)
        planned.ready_event.extended(sheet=self.sheet_title, **self.columns.log_fields).emit(LOGGER)
        return planned
