"""Сверка объектов эфиров с площадкой: опознание по минуте и метке, решения, заглушки обложки, сироты (CLAUDE.md §6
инварианты 1, 8, 9)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.config.channel import ChannelConfig
from app.form.failure import FormFailure, FormProblem
from app.observability.log_event import LogArea
from app.pipeline.decision import Decision
from app.pipeline.orphan import MarkedScan, OrphanBroadcast, OrphanKind
from app.pipeline.outcome import WarningStep
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.progress import RunProgress
from app.pipeline.reconciler import Reconciler
from app.platforms.broadcast import UpcomingBroadcast
from app.platforms.channel import ChannelStatus
from app.platforms.error import PlatformError
from app.platforms.placeholder import PlaceholderMark
from app.platforms.spec import ChangedField
from app.records.record_results import RecordResults
from app.slots.slot import SlotKey, StreamSlot
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.form import SHORT_URL
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.pipeline import (
    KYIV,
    NOW,
    PREVIEW,
    TEXTS,
    TOMORROW,
    channel_object,
    objects_of,
    planned_of,
    settings_with,
    slot_of,
    texts_of,
    too_late,
    training_form,
    with_changes,
)
from app.tests.fixtures.platform import FakePlatform, channel_of, two_channels
from app.tests.fixtures.records import slot_record

YT_UA, YT_RU_ONLY = two_channels()
YT_RU: ChannelConfig = with_changes(YT_RU_ONLY, languages=("ru", "en"))
CHANNELS: tuple[ChannelConfig, ...] = (YT_UA, YT_RU)
QUOTA: PlatformError = PlatformError("quotaExceeded", "quota exceeded")
PLACEHOLDER: str = "044eb0835668"
OWN_PICTURE: str = "aaaaaaaaaaaa"


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform()


def _slot(hours: float, language: str = "uk", previews: bool = False) -> StreamSlot:
    return slot_of(NOW + timedelta(hours=hours), language, TEXTS, (PREVIEW,) if previews else ())


def _objects(*slots: StreamSlot, channels: tuple[ChannelConfig, ...] = CHANNELS) -> list[PlannedBroadcast]:
    return objects_of(channels, *slots)


def _reconcile(
    platform: FakePlatform, *objects: PlannedBroadcast, channels: tuple[ChannelConfig, ...] = CHANNELS
) -> tuple[OrphanBroadcast, ...]:
    """Известные слоты — слоты объектов."""
    known: dict[str, datetime] = {item.slot.slot_id: item.slot.start for item in objects}
    return Reconciler(platform, KYIV, RunProgress()).reconcile(objects, known, channels)


def _seed_like(platform: FakePlatform, channel: str, slot: StreamSlot, **overrides: object) -> UpcomingBroadcast:
    """Эфир слота так, как его поставила бы программа: метка потока — slot_id."""
    values: dict[str, object] = dict(start_utc=slot.start, title=slot.title, description=slot.description)
    values["marker"] = slot.slot_id
    values.update(overrides)
    return platform.seed_broadcast(channel, **values)  # type: ignore[arg-type]


# --- решения


def test_no_broadcast_means_create(platform: FakePlatform) -> None:
    [item] = _objects(_slot(24))
    _reconcile(platform, item)
    assert item.decision is Decision.CREATE and item.match.found is None


def test_decisions_have_no_recreate_branch() -> None:
    """Эфира нет — всегда CREATE: различать «впервые» и «заново» программе нечем и незачем."""
    assert {decision.value for decision in Decision} == {
        "create", "match", "update", "no_stream", "too_late", "ambiguous", "not_admitted", "error"
    }


def test_marked_broadcast_with_same_texts_matches(platform: FakePlatform) -> None:
    slot: StreamSlot = _slot(24)
    seeded: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, stream_key="abcd-abcd-abcd-abcd-abcd")
    [item] = _objects(slot)
    _reconcile(platform, item)
    assert item.decision is Decision.MATCH and item.match.found == seeded
    assert (item.match.broadcast_id, item.match.stream_key) == (seeded.broadcast_id, "abcd-abcd-abcd-abcd-abcd")
    assert item.outcome.should_send_key is False         # эфир с меткой совпал — ключ сам по себе в форму не идёт


def test_changed_description_means_update(platform: FakePlatform) -> None:
    slot: StreamSlot = _slot(24)
    _seed_like(platform, "yt_ua", slot, description="Старое описание")
    [item] = _objects(slot)
    _reconcile(platform, item)
    assert item.decision is Decision.UPDATE and item.match.fixes.changed == (ChangedField.DESCRIPTION,)


def test_outer_spaces_and_line_endings_do_not_count(platform: FakePlatform) -> None:
    slot: StreamSlot = slot_of(NOW + timedelta(days=1), "uk", texts_of("Эфир", "Первый абзац\n\nВторой"))
    _seed_like(platform, "yt_ua", slot, title="  Эфир  ", description="Первый абзац  \r\n\r\nВторой\r\n")
    [item] = _objects(slot)
    _reconcile(platform, item)
    assert item.decision is Decision.MATCH and item.match.fixes.changed == ()


def test_title_longer_than_limit_does_not_loop_forever(platform: FakePlatform) -> None:
    """Обрезка применяется к обеим сторонам: второй прогон обязан дать MATCH."""
    slot: StreamSlot = slot_of(NOW + timedelta(days=1), "uk", texts_of("Очень длинное название эфира " * 10))
    [first] = _objects(slot)
    _seed_like(platform, "yt_ua", slot, title=first.expected.title)
    _reconcile(platform, first)
    assert len(first.expected.title) <= platform.limits.title_max_chars and first.decision is Decision.MATCH
    [second] = _objects(slot)
    _reconcile(platform, second)
    assert second.decision is Decision.MATCH


def test_two_broadcasts_of_one_minute_on_one_channel_are_told_apart_by_marker(platform: FakePlatform) -> None:
    """Канал с двумя языками: uk и ru в одну минуту — каждый опознан своей меткой, оба MATCH, не AMBIGUOUS."""
    uk, ru = _slot(24, "uk"), _slot(24, "ru")
    multi: ChannelConfig = with_changes(channel_of("@multi", "multi"), languages=("uk", "ru"))
    uk_broadcast: UpcomingBroadcast = _seed_like(platform, "multi", uk)
    ru_broadcast: UpcomingBroadcast = _seed_like(platform, "multi", ru)
    objects: list[PlannedBroadcast] = _objects(uk, ru, channels=(multi,))
    _reconcile(platform, *objects, channels=(multi,))
    assert [item.match.found for item in objects] == [uk_broadcast, ru_broadcast]
    assert {item.decision for item in objects} == {Decision.MATCH}
    assert all(not item.match.ambiguous_urls for item in objects)


def test_two_languages_on_one_minute_each_find_their_marker(platform: FakePlatform) -> None:
    ru, en = _slot(24, "ru"), _slot(24, "en")
    en_broadcast: UpcomingBroadcast = _seed_like(platform, "yt_ru", en)
    ru_broadcast: UpcomingBroadcast = _seed_like(platform, "yt_ru", ru)
    objects: list[PlannedBroadcast] = _objects(ru, en)
    _reconcile(platform, *objects)
    assert [item.match.found for item in objects] == [ru_broadcast, en_broadcast]
    assert {item.decision for item in objects} == {Decision.MATCH}
    assert len(platform.stream_calls) == len(set(platform.stream_calls))   # поток читается раз за запуск


def test_marker_of_another_slot_is_passed_by(platform: FakePlatform) -> None:
    """Метка другого слота на той же минуте — мимо; текст вида метки, который меткой не является, — эфир без метки."""
    uk: StreamSlot = _slot(24, "uk")
    _seed_like(platform, "yt_ua", uk, marker=_slot(24, "ru").slot_id)
    [item] = _objects(uk)
    _reconcile(platform, item)
    assert item.decision is Decision.CREATE and item.match.found is None
    other: FakePlatform = FakePlatform()
    manual: UpcomingBroadcast = _seed_like(other, "yt_ua", uk, marker="99-99-2027_1900_uk")
    [adopted] = _objects(uk)
    _reconcile(other, adopted)
    assert adopted.match.found == manual and adopted.match.fixes.changed == (ChangedField.MARKER,)


def test_single_manual_broadcast_is_adopted_with_its_platform_key(platform: FakePlatform) -> None:
    """Ручной эфир без метки опознан: метка программы — исправимое поле, значит UPDATE."""
    slot: StreamSlot = _slot(24)
    manual: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, marker="Мой поток")
    [item] = _objects(slot)
    _reconcile(platform, item)
    assert item.decision is Decision.UPDATE and item.match.fixes.changed == (ChangedField.MARKER,)
    assert item.match.found == manual and item.match.stream is not None
    assert item.match.stream_key == item.match.stream.stream_name


def test_broadcast_without_bound_stream_gives_no_stream(platform: FakePlatform) -> None:
    """Эфир есть, потока нет: ключ взять неоткуда — ни MATCH, ни UPDATE; метку чинить нечему."""
    slot: StreamSlot = _slot(24)
    orphaned: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, marker=None)
    [item] = _objects(slot)
    _reconcile(platform, item)
    assert item.decision is Decision.NO_STREAM and item.match.found == orphaned
    assert (item.match.stream, item.match.key) == (None, None)
    assert ChangedField.MARKER not in item.match.fixes.changed


def test_two_manual_broadcasts_are_ambiguous(platform: FakePlatform) -> None:
    slot: StreamSlot = _slot(24)
    first: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, marker=None)
    second: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, marker="Мой поток")
    [item] = _objects(slot)
    with LogCapture.on(LogArea.PIPELINE) as capture:
        orphans: tuple[OrphanBroadcast, ...] = _reconcile(platform, item)
    assert item.decision is Decision.AMBIGUOUS and orphans == ()
    # программа не выбирает, но называет все эфиры-кандидаты: предупреждение объекта со ссылками
    assert item.match.ambiguous_urls == (
        f"https://www.youtube.com/watch?v={first.broadcast_id}",
        f"https://www.youtube.com/watch?v={second.broadcast_id}",
    )
    assert [(warning.step, warning.code) for warning in item.outcome.warnings] == [(WarningStep.AMBIGUOUS, "2")]
    assert capture.messages(logging.WARNING) == [
        f'broadcast_ambiguous slot_id={slot.slot_id} channel="yt_ua" handle=@yt_ua '
        f"candidates={first.broadcast_id},{second.broadcast_id}"
    ]


def test_privacy_only_difference_means_update(platform: FakePlatform) -> None:
    slot: StreamSlot = _slot(24)
    _seed_like(platform, "yt_ua", slot, privacy="private")
    [item] = _objects(slot)
    _reconcile(platform, item)
    assert item.decision is Decision.UPDATE
    assert (item.match.fixes.changed, item.match.fixes.reported) == ((ChangedField.PRIVACY,), ())


def test_auto_start_difference_is_reported_but_keeps_the_decision(platform: FakePlatform) -> None:
    """Автостарт через API не исправить (monitorStream): решение прежнее, но владелец узнаёт."""
    slot: StreamSlot = _slot(24)
    _seed_like(platform, "yt_ua", slot, auto_start=False)
    [item] = _objects(slot)
    with LogCapture.on(LogArea.PIPELINE) as capture:
        _reconcile(platform, item)
    assert item.decision is Decision.MATCH
    assert (item.match.fixes.changed, item.match.fixes.reported) == ((), (ChangedField.AUTO_START,))
    assert [(warning.step, warning.code) for warning in item.outcome.warnings] == [
        (WarningStep.REPORTED_FIELD, "auto_start")
    ]
    assert capture.messages(logging.WARNING) == [
        f'broadcast_setting_not_fixable slot_id={slot.slot_id} channel="yt_ua" handle=@yt_ua field=auto_start '
        "wanted=yes actual=no"
    ]


def test_fields_the_platform_did_not_return_are_logged_once_per_broadcast(platform: FakePlatform) -> None:
    """Список эфиров YouTube категорию не отдаёт: сверки по ней нет — это видно в логе, а не пропадает молча."""
    slot: StreamSlot = _slot(24)
    _seed_like(platform, "yt_ua", slot)
    [item] = _objects(slot)
    with LogCapture.on(LogArea.PIPELINE) as capture:
        _reconcile(platform, item)
    lines: list[str] = [line for line in capture.messages(logging.INFO) if line.startswith("spec_fields_not_compared")]
    # у слота без превью обложка не диктуется — не сверяется
    assert lines == [
        f'spec_fields_not_compared slot_id={slot.slot_id} channel="yt_ua" handle=@yt_ua fields=category,thumbnail'
    ]


def test_decision_line_masks_the_stream_key(platform: FakePlatform) -> None:
    slot: StreamSlot = _slot(24)
    seeded: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, description="Иное", stream_key="abcd-abcd-wxyz")
    [item] = _objects(slot)
    with LogCapture.on(LogArea.PIPELINE) as capture:
        _reconcile(platform, item)
    [line] = [line for line in capture.messages() if line.startswith("pair_decision")]
    assert line == (
        f'pair_decision slot_id={slot.slot_id} channel="yt_ua" handle=@yt_ua decision=update '
        f"broadcast_id={seeded.broadcast_id} stream_key=****-wxyz fixable=description reported=-"
    )


# --- каналы


def test_list_failure_is_isolated_to_its_channel(platform: FakePlatform) -> None:
    uk, ru = _slot(24, "uk"), _slot(24, "ru")
    platform.fail_list["yt_ua"] = QUOTA
    objects: list[PlannedBroadcast] = _objects(uk, ru)
    _reconcile(platform, *objects)
    ua_item, ru_item = objects
    assert ua_item.decision is Decision.ERROR
    assert ua_item.outcome.error is not None and (ua_item.outcome.error.origin, ua_item.outcome.error.code) == (
        "youtube", "quotaExceeded"
    )
    assert ua_item.outcome.error.human == QUOTA.human
    assert ru_item.decision is Decision.CREATE


def test_list_upcoming_is_called_once_per_channel(platform: FakePlatform) -> None:
    _reconcile(platform, *_objects(_slot(24, "uk"), _slot(24, "ru"), _slot(24, "en")))
    assert platform.list_calls == ["yt_ua", "yt_ru"]


def test_channel_without_objects_is_read_for_its_orphans(platform: FakePlatform) -> None:
    """Канал запуска без объектов читается: эфир с меткой программы на нём — сирота."""
    lost: UpcomingBroadcast = _seed_like(platform, "yt_ru", _slot(48, "ru"))
    [item] = _objects(_slot(24, "uk"))
    [orphan] = _reconcile(platform, item)
    assert (orphan.channel, orphan.broadcast, orphan.kind) == (YT_RU, lost, OrphanKind.ORPHAN)


def test_progress_brackets_each_channel_read(platform: FakePlatform) -> None:
    """«Запрос» — до list_upcoming, «эфиров N» — после ответа."""
    uk, ru = _slot(24, "uk"), _slot(24, "ru")
    _seed_like(platform, "yt_ru", ru)
    record: ConsoleRecord = ConsoleRecord()
    objects: list[PlannedBroadcast] = _objects(uk, ru)
    known: dict[str, datetime] = {uk.slot_id: uk.start, ru.slot_id: ru.start}
    Reconciler(platform, KYIV, RunProgress(record.console)).reconcile(objects, known, CHANNELS)
    assert record.lines == [
        "Канал «yt_ua» @yt_ua: запрос запланированных эфиров.",
        "Канал «yt_ua» @yt_ua: запланированных эфиров — 0.",
        "Канал «yt_ru» @yt_ru: запрос запланированных эфиров.",
        "Канал «yt_ru» @yt_ru: запланированных эфиров — 1.",
    ]


def test_failed_channel_read_has_start_but_no_done(platform: FakePlatform) -> None:
    """Сбой канала владелец увидит во «Внимание»; строки «эфиров N» по нему нет."""
    platform.fail_list["yt_ua"] = QUOTA
    record: ConsoleRecord = ConsoleRecord()
    scan: MarkedScan = Reconciler(platform, KYIV, RunProgress(record.console)).marked_broadcasts(CHANNELS)
    assert record.lines == [
        "Канал «yt_ua» @yt_ua: запрос запланированных эфиров.",
        "Канал «yt_ru» @yt_ru: запрос запланированных эфиров.",
        "Канал «yt_ru» @yt_ru: запланированных эфиров — 0.",
    ]
    assert [(failure.channel, failure.error) for failure in scan.failures] == [(YT_UA, QUOTA)]


def test_marked_broadcasts_are_found_on_every_channel(platform: FakePlatform) -> None:
    """--status: эфиры с меткой программы по времени старта; ручные эфиры сюда не входят."""
    late, early = _slot(48, "ru"), _slot(24, "uk")
    _seed_like(platform, "yt_ru", late)
    _seed_like(platform, "yt_ua", early)
    platform.seed_broadcast("yt_ua", early.start, "Ручной", "", marker="Мой поток")
    scan: MarkedScan = Reconciler(platform, KYIV, RunProgress()).marked_broadcasts(CHANNELS)
    assert [(marked.channel, marked.key) for marked in scan.broadcasts] == [(YT_UA, early.key), (YT_RU, late.key)]
    assert scan.failures == ()


def test_channel_aligned_at_login_is_read_with_its_new_values(platform: FakePlatform, tmp_path: Path) -> None:
    """§14 решение 25: канал выровнен при входе — площадка читается по новому нику в том же запуске."""
    slot: StreamSlot = slot_of(TOMORROW, "uk")
    seeded: UpcomingBroadcast = _seed_like(platform, "@yt_new", slot)
    item: PlannedBroadcast = planned_of(slot, channel_of("@yt_old", "old"))
    item.admit(channel_object(item.channel), training_form(tmp_path))
    channel = item.admission.channel
    assert channel is not None
    channel.realign(channel_of("@yt_new", "Новое название"), tmp_path / "new.json")
    _reconcile(platform, item, channels=(channel.config,))
    assert platform.list_calls == ["yt_new"] and item.match.found == seeded


# --- too_late и не допущенные


def test_too_late_object_only_reads_its_key(platform: FakePlatform) -> None:
    """too_late: опознание и ключ с площадки; решение TOO_LATE, тексты не сравниваются."""
    soon, later = _slot(0.5), _slot(24)
    seeded: UpcomingBroadcast = _seed_like(platform, "yt_ua", soon, title="Другое", stream_key="soon-soon-soon-soon")
    _seed_like(platform, "yt_ua", later)
    [soon_item] = _objects(soon)
    [later_item] = _objects(later)
    _reconcile(platform, too_late(soon_item), later_item)
    assert soon_item.decision is Decision.TOO_LATE
    assert (soon_item.match.found, soon_item.match.stream_key) == (seeded, "soon-soon-soon-soon")
    assert (soon_item.match.actual, soon_item.match.fixes.changed) == (None, ())
    assert soon_item.outcome.should_send_key is False
    assert later_item.decision is Decision.MATCH
    assert platform.list_calls == ["yt_ua", "yt_ru"]                                # по-прежнему раз на канал
    assert len(platform.stream_calls) == len(set(platform.stream_calls))            # тот же кеш потоков


def test_too_late_without_broadcast_has_no_key_and_no_create(platform: FakePlatform) -> None:
    [item] = _objects(_slot(0.5))
    _reconcile(platform, too_late(item))
    assert item.decision is Decision.TOO_LATE and (item.match.found, item.match.key) == (None, None)


def test_too_late_is_not_an_error_when_the_channel_fails(platform: FakePlatform) -> None:
    platform.fail_list["yt_ua"] = QUOTA
    [item] = _objects(_slot(0.5))
    _reconcile(platform, too_late(item))
    assert (item.decision, item.outcome.error, item.match.key) == (Decision.TOO_LATE, None, None)


def test_channel_not_ready_is_never_asked(platform: FakePlatform, tmp_path: Path) -> None:
    """Канал не READY: ни list_upcoming, ни get_stream; его объекты — NOT_ADMITTED, другой канал сверен."""
    ua_slot, ru_slot = slot_of(TOMORROW, "uk"), slot_of(TOMORROW, "ru")
    _seed_like(platform, "yt_ua", ua_slot)
    ua, ru = _objects(ua_slot, ru_slot)
    ua.admit(channel_object(ua.channel, ChannelStatus.REFUSED), training_form(tmp_path))
    ru.admit(channel_object(ru.channel), training_form(tmp_path))
    with LogCapture.on(LogArea.PIPELINE) as capture:
        _reconcile(platform, ua, ru)
    assert platform.list_calls == ["yt_ru"]
    assert all(key != "yt_ua" for key, _ in platform.stream_calls)
    assert (ua.decision, ua.outcome.error, ua.match.key) == (Decision.NOT_ADMITTED, None, None)
    assert ru.decision is Decision.CREATE
    assert 'channel_skipped_not_ready channel="yt_ua" handle=@yt_ua status=refused planned=1' in capture.messages()


def test_object_not_admitted_by_form_only_reads_its_key(platform: FakePlatform) -> None:
    """Канал READY, форма объект не принимает: эфир опознан, ключ и ссылка взяты, решение NOT_ADMITTED."""
    slot: StreamSlot = slot_of(TOMORROW, "uk")
    _seed_like(platform, "yt_ua", slot, title="Старое название")
    [item] = _objects(slot)
    item.admit(channel_object(item.channel), FormFailure(FormProblem.STRUCTURE_UNREADABLE, SHORT_URL, "", "no script"))
    _reconcile(platform, item)
    key = item.match.key
    assert item.decision is Decision.NOT_ADMITTED and key is not None and key.broadcast_url
    assert item.match.fixes.changed == () and item.outcome.warnings == []
    assert platform.created == [] and platform.updated == []


def test_not_admitted_object_does_not_become_ambiguous(platform: FakePlatform) -> None:
    slot: StreamSlot = slot_of(TOMORROW, "uk")
    for title in ("Ручной 1", "Ручной 2"):
        platform.seed_broadcast("yt_ua", slot.start, title, "", marker="ручной ключ")
    [item] = _objects(slot)
    item.admit(channel_object(item.channel), FormFailure(FormProblem.STRUCTURE_UNREADABLE, SHORT_URL, "", "no script"))
    _reconcile(platform, item)
    assert item.decision is Decision.NOT_ADMITTED and item.match.ambiguous_urls == () and item.match.key is None


# --- обложка: «обложки нет» = картинка эфира совпадает с заглушкой канала


def test_picture_equal_to_stream_token_is_a_missing_thumbnail(platform: FakePlatform) -> None:
    slot: StreamSlot = _slot(24, previews=True)
    token: str = PlaceholderMark(PLACEHOLDER).token
    _seed_like(platform, "yt_ua", slot, picture=PLACEHOLDER, stream_description="Ключ Livecraft; " + token)
    [item] = _objects(slot)
    _reconcile(platform, item)
    assert item.decision is Decision.UPDATE and item.match.fixes.changed == (ChangedField.THUMBNAIL,)


def test_same_picture_on_two_broadcasts_of_a_channel_is_a_placeholder(platform: FakePlatform) -> None:
    """Эфиры, созданные без метки заглушки в описании потока: заглушка у всех одна."""
    slots: list[StreamSlot] = [_slot(24 + hour, previews=True) for hour in range(2)]
    for slot in slots:
        _seed_like(platform, "yt_ua", slot, picture=PLACEHOLDER)
    items: list[PlannedBroadcast] = _objects(*slots)
    with LogCapture.on(LogArea.PIPELINE) as capture:
        _reconcile(platform, *items)
    assert [(item.decision, item.match.fixes.changed) for item in items] == [
        (Decision.UPDATE, (ChangedField.THUMBNAIL,)),
        (Decision.UPDATE, (ChangedField.THUMBNAIL,)),
    ]
    assert f'channel_placeholders channel="yt_ua" handle=@yt_ua from_streams=- from_duplicates={PLACEHOLDER}' in (
        capture.messages()
    )


def test_unique_picture_without_tokens_is_an_own_thumbnail(platform: FakePlatform) -> None:
    slots: list[StreamSlot] = [_slot(24 + hour, previews=True) for hour in range(2)]
    _seed_like(platform, "yt_ua", slots[0], picture=OWN_PICTURE)
    _seed_like(platform, "yt_ua", slots[1], picture="bbbbbbbbbbbb")
    items: list[PlannedBroadcast] = _objects(*slots)
    _reconcile(platform, *items)
    assert [item.decision for item in items] == [Decision.MATCH, Decision.MATCH]


def test_picture_that_did_not_download_is_not_compared(platform: FakePlatform) -> None:
    slot: StreamSlot = _slot(24, previews=True)
    _seed_like(platform, "yt_ua", slot, picture=None)
    [item] = _objects(slot)
    with LogCapture.on(LogArea.PIPELINE) as capture:
        _reconcile(platform, item)
    assert item.decision is Decision.MATCH
    [line] = [line for line in capture.messages() if line.startswith("spec_fields_not_compared")]
    assert line.endswith("thumbnail")


@pytest.mark.parametrize("case", ["set_thumbnail_off", "slot_without_previews"])
def test_thumbnail_is_not_compared_when_the_program_does_not_set_it(platform: FakePlatform, case: str) -> None:
    slot: StreamSlot = _slot(24, previews=case == "set_thumbnail_off")
    _seed_like(platform, "yt_ua", slot, picture=PLACEHOLDER, stream_description=PlaceholderMark(PLACEHOLDER).token)
    item: PlannedBroadcast = planned_of(slot, YT_UA, settings_with(set_thumbnail=case != "set_thumbnail_off"))
    assert item.expected.has_own_thumbnail is None
    _reconcile(platform, item)
    assert item.decision is Decision.MATCH


def test_same_picture_on_different_channels_is_not_a_placeholder(platform: FakePlatform) -> None:
    channels: tuple[ChannelConfig, ...] = (YT_UA, channel_of("@yt_ua2", "yt_ua2"))
    slot: StreamSlot = _slot(24, previews=True)
    _seed_like(platform, "yt_ua", slot, picture=OWN_PICTURE)
    _seed_like(platform, "yt_ua2", slot, picture=OWN_PICTURE)
    items: list[PlannedBroadcast] = _objects(slot, channels=channels)
    _reconcile(platform, *items, channels=channels)
    assert [(item.channel.account_name, item.decision) for item in items] == [
        ("yt_ua", Decision.MATCH), ("yt_ua2", Decision.MATCH)
    ]


def test_thumbnail_from_memory_beats_the_placeholder_picture(platform: FakePlatform) -> None:
    """Обложку этому же эфиру ставила программа (память) — картинка ещё не обновилась, расхождения нет."""
    slot: StreamSlot = _slot(24, previews=True)
    token: str = PlaceholderMark(PLACEHOLDER).token
    seeded: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, picture=PLACEHOLDER, stream_description=token)
    [item] = _objects(slot)
    item.memory.record = with_changes(slot_record(), results=RecordResults(thumbnail_broadcast_id=seeded.broadcast_id))
    with LogCapture.on(LogArea.PIPELINE) as capture:
        _reconcile(platform, item)
    assert item.decision is Decision.MATCH and item.match.actual is not None and item.match.actual.has_own_thumbnail
    assert any(line.startswith("thumbnail_from_memory") for line in capture.messages())
    [other] = _objects(slot)
    other.memory.record = with_changes(slot_record(), results=RecordResults(thumbnail_broadcast_id="removed"))
    _reconcile(platform, other)
    assert other.match.fixes.changed == (ChangedField.THUMBNAIL,)       # память про другой эфир — решает картинка


# --- сироты и перенесённые


def test_marker_of_slot_outside_the_known_slots_is_an_orphan(platform: FakePlatform) -> None:
    moved: StreamSlot = _slot(72)
    moved_broadcast: UpcomingBroadcast = _seed_like(platform, "yt_ua", moved)
    [item] = _objects(_slot(24))
    [orphan] = _reconcile(platform, item)
    assert (orphan.channel, orphan.broadcast, orphan.marker, orphan.kind) == (
        YT_UA, moved_broadcast, moved.slot_id, OrphanKind.ORPHAN
    )
    assert SlotKey.parse(orphan.marker, KYIV) == moved.key == orphan.key
    assert item.decision is Decision.CREATE


def test_manual_broadcast_at_another_time_is_ignored(platform: FakePlatform) -> None:
    platform.seed_broadcast("yt_ua", NOW + timedelta(days=2), "Ручной", "", marker="Мой поток")
    [item] = _objects(_slot(24))
    assert _reconcile(platform, item) == ()
    assert item.decision is Decision.CREATE


def test_marker_of_known_slot_on_another_minute_is_moved(platform: FakePlatform) -> None:
    """Владелец перенёс эфир программы в Студии — слот известен, минута другая: «перенесён», не трогаем."""
    slot: StreamSlot = _slot(24)
    moved: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, start_utc=slot.start + timedelta(days=2))
    [item] = _objects(slot)
    with LogCapture.on(LogArea.PIPELINE) as capture:
        [orphan] = _reconcile(platform, item)
    assert (orphan.kind, orphan.broadcast, orphan.marker) == (OrphanKind.MOVED, moved, slot.slot_id)
    assert item.decision is Decision.CREATE and platform.updated == []
    assert (
        f'broadcast_moved slot_id={slot.slot_id} channel="yt_ua" handle=@yt_ua broadcast_id={moved.broadcast_id} '
        "start=2027-03-19T10:00:00+00:00 slot_start=2027-03-17T10:00:00+00:00"
    ) in capture.messages()


def test_past_slot_on_its_minute_is_not_an_orphan_but_moved_one_is(platform: FakePlatform) -> None:
    """Эфир прошедшего слота на своей минуте — не сирота; на чужой — «перенесён»."""
    future, past, moved_past = _slot(24), _slot(-1), _slot(-2)
    _seed_like(platform, "yt_ua", past)
    moved: UpcomingBroadcast = _seed_like(platform, "yt_ua", moved_past, start_utc=NOW + timedelta(days=5))
    [item] = _objects(future)
    known: dict[str, datetime] = {slot.slot_id: slot.start for slot in (future, past, moved_past)}
    reconciler: Reconciler = Reconciler(platform, KYIV, RunProgress())
    orphans: tuple[OrphanBroadcast, ...] = reconciler.reconcile([item], known, CHANNELS)
    assert [(orphan.kind, orphan.broadcast) for orphan in orphans] == [(OrphanKind.MOVED, moved)]


def test_found_broadcast_is_not_repeated_as_moved(platform: FakePlatform) -> None:
    """Эфир, опознанный объектом, в «Перенесён или отменён?» не повторяется; дубль метки на другой минуте — да."""
    slot: StreamSlot = _slot(24)
    found: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot)
    duplicate: UpcomingBroadcast = _seed_like(platform, "yt_ua", slot, start_utc=slot.start + timedelta(hours=3))
    [item] = _objects(slot)
    orphans: tuple[OrphanBroadcast, ...] = _reconcile(platform, item)
    assert item.match.found == found and [orphan.broadcast for orphan in orphans] == [duplicate]
