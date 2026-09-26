from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.observability.log_event import LogArea
from app.sheets.plan import HeaderAliases, PlanProblem, SheetColumns, SheetHeader, SheetPlan
from app.sheets.rows import AdmittedRow, PlannedRows, RowSkipReason, SheetRow, SkippedRow
from app.tests.conftest import SUPPLIED_VALUES
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2026, 9, 24, 12, 0, tzinfo=KYIV)
VIDEO_ID: str = "dQw4w9WgXcQ"
OTHER_ID: str = "aB3_-xYz012"
SHORT_LINK: str = f"https://youtu.be/{VIDEO_ID}"
WATCH_LINK: str = f"https://www.youtube.com/watch?v={VIDEO_ID}&t=5s"
HEADER: list[str] = ["Links", "Date", "Time"]


def plan_of(*rows: list[str], header: list[str] | None = None) -> PlannedRows:
    values: list[list[str]] = [header if header is not None else HEADER, *rows]
    return SheetPlan.from_values(values).plan_rows(KYIV, NOW)


def only(*row: str) -> AdmittedRow | SkippedRow:
    planned: PlannedRows = plan_of(list(row))
    (outcome,) = (*planned.admitted, *planned.skipped)
    return outcome


def admitted(*row: str) -> AdmittedRow:
    outcome: AdmittedRow | SkippedRow = only(*row)
    assert isinstance(outcome, AdmittedRow)
    return outcome


def skipped(*row: str) -> SkippedRow:
    outcome: AdmittedRow | SkippedRow = only(*row)
    assert isinstance(outcome, SkippedRow)
    return outcome


NO_ROWS: PlannedRows = PlannedRows(admitted=(), skipped=())


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


def test_ukrainian_header_and_yo_are_recognized() -> None:
    """«ё» в имени колонки сравнивается как «е», украинские буквы сохраняются: «Відео» — колонка ссылки."""
    plan: SheetPlan = SheetPlan.from_values([["Відео", "Дата", "Врёмя"]])
    assert plan.columns == SheetColumns(link=0, date=1, time=2)
    assert plan.problem is None


def test_header_aliases_are_the_resource_files() -> None:
    aliases: HeaderAliases = HeaderAliases.load()
    assert aliases.link[:3] == ("links", "link", "url") and "відео" in aliases.link and "посилання" in aliases.link
    assert aliases.date == ("date", "дата", "day")
    assert aliases.time == ("time", "время", "hour")


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
    assert plan.plan_rows(KYIV, NOW).skipped[0].reason is RowSkipReason.MISSING_DATE_TIME


def test_rows_are_numbered_like_the_sheet() -> None:
    plan: SheetPlan = SheetPlan.from_values([HEADER, [], [SHORT_LINK], ["x"]])
    assert [row.row_number for row in plan.rows] == [2, 3, 4]


def test_header_without_date_is_a_problem_and_has_no_rows() -> None:
    plan: SheetPlan = SheetPlan.from_values([["Links", "Time", ""], [SHORT_LINK, "19:00"]])
    assert plan.columns is None
    assert plan.rows == ()
    assert plan.problem is PlanProblem.HEADER_UNKNOWN
    assert "«Links», «Time»" in plan.problem_text
    assert plan.plan_rows(KYIV, NOW) == NO_ROWS


def test_blank_header_names_no_headers() -> None:
    plan: SheetPlan = SheetPlan.from_values([[], [SHORT_LINK, "16.10.2026", "19:00"]])
    assert plan.problem is PlanProblem.HEADER_UNKNOWN
    assert plan.problem_text == msg.SHEET_PLAN_HEADER_UNKNOWN.format(headers=msg.SHEET_PLAN_HEADER_NONE)


def test_empty_range_is_a_problem() -> None:
    plan: SheetPlan = SheetPlan.from_values([])
    assert plan.problem is PlanProblem.EMPTY
    assert plan.problem_text == msg.SHEET_PLAN_EMPTY
    assert plan.rows == ()
    assert plan.plan_rows(KYIV, NOW) == NO_ROWS


