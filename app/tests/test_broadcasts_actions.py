"""Действия по эфирам (planers _Executor e299a6d): правка только нужными вызовами, настройки видео, факты, обложка."""
from __future__ import annotations

import re

import pytest

from app.broadcasts.stage import BroadcastPartResult
from app.config.broadcasts import BroadcastSettings
from app.observability.log_event import LogArea
from app.output.result import BroadcastResult, KeyState, OutcomeKind
from app.paths import LivecraftPaths
from app.platforms.broadcast import BroadcastFacts
from app.platforms.error import PlatformError
from app.platforms.placeholder import PlaceholderMark
from app.platforms.spec import ChangedField
from app.run.exit_code import RunOutcome
from app.slots.slot import StreamSlot
from app.tests.fixtures.broadcasts import (
    BENCH_SETTINGS,
    BroadcastBench,
    form_page,
    report_of,
    report_text,
    sent_values,
)
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.pipeline import NOT_IN_FORM, NOW, PREVIEW, TEXTS, TOMORROW, slot_of, with_changes
from app.ui import messages_ru as msg

UK_SLOT: str = "17-03-2027_1900_uk"
PLATFORM_KEY: str = "abcd-abcd-abcd-abcd-abcd"
OWN_PICTURE: str = "aaaaaaaaaaaa"
LIMIT_ERROR: PlatformError = PlatformError("uploadRateLimitExceeded", "HTTP 429: limit")
UK: StreamSlot = slot_of(TOMORROW, "uk", TEXTS, (PREVIEW,))
UK_BARE: StreamSlot = slot_of(TOMORROW, "uk")


@pytest.fixture
def bench(livecraft_paths: LivecraftPaths) -> BroadcastBench:
    return BroadcastBench.with_tokens(livecraft_paths)


@pytest.fixture
def remembered(bench: BroadcastBench) -> BroadcastBench:
    """Память была задолго до эфиров на площадке, подтверждений в ней нет: стоящие эфиры — не «переданные»."""
    bench.memory_since(NOW.replace(year=2025))
    return bench


def _only(result: BroadcastPartResult) -> BroadcastResult:
    [item] = report_of(result).results
    return item


def _changed(item: BroadcastResult) -> tuple[ChangedField, ...]:
    return tuple(change.field for change in item.changes)


def _seed(bench: BroadcastBench, slot: StreamSlot = UK, **overrides: object) -> str:
    """Эфир программы на yt_ua по слоту: тексты и метка — как у слота; по умолчанию картинка — заглушка канала."""
    placeholder: str = bench.platform.placeholder_of("yt_ua")
    values: dict[str, object] = {
        "marker": slot.slot_id,
        "stream_key": PLATFORM_KEY,
        "picture": placeholder,
        "stream_description": PlaceholderMark(placeholder).token,
    }
    values.update(overrides)
    title: object = values.pop("title", slot.title)
    seeded = bench.platform.seed_broadcast("yt_ua", slot.start, str(title), slot.description, **values)  # type: ignore[arg-type]
    return seeded.broadcast_id


def test_thumbnail_failure_is_a_warning_not_an_error(bench: BroadcastBench) -> None:
    bench.platform.fail_thumbnail["fakebc00001"] = PlatformError("forbidden", "канал не подтверждён")
    result: BroadcastPartResult = bench.run(UK)
    assert result.outcome is RunOutcome.DONE
    assert msg.THUMBNAIL_REASON_TEXT["forbidden"] in report_text(result)


def test_thumbnail_upload_limit_reaches_console_and_report(bench: BroadcastBench) -> None:
    bench.platform.fail_thumbnail["fakebc00001"] = LIMIT_ERROR
    result: BroadcastPartResult = bench.run(UK)
    assert result.outcome is RunOutcome.DONE
    for text in ("\n".join(result.console_lines), report_text(result)):
        assert msg.THUMBNAIL_REASON_TEXT["uploadRateLimitExceeded"] in text


def test_video_settings_failure_is_a_warning_not_an_error(bench: BroadcastBench) -> None:
    bench.platform.fail_settings["fakebc00001"] = PlatformError("forbidden", "нельзя")
    result: BroadcastPartResult = bench.run(UK)
    assert result.outcome is RunOutcome.DONE
    assert msg.WARNING_STEP_TEXT["settings"] in report_text(result)


