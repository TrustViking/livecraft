from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.dates import build_slot_id, parse_iso_start
from app.sheets.plan import SheetPlan, SheetRow
from app.sheets.rows import PlanRow
from app.slots.builder import SlotBuild, SlotBuilder, SlotGroup
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTextOrigin
from app.sources.fetcher import SourceFailureReason
from app.sources.preview import Preview
from app.sources.video import SourceVideo
from app.tests.conftest import LogCollector, ready_source
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2026, 3, 1, 12, 0, tzinfo=KYIV)
HEADER: list[str] = ["Links", "Date", "Time"]
IDS: tuple[str, ...] = ("dQw4w9WgXcQ", "aB3_-xYz012", "Zx9_8yW7v6U", "Qw3_rTy8uI0", "Pl9-kJh7gF6")
RECORD_KEYS: tuple[str, ...] = (
    "slot_id", "date", "time", "start", "language", "title", "description", "previews", "sources",
)
PREVIEW: Preview = Preview(data=b"\xff\xd8jpeg", width=1280, height=720)


def link(index: int) -> str:
    return f"https://youtu.be/{IDS[index]}"


def watch(index: int) -> str:
    return f"https://www.youtube.com/watch?v={IDS[index]}"


def plan(*rows: list[str]) -> tuple[PlanRow, ...]:
    """Настоящий путь 3.1: значения диапазона → SheetPlan → разобранные ряды с подменённым «сейчас»."""
    return SheetPlan.from_values([HEADER, *rows]).plan_rows(KYIV, NOW)


def sources(rows: tuple[PlanRow, ...], languages: dict[int, str]) -> tuple[SourceVideo, ...]:
    """Источник на каждый допущенный ряд: язык по номеру ряда, название и описание с номером ряда."""
    return tuple(
        ready_source(row, f"Эфир ряда {row.row_number}", f"Описание ряда {row.row_number}", languages[row.row_number])
        for row in rows
        if row.is_admitted
    )


def failed(row: PlanRow) -> SourceVideo:
    return SourceVideo(
        row=row, metadata=None, preview=None, failure=SourceFailureReason.UNAVAILABLE,
        preview_problem=None, language=None,
    )


def row_source(row_number: int, index: int, title: str) -> SourceVideo:
    """Источник ряда в обход отсева 3.1: так в группу может попасть повтор ссылки."""
    start: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
    row: PlanRow = PlanRow.admitted(SheetRow(row_number, link(index), "", ""), start, link(index))
    return ready_source(row, title, "", "uk")


def build(videos: tuple[SourceVideo, ...]) -> SlotBuild:
    return SlotBuilder(zone=KYIV).build(videos)


# --- группировка


