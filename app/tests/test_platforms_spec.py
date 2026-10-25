from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config.channel import ChannelConfig, Platform, Privacy
from app.config.files import SettingsFile, ShippedSettings
from app.config.settings import LivecraftSettings
from app.platforms.broadcast import BroadcastFacts, UpcomingBroadcast
from app.platforms.limits import PlatformLimits
from app.platforms.spec import SPEC_ATTRIBUTES, BroadcastSpec, ChangedField, SpecTexts
from app.platforms.stream import StreamInfo
from app.slots.preview import Preview
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.fixtures.config import settings_data, write_json

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
START: datetime = datetime(2027, 3, 17, 19, 0, tzinfo=KYIV)
LIMITS: PlatformLimits = PlatformLimits(
    title_max_chars=20,
    description_max_chars=40,
    auto_stop=True,
    latency_preference="normal",
)
CHANNEL: ChannelConfig = ChannelConfig(
    platform=Platform.YOUTUBE,
    account_name="Канал UA",
    handle="@KanalUA",
    google_account="owner@gmail.com",
    languages=("uk",),
    privacy=Privacy.UNLISTED,
)
SETTINGS: LivecraftSettings = ShippedSettings().settings
PREVIEW: Preview = Preview(data=b"\xff\xd8jpeg", width=1280, height=720)


def slot(title: str = "Эфир", description: str = "Текст", previews: tuple[Preview, ...] = ()) -> StreamSlot:
    texts: SlotTexts = SlotTexts(title=title, description=description, origin=SlotTextOrigin.SOURCE_SINGLE)
    return StreamSlot(SlotKey(START, "uk"), texts, previews, ("https://www.youtube.com/watch?v=dQw4w9WgXcQ",))


def expected(item: StreamSlot, settings: LivecraftSettings = SETTINGS) -> BroadcastSpec:
    return BroadcastSpec.from_slot(item, LIMITS, CHANNEL, settings)


def broadcast(title: str, description: str, stream_id: str | None = "S1", **overrides: Any) -> UpcomingBroadcast:
    """Эфир так, как его вернул бы список YouTube для эфира, поставленного программой с поставочными настройками."""
    values: dict[str, Any] = dict(
        broadcast_id="B1",
        start_utc=START.astimezone(timezone.utc),
        title=title,
        description=description,
        stream_id=stream_id,
        privacy_status=CHANNEL.privacy.value,
        auto_start=SETTINGS.auto_start,
        auto_stop=LIMITS.auto_stop,
        latency_preference=LIMITS.latency_preference,
    )
    values.update(overrides)
    return UpcomingBroadcast(**values)


def stream(title: str) -> StreamInfo:
    return StreamInfo(
        stream_id="S1", title=title, ingestion_address="rtmp://a.rtmp.youtube.com/live2", stream_name="abcd-abcd-abcd-abcd"
    )


def changed_spec(spec: BroadcastSpec, **changes: Any) -> BroadcastSpec:
    return BroadcastSpec(**{**asdict(spec), **changes})


def settings_with(tmp_path: Path, **changes: Any) -> LivecraftSettings:
    """Настройки из livecraft.json с этими полями — тем же разбором, что у программы."""
    data: dict[str, Any] = settings_data()
    data.update(changes)
    return SettingsFile(write_json(tmp_path / "livecraft.json", data)).load()


def test_texts_follow_one_rule_for_both_sides() -> None:
    """Название — без краёв; описание — LF, без хвостовых пробелов строк и краёв; пустые строки внутри остаются."""
    fitted: SpecTexts = SpecTexts("  Эфир недели  ", "  Текст  \r\n\r\nещё  \r\n").fitted(LIMITS)
    assert fitted == SpecTexts("Эфир недели", "Текст\n\nещё")
    assert SpecTexts("Эфир  недели", "Строка\rвторая\n\n\nтретья").fitted(LIMITS) == SpecTexts(
        "Эфир  недели", "Строка\nвторая\n\n\nтретья"
    )


def test_spec_from_slot_normalizes_and_trims() -> None:
    item: StreamSlot = slot(title="  Очень длинное название эфира на канале  ", description="Первый абзац  \r\n\r\nВторой  ")
    spec: BroadcastSpec = expected(item)
    assert len(spec.title) <= LIMITS.title_max_chars
    assert spec.title == spec.title.strip()
    assert spec.description == "Первый абзац\n\nВторой"
    assert spec.marker == item.slot_id == "17-03-2027_1900_uk"
    assert spec.start_minute == datetime(2027, 3, 17, 17, 0, tzinfo=timezone.utc)
    assert spec.start_minute.tzinfo is timezone.utc


def test_fields_come_from_slot_and_channel() -> None:
    """Метка и тексты — из слота, видимость — из канала (§6 инвариант 7)."""
    spec: BroadcastSpec = expected(slot(title="Эфир", description="Текст"))
    assert (spec.marker, spec.title, spec.description) == ("17-03-2027_1900_uk", "Эфир", "Текст")
    assert spec.privacy == "unlisted"


def test_spec_from_slot_takes_every_dictated_value_from_its_source(tmp_path: Path) -> None:
    """Категория и автостарт — из livecraft.json, автостоп и задержка — от площадки."""
    settings: LivecraftSettings = settings_with(tmp_path, auto_start=False, category_id="25")
    spec: BroadcastSpec = expected(slot(), settings)
    assert (spec.privacy, spec.category_id, spec.auto_start) == ("unlisted", "25", False)
    assert (spec.auto_stop, spec.latency_preference) == (LIMITS.auto_stop, LIMITS.latency_preference)
    # слот без превью: обложку программа не ставит — и не сверяет; остальные диктуемые поля заполнены
    assert spec.has_own_thumbnail is None
    assert all(spec.value(name) is not None for name in ChangedField if name is not ChangedField.THUMBNAIL)
    # слот с превью: обложка должна стоять
    assert expected(slot(previews=(PREVIEW,)), settings).has_own_thumbnail is True


