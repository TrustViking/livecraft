from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.dates import parse_iso_start
from app.slots.preview import Preview
from app.slots.slot import (
    DESCRIPTION_HEAD_CHARS,
    RecordFault,
    SlotEntry,
    SlotKey,
    SlotRecordError,
    SlotRecordKey,
    StreamSlot,
)
from app.observability.log_event import LogEvent, Quoted
from app.slots.texts import SlotProblem, SlotTextOrigin, SlotTexts

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
RECORD_KEYS: tuple[str, ...] = (
    "slot_id", "date", "time", "start", "language", "title", "description", "previews", "sources",
)
PREVIEW: Preview = Preview(data=b"\xff\xd8jpeg", width=1280, height=720)
OTHER_PREVIEW: Preview = Preview(data=b"\xff\xd8other", width=640, height=360)
SOURCES: tuple[str, ...] = (
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=aB3_-xYz012",
)


def texts(title: str = "Эфир ‹live›", description: str = "Опис") -> SlotTexts:
    return SlotTexts(title=title, description=description, origin=SlotTextOrigin.SOURCE_COMPOSED)


def slot(key: SlotKey = SlotKey(START, "uk"), title: str = "Эфир ‹live›") -> StreamSlot:
    return StreamSlot(key=key, texts=texts(title), previews=(PREVIEW, OTHER_PREVIEW), sources=SOURCES)


# --- имена файлов обложек


def test_the_cover_file_names_are_numbered_from_one_in_cover_order() -> None:
    """Одно правило имени обложки для пакета и Telegram: «{slot_id}_{номер}.jpg»."""
    assert slot().preview_file_names == ("16-10-2026_1900_uk_1.jpg", "16-10-2026_1900_uk_2.jpg")
    assert StreamSlot(SlotKey(START, "en"), texts(), (), SOURCES).preview_file_names == ()


# --- ключ слота


def test_the_key_is_parsed_back_from_its_slot_id() -> None:
    """Метка программы в названии потока снова становится ключом слота в зоне программы."""
    key: SlotKey | None = SlotKey.parse("16-10-2026_1900_uk", KYIV)
    assert key == SlotKey(START, "uk")
    assert key is not None and (key.date_text, key.time_text, key.language) == ("16-10-2026", "19:00", "uk")


@pytest.mark.parametrize(
    "text",
    ["Мой поток", "99-99-2027_1900_uk", "16-10-2026_2500_uk", "16-10-2026_1900_UK", "16-10-2026_1900_", "x16-10-2026_1900_uk"],
)
def test_text_that_is_not_a_slot_id_gives_no_key(text: str) -> None:
    assert SlotKey.parse(text, KYIV) is None


def test_the_key_counts_the_slot_id_in_its_own_zone() -> None:
    utc_start: datetime = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
    key: SlotKey = SlotKey(utc_start.astimezone(KYIV), "uk")
    assert key.slot_id == "16-10-2026_1900_uk"
    assert (key.date_text, key.time_text) == ("16-10-2026", "19:00")
    assert key.start == utc_start and key.start.utcoffset() == timedelta(hours=3)


def test_slot_key_sort_follows_start_then_language_priority() -> None:
    keys: list[SlotKey] = [
        SlotKey(START, "pl"), SlotKey(START, "de"), SlotKey(START, "en"), SlotKey(START, "uk"),
        SlotKey(START - timedelta(hours=1), "pl"),
    ]
    ordered: list[str] = [key.slot_id for key in sorted(keys, key=lambda key: key.sort_key)]
    assert ordered == [
        "16-10-2026_1800_pl", "16-10-2026_1900_uk", "16-10-2026_1900_en",
        "16-10-2026_1900_de", "16-10-2026_1900_pl",
    ]


# --- слот и его запись


def test_the_slot_takes_the_key_texts_previews_and_sources_as_given() -> None:
    """Порядок обложек и ссылок даёт тот, кто собирает слот (группа источников), — слот его не меняет."""
    made: StreamSlot = slot()
    assert (made.slot_id, made.date, made.time, made.language) == ("16-10-2026_1900_uk", "16-10-2026", "19:00", "uk")
    assert made.start == START
    assert (made.title, made.description, made.text_origin) == ("Эфир ‹live›", "Опис", SlotTextOrigin.SOURCE_COMPOSED)
    assert made.previews == (PREVIEW, OTHER_PREVIEW) and made.sources == SOURCES
    assert (made.key, made.texts) == (SlotKey(START, "uk"), texts())


def test_a_slot_with_an_empty_title_has_a_problem_and_an_empty_description_does_not() -> None:
    assert slot(title="   ").problem is SlotProblem.EMPTY_TITLE
    assert slot(title="   ").problem is texts("   ").problem
    assert StreamSlot(SlotKey(START, "uk"), texts(description=""), (), SOURCES).problem is None


def test_record_follows_the_slot_schema() -> None:
    record: dict[str, object] = slot().to_record(("preview_1.jpg", "preview_2.jpg"))
    assert tuple(record) == RECORD_KEYS == tuple(key.value for key in SlotRecordKey)
    assert record == {
        "slot_id": "16-10-2026_1900_uk",
        "date": "16-10-2026",
        "time": "19:00",
        "start": "2026-10-16T19:00:00+03:00",
        "language": "uk",
        "title": "Эфир ‹live›",
        "description": "Опис",
        "previews": ["preview_1.jpg", "preview_2.jpg"],
        "sources": list(SOURCES),
    }


