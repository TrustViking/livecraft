from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.dates import FILE_STAMP_FORMAT, parse_datetime_text
from app.observability.log_event import LogArea
from app.paths import LivecraftPaths
from app.records.record_meta import SCHEMA_VERSION
from app.records.record_store import RecordStore
from app.records.slot_record import SlotRecord, SlotStage
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.records import (
    CHANNEL_ID,
    CLOCK,
    KEY,
    LATER,
    LATER_CLOCK,
    NOW,
    SLOT_ID,
    records_file,
    slot_record,
    utc,
    with_stage,
)
from app.ui import messages_ru as msg


def _drop_created_utc(path: Path) -> None:
    """База из сборки, где отметки «когда появилась память» ещё не было."""
    connection: sqlite3.Connection = sqlite3.connect(path)
    with connection:
        connection.execute("DELETE FROM meta WHERE key = 'created_utc'")
    connection.close()


def _stored_created_utc(path: Path) -> str:
    connection: sqlite3.Connection = sqlite3.connect(path)
    value: str = connection.execute("SELECT value FROM meta WHERE key = 'created_utc'").fetchone()[0]
    connection.close()
    return value


def test_new_file_is_new_then_existing_is_not(livecraft_paths: LivecraftPaths) -> None:
    path: Path = records_file(livecraft_paths)
    assert path == livecraft_paths.root / "secrets" / "livecraft.sqlite3"
    store: RecordStore = RecordStore.open(path, read_only=False, clock=CLOCK)
    assert store.is_new and path.exists()
    store.close()
    again: RecordStore = RecordStore.open(path, read_only=False, clock=CLOCK)
    assert not again.is_new
    again.close()


def test_a_missing_folder_is_created(tmp_path: Path) -> None:
    path: Path = tmp_path / "secrets" / "livecraft.sqlite3"
    RecordStore.open(path, read_only=False, clock=CLOCK).close()
    assert path.exists()


