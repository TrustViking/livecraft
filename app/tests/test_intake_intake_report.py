"""Часть «Таблица плана и тексты» отчёта запуска (app\\intake\\intake_report.py; CLAUDE.md §3 шаги 2.3–2.6, задача 6.3)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.intake.intake import IntakeResult
from app.intake.intake_report import IntakeReport
from app.run.report_section import PartReport
from app.slots.texts import SlotTextOrigin
from app.sheets.rows import AdmittedRow, PlannedRows, RowSkipReason, SheetRow, SkippedRow
from app.sources.metadata import SourceFailureReason
from app.sources.video import PreparedSources, SourceVideo
from app.tests.fixtures.pipeline import PREVIEW
from app.tests.fixtures.slots import build_slots
from app.tests.fixtures.sources import admitted_row, failed_source, ready_source
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
START: datetime = datetime(2027, 3, 17, 19, 0, tzinfo=KYIV)
UK_LINK: str = "https://youtu.be/dQw4w9WgXcQ"
RU_LINK: str = "https://youtu.be/aB3_-xYz012"
BROKEN_LINK: str = "https://youtu.be/zzzzzzzzzzz"
UK_ROW: AdmittedRow = admitted_row(2, UK_LINK, START)
RU_ROW: AdmittedRow = admitted_row(3, RU_LINK, START)
BROKEN_ROW: AdmittedRow = admitted_row(4, BROKEN_LINK, START)
EMPTY_ROW: SkippedRow = SkippedRow(SheetRow(7, "", "", ""), RowSkipReason.EMPTY_LINK)
PAST_ROW: SkippedRow = SkippedRow(SheetRow(8, UK_LINK, "01.03.2027", "19:00"), RowSkipReason.IN_PAST)


def _result() -> IntakeResult:
    videos: tuple[SourceVideo, ...] = (
        ready_source(UK_ROW, "Эфир UK", "Описание", "uk", PREVIEW),
        ready_source(RU_ROW, "Эфир RU", "Описание", "ru"),
        failed_source(BROKEN_ROW, SourceFailureReason.UNAVAILABLE),
    )
    return IntakeResult(
        rows=PlannedRows(admitted=(UK_ROW, RU_ROW, BROKEN_ROW), skipped=(EMPTY_ROW, PAST_ROW)),
        sources=PreparedSources(videos),
        build=build_slots(videos, KYIV),
    )


def test_the_part_is_the_console_lines_and_three_sections() -> None:
    result: IntakeResult = _result()
    part: PartReport = IntakeReport(result).part_report
    assert part.title == msg.REPORT_PART_INTAKE and part.body == result.console_lines
    assert [section.header for section in part.sections] == [
        "### Отсеянные строки таблицы (2)", "### Видео (3)", "### Слоты (2)"
    ]


def test_the_rows_the_videos_and_the_slots_are_written_line_by_line() -> None:
    skipped, videos, slots = IntakeReport(_result()).part_report.sections
    assert list(skipped.items) == [
        f"строка 7: - — {RowSkipReason.EMPTY_LINK.human}",
        f"строка 8: {UK_LINK} — {RowSkipReason.IN_PAST.human}",
    ]
    assert list(videos.items) == [
        f"строка 2: {UK_LINK} — язык uk, превью есть",
        f"строка 3: {RU_LINK} — язык ru, превью нет",
        f"строка 4: {BROKEN_LINK} — {SourceFailureReason.UNAVAILABLE.human}",
    ]
    assert list(slots.items) == [
        "17.03.2027 19:00 uk — видео: 1, тексты: тексты видео — «Эфир UK»",
        "17.03.2027 19:00 ru — видео: 1, тексты: тексты видео — «Эфир RU»",
    ]


def test_a_table_that_did_not_read_gives_only_its_line() -> None:
    """Таблица не дала рядов: строка причины, разделов нет."""
    part: PartReport = IntakeReport(IntakeResult()).part_report
    assert all(not section.lines for section in part.sections)
    assert part.body == IntakeResult().console_lines


def test_every_text_origin_has_its_words() -> None:
    assert set(msg.REPORT_TEXT_ORIGINS) == {origin.value for origin in SlotTextOrigin}
