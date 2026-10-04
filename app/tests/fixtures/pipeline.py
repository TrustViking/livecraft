"""План и сверка в тестах контура B (CLAUDE.md §11): слоты, каналы, форма и объекты эфиров — тем же путём, что у
программы (`SelectionRequest.planned`).

Момент тестов — 16.03.2027 12:00 по Киеву; тренировочная форма (app\\tests\\data\\form\\) принимает даты 11–13.09.2026
и 17.03.2027, языки uk, ru, en; 18.03.2027 в ней нет.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from app.config.channel import ChannelConfig
from app.config.files import ShippedSettings
from app.config.settings import FormSettings, LivecraftSettings
from app.form.failure import FormFailure
from app.form.key_form import KeyForm
from app.form.structure import FormStructure
from app.packages.package_slot import PackageSlot
from app.pipeline.decision import Decision
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.selection import SelectionRequest
from app.platforms.broadcast import CreatedBroadcast, UpcomingBroadcast
from app.platforms.channel import Channel, ChannelStatus
from app.platforms.limits import PlatformLimits
from app.slots.preview import Preview
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.form import REFUSAL_PAGE, SHORT_URL, FakeForms, form_settings
from app.tests.fixtures.platform import FAKE_STREAM_URL, FakePlatform, channel_of

Value = TypeVar("Value")

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2027, 3, 16, 12, 0, tzinfo=KYIV)
CLOCK: StoppedClock = StoppedClock.at(NOW)
TOMORROW: datetime = datetime(2027, 3, 17, 19, 0, tzinfo=KYIV)        # дата есть в тренировочной форме
NOT_IN_FORM: datetime = datetime(2027, 3, 18, 20, 0, tzinfo=KYIV)     # даты нет в тренировочной форме
SETTINGS: LivecraftSettings = ShippedSettings().settings
FORM: FormSettings = form_settings()
LIMITS: PlatformLimits = FakePlatform().limits
TEXTS: SlotTexts = SlotTexts(title="Эфир", description="Описание эфира", origin=SlotTextOrigin.SOURCE_SINGLE)
PREVIEW: Preview = Preview(data=b"\xff\xd8jpeg", width=1280, height=720)
SOURCE: str = "https://www.youtube.com/watch?v=abcdefghijk"
CREATED: CreatedBroadcast = CreatedBroadcast(
    broadcast_id="newbc000001",
    broadcast_url="https://www.youtube.com/watch?v=newbc000001",
    stream_id="S9",
    stream_url=FAKE_STREAM_URL,
    stream_key="newk-newk-newk-newk-newk",
)


def with_changes(value: Value, **changes: Any) -> Value:
    """Тот же объект программы с другими значениями полей."""
    return dataclasses.replace(value, **changes)  # type: ignore[type-var]


def texts_of(title: str = "Эфир", description: str = "Описание эфира") -> SlotTexts:
    return SlotTexts(title=title, description=description, origin=SlotTextOrigin.SOURCE_SINGLE)


def slot_of(
    start: datetime, language: str = "uk", texts: SlotTexts = TEXTS, previews: tuple[Preview, ...] = ()
) -> StreamSlot:
    """Слот в поясе программы: одно видео-источник."""
    return StreamSlot(SlotKey(start.astimezone(KYIV), language), texts, previews, (SOURCE,))


def slot_in(hours: float, language: str = "uk", texts: SlotTexts = TEXTS) -> StreamSlot:
    """Слот через `hours` часов от момента тестов."""
    return slot_of(NOW + timedelta(hours=hours), language, texts)


def request_of(
    slots: tuple[StreamSlot, ...], channels: tuple[ChannelConfig, ...], settings: LivecraftSettings = SETTINGS
) -> SelectionRequest:
    """Запрос отбора на момент тестов: форма — раздел form поставки со ссылкой тестов, пределы — площадки-подделки."""
    return SelectionRequest(
        slots=PackageSlot.with_form(slots, FORM), channels=channels, settings=settings, limits=LIMITS, now=NOW
    )


def planned_of(
    slot: StreamSlot, channel: ChannelConfig | None = None, settings: LivecraftSettings = SETTINGS
) -> PlannedBroadcast:
    """Объект эфира так же, как его строит отбор; канал по умолчанию — yt_ua (uk)."""
    config: ChannelConfig = channel if channel is not None else channel_of()
    return request_of((slot,), (config,), settings).planned(PackageSlot(slot, FORM), config)


def objects_of(channels: tuple[ChannelConfig, ...], *slots: StreamSlot) -> list[PlannedBroadcast]:
    """Объекты всех слотов на каналах своего языка — как отбор, но без его порядка."""
    return [planned_of(slot, channel) for slot in slots for channel in channels if slot.language in channel.languages]


def settings_with(**changes: Any) -> LivecraftSettings:
    return dataclasses.replace(SETTINGS, **changes)


def channel_object(config: ChannelConfig, status: ChannelStatus = ChannelStatus.READY) -> Channel:
    """Объект канала после проверки: READY — с ответом YouTube «тот же канал»."""
    channel: Channel = Channel(config=config, token_file=Path("t.json"), status=status)
    if status is ChannelStatus.READY:
        channel.info = FakePlatform.default_channel_info(config)
    return channel


def training_form(logs_dir: Path) -> KeyForm:
    """Тренировочная форма ключей с настройками поставки: та же страница, что у тестов формы."""
    read: FormStructure | FormFailure = FakeForms.answering(REFUSAL_PAGE).reader(logs_dir).read(SHORT_URL)
    assert isinstance(read, FormStructure)
    return KeyForm.build(FORM, read)


def with_response_url(form: KeyForm, url: str) -> KeyForm:
    """Та же форма с другим адресом отправки ответа."""
    route = dataclasses.replace(form.route, structure=dataclasses.replace(form.structure, response_url=url))
    return dataclasses.replace(form, route=route)


def too_late(item: PlannedBroadcast) -> PlannedBroadcast:
    """Как его строит отбор: признак и решение TOO_LATE."""
    item.is_too_late = True
    item.decision = Decision.TOO_LATE
    return item


def admitted(item: PlannedBroadcast, logs_dir: Path, status: ChannelStatus = ChannelStatus.READY) -> PlannedBroadcast:
    """Объект после допуска: канал со статусом `status`, тренировочная форма."""
    item.admit(channel_object(item.channel, status), training_form(logs_dir))
    return item


def upcoming_of(slot: StreamSlot, published_utc: datetime | None, broadcast_id: str = "fbc") -> UpcomingBroadcast:
    """Эфир слота на площадке, созданный в `published_utc`."""
    return UpcomingBroadcast(broadcast_id, slot.start, slot.title, "", "fs", published_utc=published_utc)