def test_header_only_is_no_problem_and_no_rows() -> None:
    plan: SheetPlan = SheetPlan.from_values([HEADER])
    assert plan.problem is None and plan.problem_text == ""
    assert plan.plan_rows(KYIV, NOW) == NO_ROWS


def test_plan_problems_carry_no_vault_values() -> None:
    for text in (SheetPlan.from_values([]).problem_text, SheetPlan.from_values([["x"]]).problem_text):
        assert text
        for value in SUPPLIED_VALUES.values():
            assert value not in text


def test_the_header_finds_a_column_by_exact_name_first_then_by_part() -> None:
    header: SheetHeader = SheetHeader(("Video title", "Link", "Ссылки на видео"))
    assert header.index_of(("link",)) == 1
    assert header.index_of(("ссылк",)) == 2
    assert header.index_of(("date",)) is None


# --- допуск ряда


def test_future_row_is_admitted_with_short_link_and_kyiv_offset() -> None:
    planned: AdmittedRow = admitted(WATCH_LINK, "16.10.2026", "19:00")
    assert planned.link == SHORT_LINK
    assert planned.video.value == VIDEO_ID
    assert planned.row.link == WATCH_LINK
    assert planned.start == datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
    assert planned.start.utcoffset() == timedelta(hours=3)


def test_admitted_row_reads_other_date_and_time_formats() -> None:
    planned: AdmittedRow = admitted(SHORT_LINK, "2026-11-05", "7:05 PM")
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
    planned: SkippedRow = skipped(*row)
    assert planned.reason is reason
    assert planned.duplicate_of is None


def test_a_skipped_row_keeps_the_start_once_date_and_time_are_read() -> None:
    assert skipped(SHORT_LINK, "24.09.2026", "11:59").start == datetime(2026, 9, 24, 11, 59, tzinfo=KYIV)
    assert skipped(SHORT_LINK, "16 октября", "19:00").start is None


def test_start_exactly_now_is_admitted() -> None:
    assert isinstance(only(SHORT_LINK, "24.09.2026", "12:00"), AdmittedRow)


def test_empty_link_is_checked_before_the_past() -> None:
    assert skipped("", "01.01.2020", "10:00").reason is RowSkipReason.EMPTY_LINK


def test_past_is_checked_before_the_link() -> None:
    assert skipped("не ссылка", "01.01.2020", "10:00").reason is RowSkipReason.IN_PAST


def test_spring_forward_gap_in_the_past_is_nonexistent_time() -> None:
    assert skipped(SHORT_LINK, "29.03.2026", "03:30").reason is RowSkipReason.NONEXISTENT_TIME


def test_repeated_autumn_hour_is_admitted_on_its_first_occurrence() -> None:
    planned: AdmittedRow = admitted(SHORT_LINK, "25.10.2026", "03:30")
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
    planned: PlannedRows = plan_of(
        [WATCH_LINK, "16.10.2026", "19:00"],
        [f"https://www.youtube.com/watch?v={OTHER_ID}", "16.10.2026", "19:00"],
        [SHORT_LINK, "2026-10-16", "19.00"],
    )
    assert [row.row_number for row in planned.admitted] == [2, 3]
    (repeat,) = planned.skipped
    assert (repeat.row_number, repeat.reason, repeat.duplicate_of) == (4, RowSkipReason.DUPLICATE, 2)
    assert repeat.start == datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)


def test_same_video_at_another_moment_is_admitted_twice() -> None:
    planned: PlannedRows = plan_of(
        [SHORT_LINK, "16.10.2026", "19:00"],
        [WATCH_LINK, "16.10.2026", "20:00"],
    )
    assert len(planned.admitted) == 2 and planned.skipped == ()


def test_the_same_moment_in_another_zone_is_the_same_moment() -> None:
    """Повтор узнаётся по моменту, а не по записи: 19:00 по Киеву и 16:00 UTC — один момент."""
    kyiv: AdmittedRow = admitted(SHORT_LINK, "16.10.2026", "19:00")
    utc: AdmittedRow = AdmittedRow(kyiv.row, kyiv.start.astimezone(ZoneInfo("UTC")), kyiv.video)
    assert utc.identity == kyiv.identity


