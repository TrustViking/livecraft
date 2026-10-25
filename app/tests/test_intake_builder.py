from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.intake.builder import SlotBuild, SlotBuilder, SlotGroup
from app.sheets.rows import AdmittedRow
from app.slots.preview import Preview
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotProblem, SlotTextOrigin, SlotTexts
from app.sources.metadata import SourceFailureReason
from app.sources.video import SourceVideo
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.slots import build_slots
from app.tests.fixtures.sources import admitted_row, failed_source, planned_rows, ready_source
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2026, 3, 1, 12, 0, tzinfo=KYIV)
START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
IDS: tuple[str, ...] = ("dQw4w9WgXcQ", "aB3_-xYz012", "Zx9_8yW7v6U", "Qw3_rTy8uI0", "Pl9-kJh7gF6")
PREVIEW: Preview = Preview(data=b"\xff\xd8jpeg", width=1280, height=720)


def link(index: int) -> str:
    return f"https://youtu.be/{IDS[index]}"


def watch(index: int) -> str:
    return f"https://www.youtube.com/watch?v={IDS[index]}"


def plan(*rows: list[str]) -> tuple[AdmittedRow, ...]:
    """Допущенные ряды настоящего разбора таблицы с подменённым «сейчас»."""
    return planned_rows(*rows, zone=KYIV, now=NOW).admitted


def sources(rows: tuple[AdmittedRow, ...], languages: dict[int, str]) -> tuple[SourceVideo, ...]:
    """Источник на каждый допущенный ряд: язык по номеру ряда, название и описание с номером ряда."""
    return tuple(
        ready_source(row, f"Эфир ряда {row.row_number}", f"Описание ряда {row.row_number}", languages[row.row_number])
        for row in rows
    )


def failed(row: AdmittedRow) -> SourceVideo:
    return failed_source(row, SourceFailureReason.UNAVAILABLE)


def build(videos: tuple[SourceVideo, ...]) -> SlotBuild:
    return build_slots(videos, KYIV)


# --- группировка