def test_language_is_set_from_the_slot(bench: BroadcastBench) -> None:
    bench.run(slot_of(TOMORROW, "ru"))
    assert bench.platform.languages == {"fakebc00001": "ru"}


def test_attach_failure_stays_an_error(bench: BroadcastBench) -> None:
    found: str = _seed(bench, UK_BARE, marker=None)
    bench.platform.fail_attach[found] = PlatformError("forbidden", "нельзя")
    result: BroadcastPartResult = bench.run(UK_BARE)
    assert result.outcome is RunOutcome.FAILED and bench.posts == []


def test_made_for_kids_is_fixed_and_warned(bench: BroadcastBench) -> None:
    """Настройка канала может перебить флаг: программа снимает его и говорит об этом владельцу."""
    found: str = _seed(bench, UK_BARE, picture=None)
    bench.platform.made_for_kids[found] = True
    result: BroadcastPartResult = bench.run(UK_BARE)
    assert result.outcome is RunOutcome.DONE
    assert bench.platform.made_for_kids[found] is False
    assert msg.WARNING_STEP_TEXT["audience"] in report_text(result)


def test_age_restricted_broadcast_is_reported_but_not_an_error(bench: BroadcastBench) -> None:
    found: str = _seed(bench, UK_BARE, picture=None)
    bench.platform.age_restricted.add(found)
    result: BroadcastPartResult = bench.run(UK_BARE)
    assert result.outcome is RunOutcome.DONE
    assert msg.WARNING_STEP_TEXT["age_restricted"] in report_text(result)


def test_facts_are_read_once_per_object(bench: BroadcastBench) -> None:
    bench.run(UK, slot_of(TOMORROW, "ru"))
    assert len(bench.platform.facts_calls) == 2 and len(set(bench.platform.facts_calls)) == 2


def test_facts_and_settings_are_not_touched_for_too_late_and_ambiguous(bench: BroadcastBench) -> None:
    ambiguous: StreamSlot = slot_of(NOT_IN_FORM.replace(hour=19), "ru")
    bench.platform.seed_broadcast("yt_ru", ambiguous.start, "Ручной 1", "", marker=None)
    bench.platform.seed_broadcast("yt_ru", ambiguous.start, "Ручной 2", "", marker="Мой поток")
    bench.run(slot_of(NOW.replace(minute=30), "uk"), ambiguous)
    assert bench.platform.facts_calls == [] and bench.platform.settings_calls == []


def test_created_broadcast_matches_its_facts(bench: BroadcastBench) -> None:
    """Время, тексты и метка совпали — расхождений нет, строки лога found у созданного эфира нет."""
    with LogCapture.on(LogArea.BROADCASTS) as log:
        result: BroadcastPartResult = bench.run(UK)
    assert report_of(result).mismatches == ()
    messages: list[str] = log.messages()
    assert not any(line.startswith("broadcast_found") for line in messages)
    assert any(line.startswith("broadcast_expected") for line in messages)


def test_expected_found_and_facts_log_lines_share_keys(bench: BroadcastBench) -> None:
    bench.run(UK)
    with LogCapture.on(LogArea.BROADCASTS) as log:
        bench.run(UK)
    lines: dict[str, str] = {
        line.split(" ", 1)[0]: line
        for line in log.messages()
        if line.startswith(("broadcast_expected", "broadcast_found", "broadcast_facts"))
    }
    assert set(lines) == {"broadcast_expected", "broadcast_found", "broadcast_facts"}
    keys: dict[str, list[str]] = {name: re.findall(r"(?:^| )([a-z_]+)=", line) for name, line in lines.items()}
    assert keys["broadcast_expected"] == keys["broadcast_found"]
    assert keys["broadcast_facts"][:3] == keys["broadcast_expected"][:3] == ["slot_id", "channel", "handle"]
    assert "description_head" in keys["broadcast_expected"] and "made_for_kids" in keys["broadcast_facts"]


def test_description_mismatch_is_reported_shortened(bench: BroadcastBench) -> None:
    long_text: str = "Очень длинное описание эфира. " * 40
    slot: StreamSlot = slot_of(TOMORROW, "uk", with_changes(TEXTS, description=long_text))
    found: str = _seed(bench, slot, picture=None)
    facts: BroadcastFacts = bench.platform.read_facts(bench.channels[0], found)
    bench.platform.facts_override[found] = with_changes(facts, description="Совсем другое описание")
    result: BroadcastPartResult = bench.run(slot)
    text: str = report_text(result)
    assert "описание — хотели:" in text and long_text.strip() not in text


