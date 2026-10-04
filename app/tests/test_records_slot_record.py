from __future__ import annotations

import json

import pytest

from app.records.record_results import RecordResults, UnconfirmedSends
from app.records.slot_record import RecordRow, SlotRecord, SlotStage
from app.tests.fixtures.records import (
    ANSWERS,
    FORM_URL,
    KEY,
    slot_record,
    snapshot_record,
    with_results,
    with_stage,
    with_updated_at,
)


def _read(record: SlotRecord, record_json: str | None = None) -> SlotRecord:
    """Запись, как её прочитает память: из строки таблицы."""
    row: RecordRow = record.row
    return SlotRecord.of(
        RecordRow(row.slot_id, row.youtube_channel_id, row.slot_start_utc, row.stage, row.updated_at,
                  record_json if record_json is not None else row.record_json)
    )


def test_json_round_trip_keeps_results_and_drops_snapshot() -> None:
    results: RecordResults = RecordResults(
        broadcast_id="B1", broadcast_url="https://www.youtube.com/watch?v=B1", stream_id="S1",
        stream_url="rtmp://a.rtmp.youtube.com/live2", stream_key=KEY, published_at="16-03-2027 12:00",
        confirmed_stream_key=KEY, confirmed_form_url=FORM_URL, confirmed_answers=ANSWERS,
        confirmed_at="16-03-2027 12:01", unconfirmed=UnconfirmedSends(KEY, FORM_URL, 1),
    )
    record: SlotRecord = snapshot_record(results)
    payload = json.loads(record.record_json())
    assert payload["schema"] == 1 and payload["snapshot"]["account_name"] == "Канал RU"
    assert payload["results"]["stream_key"] == KEY                    # ключ — полностью
    assert "Канал RU" in record.record_json()                         # не-ASCII — как есть
    restored: SlotRecord = _read(record)
    assert restored.results == results
    assert (restored.stage, restored.snapshot) == (SlotStage.KEY_CONFIRMED, None)


def test_unknown_fields_are_ignored_and_missing_are_none() -> None:
    record_json: str = json.dumps(
        {"schema": 7, "future": 1, "results": {"stream_key": KEY, "new_field": "x", "confirmed_at": 5}}
    )
    assert _read(snapshot_record(RecordResults()), record_json).results == RecordResults(stream_key=KEY)


@pytest.mark.parametrize("record_json", ["", "не json", "[1, 2]", '{"results": "x"}'])
def test_unreadable_json_gives_empty_results(record_json: str) -> None:
    assert _read(snapshot_record(RecordResults()), record_json).results == RecordResults()


def test_unknown_stage_reads_as_admitted() -> None:
    row: RecordRow = slot_record().row
    unknown: RecordRow = RecordRow("s", "c", "t", "future_stage", "u", row.record_json)
    assert SlotRecord.of(unknown).stage is SlotStage.ADMITTED


def test_stage_rank_follows_the_order_of_members() -> None:
    assert [stage.rank for stage in SlotStage] == [0, 1, 2]
    assert SlotStage.ADMITTED.rank < SlotStage.PUBLISHED.rank < SlotStage.KEY_CONFIRMED.rank


def test_the_row_carries_the_columns_in_query_order() -> None:
    record: SlotRecord = slot_record()
    assert record.row.values == (
        record.slot_id, record.youtube_channel_id, record.slot_start_utc, "published", record.updated_at,
        record.record_json(),
    )


def test_same_content_ignores_only_the_moment_of_the_record() -> None:
    stored: SlotRecord = _read(slot_record())
    later: SlotRecord = with_updated_at(slot_record(), "16-03-2027 13:00")
    assert later.has_same_content(stored)
    assert not later.has_same_content(None)
    assert not with_stage(later, SlotStage.KEY_CONFIRMED).has_same_content(stored)
    assert not with_results(later, RecordResults(stream_key="bcde-bcde-bcde-bcde-bcde")).has_same_content(stored)


def test_the_saved_line_masks_the_key_and_names_a_different_requested_stage() -> None:
    record: SlotRecord = slot_record()
    assert record.saved_event(SlotStage.ADMITTED).text == (
        "record_saved slot_id=17-03-2027_1900_uk youtube_channel_id=UC1 stage=published stream_key=****-abcd "
        "requested=admitted"
    )
    assert record.saved_event(SlotStage.PUBLISHED).text == (
        "record_saved slot_id=17-03-2027_1900_uk youtube_channel_id=UC1 stage=published stream_key=****-abcd"
    )
    without_key: SlotRecord = with_results(record, RecordResults())
    assert without_key.saved_event(None).text == "record_saved slot_id=17-03-2027_1900_uk youtube_channel_id=UC1 stage=published"
    assert KEY not in record.saved_event(None).text