def test_skipped_row_does_not_hide_a_later_admitted_one() -> None:
    planned: PlannedRows = plan_of(
        [SHORT_LINK, "16.09.2026", "19:00"],
        [SHORT_LINK, "16.10.2026", "19:00"],
    )
    assert planned.skipped[0].reason is RowSkipReason.IN_PAST
    assert [row.row_number for row in planned.admitted] == [3]


def test_plan_keeps_the_sheet_order() -> None:
    planned: PlannedRows = plan_of(
        [SHORT_LINK, "18.10.2026", "19:00"],
        ["", "", ""],
        [SHORT_LINK, "17.10.2026", "19:00"],
        ["", "", ""],
    )
    assert [row.row_number for row in planned.admitted] == [2, 4]
    assert [row.row_number for row in planned.skipped] == [3, 5]
    assert planned.total == 4


def test_the_counts_follow_the_order_of_the_checks() -> None:
    planned: PlannedRows = plan_of(
        [SHORT_LINK, "16.10.2026", "19:00"],
        [SHORT_LINK, "16.09.2026", "19:00"],
        ["", "16.10.2026", "19:00"],
        [WATCH_LINK, "16.10.2026", "19:00"],
        [SHORT_LINK, "01.09.2026", "19:00"],
    )
    assert [(item.key, item.count) for item in planned.counts.items] == [
        (RowSkipReason.EMPTY_LINK, 1), (RowSkipReason.IN_PAST, 2), (RowSkipReason.DUPLICATE, 1)
    ]
    assert planned.console_line == msg.INTAKE_TABLE_LINE.format(
        rows=5, admitted=1, skipped=4, reasons=msg.INTAKE_TABLE_REASONS.format(items=msg.ITEM_JOINER.join((
            msg.INTAKE_COUNT_ITEM.format(name=RowSkipReason.EMPTY_LINK.human, count=1),
            msg.INTAKE_COUNT_ITEM.format(name=RowSkipReason.IN_PAST.human, count=2),
            msg.INTAKE_COUNT_ITEM.format(name=RowSkipReason.DUPLICATE.human, count=1),
        ))),
    )


def test_the_console_line_without_skipped_rows_names_no_reasons() -> None:
    planned: PlannedRows = plan_of([SHORT_LINK, "16.10.2026", "19:00"])
    assert planned.console_line == msg.INTAKE_TABLE_LINE.format(rows=1, admitted=1, skipped=0, reasons="")


# --- лог


def test_skipped_rows_and_summary_go_to_the_log() -> None:
    with LogCapture.on(LogArea.SHEETS) as capture:
        plan_of(
            ["", "16.10.2026", "19:00"],
            [SHORT_LINK, "16.10.2026", "19:00"],
            [WATCH_LINK, "16.10.2026", "19:00"],
        )
    messages: list[str] = capture.messages()
    assert [line for line in messages if line.startswith("sheet_row_skipped")] == [
        "sheet_row_skipped row=2 reason=empty_link link=- date=16.10.2026 time=19:00 start=- duplicate_of=-",
        f"sheet_row_skipped row=4 reason=duplicate link={WATCH_LINK} date=16.10.2026 time=19:00 "
        "start=2026-10-16T19:00:00+03:00 duplicate_of=3",
    ]
    summary: list[str] = [line for line in messages if line.startswith("sheet_plan_ready")]
    assert summary == [
        "sheet_plan_ready rows=3 admitted=1 skipped=empty_link:1,duplicate:1 link_column=0 date_column=1 time_column=2"
    ]


def test_a_plan_with_a_problem_logs_the_problem_and_no_summary() -> None:
    with LogCapture.on(LogArea.SHEETS) as capture:
        SheetPlan.from_values([["Links", "Time"]]).plan_rows(KYIV, NOW)
    assert capture.messages() == ["sheet_plan_problem problem=header_unknown range_rows=1 header=Links,Time"]
