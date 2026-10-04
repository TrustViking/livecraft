"""Объекты тестов памяти программы (app\\records\\): записи, ответы, часы в поясе программы."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.dates import format_datetime_text
from app.paths import DataDir, FileName, LivecraftPaths
from app.records.record_results import ConfirmedAnswer, RecordResults
from app.records.slot_record import RecordSnapshot, SlotRecord, SlotStage
from app.tests.fixtures.clock import StoppedClock

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2027, 3, 16, 12, 0, tzinfo=KYIV)
LATER: datetime = NOW + timedelta(days=2)
CLOCK: StoppedClock = StoppedClock.at(NOW)
LATER_CLOCK: StoppedClock = StoppedClock.at(LATER)
SLOT_ID: str = "17-03-2027_1900_uk"
CHANNEL_ID: str = "UC1"
START_UTC: str = "2027-03-17T17:00:00+00:00"
KEY: str = "abcd-abcd-abcd-abcd-abcd"
OTHER_KEY: str = "wxyz-wxyz-wxyz-wxyz-wxyz"
FORM_URL: str = "https://docs.google.com/forms/d/e/ABC/formResponse"
ANSWERS: tuple[ConfirmedAnswer, ...] = (
    ConfirmedAnswer("entry.1", "Язык стрима ( Language of stream)", "Русский ( Russian)"),
    ConfirmedAnswer("entry.2", "Название канала ( Channel name)", "Канал RU"),
    ConfirmedAnswer("entry.5", "You Tube Stream Key", KEY),
)
SNAPSHOT: RecordSnapshot = RecordSnapshot(
    date="17-03-2027", time="19:00", language="ru", account_name="Канал RU", handle="kanalru",
    title="Эфир", form_url="https://forms.gle/x", decision="create", warnings=("thumbnail:forbidden",),
)


def records_file(paths: LivecraftPaths) -> Path:
    """secrets\\livecraft.sqlite3 во временном корне теста."""
    return paths.dir(DataDir.SECRETS) / FileName.RECORDS.value


def slot_record(
    slot_id: str = SLOT_ID, start: str = START_UTC, stage: SlotStage = SlotStage.PUBLISHED, updated_at: str = ""
) -> SlotRecord:
    """Запись канала UC1 с ключом потока; момент записи по умолчанию — NOW в поясе программы."""
    return SlotRecord(
        slot_id=slot_id,
        youtube_channel_id=CHANNEL_ID,
        slot_start_utc=start,
        stage=stage,
        updated_at=updated_at or format_datetime_text(NOW),
        results=RecordResults(stream_key=KEY),
    )


def with_results(record: SlotRecord, results: RecordResults) -> SlotRecord:
    return replace(record, results=results)


def with_stage(record: SlotRecord, stage: SlotStage) -> SlotRecord:
    return replace(record, stage=stage)


def with_updated_at(record: SlotRecord, updated_at: str) -> SlotRecord:
    return replace(record, updated_at=updated_at)


def snapshot_record(results: RecordResults) -> SlotRecord:
    """Запись со снимком для людей и заданными результатами."""
    return SlotRecord(
        slot_id="17-03-2027_1900_ru",
        youtube_channel_id="UC123",
        slot_start_utc=START_UTC,
        stage=SlotStage.KEY_CONFIRMED,
        updated_at="16-03-2027 12:00",
        results=results,
        snapshot=SNAPSHOT,
    )


def utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc)