def test_category_from_settings_is_used_everywhere(bench: BroadcastBench) -> None:
    bench.settings = with_changes(BENCH_SETTINGS, category_id="25")
    bench.run(UK)
    [created] = bench.platform.created
    assert bench.platform.categories[created.broadcast_id] == "25"


def test_set_thumbnail_off_skips_the_preview(bench: BroadcastBench) -> None:
    bench.settings = with_changes(BENCH_SETTINGS, set_thumbnail=False)
    bench.run(UK)
    assert len(bench.platform.created) == 1 and bench.platform.thumbnail_attempts == []


def test_video_resource_is_touched_once_per_broadcast_and_not_written_again(bench: BroadcastBench) -> None:
    bench.run(UK)
    [created] = bench.platform.created
    assert bench.platform.settings_calls == [created.broadcast_id] == bench.platform.settings_writes
    bench.run(UK)
    assert len(bench.platform.settings_writes) == 1 and len(bench.platform.settings_calls) == 2


def test_category_mismatch_after_actions_is_reported(bench: BroadcastBench) -> None:
    found: str = _seed(bench, UK_BARE, picture=None)
    facts: BroadcastFacts = bench.platform.read_facts(bench.channels[0], found)
    bench.platform.facts_override[found] = with_changes(facts, category_id="24")
    result: BroadcastPartResult = bench.run(UK_BARE)
    assert result.outcome is RunOutcome.DONE
    assert "категория — хотели: 22; на платформе: 24" in report_text(result)


def test_privacy_only_difference_is_fixed_and_the_standing_key_stays(remembered: BroadcastBench) -> None:
    """Владелец поставил «доступ ограничен» — программа возвращает видимость одним проходом по видео; эфир стоял —
    ключ при «новые» не уходит (§14 решение 49)."""
    found: str = _seed(remembered, UK_BARE, picture=None, privacy="private")
    result: BroadcastPartResult = remembered.run(UK_BARE)
    item: BroadcastResult = _only(result)
    assert (item.kind, _changed(item), item.key_state) == (OutcomeKind.FIXED, (ChangedField.PRIVACY,), None)
    assert remembered.posts == []
    assert remembered.platform.updated == [] and remembered.platform.thumbnail_attempts == []
    assert remembered.platform.settings_calls == [found]
    assert result.outcome is RunOutcome.DONE


def test_category_fixed_on_the_video_counts_as_a_fix(remembered: BroadcastBench) -> None:
    """Категорию список эфиров не возвращает: её расхождение видно у ресурса видео — и это тоже исправление."""
    _seed(remembered, UK_BARE, picture=None, category_id="24")
    item: BroadcastResult = _only(remembered.run(UK_BARE))
    assert (item.kind, _changed(item), item.key_state) == (OutcomeKind.FIXED, (ChangedField.CATEGORY,), None)
    assert remembered.posts == []


def test_privacy_fixed_at_the_video_resource_needs_no_other_calls(remembered: BroadcastBench) -> None:
    """Список эфиров видимость не вернул — MATCH; ресурс видео её исправил — UPDATE без других вызовов."""
    found: str = _seed(remembered, UK, picture=OWN_PICTURE, privacy=None)
    item: BroadcastResult = _only(remembered.run(UK))
    assert (item.kind, _changed(item), item.key_state) == (OutcomeKind.FIXED, (ChangedField.PRIVACY,), None)
    assert remembered.platform.updated == [] and remembered.platform.thumbnail_attempts == []
    assert remembered.platform.settings_calls == [found]


def test_auto_start_difference_keeps_the_decision_but_reaches_the_owner(bench: BroadcastBench) -> None:
    """Автостарт через API не исправить: решение MATCH, ключ не шлём, но строка во ВНИМАНИЕ и расхождение."""
    _seed(bench, UK_BARE, picture=None, auto_start=False)
    result: BroadcastPartResult = bench.run(UK_BARE)
    assert _only(result).kind is OutcomeKind.MATCHED and bench.posts == []
    assert any(msg.CHANGED_FIELD_TEXT["auto_start"] in line for line in report_of(result).warnings)
    assert result.outcome is RunOutcome.DONE


