"""Вывод контура B в тестах (app\\output\\): каналы, ключи слотов, итоги эфиров и объекты эфиров после действий.

Объекты эфиров — тем же путём, что у программы: отбор (`planned_of`) → части, которые заполняют сверка и действия
(ключ с площадки, решение, память). Момент тестов — 16.03.2027 12:00 по Киеву (`NOW`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config.channel import ChannelConfig
from app.core.dates import ISO_TIMESPEC
from app.core.youtube_video import YouTubeVideoId
from app.output.report import ReportKind, ReportRequest, RunReport
from app.output.result import BroadcastResult, OutcomeKind
from app.paths import LivecraftPaths
from app.pipeline.decision import Decision
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.selection import Selection
from app.platforms.broadcast import CreatedBroadcast, UpcomingBroadcast
from app.platforms.stream import StreamInfo
from app.records.record_results import RecordResults
from app.records.slot_record import SlotRecord, SlotStage
from app.slots.slot import SlotKey
from app.tests.fixtures.pipeline import KYIV, LIMITS, NOW, SETTINGS, planned_of, slot_of
from app.tests.fixtures.platform import FAKE_STREAM_URL, channel_of

UA: ChannelConfig = channel_of("@Kanal_UA", "Канал UA", "uk", "ua.owner@gmail.com")
RU: ChannelConfig = channel_of("@Kanal_RU", "Канал RU", "ru", "ru.owner@gmail.com")
STREAM_ID: str = "s1"
CONFIRMED_AT: str = "12-03-2027 20:00"     # момент подтверждения в памяти: DD-MM-YYYY HH:MM по Киеву


def start_at(day: int, hour: int = 19, minute: int = 0) -> datetime:
    """Момент марта 2027 года по Киеву."""
    return datetime(2027, 3, day, hour, minute, tzinfo=KYIV)


def key_at(day: int, hour: int = 19, language: str = "uk", minute: int = 0) -> SlotKey:
    return SlotKey(start_at(day, hour, minute), language)


def result_of(kind: OutcomeKind, key: SlotKey | None = None, channel: ChannelConfig = UA, **fields: Any) -> BroadcastResult:
    """Итог эфира как значение: по умолчанию — 17.03.2027 19:00 uk на «Канал UA»."""
    return BroadcastResult(kind, key_at(17) if key is None else key, channel, **fields)


def item_at(day: int, hour: int = 19, language: str = "uk", channel: ChannelConfig = UA) -> PlannedBroadcast:
    """Объект эфира слота марта 2027 года так же, как его строит отбор."""
    return planned_of(slot_of(start_at(day, hour), language), channel)


def with_new_key(item: PlannedBroadcast, broadcast_id: str, stream_key: str) -> PlannedBroadcast:
    """Эфир создан этим запуском: ключ — из ответа площадки."""
    watch_url: str = YouTubeVideoId(broadcast_id).watch_url
    item.match.take_new_key(CreatedBroadcast(broadcast_id, watch_url, STREAM_ID, FAKE_STREAM_URL, stream_key))
    item.decision = Decision.CREATE
    return item


def with_found_key(
    item: PlannedBroadcast, broadcast_id: str, stream_key: str, decision: Decision = Decision.MATCH
) -> PlannedBroadcast:
    """Эфир найден сверкой: ключ — тот, что сейчас на площадке."""
    item.match.found = UpcomingBroadcast(broadcast_id, item.slot.start, item.slot.title, "", STREAM_ID)
    item.match.stream = StreamInfo(STREAM_ID, item.slot.slot_id, FAKE_STREAM_URL, stream_key)
    item.decision = decision
    return item


def confirmed(item: PlannedBroadcast, *, at: str = CONFIRMED_AT) -> PlannedBroadcast:
    """Память хранит подтверждение текущего ключа объекта."""
    return remembered(item, confirmed_results(item.match.stream_key or "", at=at), at)


def given_up(item: PlannedBroadcast) -> PlannedBroadcast:
    """Память помнит две отправки текущего ключа в форму объекта без подтверждения (§14 решение 49)."""
    results: RecordResults = RecordResults()
    for _ in range(2):
        results = results.with_unconfirmed_send(item.match.stream_key or "", item.admission.response_url(item.form))
    return remembered(item, results, CONFIRMED_AT)


def remembered(item: PlannedBroadcast, results: RecordResults, at: str) -> PlannedBroadcast:
    """Запись памяти объекта с этими результатами."""
    item.memory.record = SlotRecord(
        slot_id=item.slot.slot_id,
        youtube_channel_id="UC1",
        slot_start_utc=item.slot.start.astimezone(timezone.utc).isoformat(timespec=ISO_TIMESPEC),
        stage=SlotStage.KEY_CONFIRMED,
        updated_at=at,
        results=results,
    )
    return item


def confirmed_results(stream_key: str, *, at: str = CONFIRMED_AT) -> RecordResults:
    return RecordResults(confirmed_stream_key=stream_key, confirmed_at=at)


def report_of(kind: ReportKind = ReportKind.FULL, **fields: Any) -> RunReport:
    """Отчёт запуска, начатого в момент тестов."""
    return RunReport(kind, NOW, **fields)


def report_request(selection: Selection, paths: LivecraftPaths, **fields: Any) -> ReportRequest:
    """Входы прогона: момент тестов, настройки поставки, каналы UA и RU в порядке channels.json."""
    values: dict[str, Any] = dict(
        kind=ReportKind.FULL,
        started=NOW,
        selection=selection,
        settings=SETTINGS,
        limits=LIMITS,
        channels=(UA, RU),
        paths=paths,
    )
    values.update(fields)
    return ReportRequest(**values)

