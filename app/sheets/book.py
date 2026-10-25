"""Какой лист таблицы — план стримов (CLAUDE.md §14 решение 26).

Таблицу задаёт одна ссылка; лист и колонки программа находит сама. `SheetTitles` — листы таблицы (`SheetName`:
название и id листа; id нужен записи ссылок на превью): по названиям читатель спрашивает первую строку каждого листа
(`header_ranges`). `SheetBook` — листы с их первыми строками: лист
плана — первый, в первой строке которого есть колонки ссылки, даты и времени. Нет такого — план без колонок с листа,
который ближе всех (больше всего найденных колонок, при равенстве — первый): он называет, чего не хватает. Правило
«какой лист» живёт только здесь. Сети здесь нет: обращения к Google — `sheets\\client.py`.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.sheet_text import quoted_sheet_title, sheet_header_range
from app.sheets.plan import PlanColumn, SheetColumns, SheetHeader, SheetPlan


@dataclass(frozen=True)
class SheetName:
    """Лист таблицы по ответу `spreadsheets.get`: название и id листа."""

    title: str
    sheet_id: int


@dataclass(frozen=True)
class SheetTab:
    """Лист таблицы: название, id и первая строка."""

    title: str
    sheet_id: int
    header: SheetHeader

    @property
    def columns(self) -> SheetColumns | None:
        return SheetColumns.from_header(self.header)

    @property
    def found_count(self) -> int:
        """Сколько колонок плана нашлось в первой строке."""
        return len(PlanColumn) - len(self.header.missing)

    @property
    def values_range(self) -> str:
        """Диапазон «весь лист» в нотации A1."""
        return quoted_sheet_title(self.title)

    def plan(self, values: Sequence[Sequence[object]]) -> SheetPlan:
        """План по значениям всего листа."""
        return SheetPlan.from_values(self.title, self.sheet_id, values)

    @property
    def unrecognized(self) -> SheetPlan:
        """План без колонок: лист и его шапка — чтобы план назвал, чего в ней не хватает."""
        return SheetPlan(
            sheet_title=self.title, sheet_id=self.sheet_id, header=self.header, columns=None, rows=(),
            values=(self.header.names,),
        )


@dataclass(frozen=True)
class SheetTitles:
    """Листы таблицы в порядке таблицы."""

    sheets: tuple[SheetName, ...]

    @property
    def header_ranges(self) -> tuple[str, ...]:
        """Диапазоны первых строк листов в нотации A1 — в порядке листов."""
        return tuple(sheet_header_range(sheet.title) for sheet in self.sheets)

    def book(self, first_rows: Sequence[Sequence[object]]) -> SheetBook:
        """Листы с их первыми строками; строки — в порядке `header_ranges`."""
        return SheetBook(
            tabs=tuple(
                SheetTab(sheet.title, sheet.sheet_id, SheetHeader.of(row))
                for sheet, row in zip(self.sheets, first_rows, strict=True)
            )
        )


@dataclass(frozen=True)
class SheetBook:
    """Листы таблицы с первыми строками; сам выбирает лист плана."""

    tabs: tuple[SheetTab, ...]

    @property
    def plan_tab(self) -> SheetTab | None:
        """Первый лист, в первой строке которого есть все три колонки плана; нет такого — None."""
        return next((tab for tab in self.tabs if tab.columns is not None), None)

    @property
    def closest(self) -> SheetTab:
        """Лист, которому меньше всех не хватает: больше всего найденных колонок, при равенстве — первый."""
        return max(self.tabs, key=lambda tab: tab.found_count)
