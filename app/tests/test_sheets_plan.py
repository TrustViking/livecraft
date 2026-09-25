from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.sheets.plan import SheetColumns, SheetPlan, SheetRow
from app.sheets.rows import PlanRow, RowSkipReason
from app.tests.conftest import SUPPLIED_VALUES
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2026, 9, 24, 12, 0, tzinfo=KYIV)
VIDEO_ID: str = "dQw4w9WgXcQ"
OTHER_ID: str = "aB3_-xYz012"
SHORT_LINK: str = f"https://youtu.be/{VIDEO_ID}"
WATCH_LINK: str = f"https://www.youtube.com/watch?v={VIDEO_ID}&t=5s"
HEADER: list[str] = ["Links", "Date", "Time"]


def plan_of(*rows: list[str], header: list[str] | None = None) -> tuple[PlanRow, ...]:
    values: list[list[str]] = [header if header is not None else HEADER, *rows]
    return SheetPlan.from_values(values).plan_rows(KYIV, NOW)


def only(*row: str) -> PlanRow:
    (planned,) = plan_of(list(row))
    return planned


# --- шапка


def test_latin_header_is_recognized() -> None:
    plan: SheetPlan = SheetPlan.from_values([HEADER, [SHORT_LINK, "16.10.2026", "19:00"]])
    assert plan.columns == SheetColumns(link=0, date=1, time=2)
    assert plan.problem is None
    assert plan.rows == (SheetRow(row_number=2, link=SHORT_LINK, date_raw="16.10.2026", time_raw="19:00"),)


def test_russian_header_is_recognized() -> None:
    plan: SheetPlan = SheetPlan.from_values([["Ссылка на видео", "Дата", "Время"]])
    assert plan.columns == SheetColumns(link=0, date=1, time=2)
    assert plan.problem is None


def test_shuffled_columns_with_extra_ones_are_found() -> None:
    header: list[str] = ["Time", "Заметки", "Date", "№", "YouTube links"]
    plan: SheetPlan = SheetPlan.from_values([header, ["19:00", "x", "16.10.2026", "1", f"  {SHORT_LINK} "]])
    assert plan.columns == SheetColumns(link=4, date=2, time=0)
    assert plan.rows[0] == SheetRow(row_number=2, link=SHORT_LINK, date_raw="16.10.2026", time_raw="19:00")


def test_exact_alias_wins_over_an_earlier_partial_match() -> None:
    plan: SheetPlan = SheetPlan.from_values([["Video title", "Link", "Date", "Time"]])
    assert plan.columns == SheetColumns(link=1, date=2, time=3)


def test_short_row_gives_empty_cells() -> None:
    header: list[str] = ["№", "Links", "Date", "Time", "Комментарий"]
    plan: SheetPlan = SheetPlan.from_values([header, ["1", SHORT_LINK]])
    assert plan.rows[0] == SheetRow(row_number=2, link=SHORT_LINK, date_raw="", time_raw="")
    assert plan.plan_rows(KYIV, NOW)[0].skip is RowSkipReason.MISSING_DATE_TIME


def test_rows_are_numbered_like_the_sheet() -> None:
    plan: SheetPlan = SheetPlan.from_values([HEADER, [], [SHORT_LINK], ["x"]])
    assert [row.row_number for row in plan.rows] == [2, 3, 4]


def test_header_without_date_is_a_problem_and_has_no_rows() -> None:
    plan: SheetPlan = SheetPlan.from_values([["Links", "Time", ""], [SHORT_LINK, "19:00"]])
    assert plan.columns is None
    assert plan.rows == ()
    assert plan.problem is not None
    assert "«Links», «Time»" in plan.problem
    assert plan.plan_rows(KYIV, NOW) == ()


def test_blank_header_names_no_headers() -> None:
    plan: SheetPlan = SheetPlan.from_values([[], [SHORT_LINK, "16.10.2026", "19:00"]])
    assert plan.problem == msg.SHEET_PLAN_HEADER_UNKNOWN.format(headers=msg.SHEET_PLAN_HEADER_NONE)


def test_empty_range_is_a_problem() -> None:
    plan: SheetPlan = SheetPlan.from_values([])
    assert plan.problem == msg.SHEET_PLAN_EMPTY
    assert plan.rows == ()
    assert plan.plan_rows(KYIV, NOW) == ()


def test_header_only_is_no_problem_and_no_rows() -> None:
    plan: SheetPlan = SheetPlan.from_values([HEADER])
    assert plan.problem is None
    assert plan.plan_rows(KYIV, NOW) == ()


def test_plan_problems_carry_no_vault_values() -> None:
    for problem in (SheetPlan.from_values([]).problem, SheetPlan.from_values([["x"]]).problem):
        assert problem is not None
        for value in SUPPLIED_VALUES.values():
            assert value not in problem


# --- допуск ряда


def test_future_row_is_admitted_with_short_link_and_kyiv_offset() -> None:
    planned: PlanRow = only(WATCH_LINK, "16.10.2026", "19:00")
    assert planned.is_admitted
    assert planned.skip is None
    assert planned.link == SHORT_LINK
    assert planned.start == datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
    assert planned.start is not None and planned.start.utcoffset() == timedelta(hours=3)
    assert planned.duplicate_of is None


