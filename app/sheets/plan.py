"""План стримов из значений диапазона Google-таблицы (CLAUDE.md §2 контур A, §3 шаг 2.3).

Вход — список списков строк, как его отдаёт `values.get`: первая строка — шапка, ряды данных нумеруются
с 2 (как в самой таблице). Сети здесь нет: чтение таблицы — задача `sheets\\client.py`.

Объекты:
- `SheetHeader` — шапка диапазона; сама находит колонку по названиям;
- `SheetColumns` — где в диапазоне колонки ссылки, даты и времени; строит ряды `SheetRow` (app\\sheets\\rows.py);
- `SheetPlan` — шапка и ряды; сам называет свою проблему (`problem`) и разбирает ряды (`plan_rows` → `PlannedRows`).

Обратной записи в таблицу нет (§6 инвариант 3); запасного диапазона при ошибке разбора тоже: диапазон — значение
пользователя, своё программа не подставляет.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final
from zoneinfo import ZoneInfo

from app.core.sheet_text import normalize_header_name
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.resources.loader import TextResource
from app.sheets.rows import PlannedRows, SheetRow
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.SHEETS)

# Названия колонок шапки — ресурсы: сначала точное совпадение имени, затем вхождение названия в имя.
LINK_ALIASES_RESOURCE: Final[str] = "sheet_header_link.txt"
DATE_ALIASES_RESOURCE: Final[str] = "sheet_header_date.txt"
TIME_ALIASES_RESOURCE: Final[str] = "sheet_header_time.txt"
FIRST_DATA_ROW_NUMBER: Final[int] = 2        # строка 1 таблицы — шапка
HEADER_ITEM_TEMPLATE: Final[str] = "«{name}»"


class PlanProblem(str, Enum):
    """Почему по плану нельзя работать."""

    EMPTY = "empty"                     # в диапазоне нет ни шапки, ни рядов
    HEADER_UNKNOWN = "header_unknown"   # в шапке не нашлась колонка ссылки, даты или времени


class PlanEvent(str, Enum):
    """События плана в логе."""

    PROBLEM = "sheet_plan_problem"


@dataclass(frozen=True)
class HeaderAliases:
    """Названия колонок шапки, по которым план узнаёт колонки ссылки, даты и времени."""

    link: tuple[str, ...]
    date: tuple[str, ...]
    time: tuple[str, ...]

    @classmethod
    def load(cls) -> HeaderAliases:
        return cls(
            link=TextResource(LINK_ALIASES_RESOURCE).lines,
            date=TextResource(DATE_ALIASES_RESOURCE).lines,
            time=TextResource(TIME_ALIASES_RESOURCE).lines,
        )


@dataclass(frozen=True)
class SheetHeader:
    """Шапка диапазона: заголовки колонок как в таблице, без краёв."""

    names: tuple[str, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        """Заголовки в виде для сравнения с названиями колонок (`normalize_header_name`)."""
        return tuple(normalize_header_name(name) for name in self.names)

    def index_of(self, aliases: tuple[str, ...]) -> int | None:
        """Колонка по названиям: сначала точное совпадение, затем название внутри заголовка; не нашлась — None."""
        wanted: tuple[str, ...] = tuple(normalize_header_name(alias) for alias in aliases)
        keys: tuple[str, ...] = self.keys
        exact: int | None = next((index for index, key in enumerate(keys) if key in wanted), None)
        if exact is not None:
            return exact
        return next((index for index, key in enumerate(keys) if any(alias in key for alias in wanted if alias)), None)

    @property
    def text(self) -> str:
        """Непустые заголовки для человека: «a», «b»; ни одного — «нет ни одного»."""
        names: list[str] = [HEADER_ITEM_TEMPLATE.format(name=name) for name in self.names if name]
        return msg.LIST_JOINER.join(names) if names else msg.SHEET_PLAN_HEADER_NONE


@dataclass(frozen=True)
class SheetColumns:
    """Индексы (с 0) колонок ссылки, даты и времени в значениях диапазона."""

    link: int
    date: int
    time: int

    @classmethod
    def from_header(cls, header: SheetHeader) -> SheetColumns | None:
        """Колонки по шапке; не нашлась хотя бы одна — None."""
        aliases: HeaderAliases = HeaderAliases.load()
        link: int | None = header.index_of(aliases.link)
        date: int | None = header.index_of(aliases.date)
        time: int | None = header.index_of(aliases.time)
        if link is None or date is None or time is None:
            return None
        return cls(link=link, date=date, time=time)

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
        """Колонки для строки лога, номера — с 0, как в значениях диапазона."""
        return dict(link_column=self.link, date_column=self.date, time_column=self.time)

    def _cell(self, values: Sequence[str], index: int) -> str:
        return str(values[index]).strip() if index < len(values) else ""


@dataclass(frozen=True)
class SheetPlan:
    """План из значений диапазона: шапка, распознанные колонки и ряды данных.

    `range_row_count` — сколько строк пришло в диапазоне вместе с шапкой: отличает пустой диапазон от
    диапазона с нераспознанной шапкой. Шапка не распознана — `columns` None и рядов нет: план не падает,
    а называет проблему (`problem`).
    """

    columns: SheetColumns | None
    rows: tuple[SheetRow, ...]
    header: SheetHeader
    range_row_count: int

    @classmethod
    def from_values(cls, values: list[list[str]]) -> SheetPlan:
        if not values:
            return cls(columns=None, rows=(), header=SheetHeader(()), range_row_count=0)
        header: SheetHeader = SheetHeader(tuple(str(cell).strip() for cell in values[0]))
        columns: SheetColumns | None = SheetColumns.from_header(header)
        rows: tuple[SheetRow, ...] = ()
        if columns is not None:
            rows = tuple(
                columns.row(row_number, row_values)
                for row_number, row_values in enumerate(values[1:], start=FIRST_DATA_ROW_NUMBER)
            )
        return cls(columns=columns, rows=rows, header=header, range_row_count=len(values))

    @property
    def problem(self) -> PlanProblem | None:
        """Почему по этому плану нельзя работать; годному плану — None."""
        if self.range_row_count == 0:
            return PlanProblem.EMPTY
        if self.columns is None:
            return PlanProblem.HEADER_UNKNOWN
        return None

    @property
    def problem_text(self) -> str:
        """Проблема плана для человека: у нераспознанной шапки — с перечнем её заголовков; у годного плана — пусто."""
        if self.problem is PlanProblem.EMPTY:
            return msg.SHEET_PLAN_EMPTY
        if self.problem is PlanProblem.HEADER_UNKNOWN:
            return msg.SHEET_PLAN_HEADER_UNKNOWN.format(headers=self.header.text)
        return ""

    def plan_rows(self, zone: ZoneInfo, now: datetime) -> PlannedRows:
        """Разбор рядов с отсевом повторов; отсеянные ряды и итог — строками лога."""
        planned: PlannedRows = PlannedRows.of(self.rows, zone, now)
        if self.columns is None:
            problem: LogEvent = LogEvent.of(PlanEvent.PROBLEM, problem=self.problem, range_rows=self.range_row_count)
            problem.extended(header=self.header.names).emit(LOGGER, logging.WARNING)
            return planned
        for row in planned.skipped:
            row.event.emit(LOGGER)
        planned.ready_event.extended(**self.columns.log_fields).emit(LOGGER)
        return planned