def test_manual_broadcast_is_adopted_and_marked_and_its_key_goes_only_at_all(bench: BroadcastBench) -> None:
    """Ручной эфир без метки программы: метку ставим; эфир стоял — при «новые» ключ не уходит, при «все» — уходит
    (§14 решение 49)."""
    _seed(bench, UK_BARE, picture=None, marker="Мой поток")
    first: BroadcastPartResult = bench.run(UK_BARE)
    [marked] = bench.platform.markers_set
    assert marked.marker == UK_SLOT and _changed(_only(first)) == (ChangedField.MARKER,)
    assert bench.platform.created == [] and bench.platform.updated == [] and bench.posts == []
    bench.settings = with_changes(bench.settings, broadcasts=BroadcastSettings(resend_keys=True))
    second: BroadcastPartResult = bench.run(UK_BARE)
    assert _only(second).kind is OutcomeKind.MATCHED
    assert [PLATFORM_KEY in sent_values(post) for post in bench.posts] == [True]


def test_two_unmarked_broadcasts_are_ambiguous_with_links(bench: BroadcastBench) -> None:
    """Программа не выбирает и не удаляет, но называет ссылки на всех кандидатов."""
    first: str = bench.platform.seed_broadcast("yt_ua", TOMORROW, "Ручной 1", "", marker=None).broadcast_id
    second: str = bench.platform.seed_broadcast("yt_ua", TOMORROW, "Ручной 2", "", marker="Мой поток").broadcast_id
    result: BroadcastPartResult = bench.run(UK_BARE)
    assert _only(result).kind is OutcomeKind.AMBIGUOUS
    urls: str = f"https://www.youtube.com/watch?v={first}, https://www.youtube.com/watch?v={second}"
    assert any(line.endswith(urls) for line in report_of(result).warnings)
    assert bench.platform.created == [] and bench.platform.markers_set == [] and bench.posts == []
    assert result.outcome is RunOutcome.FAILED


def test_language_just_written_is_taken_from_the_write_response(bench: BroadcastBench) -> None:
    """Язык uk записан, перечитывание сразу после записи отдало ru — расхождение было бы ложным."""
    bench.run(UK)
    [created] = bench.platform.created
    facts: BroadcastFacts = bench.platform.read_facts(bench.channels[0], created.broadcast_id)
    bench.platform.facts_override[created.broadcast_id] = with_changes(
        facts, default_language="ru", default_audio_language="ru"
    )
    bench.platform.languages[created.broadcast_id] = "en"          # язык опять разошёлся — будет запись
    result: BroadcastPartResult = bench.run(UK)
    assert not any(msg.MISMATCH_FIELD_LANGUAGE in line for line in report_of(result).mismatches)


def test_missing_thumbnail_alone_sets_only_the_thumbnail(remembered: BroadcastBench) -> None:
    found: str = _seed(remembered)
    first: BroadcastPartResult = remembered.run(UK)
    item: BroadcastResult = _only(first)
    assert (item.kind, _changed(item), item.key_state) == (OutcomeKind.FIXED, (ChangedField.THUMBNAIL,), None)
    assert remembered.platform.updated == []                  # только обложка — thumbnails.set, без liveBroadcasts.update
    [thumbnail] = remembered.platform.thumbnails
    assert (thumbnail.broadcast_id, thumbnail.preview) == (found, PREVIEW.data)
    assert remembered.posts == []                             # эфир стоял: при «новые» ключ не уходит
    second: BroadcastPartResult = remembered.run(UK)
    assert _only(second).kind is OutcomeKind.MATCHED and remembered.posts == []


def test_title_fix_calls_update_and_leaves_the_own_thumbnail(bench: BroadcastBench) -> None:
    found: str = _seed(bench, title="Старое название", picture=OWN_PICTURE)
    item: BroadcastResult = _only(bench.run(UK))
    assert (item.kind, _changed(item)) == (OutcomeKind.FIXED, (ChangedField.TITLE,))
    assert [call.broadcast_id for call in bench.platform.updated] == [found]
    assert bench.platform.thumbnail_attempts == [] and bench.platform.pictures[found] == OWN_PICTURE