def test_two_rows_of_one_hour_and_language_make_one_slot_with_sources_in_row_order() -> None:
    rows: tuple[PlanRow, ...] = plan([link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"])
    result: SlotBuild = build(sources(rows, {2: "uk", 3: "uk"}))
    (slot,) = result.slots
    assert slot.slot_id == "16-10-2026_1900_uk"
    assert (slot.date, slot.time, slot.language) == ("16-10-2026", "19:00", "uk")
    assert slot.sources == (watch(0), watch(1))
    assert slot.title == "Эфир ряда 2"
    assert slot.description == "Описание ряда 2\n\nОписание ряда 3"
    assert slot.text_origin is SlotTextOrigin.SOURCE_COMPOSED
    assert result.refused == ()


def test_one_hour_in_three_languages_gives_three_slots_uk_en_then_others() -> None:
    rows: tuple[PlanRow, ...] = plan(
        [link(0), "16.10.2026", "19:00"],
        [link(1), "16.10.2026", "19:00"],
        [link(2), "16.10.2026", "19:00"],
        [link(3), "16.10.2026", "18:00"],
    )
    result: SlotBuild = build(sources(rows, {2: "de", 3: "en", 4: "uk", 5: "de"}))
    assert [slot.slot_id for slot in result.slots] == [
        "16-10-2026_1800_de", "16-10-2026_1900_uk", "16-10-2026_1900_en", "16-10-2026_1900_de",
    ]
    assert all(slot.text_origin is SlotTextOrigin.SOURCE_SINGLE for slot in result.slots)
    assert result.log_line == "slots=4 refused=0 languages=de:2,uk:1,en:1"


def test_unfit_source_does_not_get_into_a_slot() -> None:
    rows: tuple[PlanRow, ...] = plan([link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"])
    good, bad = rows
    result: SlotBuild = build((ready_source(good, "Эфир", "", "uk"), failed(bad)))
    (slot,) = result.slots
    assert slot.sources == (watch(0),)
    assert slot.text_origin is SlotTextOrigin.SOURCE_SINGLE


def test_no_fit_sources_give_no_slots(slot_log: LogCollector) -> None:
    (row,) = plan([link(0), "16.10.2026", "19:00"])
    result: SlotBuild = build((failed(row),))
    assert (result.groups, result.slots, result.refused) == ((), (), ())
    assert slot_log.messages(logging.INFO) == ["slots_built slots=0 refused=0 languages=-"]


@pytest.mark.parametrize(
    ("date_text", "slot_id", "offset"),
    [
        ("28.03.2026", "28-03-2026_1900_uk", "+02:00"),
        ("29.03.2026", "29-03-2026_1900_uk", "+03:00"),
        ("24.10.2026", "24-10-2026_1900_uk", "+03:00"),
        ("25.10.2026", "25-10-2026_1900_uk", "+02:00"),
    ],
)
def test_slot_id_across_daylight_saving_uses_local_time(date_text: str, slot_id: str, offset: str) -> None:
    rows: tuple[PlanRow, ...] = plan([link(0), date_text, "19:00"])
    (slot,) = build(sources(rows, {2: "uk"})).slots
    assert slot.slot_id == slot_id
    assert slot.time == "19:00"
    assert slot.to_record(())["start"] == f"{slot_id[6:10]}-{slot_id[3:5]}-{slot_id[:2]}T19:00:00{offset}"


def test_key_of_a_start_in_utc_is_counted_in_the_program_zone() -> None:
    utc_start: datetime = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
    row: PlanRow = PlanRow.admitted(SheetRow(2, link(0), "", ""), utc_start, link(0))
    key: SlotKey = SlotKey.of(ready_source(row, "Эфир", "", "uk"), KYIV)
    assert key.slot_id == "16-10-2026_1900_uk"
    assert key.start == utc_start
    assert key.start.utcoffset() == timedelta(hours=3)


def test_key_of_an_unfit_source_is_a_programming_error() -> None:
    (row,) = plan([link(0), "16.10.2026", "19:00"])
    with pytest.raises(ValueError):
        SlotKey.of(failed(row), KYIV)


def test_slot_key_sort_follows_start_then_language_priority() -> None:
    start: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
    keys: list[SlotKey] = [
        SlotKey(start, "pl"), SlotKey(start, "de"), SlotKey(start, "en"), SlotKey(start, "uk"),
        SlotKey(start - timedelta(hours=1), "pl"),
    ]
    ordered: list[str] = [key.slot_id for key in sorted(keys, key=lambda key: key.sort_key)]
    assert ordered == [
        "16-10-2026_1800_pl", "16-10-2026_1900_uk", "16-10-2026_1900_en",
        "16-10-2026_1900_de", "16-10-2026_1900_pl",
    ]


# --- проблема и страховка повторов


def test_slot_with_an_empty_title_is_refused_not_dropped(slot_log: LogCollector) -> None:
    rows: tuple[PlanRow, ...] = plan([link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "20:00"])
    first, second = rows
    result: SlotBuild = build(
        (ready_source(first, "x" * 150, "описание", "uk"), ready_source(second, "Эфир", "", "uk"))
    )
    assert [slot.slot_id for slot in result.slots] == ["16-10-2026_2000_uk"]
    (refused,) = result.refused
    assert refused.slot_id == "16-10-2026_1900_uk"
    assert refused.problem == msg.SLOT_EMPTY_TITLE
    warnings: list[str] = slot_log.messages(logging.WARNING)
    assert len(warnings) == 1
    assert warnings[0].startswith("slot_refused slot=16-10-2026_1900_uk ")
    assert "title_chars=0" in warnings[0]
    assert "slots_built slots=1 refused=1 languages=uk:1" in slot_log.messages(logging.INFO)


def test_same_link_twice_in_a_group_keeps_the_earlier_row(slot_log: LogCollector) -> None:
    earlier: SourceVideo = row_source(3, 0, "Ранний")
    later: SourceVideo = row_source(7, 0, "Поздний")
    other: SourceVideo = row_source(5, 1, "Другой")
    (group,) = SlotBuilder(zone=KYIV).groups((later, other, earlier))
    assert group.videos == (earlier, other)
    assert slot_log.messages(logging.WARNING) == [
        f"slot_duplicate_link slot=16-10-2026_1900_uk link={link(0)} kept_row=3 skipped_row=7"
    ]
    assert group.slot().title == "Ранний"


def test_group_of_keeps_row_order() -> None:
    start: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
    videos: list[SourceVideo] = [
        ready_source(PlanRow.admitted(SheetRow(number, link(index), "", ""), start, link(index)), "t", "", "uk")
        for number, index in ((9, 0), (4, 1), (6, 2))
    ]
    group: SlotGroup = SlotGroup.of(SlotKey(start, "uk"), videos)
    assert [video.row.row_number for video in group.videos] == [4, 6, 9]


# --- запись слота


def test_slot_takes_previews_of_sources_that_have_them_in_row_order() -> None:
    rows: tuple[PlanRow, ...] = plan(
        [link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"], [link(2), "16.10.2026", "19:00"],
    )
    other_preview: Preview = Preview(data=b"\xff\xd8other", width=640, height=360)
    videos: tuple[SourceVideo, ...] = (
        ready_source(rows[0], "Эфир", "", "uk", PREVIEW),
        ready_source(rows[1], "Без обложки", "", "uk"),
        ready_source(rows[2], "Ещё", "", "uk", other_preview),
    )
    (slot,) = build(videos).slots
    assert slot.previews == (PREVIEW, other_preview)


def test_record_follows_the_slot_schema() -> None:
    rows: tuple[PlanRow, ...] = plan(
        [f"https://www.youtube.com/watch?v={IDS[0]}&t=5s", "16.10.2026", "19:00"],
        [link(1), "16.10.2026", "19:00"],
    )
    videos: tuple[SourceVideo, ...] = (
        ready_source(rows[0], "Эфир <live>", "Опис", "uk", PREVIEW), ready_source(rows[1], "Другой", "", "uk"),
    )
    (slot,) = build(videos).slots
    record: dict[str, object] = slot.to_record(("preview_1.jpg",))
    assert tuple(record) == RECORD_KEYS
    assert record == {
        "slot_id": "16-10-2026_1900_uk",
        "date": "16-10-2026",
        "time": "19:00",
        "start": "2026-10-16T19:00:00+03:00",
        "language": "uk",
        "title": "Эфир ‹live›",
        "description": "Опис",
        "previews": ["preview_1.jpg"],
        "sources": [watch(0), watch(1)],
    }


def test_record_passes_the_rules_of_the_package_reader() -> None:
    """То, что проверяет planers `_ManifestParser._slot`: slot_id по полям, start со смещением, строки."""
    rows: tuple[PlanRow, ...] = plan([link(0), "25.10.2026", "02:30"], [link(1), "29.03.2026", "04:15"])
    for slot in build(sources(rows, {2: "en", 3: "uk"})).slots:
        record: dict[str, object] = slot.to_record(())
        assert record["slot_id"] == build_slot_id(str(record["date"]), str(record["time"]), str(record["language"]))
        assert parse_iso_start(str(record["start"])) == slot.start
        assert datetime.fromisoformat(str(record["start"])) == slot.start
        assert isinstance(record["title"], str) and record["title"]
        assert isinstance(record["description"], str)
        sources_list: object = record["sources"]
        assert isinstance(sources_list, list) and sources_list
        assert all(isinstance(item, str) and item for item in sources_list)
        assert "text_origin" not in record


def test_record_needs_a_name_for_each_preview() -> None:
    (row,) = plan([link(0), "16.10.2026", "19:00"])
    (slot,) = build((ready_source(row, "Эфир", "", "uk", PREVIEW),)).slots
    with pytest.raises(ValueError):
        slot.to_record(())


def test_source_without_a_video_id_is_recorded_as_it_is() -> None:
    start: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
    odd_link: str = "https://example.org/stream"
    video: SourceVideo = ready_source(PlanRow.admitted(SheetRow(2, odd_link, "", ""), start, odd_link), "t", "", "uk")
    slot: StreamSlot = SlotGroup.of(SlotKey(start, "uk"), (video,)).slot()
    assert slot.sources == (odd_link,)


def test_log_line_has_no_texts() -> None:
    (row,) = plan([link(0), "16.10.2026", "19:00"])
    (slot,) = build((ready_source(row, "Секретное название", "Длинное описание", "uk"),)).slots
    line: str = slot.log_line
    assert "Секретное" not in line and "Длинное" not in line
    assert line == (
        "slot=16-10-2026_1900_uk start=2026-10-16T19:00:00+03:00 language=uk sources=1 previews=0 "
        "texts=source_single title_chars=18 description_chars=16 description_bytes=31"
    )