def test_thumbnail_is_not_dictated_when_settings_say_so(tmp_path: Path) -> None:
    settings: LivecraftSettings = settings_with(tmp_path, set_thumbnail=False)
    assert expected(slot(previews=(PREVIEW,)), settings).has_own_thumbnail is None


def test_spec_from_platform_applies_the_same_rules() -> None:
    item: StreamSlot = slot(title="Эфир", description="Текст")
    actual: BroadcastSpec = BroadcastSpec.from_platform(
        broadcast("  Эфир  ", "Текст  \r\n", category_id=SETTINGS.category_id), stream(item.slot_id), LIMITS
    )
    assert actual == expected(item)
    assert actual.diff(expected(item)) == ()


def test_spec_from_platform_without_stream_has_empty_marker() -> None:
    assert BroadcastSpec.from_platform(broadcast("Эфир", "", None), None, LIMITS).marker == ""


def test_own_thumbnail_is_a_picture_other_than_the_channel_placeholders() -> None:
    """Картинка эфира совпала с заглушкой канала — обложки нет; картинку не скачали — не сверяется."""
    placeholders: frozenset[str] = frozenset({"044eb0835668"})
    assert BroadcastSpec.from_platform(
        broadcast("Эфир", "", thumbnail_sha="044eb0835668"), None, LIMITS, placeholders
    ).has_own_thumbnail is False
    assert BroadcastSpec.from_platform(
        broadcast("Эфир", "", thumbnail_sha="aaaaaaaaaaaa"), None, LIMITS, placeholders
    ).has_own_thumbnail is True
    assert BroadcastSpec.from_platform(broadcast("Эфир", ""), None, LIMITS, placeholders).has_own_thumbnail is None


def test_diff_reports_both_texts() -> None:
    item: StreamSlot = slot(title="Новое", description="Новое описание")
    actual: BroadcastSpec = BroadcastSpec.from_platform(broadcast("Старое", "Старое описание"), stream(item.slot_id), LIMITS)
    assert actual.diff(expected(item)) == (ChangedField.TITLE, ChangedField.DESCRIPTION)


@pytest.mark.parametrize(
    ("overrides", "marker", "changed"),
    [
        ({"privacy_status": "private"}, None, ChangedField.PRIVACY),
        ({"category_id": "24"}, None, ChangedField.CATEGORY),
        ({}, "Мой ключ", ChangedField.MARKER),
        ({"auto_start": False}, None, ChangedField.AUTO_START),
        ({"auto_stop": False}, None, ChangedField.AUTO_STOP),
        ({"latency_preference": "low"}, None, ChangedField.LATENCY),
    ],
    ids=["privacy", "category", "marker", "auto_start", "auto_stop", "latency"],
)
def test_diff_covers_every_dictated_field(overrides: dict[str, Any], marker: str | None, changed: ChangedField) -> None:
    item: StreamSlot = slot()
    spec: BroadcastSpec = expected(item)
    actual: BroadcastSpec = BroadcastSpec.from_platform(
        broadcast(spec.title, spec.description, **overrides), stream(marker or item.slot_id), LIMITS
    )
    assert actual.diff(spec) == (changed,)


def test_diff_ignores_time_and_unreported_values() -> None:
    """По времени эфир опознают; поле, которое площадка не вернула (None), сравнивать не с чем."""
    spec: BroadcastSpec = expected(slot())
    other: BroadcastSpec = changed_spec(
        spec, start_minute=spec.start_minute + timedelta(days=5), category_id=None, privacy=None, auto_start=None
    )
    assert other.diff(spec) == ()
    # но пропажа поля не беззвучна: not_compared называет, по чему сверки не было; у слота без превью — и обложка
    assert other.not_compared(spec) == (
        ChangedField.CATEGORY,
        ChangedField.PRIVACY,
        ChangedField.THUMBNAIL,
        ChangedField.AUTO_START,
    )
    assert spec.not_compared(spec) == (ChangedField.THUMBNAIL,)


def test_every_dictated_field_has_a_spec_attribute() -> None:
    assert set(SPEC_ATTRIBUTES) == set(ChangedField)


def test_spec_from_facts_uses_expected_start_when_platform_has_none() -> None:
    spec: BroadcastSpec = expected(slot())
    facts: BroadcastFacts = BroadcastFacts(
        broadcast_id="B1", title=spec.title, description=spec.description, start_utc=None,
        privacy_status="private", made_for_kids=False, age_restricted=False, default_language="uk",
        default_audio_language="uk", category_id="22", bound_stream_id="S1", stream_marker=spec.marker,
        auto_start=True, auto_stop=True, latency_preference="normal",
    )
    read: BroadcastSpec = BroadcastSpec.from_facts(facts, LIMITS, spec.start_minute)
    assert read.start_minute == spec.start_minute
    assert read.diff(spec) == (ChangedField.PRIVACY,)


def test_long_title_is_trimmed_on_both_sides() -> None:
    """Слот длиннее предела не должен считаться отличающимся от того, что лежит на площадке."""
    item: StreamSlot = slot(title="Очень длинное название эфира " * 5)
    spec: BroadcastSpec = expected(item)
    actual: BroadcastSpec = BroadcastSpec.from_platform(broadcast(spec.title, item.description), stream(item.slot_id), LIMITS)
    assert actual.diff(spec) == ()