def test_matching_broadcast_is_not_touched(bench: BroadcastBench) -> None:
    _seed(bench, picture=OWN_PICTURE)
    assert _only(bench.run(UK)).kind is OutcomeKind.MATCHED
    assert bench.platform.updated == [] and bench.platform.thumbnail_attempts == [] and bench.posts == []


def test_upload_limit_on_a_thumbnail_fix_keeps_the_key(remembered: BroadcastBench) -> None:
    """Лимит загрузок на обложке — предупреждение: ключ при «все» уходит всё равно."""
    found: str = _seed(remembered)
    remembered.platform.fail_thumbnail[found] = LIMIT_ERROR
    remembered.settings = with_changes(remembered.settings, broadcasts=BroadcastSettings(resend_keys=True))
    result: BroadcastPartResult = remembered.run(UK)
    assert result.outcome is RunOutcome.DONE and remembered.platform.updated == []
    assert remembered.platform.thumbnail_attempts == [found]
    assert [PLATFORM_KEY in sent_values(post) for post in remembered.posts] == [True]


def test_thumbnail_refused_on_a_fix_is_matched_not_fixed(remembered: BroadcastBench) -> None:
    """Обложка не поставилась: эфир «уже стоял» с хвостом «обложка не поставлена», ИСПРАВИЛИ пуст."""
    found: str = _seed(remembered)
    remembered.platform.fail_thumbnail[found] = LIMIT_ERROR
    result: BroadcastPartResult = remembered.run(UK)
    item: BroadcastResult = _only(result)
    assert (item.kind, item.changes, item.unfixed) == (OutcomeKind.MATCHED, (), (ChangedField.THUMBNAIL,))
    console: str = "\n".join(result.console_lines)
    assert msg.CONSOLE_BLOCK_FIXED not in console and msg.UNFIXED_FIELD_TEXT["thumbnail"] in console


def test_refused_thumbnails_skip_empty_resends(remembered: BroadcastBench) -> None:
    """После отказа обложек канала: только обложка — ни правки, ни загрузки; ещё и название — правка без загрузки."""
    remembered.form_page = form_page("17.03.2027", "18.03.2027", "19.03.2027")
    first, second, third = (slot_of(TOMORROW.replace(day=day), "uk", TEXTS, (PREVIEW,)) for day in (17, 18, 19))
    refused: str = _seed(remembered, first, stream_key="aaaa-aaaa-aaaa-aaaa-aaaa")
    only_cover: str = _seed(remembered, second, stream_key="bbbb-bbbb-bbbb-bbbb-bbbb")
    with_title: str = _seed(remembered, third, stream_key="cccc-cccc-cccc-cccc-cccc", title="Старое название")
    remembered.platform.fail_thumbnail[refused] = LIMIT_ERROR
    result: BroadcastPartResult = remembered.run(first, second, third)
    assert [call.broadcast_id for call in remembered.platform.updated] == [with_title]
    assert remembered.platform.thumbnail_attempts == [refused]
    assert only_cover not in remembered.platform.thumbnail_attempts
    kinds: dict[str, tuple[OutcomeKind, tuple[ChangedField, ...], tuple[ChangedField, ...]]] = {
        item.key.human_date: (item.kind, _changed(item), item.unfixed) for item in report_of(result).results
    }
    assert kinds["18.03.2027"] == (OutcomeKind.MATCHED, (), (ChangedField.THUMBNAIL,))
    assert kinds["19.03.2027"] == (OutcomeKind.FIXED, (ChangedField.TITLE,), (ChangedField.THUMBNAIL,))


def test_error_after_the_key_was_taken_does_not_stop_the_send(bench: BroadcastBench) -> None:
    """Поток привязан, правка эфира упала — эфир с ошибкой, но уже взятый ключ ушёл в форму."""
    ru: StreamSlot = slot_of(TOMORROW, "ru")
    bare: str = bench.platform.seed_broadcast("yt_ru", TOMORROW, "Старое название", ru.description).broadcast_id
    bench.platform.fail_update[bare] = PlatformError("backendError", "HTTP 503")
    result: BroadcastPartResult = bench.run(ru)
    assert _only(result).kind is OutcomeKind.ERROR
    assert len(bench.posts) == 1 and len(bench.platform.attached) == 1