def test_record_passes_the_rules_of_the_package_reader() -> None:
    """То, что проверяет читатель пакета: slot_id по полям, start со смещением, строки; происхождения текстов нет."""
    for key in (SlotKey(datetime(2026, 10, 25, 2, 30, tzinfo=KYIV), "en"), SlotKey(START, "uk")):
        made: StreamSlot = slot(key)
        record: dict[str, object] = made.to_record(("a.jpg", "b.jpg"))
        assert record["slot_id"] == f'{record["date"]}_{str(record["time"]).replace(":", "")}_{record["language"]}'
        assert parse_iso_start(str(record["start"])) == made.start
        assert isinstance(record["title"], str) and record["title"]
        assert isinstance(record["sources"], list) and all(isinstance(item, str) for item in record["sources"])
        assert "text_origin" not in record


def test_log_fields_carry_the_links_the_title_and_the_head_of_the_description() -> None:
    """Решение 38: ссылки источников, название целиком и начало описания — не длиннее DESCRIPTION_HEAD_CHARS знаков."""
    made: StreamSlot = StreamSlot(
        SlotKey(START, "uk"),
        SlotTexts(title="Название эфира", description="Короткое описание", origin=SlotTextOrigin.SOURCE_SINGLE),
        (),
        SOURCES,
    )
    line: str = LogEvent.of("slot", **made.log_fields).text
    assert line == (
        "slot slot=16-10-2026_1900_uk start=2026-10-16T19:00:00+03:00 language=uk sources=2 "
        f"links={SOURCES[0]},{SOURCES[1]} previews=0 texts=source_single title_chars=14 description_chars=17 "
        'title="Название эфира" description_head="Короткое описание"'
    )


def test_the_head_of_a_long_description_is_cut_to_the_limit() -> None:
    description: str = "а" * (DESCRIPTION_HEAD_CHARS + 50)
    made: StreamSlot = StreamSlot(
        SlotKey(START, "uk"), SlotTexts("Эфир", description, SlotTextOrigin.SOURCE_SINGLE), (), SOURCES[:1]
    )
    head: object = made.log_fields["description_head"]
    assert head == Quoted("а" * DESCRIPTION_HEAD_CHARS)


KYIV_ZONE: ZoneInfo = ZoneInfo("Europe/Kyiv")


def test_an_entry_is_the_record_of_a_slot_read_back() -> None:
    """`to_record` и `SlotEntry.of_record` — одно правило в обе стороны: тексты становятся «из пакета»."""
    start: datetime = datetime(2027, 3, 17, 19, 0, tzinfo=KYIV_ZONE)
    preview: Preview = Preview(data=b"jpeg", width=1, height=1)
    slot: StreamSlot = StreamSlot(
        SlotKey(start, "uk"), SlotTexts("Эфир", "", SlotTextOrigin.MERGED), (preview,), ("https://youtu.be/x",)
    )
    record: dict[str, object] = slot.to_record(("previews/17-03-2027_1900_uk_1.jpg",))
    entry: SlotEntry = SlotEntry.of_record(record, KYIV_ZONE)
    assert entry.slot_id == slot.slot_id and entry.start == start and entry.language == "uk"
    assert entry.preview_names == ("previews/17-03-2027_1900_uk_1.jpg",) and entry.title == "Эфир"
    rebuilt: StreamSlot = entry.slot((preview,))
    assert rebuilt.key == slot.key and rebuilt.previews == (preview,) and rebuilt.sources == slot.sources
    assert rebuilt.texts == SlotTexts("Эфир", "", SlotTextOrigin.PACKAGE) and rebuilt.is_for_youtube


def test_an_entry_takes_the_start_into_the_program_zone() -> None:
    """Старт с другим смещением — тот же момент; ключ — в зоне программы, slot_id записи с ним сходится."""
    record: dict[str, object] = {
        "slot_id": "17-03-2027_1900_uk", "date": "17-03-2027", "time": "19:00", "start": "2027-03-17T17:00:00+00:00",
        "language": "uk", "title": "Эфир", "description": "", "previews": [], "sources": [],
    }
    entry: SlotEntry = SlotEntry.of_record(record, KYIV_ZONE)
    assert entry.start == datetime(2027, 3, 17, 19, 0, tzinfo=KYIV_ZONE) and entry.start.tzinfo is KYIV_ZONE


@pytest.mark.parametrize(
    ("key", "value", "fault"),
    [
        (SlotRecordKey.TITLE, None, RecordFault.MISSING),
        (SlotRecordKey.TITLE, "", RecordFault.BAD_VALUE),
        (SlotRecordKey.DESCRIPTION, 5, RecordFault.BAD_VALUE),
        (SlotRecordKey.PREVIEWS, ["", "b.jpg"], RecordFault.BAD_VALUE),
        (SlotRecordKey.SOURCES, "https://youtu.be/x", RecordFault.BAD_VALUE),
        (SlotRecordKey.START, "17-03-2027 19:00", RecordFault.BAD_VALUE),
        (SlotRecordKey.SLOT_ID, "17-03-2027_1900_ru", RecordFault.BAD_VALUE),
    ],
)
def test_a_bad_field_of_the_record_names_itself(key: SlotRecordKey, value: object, fault: RecordFault) -> None:
    start: datetime = datetime(2027, 3, 17, 19, 0, tzinfo=KYIV_ZONE)
    slot: StreamSlot = StreamSlot(SlotKey(start, "uk"), SlotTexts("Эфир", "", SlotTextOrigin.MERGED), (), ())
    record: dict[str, object] = slot.to_record(())
    if value is None:
        del record[key.value]
    else:
        record[key.value] = value
    with pytest.raises(SlotRecordError) as raised:
        SlotEntry.of_record(record, KYIV_ZONE)
    assert (raised.value.key, raised.value.fault) == (key, fault)