def test_two_rows_of_one_hour_and_language_make_one_slot_with_sources_in_row_order() -> None:
    rows: tuple[AdmittedRow, ...] = plan([link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"])
    result: SlotBuild = build(sources(rows, {2: "uk", 3: "uk"}))
    (slot,) = result.slots
    assert slot.slot_id == "16-10-2026_1900_uk"
    assert (slot.date, slot.time, slot.language) == ("16-10-2026", "19:00", "uk")
    assert slot.sources == (watch(0), watch(1))
    # два описания без ответа модели — тексты «по номерам», не для YouTube (§14 решение 32)
    assert slot.title == "1) Эфир ряда 2\n2) Эфир ряда 3"
    assert slot.description == "1) Описание ряда 2\n\n2) Описание ряда 3"
    assert slot.text_origin is SlotTextOrigin.NUMBERED
    assert result.refused == () and result.for_youtube == () and result.not_for_youtube == (slot,)
    assert result.has_errors


def test_one_hour_in_three_languages_gives_three_slots_uk_en_then_others(slot_log: LogCapture) -> None:
    rows: tuple[AdmittedRow, ...] = plan(
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
    assert "slots_built slots=4 not_for_youtube=0 refused=0 languages=de:2,uk:1,en:1" in slot_log.messages(logging.INFO)
    assert result.for_youtube == result.slots and not result.has_errors


def test_unfit_source_does_not_get_into_a_slot() -> None:
    rows: tuple[AdmittedRow, ...] = plan([link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"])
    good, bad = rows
    result: SlotBuild = build((ready_source(good, "Эфир", "", "uk"), failed(bad)))
    (slot,) = result.slots
    assert slot.sources == (watch(0),)
    assert slot.text_origin is SlotTextOrigin.SOURCE_SINGLE


def test_no_fit_sources_give_no_groups_and_no_slots(slot_log: LogCapture) -> None:
    (row,) = plan([link(0), "16.10.2026", "19:00"])
    assert SlotBuilder(KYIV).groups((failed(row),)) == ()
    result: SlotBuild = build((failed(row),))
    assert (result.slots, result.refused) == ((), ())
    assert slot_log.messages(logging.INFO) == ["slots_built slots=0 not_for_youtube=0 refused=0 languages=-"]


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
    rows: tuple[AdmittedRow, ...] = plan([link(0), date_text, "19:00"])
    (slot,) = build(sources(rows, {2: "uk"})).slots
    assert slot.slot_id == slot_id
    assert slot.time == "19:00"
    assert slot.to_record(())["start"] == f"{slot_id[6:10]}-{slot_id[3:5]}-{slot_id[:2]}T19:00:00{offset}"


# --- слот с проблемой


def test_slot_with_an_empty_title_is_refused_not_dropped(slot_log: LogCapture) -> None:
    rows: tuple[AdmittedRow, ...] = plan([link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "20:00"])
    first, second = rows
    result: SlotBuild = build(
        (ready_source(first, "x" * 150, "описание", "uk"), ready_source(second, "Эфир", "", "uk"))
    )
    assert [slot.slot_id for slot in result.slots] == ["16-10-2026_2000_uk"]
    (refused,) = result.refused
    assert refused.slot_id == "16-10-2026_1900_uk"
    assert refused.problem is SlotProblem.EMPTY_TITLE
    assert result.has_errors
    warnings: list[str] = slot_log.messages(logging.WARNING)
    assert len(warnings) == 1
    assert warnings[0].startswith("slot_refused slot=16-10-2026_1900_uk ")
    assert "title_chars=0" in warnings[0] and warnings[0].endswith("problem=empty_title")
    assert "slots_built slots=1 not_for_youtube=0 refused=1 languages=uk:1" in slot_log.messages(logging.INFO)


# --- группа источников и её слот


def test_the_group_takes_previews_of_sources_that_have_them_in_row_order() -> None:
    rows: tuple[AdmittedRow, ...] = plan(
        [link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"], [link(2), "16.10.2026", "19:00"],
    )
    other_preview: Preview = Preview(data=b"\xff\xd8other", width=640, height=360)
    videos: tuple[SourceVideo, ...] = (
        ready_source(rows[0], "Эфир", "", "uk", PREVIEW),
        ready_source(rows[1], "Без обложки", "", "uk"),
        ready_source(rows[2], "Ещё", "", "uk", other_preview),
    )
    (group,) = SlotBuilder(KYIV).groups(videos)
    assert group.previews == (PREVIEW, other_preview)
    (slot,) = build(videos).slots
    assert slot.previews == (PREVIEW, other_preview)


def test_the_group_sources_are_clean_watch_links_in_row_order() -> None:
    rows: tuple[AdmittedRow, ...] = plan(
        [f"https://www.youtube.com/watch?v={IDS[0]}&t=5s", "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"]
    )
    group: SlotGroup = SlotGroup(SlotKey(START, "uk"), tuple(ready_source(row, "Эфир", "", "uk") for row in rows))
    assert group.sources == (watch(0), watch(1))


def test_two_videos_with_one_description_need_no_merge_and_get_no_numbers() -> None:
    """Merge не нужен (одно непустое описание): тексты видео как есть — название первого, описание без «1)»."""
    rows: tuple[AdmittedRow, ...] = plan([link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"])
    videos: tuple[SourceVideo, ...] = (
        ready_source(rows[0], "Первое", "", "uk"), ready_source(rows[1], "Второе", "Опис", "uk")
    )
    (group,) = SlotBuilder(KYIV).groups(videos)
    assert not group.needs_merge
    assert group.video_texts == SlotTexts(title="Первое", description="Опис", origin=SlotTextOrigin.SOURCE_COMPOSED)
    assert group.video_texts.is_for_youtube


def test_two_descriptions_without_the_model_give_the_numbered_texts() -> None:
    rows: tuple[AdmittedRow, ...] = plan([link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "19:00"])
    (group,) = SlotBuilder(KYIV).groups(sources(rows, {2: "uk", 3: "uk"}))
    assert group.needs_merge
    assert group.video_texts.origin is SlotTextOrigin.NUMBERED and not group.video_texts.is_for_youtube


def test_a_slot_not_for_youtube_has_its_own_console_line_with_the_human_date() -> None:
    rows: tuple[AdmittedRow, ...] = plan(
        [link(0), "17.03.2027", "19:00"], [link(1), "17.03.2027", "19:00"], [link(2), "17.03.2027", "20:00"],
    )
    result: SlotBuild = build(sources(rows, {2: "uk", 3: "uk", 4: "en"}))
    assert [slot.slot_id for slot in result.for_youtube] == ["17-03-2027_2000_en"]
    assert result.console_lines[1:] == (
        msg.INTAKE_SLOT_NOT_FOR_YOUTUBE.format(language="UK", time="19:00", date="17.03.2027"),
    )
    assert result.has_errors


def test_the_source_texts_follow_the_platform_rules() -> None:
    (row,) = plan([link(0), "16.10.2026", "19:00"])
    group: SlotGroup = SlotGroup(SlotKey(START, "uk"), (ready_source(row, "Эфир <live>", "Опис", "uk", PREVIEW),))
    assert group.video_texts == SlotTexts(title="Эфир ‹live›", description="Опис", origin=SlotTextOrigin.SOURCE_SINGLE)


def test_the_slot_takes_the_texts_it_is_given() -> None:
    """Какие тексты получит слот, решает прогон: группа ставит в слот те, что ей дали."""
    (row,) = plan([link(0), "16.10.2026", "19:00"])
    group: SlotGroup = SlotGroup(SlotKey(START, "uk"), (ready_source(row, "Эфир", "Опис", "uk", PREVIEW),))
    merged: SlotTexts = SlotTexts(title="Одно название", description="Одно описание", origin=SlotTextOrigin.MERGED)
    slot: StreamSlot = group.slot(merged)
    assert (slot.title, slot.description, slot.text_origin) == ("Одно название", "Одно описание", SlotTextOrigin.MERGED)
    assert slot.sources == (watch(0),) and slot.previews == (PREVIEW,)


def test_groups_keep_the_order_of_the_sources_inside_a_slot() -> None:
    """Внутри слота источники идут в том порядке, в каком их дал каталог, — это порядок рядов."""
    videos: list[SourceVideo] = [
        ready_source(admitted_row(number, link(index), START), "t", "", "uk")
        for number, index in ((4, 1), (6, 2), (9, 0))
    ]
    (group,) = SlotBuilder(KYIV).groups(videos)
    assert [video.row.row_number for video in group.videos] == [4, 6, 9]


# --- без нейросети (§14 решение 50)


def test_without_the_ai_one_video_keeps_its_whole_texts_and_several_are_numbered() -> None:
    """Нейросеть не идёт: одно видео — его название и описание целиком (без подгонки под YouTube), несколько —
    «по номерам», даже когда merge и не был бы нужен."""
    rows: tuple[AdmittedRow, ...] = plan(
        [link(0), "16.10.2026", "19:00"], [link(1), "16.10.2026", "20:00"], [link(2), "16.10.2026", "20:00"],
    )
    long_title: str = "Эфир " + "x" * 150
    videos: tuple[SourceVideo, ...] = (
        ready_source(rows[0], long_title, "Опис <1>", "uk"),
        ready_source(rows[1], "Первое", "", "uk"),
        ready_source(rows[2], "Второе", "Опис", "uk"),
    )
    single, pair = SlotBuilder(KYIV).groups(videos)
    assert single.people_texts == SlotTexts(long_title, "Опис <1>", SlotTextOrigin.SOURCE_SINGLE)
    assert not pair.needs_merge and pair.people_texts.origin is SlotTextOrigin.NUMBERED


def test_numbered_slots_without_the_ai_are_no_error_and_have_no_lines() -> None:
    """«По номерам» без нейросети — настройка, а не отказ merge: ошибки нет, строк о слотах не для YouTube нет."""
    rows: tuple[AdmittedRow, ...] = plan([link(0), "17.03.2027", "19:00"], [link(1), "17.03.2027", "19:00"])
    groups: tuple[SlotGroup, ...] = SlotBuilder(KYIV).groups(sources(rows, {2: "uk", 3: "uk"}))
    result: SlotBuild = SlotBuild.of([group.slot(group.people_texts) for group in groups], False)
    assert result.not_for_youtube and result.merge_refused == () and not result.has_errors
    assert len(result.console_lines) == 1