def test_upsert_find_and_keys_in_full(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    store: RecordStore = RecordStore.open(path, read_only=False, clock=CLOCK)
    assert store.find(SLOT_ID, CHANNEL_ID) is None
    assert store.save(slot_record())
    assert store.save(slot_record(stage=SlotStage.KEY_CONFIRMED))
    store.close()
    reopened: RecordStore = RecordStore.open(path, read_only=True, clock=CLOCK)
    found: SlotRecord | None = reopened.find(SLOT_ID, CHANNEL_ID)
    assert found is not None and found.stage is SlotStage.KEY_CONFIRMED
    assert found.results.stream_key == KEY
    assert reopened.find(SLOT_ID, "UC2") is None                        # запись — по id канала YouTube
    reopened.close()
    connection: sqlite3.Connection = sqlite3.connect(path)
    assert connection.execute("SELECT count(*) FROM slots").fetchone()[0] == 1
    connection.close()


def test_delete_started_before(tmp_path: Path) -> None:
    store: RecordStore = RecordStore.open(tmp_path / "livecraft.sqlite3", read_only=False, clock=CLOCK)
    store.save(slot_record("15-02-2027_1900_uk", "2027-02-15T17:00:00+00:00"))
    store.save(slot_record())
    assert store.delete_started_before(datetime(2027, 3, 1, tzinfo=timezone.utc)) == 1
    assert store.find("15-02-2027_1900_uk", CHANNEL_ID) is None
    assert store.find(SLOT_ID, CHANNEL_ID) is not None
    store.close()


def test_broken_file_is_renamed_by_the_program_clock_and_a_new_memory_is_created(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    path.write_bytes(b"this is not a sqlite database at all" * 100)
    with LogCapture.on(LogArea.RECORDS) as capture:
        store: RecordStore = RecordStore.open(path, read_only=False, clock=CLOCK)
    assert store.is_new
    broken: list[Path] = list(tmp_path.glob("livecraft.sqlite3.broken-*"))
    assert [item.name for item in broken] == ["livecraft.sqlite3.broken-16-03-2027_120000"]
    assert broken[0].name.endswith(NOW.strftime(FILE_STAMP_FORMAT))
    assert broken[0].read_bytes().startswith(b"this is not")
    assert store.save(slot_record())
    assert store.take_warnings() == [msg.RECORDS_BROKEN.format(path=path, renamed=broken[0].name)]
    assert store.take_warnings() == []
    assert capture.messages(logging.WARNING)[0].startswith(
        f"records_broken path={path} renamed=livecraft.sqlite3.broken-16-03-2027_120000 error="
    )
    store.close()


def test_read_only_without_file_writes_nothing(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    store: RecordStore = RecordStore.open(path, read_only=True, clock=CLOCK)
    assert store.is_new and store.is_read_only and store.path == path
    assert store.save(slot_record()) is False
    assert store.find(SLOT_ID, CHANNEL_ID) is None
    assert store.delete_started_before(NOW) == 0
    store.close()
    assert list(tmp_path.iterdir()) == []


def test_read_only_with_file_does_not_change_it(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    writable: RecordStore = RecordStore.open(path, read_only=False, clock=CLOCK)
    writable.save(slot_record())
    writable.close()
    before: bytes = path.read_bytes()
    store: RecordStore = RecordStore.open(path, read_only=True, clock=CLOCK)
    assert not store.is_new and store.find(SLOT_ID, CHANNEL_ID) is not None
    assert store.save(slot_record(stage=SlotStage.KEY_CONFIRMED)) is False
    store.close()
    assert path.read_bytes() == before


def test_read_only_file_without_the_slots_table_reads_as_empty(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    connection: sqlite3.Connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE other (x TEXT)")
    connection.close()
    store: RecordStore = RecordStore.open(path, read_only=True, clock=CLOCK)
    assert store.is_new and store.find(SLOT_ID, CHANNEL_ID) is None and store.created_utc == utc(NOW)
    store.close()


def test_read_only_broken_file_works_without_records(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    path.write_bytes(b"garbage" * 1000)
    store: RecordStore = RecordStore.open(path, read_only=True, clock=CLOCK)
    assert store.find(SLOT_ID, CHANNEL_ID) is None
    assert store.take_warnings() == [msg.RECORDS_BROKEN_READ_ONLY.format(path=path)]
    store.close()
    assert path.read_bytes() == b"garbage" * 1000 and len(list(tmp_path.iterdir())) == 1


def test_write_failure_does_not_escape_and_is_reported_once(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    store: RecordStore = RecordStore.open(path, read_only=False, clock=CLOCK)
    store.connection.close()                                           # сбой базы
    with LogCapture.on(LogArea.RECORDS) as capture:
        assert store.save(slot_record()) is False
        assert store.save(slot_record("18-03-2027_1900_uk")) is False
        assert store.find(SLOT_ID, CHANNEL_ID) is None                  # чтение тоже не падает
        assert store.delete_started_before(NOW) == 0
    lines: list[str] = capture.messages(logging.WARNING)
    assert sum(1 for line in lines if line.startswith("records_write_failed")) == 2
    assert sum(1 for line in lines if line.startswith("records_read_failed")) == 1
    assert sum(1 for line in lines if line.startswith("records_clean_failed")) == 1
    [warning] = store.take_warnings()
    assert warning.startswith(f"Память программы {path} не записывается (")


def test_close_is_idempotent() -> None:
    store: RecordStore = RecordStore.memory(utc(NOW))
    store.close()
    store.close()
    assert store.is_closed


def test_schema_version_is_recorded(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    RecordStore.open(path, read_only=False, clock=CLOCK).close()
    connection: sqlite3.Connection = sqlite3.connect(path)
    assert connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone() == (SCHEMA_VERSION,)
    connection.close()


def test_saved_line_names_requested_stage_only_when_it_differs_and_masks_the_key(tmp_path: Path) -> None:
    store: RecordStore = RecordStore.open(tmp_path / "livecraft.sqlite3", read_only=False, clock=CLOCK)
    with LogCapture.on(LogArea.RECORDS) as capture:
        store.save(slot_record(), requested=SlotStage.ADMITTED)
        store.save(slot_record(), requested=SlotStage.PUBLISHED)
    store.close()
    assert capture.messages(logging.INFO) == [
        "record_saved slot_id=17-03-2027_1900_uk youtube_channel_id=UC1 stage=published stream_key=****-abcd "
        "requested=admitted",
        "record_saved slot_id=17-03-2027_1900_uk youtube_channel_id=UC1 stage=published stream_key=****-abcd",
    ]


def test_record_read_back_has_same_content_except_updated_at(tmp_path: Path) -> None:
    """Сравнение «запись изменилась»: прочитанная из памяти и та же, построенная заново, — одинаковые."""
    store: RecordStore = RecordStore.open(tmp_path / "livecraft.sqlite3", read_only=False, clock=CLOCK)
    store.save(slot_record())
    found: SlotRecord | None = store.find(SLOT_ID, CHANNEL_ID)
    store.close()
    assert found is not None
    later: SlotRecord = slot_record(updated_at="16-03-2027 13:00")
    assert later.has_same_content(found)
    assert not with_stage(later, SlotStage.KEY_CONFIRMED).has_same_content(found)


def test_created_utc_is_written_with_a_new_base_and_kept(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    store: RecordStore = RecordStore.open(path, read_only=False, clock=CLOCK)
    assert store.created_utc == utc(NOW)
    store.close()
    again: RecordStore = RecordStore.open(path, read_only=False, clock=LATER_CLOCK)
    assert again.created_utc == utc(NOW)
    again.close()
    reader: RecordStore = RecordStore.open(path, read_only=True, clock=LATER_CLOCK)
    assert reader.created_utc == utc(NOW)
    reader.close()


def test_base_with_records_without_created_utc_gets_the_earliest_record(tmp_path: Path) -> None:
    """Отметка «сейчас» у непустой базы молча записала бы ключи эфиров как уже переданные стримеру."""
    path: Path = tmp_path / "livecraft.sqlite3"
    store: RecordStore = RecordStore.open(path, read_only=False, clock=CLOCK)
    store.save(slot_record(updated_at="16-03-2027 11:00"))
    store.save(slot_record("18-03-2027_1900_uk", updated_at="15-03-2027 09:30"))
    store.close()
    _drop_created_utc(path)
    earliest: datetime = datetime(2027, 3, 15, 7, 30, tzinfo=timezone.utc)      # 09:30 по Киеву, зима
    reader: RecordStore = RecordStore.open(path, read_only=True, clock=LATER_CLOCK)
    assert reader.created_utc == earliest
    reader.close()
    with LogCapture.on(LogArea.RECORDS) as capture:
        writer: RecordStore = RecordStore.open(path, read_only=False, clock=LATER_CLOCK)
    assert writer.created_utc == earliest
    writer.close()
    assert capture.messages() == [
        f"records_created_utc_initialized value={earliest.isoformat()} source=min_updated_at"
    ]
    assert _stored_created_utc(path) == earliest.isoformat()


def test_updated_at_is_read_in_the_zone_of_the_program_clock(tmp_path: Path) -> None:
    """Момент записи — по поясу часов программы, а не машины: одна база — одна граница на любой машине."""
    zone: ZoneInfo = ZoneInfo("America/New_York")
    clock: StoppedClock = StoppedClock.at(LATER, zone)
    path: Path = tmp_path / "livecraft.sqlite3"
    store: RecordStore = RecordStore.open(path, read_only=False, clock=clock)
    store.save(slot_record(updated_at="15-03-2027 09:30"))
    store.close()
    _drop_created_utc(path)
    reader: RecordStore = RecordStore.open(path, read_only=True, clock=clock)
    assert reader.created_utc == datetime(2027, 3, 15, 13, 30, tzinfo=timezone.utc)   # 09:30 в Нью-Йорке, лето
    assert reader.created_utc == parse_datetime_text("15-03-2027 09:30", zone)
    reader.close()


def test_base_without_created_utc_gets_the_current_time(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.sqlite3"
    RecordStore.open(path, read_only=False, clock=CLOCK).close()
    _drop_created_utc(path)
    reader: RecordStore = RecordStore.open(path, read_only=True, clock=LATER_CLOCK)
    assert reader.created_utc == utc(LATER)                             # только чтение: в базу не пишет
    reader.close()
    with LogCapture.on(LogArea.RECORDS) as capture:
        store: RecordStore = RecordStore.open(path, read_only=False, clock=LATER_CLOCK)
    assert store.created_utc == utc(LATER) and not store.is_new
    store.close()
    assert capture.messages() == [f"records_created_utc_initialized value={utc(LATER).isoformat()} source=now"]
    assert _stored_created_utc(path) == utc(LATER).isoformat()


def test_memory_without_file_keeps_the_given_time() -> None:
    moment: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store: RecordStore = RecordStore.memory(moment)
    assert store.created_utc == moment and store.is_new and not store.is_read_only and store.path is None
    store.close()
