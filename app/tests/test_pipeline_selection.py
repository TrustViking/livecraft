"""Отбор: слот → объекты эфиров по каналам своего языка, признак too_late, порядок (CLAUDE.md §3 шаг 8)."""
from __future__ import annotations

from datetime import timedelta

from app.config.channel import ChannelConfig
from app.observability.log_event import LogArea
from app.pipeline.decision import Decision
from app.config.settings import FormSettings
from app.packages.package_slot import PackageSlot
from app.pipeline.selection import Selection, SelectionRequest, SkipReason
from app.slots.slot import StreamSlot
from app.tests.fixtures.form import form_settings
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.pipeline import FORM, NOW, PREVIEW, TEXTS, request_of, settings_with, slot_of, with_changes
from app.tests.fixtures.platform import channel_of, two_channels

YT_UA, YT_RU = two_channels()


def _slot(minutes: int, language: str) -> StreamSlot:
    return slot_of(NOW + timedelta(minutes=minutes), language)


def _select(*slots: StreamSlot, channels: tuple[ChannelConfig, ...] = (YT_UA, YT_RU)) -> Selection:
    return Selection.of(request_of(slots, channels))


def test_too_late_slot_becomes_an_object_with_a_flag() -> None:
    """Слот внутри min_lead_minutes (поставка — 60) не выбрасывается: иначе его ключ пропал бы из keys.txt."""
    soon: StreamSlot = _slot(30, "uk")
    boundary: StreamSlot = _slot(60, "uk")
    selection: Selection = _select(soon, boundary)
    assert selection.skipped == ()
    assert {item.slot.slot_id: item.is_too_late for item in selection.planned} == {
        soon.slot_id: True,
        boundary.slot_id: False,
    }
    assert [item.decision for item in selection.planned] == [Decision.TOO_LATE, Decision.CREATE]


def test_language_without_channel_is_skipped() -> None:
    slot: StreamSlot = _slot(180, "hu")
    selection: Selection = _select(slot)
    assert [(item.slot, item.reason) for item in selection.skipped] == [(slot, SkipReason.NO_CHANNEL)]
    assert selection.planned == ()


def test_two_channels_for_one_language_give_two_objects() -> None:
    channels: tuple[ChannelConfig, ...] = (channel_of("@yt_b", "yt_b"), channel_of("@yt_a", "yt_a"))
    selection: Selection = _select(_slot(180, "uk"), channels=channels)
    assert [item.channel.account_name for item in selection.planned] == ["yt_a", "yt_b"]


def test_channel_with_two_languages_gives_an_object_per_slot_of_one_minute() -> None:
    """Канал из старого файла с двумя языками: два слота одной минуты — два объекта на этом канале."""
    uk: StreamSlot = _slot(180, "uk")
    ru: StreamSlot = _slot(180, "ru")
    multi: ChannelConfig = with_changes(channel_of("@multi", "multi"), languages=("uk", "ru"))
    selection: Selection = _select(uk, ru, channels=(multi,))
    assert [(item.slot.slot_id, item.channel.account_name) for item in selection.planned] == [
        (uk.slot_id, "multi"),
        (ru.slot_id, "multi"),
    ]
    assert selection.skipped == ()


def test_objects_are_ordered_by_start_language_and_channel() -> None:
    """Порядок слотов — SlotKey.sort_key: момент старта, затем uk, en, прочие языки."""
    later_en: StreamSlot = _slot(300, "en")
    early_uk: StreamSlot = _slot(120, "uk")
    early_ru: StreamSlot = _slot(120, "ru")
    yt_ru: ChannelConfig = with_changes(YT_RU, languages=("ru", "en"))
    selection: Selection = _select(later_en, early_ru, early_uk, channels=(YT_UA, yt_ru))
    assert [(item.slot.slot_id, item.channel.account_name) for item in selection.planned] == [
        (early_uk.slot_id, "yt_ua"),
        (early_ru.slot_id, "yt_ru"),
        (later_en.slot_id, "yt_ru"),
    ]


def test_object_is_built_from_the_request() -> None:
    """Форма — запроса; спека — из слота, канала, настроек и пределов площадки; обложки — у слота."""
    slot: StreamSlot = slot_of(NOW + timedelta(days=1), "uk", TEXTS, (PREVIEW,))
    [item] = Selection.of(request_of((slot,), (YT_UA,))).planned
    assert item.form == FORM and item.slot is slot and item.channel is YT_UA
    assert (item.expected.marker, item.expected.has_own_thumbnail) == (slot.slot_id, True)
    request = request_of((slot,), (YT_UA,), settings_with(set_thumbnail=False, min_lead_minutes=24 * 60 + 1))
    [late] = Selection.of(request).planned
    assert late.expected.has_own_thumbnail is None and late.is_too_late


def test_selection_is_logged_with_counts() -> None:
    with LogCapture.on(LogArea.PIPELINE) as capture:
        _select(_slot(30, "uk"), _slot(180, "uk"), _slot(180, "hu"))
    assert capture.messages() == ["selection_done planned=2 too_late=1 skipped=1"]


def test_every_slot_gets_the_form_of_its_own_package() -> None:
    """Режим Б: у слотов разных пакетов разные формы — объект эфира получает форму своего слота (§14 решение 18)."""
    uk: StreamSlot = _slot(180, "uk")
    ru: StreamSlot = _slot(180, "ru")
    other: FormSettings = form_settings("https://forms.gle/otherPackageForm")
    request: SelectionRequest = request_of((), (YT_UA, YT_RU))
    both: SelectionRequest = with_changes(request, slots=(PackageSlot(uk, FORM), PackageSlot(ru, other)))
    forms: dict[str, FormSettings] = {item.slot.language: item.form for item in Selection.of(both).planned}
    assert forms == {"uk": FORM, "ru": other}