def test_admitted_row_reads_other_date_and_time_formats() -> None:
    planned: PlanRow = only(SHORT_LINK, "2026-11-05", "7:05 PM")
    assert planned.start == datetime(2026, 11, 5, 19, 5, tzinfo=KYIV)


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (["", "16.10.2026", "19:00"], RowSkipReason.EMPTY_LINK),
        ([SHORT_LINK, "", "19:00"], RowSkipReason.MISSING_DATE_TIME),
        ([SHORT_LINK, "16.10.2026", ""], RowSkipReason.MISSING_DATE_TIME),
        ([SHORT_LINK, "16 октября", "19:00"], RowSkipReason.BAD_DATE_TIME),
        ([SHORT_LINK, "16.10.2026", "вечером"], RowSkipReason.BAD_DATE_TIME),
        ([SHORT_LINK, "28.03.2027", "03:30"], RowSkipReason.NONEXISTENT_TIME),
        ([SHORT_LINK, "24.09.2026", "11:59"], RowSkipReason.IN_PAST),
        (["https://vimeo.com/123456789", "16.10.2026", "19:00"], RowSkipReason.BAD_LINK),
    ],
)
def test_every_skip_reason(row: list[str], reason: RowSkipReason) -> None:
    planned: PlanRow = only(*row)
    assert planned.skip is reason
    assert not planned.is_admitted
    assert planned.link is None


def test_start_exactly_now_is_admitted() -> None:
    assert only(SHORT_LINK, "24.09.2026", "12:00").is_admitted


def test_empty_link_is_checked_before_the_past() -> None:
    assert only("", "01.01.2020", "10:00").skip is RowSkipReason.EMPTY_LINK


def test_past_is_checked_before_the_link() -> None:
    assert only("не ссылка", "01.01.2020", "10:00").skip is RowSkipReason.IN_PAST


def test_spring_forward_gap_in_the_past_is_nonexistent_time() -> None:
    assert only(SHORT_LINK, "29.03.2026", "03:30").skip is RowSkipReason.NONEXISTENT_TIME


def test_repeated_autumn_hour_is_admitted_on_its_first_occurrence() -> None:
    planned: PlanRow = only(SHORT_LINK, "25.10.2026", "03:30")
    assert planned.is_admitted
    assert planned.start is not None
    assert planned.start.fold == 0
    assert planned.start.utcoffset() == timedelta(hours=3)


def test_naive_now_is_refused() -> None:
    row: SheetRow = SheetRow(row_number=2, link=SHORT_LINK, date_raw="16.10.2026", time_raw="19:00")
    with pytest.raises(ValueError):
        row.plan(KYIV, datetime(2026, 9, 24, 12, 0))


def test_every_skip_reason_has_a_russian_text() -> None:
    for reason in RowSkipReason:
        assert reason.human == msg.SHEET_ROW_SKIP_REASONS[reason.value]
        assert reason.human
    assert set(msg.SHEET_ROW_SKIP_REASONS) == {reason.value for reason in RowSkipReason}


# --- повторы


def test_same_video_in_other_spelling_at_the_same_moment_is_a_duplicate_of_the_earlier_row() -> None:
    planned: tuple[PlanRow, ...] = plan_of(
        [WATCH_LINK, "16.10.2026", "19:00"],
        [f"https://www.youtube.com/watch?v={OTHER_ID}", "16.10.2026", "19:00"],
        [SHORT_LINK, "2026-10-16", "19.00"],
    )
    assert [row.is_admitted for row in planned] == [True, True, False]
    assert planned[2].skip is RowSkipReason.DUPLICATE
    assert planned[2].duplicate_of == 2
    assert planned[2].link == SHORT_LINK


def test_same_video_at_another_moment_is_admitted_twice() -> None:
    planned: tuple[PlanRow, ...] = plan_of(
        [SHORT_LINK, "16.10.2026", "19:00"],
        [WATCH_LINK, "16.10.2026", "20:00"],
    )
    assert all(row.is_admitted for row in planned)


def test_skipped_row_does_not_hide_a_later_admitted_one() -> None:
    planned: tuple[PlanRow, ...] = plan_of(
        [SHORT_LINK, "16.09.2026", "19:00"],
        [SHORT_LINK, "16.10.2026", "19:00"],
    )
    assert planned[0].skip is RowSkipReason.IN_PAST
    assert planned[1].is_admitted


def test_plan_keeps_the_sheet_order() -> None:
    planned: tuple[PlanRow, ...] = plan_of(
        [SHORT_LINK, "18.10.2026", "19:00"],
        ["", "", ""],
        [SHORT_LINK, "17.10.2026", "19:00"],
    )
    assert [row.row_number for row in planned] == [2, 3, 4]


# --- лог


class _Collector(logging.Handler):
    """Свой обработчик прямо на логгере livecraft.sheets: не зависит от того, что прежние тесты сделали
    с propagate и обработчиками логгера livecraft."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_skipped_rows_and_summary_go_to_the_log(monkeypatch: pytest.MonkeyPatch) -> None:
    logger: logging.Logger = logging.getLogger("livecraft.sheets")
    collector: _Collector = _Collector()
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    logger.addHandler(collector)
    try:
        plan_of(
            ["", "16.10.2026", "19:00"],
            [SHORT_LINK, "16.10.2026", "19:00"],
            [WATCH_LINK, "16.10.2026", "19:00"],
        )
    finally:
        logger.removeHandler(collector)
    messages: list[str] = collector.messages
    skipped: list[str] = [line for line in messages if line.startswith("sheet_row_skipped")]
    assert len(skipped) == 2
    assert "row=2 reason=empty_link" in skipped[0]
    assert "row=4 reason=duplicate" in skipped[1]
    assert f"link='{WATCH_LINK}'" in skipped[1]
    assert "duplicate_of=3" in skipped[1]
    summary: list[str] = [line for line in messages if line.startswith("sheet_plan_ready")]
    assert summary == [
        "sheet_plan_ready rows=3 admitted=1 link_column=0 date_column=1 time_column=2 empty_link=1 duplicate=1"
    ]
