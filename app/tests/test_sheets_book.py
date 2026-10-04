from __future__ import annotations

from app.sheets.book import SheetBook, SheetName, SheetTab, SheetTitles
from app.sheets.plan import PlanColumn, PlanProblem, SheetColumns, SheetPlan
from app.ui import messages_ru as msg

PLAN_HEADER: list[str] = ["Links", "Date", "Time"]


def book_of(*sheets: tuple[str, list[str]]) -> SheetBook:
    names: tuple[SheetName, ...] = tuple(SheetName(title, index) for index, (title, _row) in enumerate(sheets))
    return SheetTitles(names).book([row for _title, row in sheets])


def test_the_plan_is_the_first_sheet_with_all_three_columns() -> None:
    book: SheetBook = book_of(("Заметки", ["Дата", "Кто"]), ("План", PLAN_HEADER), ("Архив", PLAN_HEADER))
    tab: SheetTab | None = book.plan_tab
    assert tab is not None and tab.title == "План"
    assert tab.columns == SheetColumns(link=0, date=1, time=2)


def test_no_suitable_sheet_names_the_closest_one_and_what_it_lacks() -> None:
    book: SheetBook = book_of(("Заметки", ["Дата"]), ("Черновик", ["Links", "Time"]), ("Итоги", []))
    assert book.plan_tab is None
    plan: SheetPlan = book.closest.unrecognized
    assert plan.sheet_title == "Черновик" and plan.problem is PlanProblem.HEADER_UNKNOWN
    assert plan.header.missing == (PlanColumn.DATE,)
    assert plan.problem_text == msg.SHEET_PLAN_HEADER_UNKNOWN.format(
        sheet="Черновик", missing=PlanColumn.DATE.human, headers="«Links», «Time»"
    )


def test_on_a_tie_the_first_sheet_is_the_closest() -> None:
    book: SheetBook = book_of(("Первый", ["Links"]), ("Второй", ["Date"]), ("Третий", []))
    assert book.closest.title == "Первый"


def test_a_quote_in_the_sheet_title_is_doubled_in_every_range() -> None:
    titles: SheetTitles = SheetTitles((SheetName("План 'осень'", 0),))
    assert titles.header_ranges == ("'План ''осень'''!1:1",)
    tab: SheetTab | None = titles.book([PLAN_HEADER]).plan_tab
    assert tab is not None and tab.values_range == "'План ''осень'''"


def test_the_plan_of_a_tab_reads_its_rows_under_the_header() -> None:
    tab: SheetTab | None = book_of(("План", PLAN_HEADER)).plan_tab
    assert tab is not None
    plan: SheetPlan = tab.plan([PLAN_HEADER, ["https://youtu.be/dQw4w9WgXcQ", "28-09-2026", "19:00"]])
    assert plan.sheet_title == "План" and plan.problem is None and len(plan.rows) == 1


def test_the_plan_and_the_closest_sheet_keep_the_sheet_id() -> None:
    """id листа нужен записи ссылок на превью (формат ячеек задаётся по id листа, а не по названию)."""
    book: SheetBook = book_of(("Заметки", ["Дата"]), ("План", PLAN_HEADER))
    tab: SheetTab | None = book.plan_tab
    assert tab is not None and tab.sheet_id == 1
    assert tab.plan([PLAN_HEADER]).sheet_id == 1
    assert book_of(("Черновик", ["Links"])).closest.unrecognized.sheet_id == 0
