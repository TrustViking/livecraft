"""Память программы в прогоне части «эфиры» (planers e299a6d, задачи 5m-C и 5m-E; §14 решение 49): одно правило
отправки ключа «новые | все» с одним повтором неподтверждённого ключа, записи по стадиям, чистка по keep_days, два
ключа на слот."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.broadcasts.stage import BroadcastPartResult
from app.config.channel import ChannelConfig
from app.core.dates import format_datetime_text
from app.observability.log_event import LogArea
from app.observability.logging_setup import mask_stream_key
from app.output.result import BroadcastResult, KeyState, OutcomeKind
from app.paths import FileName, LivecraftPaths
from app.platforms.placeholder import PlaceholderMark
from app.platforms.youtube import YOUTUBE_STREAM_KEY_PATTERN
from app.records.record_results import RecordResults
from app.records.record_store import RecordStore
from app.records.slot_record import SlotRecord, SlotStage
from app.slots.slot import StreamSlot
from app.slots.texts import SlotTexts
from app.tests.fixtures.broadcasts import FORM_REFUSED, BroadcastBench, form_page, report_of, report_text, sent_values
from app.tests.fixtures.form import SUCCESS_PAGE, FakeFormResponse
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.pipeline import NOT_IN_FORM, NOW, PREVIEW, TEXTS, TOMORROW, slot_of, texts_of
from app.tests.fixtures.platform import FakePlatform, channel_of, changed_channel
from app.ui import messages_ru as msg

UK_SLOT: str = "17-03-2027_1900_uk"
PLATFORM_KEY: str = "abcd-abcd-abcd-abcd-abcd"
FIRST_KEY: str = "fake-0001-0000-0000-0000"
SECOND_KEY: str = "fake-0002-0000-0000-0000"
UK: StreamSlot = slot_of(TOMORROW, "uk", TEXTS, (PREVIEW,))
UK_BARE: StreamSlot = slot_of(TOMORROW, "uk")
MOVED_MARK: str = "время эфира менял владелец"


@pytest.fixture
def bench(livecraft_paths: LivecraftPaths) -> BroadcastBench:
    return BroadcastBench.with_tokens(livecraft_paths)


def with_title(title: str) -> SlotTexts:
    return texts_of(title=title)


def _only(result: BroadcastPartResult) -> BroadcastResult:
    [item] = report_of(result).results
    return item


def old_record(slot_id: str, channel_id: str, start: str) -> SlotRecord:
    """Подтверждённая запись слота, начавшегося в `start` (UTC)."""
    utc: str = start + "+00:00"
    return SlotRecord(slot_id, channel_id, utc, SlotStage.KEY_CONFIRMED, "01-01-2027 12:00", RecordResults())


def _keys_sent(bench: BroadcastBench) -> list[str]:
    """Ключи потока всех отправок формы по порядку."""
    return [
        value for post in bench.posts for value in sent_values(post) if YOUTUBE_STREAM_KEY_PATTERN.fullmatch(value)
    ]


def test_confirmed_match_sends_nothing(bench: BroadcastBench) -> None:
    """Подтверждённый MATCH — ни одного POST; память помнит момент подтверждения."""
    bench.run(UK)
    second: BroadcastPartResult = bench.run(UK)
    assert len(bench.posts) == 1 and report_of(second).exit.reasons == ()
    assert msg.KEY_FORM_CONFIRMED.format(confirmed_at="16.03.2027 12:00") in bench.keys_text
    assert report_of(second).has_kept_keys


def test_a_standing_broadcast_sends_nothing_at_new_even_when_the_answers_change(bench: BroadcastBench) -> None:
    """Исправлен — POST нет; изменилось название канала в ответах — при «новые» тоже нет: эфир стоял (§14 решение 49)."""
    bench.run(UK)
    second: BroadcastPartResult = bench.run(slot_of(TOMORROW, "uk", with_title("Новое"), (PREVIEW,)))
    assert _only(second).kind is OutcomeKind.FIXED
    assert len(bench.platform.updated) == 1 and len(bench.posts) == 1
    ua, ru = bench.channels
    bench.channels = (changed_channel(ua, account_name="Новое имя канала"), ru)
    bench.platform.channel_info["yt_ua"] = FakePlatform.default_channel_info(bench.channels[0])
    third: BroadcastPartResult = bench.run(slot_of(TOMORROW, "uk", with_title("Ещё"), (PREVIEW,)))
    assert _only(third).kind is OutcomeKind.FIXED and _keys_sent(bench) == [FIRST_KEY]


def test_broadcast_removed_by_hand_is_recreated_and_its_new_key_sent(bench: BroadcastBench) -> None:
    bench.run(UK)
    bench.platform.remove_broadcast("yt_ua", bench.platform.created[0].broadcast_id)
    bench.run(UK)
    assert _keys_sent(bench) == [FIRST_KEY, SECOND_KEY]
    record: SlotRecord | None = bench.stored(UK_SLOT)
    assert record is not None and record.results.confirmed_stream_key == SECOND_KEY


def test_standing_broadcasts_send_nothing_and_a_new_one_sends_its_key(bench: BroadcastBench) -> None:
    """Эфир с меткой и ручной эфир уже стоят, третьего нет: при «новые» ключ уходит только у созданного; память ничего не
    выдумывает — подтверждения у стоявших нет."""
    marked, manual, new = (slot_of(TOMORROW.replace(day=day), "uk") for day in (17, 18, 19))
    bench.form_page = form_page("17.03.2027", "18.03.2027", "19.03.2027")
    bench.platform.seed_broadcast("yt_ua", marked.start, marked.title, marked.description, UK_SLOT, PLATFORM_KEY)
    bench.platform.seed_broadcast(
        "yt_ua", manual.start, manual.title, manual.description, "ручной ключ", "mmmm-mmmm-mmmm-mmmm-mmmm"
    )
    bench.run(marked, manual, new)
    assert _keys_sent(bench) == ["fake-0003-0000-0000-0000"]
    record: SlotRecord | None = bench.stored(UK_SLOT)
    assert record is not None and record.stage is SlotStage.PUBLISHED and record.results.confirmed_stream_key is None
    assert bench.keys_text.split(f"{PLATFORM_KEY}\n", 1)[1].split("\n\n", 1)[0].endswith(msg.KEY_FORM_UNKNOWN)
    bench.run(marked, manual, new)
    assert len(bench.posts) == 1                          # второй запуск подряд — ни одного POST


def test_a_key_the_form_did_not_confirm_goes_once_more_then_stops_with_a_line(bench: BroadcastBench) -> None:
    """Форма не подтвердила ключ нового эфира: следующий запуск шлёт его ещё раз; не подтвердила и тогда — третий
    запуск ключ сам не шлёт, а строка отчёта и консоли называет действие «все» (§14 решение 49)."""
    bench.post_replies = (FORM_REFUSED,)
    first: BroadcastPartResult = bench.run(UK)
    assert _keys_sent(bench) == [FIRST_KEY] and _only(first).key_state is KeyState.FAILED
    second: BroadcastPartResult = bench.run(UK)
    assert _keys_sent(bench) == [FIRST_KEY, FIRST_KEY] and _only(second).key_state is KeyState.FAILED
    record: SlotRecord | None = bench.stored(UK_SLOT)
    assert record is not None and record.results.unconfirmed is not None and record.results.unconfirmed.count == 2
    third: BroadcastPartResult = bench.run(UK)
    assert len(bench.posts) == 2 and _only(third).key_state is None
    [line] = [warning for warning in report_of(third).warnings if "«все»" in warning]
    assert line == msg.KEYS_GIVEN_UP.format(prefix=_only(third).label.text)
    assert any(line in text for text in third.console_lines) and line in report_text(third)
    assert bench.keys_text.split(f"{FIRST_KEY}\n", 1)[1].split("\n\n", 1)[0].rstrip().endswith(msg.KEY_FORM_GIVEN_UP)


def test_a_retry_the_form_confirms_clears_the_count(bench: BroadcastBench) -> None:
    """Повтор дошёл: память хранит подтверждение, счёта нет, дальше ключ не уходит."""
    bench.post_replies = (FORM_REFUSED,)
    bench.run(UK)
    bench.post_replies = (FakeFormResponse(SUCCESS_PAGE),)
    bench.run(UK)
    record: SlotRecord | None = bench.stored(UK_SLOT)
    assert record is not None and record.results.confirmed_stream_key == FIRST_KEY and record.results.unconfirmed is None
    bench.run(UK)
    assert _keys_sent(bench) == [FIRST_KEY, FIRST_KEY]


def test_slot_admitted_later_creates_its_broadcast_and_sends_the_key(livecraft_paths: LivecraftPaths) -> None:
    """18.03 не допущен (нет даты) — эфир не ставится; дату добавили в форму — эфир создан, ключ ушёл."""
    bench: BroadcastBench = BroadcastBench.with_tokens(livecraft_paths, channel_of("@nick", "nick", "en"))
    standing: StreamSlot = slot_of(NOT_IN_FORM, "en")
    first: BroadcastPartResult = bench.run(standing)
    assert bench.posts == [] and _only(first).kind is OutcomeKind.NOT_ADMITTED and bench.platform.created == []
    bench.form_page = form_page("17.03.2027", "18.03.2027")
    second: BroadcastPartResult = bench.run(standing)
    assert _keys_sent(bench) == [FIRST_KEY]
    assert (_only(second).kind, _only(second).key_state) == (OutcomeKind.CREATED, KeyState.SENT)


def test_dry_run_reads_memory_and_writes_nothing(bench: BroadcastBench) -> None:
    """dry-run: базы нет — не создаётся; есть — не меняется; «ключ будет передан» — по записям."""
    later: StreamSlot = slot_of(NOT_IN_FORM.replace(hour=19), "uk")
    bench.form_page = form_page("17.03.2027", "18.03.2027")
    bench.run(UK_BARE, later, dry_run=True)
    assert not bench.paths.file(FileName.RECORDS).exists()
    bench.post_replies = (bench.post_replies[0], FORM_REFUSED)        # 18.03 форма не подтвердила
    bench.run(UK_BARE, later)
    before: bytes = bench.paths.file(FileName.RECORDS).read_bytes()
    posts: int = len(bench.posts)
    result: BroadcastPartResult = bench.run(UK_BARE, later, dry_run=True)
    assert bench.paths.file(FileName.RECORDS).read_bytes() == before and len(bench.posts) == posts
    states: dict[str, KeyState | None] = {item.key.human_date: item.key_state for item in report_of(result).results}
    assert states == {"17.03.2027": None, "18.03.2027": KeyState.PLANNED}


def test_old_records_are_cleaned_by_keep_days(bench: BroadcastBench) -> None:
    channel_id: str = FakePlatform.default_channel_info(bench.channels[0]).youtube_channel_id
    store: RecordStore = RecordStore.open(bench.paths.file(FileName.RECORDS), False, bench.clock)
    for slot_id, start in (("01-01-2027_1900_uk", "2027-01-01T17:00:00"), ("10-03-2027_1900_uk", "2027-03-10T17:00:00")):
        store.save(old_record(slot_id, channel_id, start))
    store.close()
    with LogCapture.on(LogArea.BROADCASTS) as log:
        bench.run(UK)
    assert bench.stored("01-01-2027_1900_uk") is None
    assert bench.stored("10-03-2027_1900_uk") is not None and bench.stored(UK_SLOT) is not None
    assert "records_cleaned removed=1" in log.messages()


def test_dry_run_does_not_clean_the_memory(bench: BroadcastBench) -> None:
    channel_id: str = FakePlatform.default_channel_info(bench.channels[0]).youtube_channel_id
    store: RecordStore = RecordStore.open(bench.paths.file(FileName.RECORDS), False, bench.clock)
    store.save(old_record("01-01-2027_1900_uk", channel_id, "2027-01-01T17:00:00"))
    store.close()
    bench.run(UK, dry_run=True)
    assert bench.stored("01-01-2027_1900_uk") is not None


def _step(message: str) -> str:
    """Имя события; у записи памяти — ещё и стадия."""
    name: str = message.split(" ", 1)[0]
    if not message.startswith("record_saved"):
        return name
    return name + " " + message.split("stage=", 1)[1].split(" ", 1)[0]


def test_record_log_lines_follow_the_object(bench: BroadcastBench) -> None:
    with LogCapture.on(LogArea.RECORDS) as records, LogCapture.on(LogArea.BROADCASTS) as broadcasts:
        bench.run(UK)
    merged: list[tuple[float, str]] = sorted(
        [(record.created, record.getMessage()) for record in (*records.records, *broadcasts.records)],
        key=lambda pair: pair[0],
    )
    names: list[str] = [
        _step(message)
        for _moment, message in merged
        if message.startswith(("broadcast_created", "record_saved", "form_send "))
    ]
    # ключ с площадки — запись; отправка до ответа формы — ещё запись (счёт неподтверждённых); подтверждение — запись
    assert names == [
        "record_saved admitted", "broadcast_created", "record_saved published", "record_saved published", "form_send",
        "record_saved key_confirmed",
    ]


def test_event_times_come_from_the_clock_and_later_runs_show_the_confirmation(bench: BroadcastBench) -> None:
    confirmed: str = format_datetime_text(NOW)
    bench.run(UK)
    record: SlotRecord | None = bench.stored(UK_SLOT)
    assert record is not None and record.results.published_at == confirmed == record.results.confirmed_at
    bench.clock = StoppedClock.at(NOW + timedelta(hours=2))
    bench.run(UK)
    assert msg.KEY_FORM_CONFIRMED.format(confirmed_at="16.03.2027 12:00") in bench.keys_text


def test_unchanged_record_is_not_written_again(bench: BroadcastBench) -> None:
    """Запуск без изменений ничего не пишет в память; изменение — пишет; в лог — итоговая и запрошенная стадии."""
    bench.run(UK)
    bench.run(UK)                   # решение сменилось (создан → совпал): снимок другой, одна запись
    before: SlotRecord | None = bench.stored(UK_SLOT)
    bench.clock = StoppedClock.at(NOW + timedelta(hours=1))
    with LogCapture.on(LogArea.RECORDS) as records, LogCapture.on(LogArea.BROADCASTS) as broadcasts:
        bench.run(UK)
    assert not [line for line in records.messages() if line.startswith("record_saved")]
    unchanged: list[str] = [line for line in broadcasts.messages() if line.startswith("record_unchanged")]
    assert unchanged and all("stage=key_confirmed" in line for line in unchanged)
    assert bench.stored(UK_SLOT) == before and len(bench.posts) == 1
    with LogCapture.on(LogArea.RECORDS) as records:
        bench.run(slot_of(TOMORROW, "uk", with_title("Новое название"), (PREVIEW,)))
    saved: list[str] = [line for line in records.messages() if line.startswith("record_saved")]
    assert saved and "stage=key_confirmed" in saved[0] and saved[0].endswith("requested=admitted")
    after: SlotRecord | None = bench.stored(UK_SLOT)
    assert after is not None and after.updated_at == format_datetime_text(NOW + timedelta(hours=1))


def test_thumbnail_set_by_the_program_is_remembered_over_a_stale_picture(bench: BroadcastBench) -> None:
    """Картинка на площадке ещё заглушка, но обложку этому эфиру ставила программа — MATCH, повторной загрузки нет."""
    bench.platform.picture_lags = True
    bench.run(UK)
    [created] = bench.platform.created
    record: SlotRecord | None = bench.stored(UK_SLOT)
    assert record is not None and record.results.thumbnail_broadcast_id == created.broadcast_id
    second: BroadcastPartResult = bench.run(UK)
    assert _only(second).kind is OutcomeKind.MATCHED
    assert bench.platform.updated == [] and len(bench.platform.thumbnail_attempts) == 1
    # владелец удалил эфир и завёл новый с той же меткой: память — про другой эфир, сверка по картинке
    bench.platform.remove_broadcast("yt_ua", created.broadcast_id)
    placeholder: str = bench.platform.placeholder_of("yt_ua")
    renewed: str = bench.platform.seed_broadcast(
        "yt_ua", TOMORROW, TEXTS.title, TEXTS.description, UK_SLOT, PLATFORM_KEY,
        picture=placeholder, stream_description=PlaceholderMark(placeholder).token,
    ).broadcast_id
    bench.run(UK)
    assert bench.platform.updated == [] and bench.platform.thumbnail_attempts[-1] == renewed
    stored: SlotRecord | None = bench.stored(UK_SLOT)
    assert stored is not None and stored.results.thumbnail_broadcast_id == renewed


def test_broadcast_moved_by_the_owner_gives_two_keys_and_a_moved_line(bench: BroadcastBench) -> None:
    """Эфир A перенесён владельцем, поставлен B, ключ B — в форму; в форме два ключа, A — «перенесён»."""
    bench.run(UK)
    [first] = bench.platform.created
    bench.platform.move_broadcast("yt_ua", first.broadcast_id, TOMORROW + timedelta(days=2))
    with LogCapture.on(LogArea.BROADCASTS) as log:
        result: BroadcastPartResult = bench.run(UK)
    assert _keys_sent(bench) == [FIRST_KEY, SECOND_KEY]
    text: str = report_text(result)
    header: int = text.splitlines().index(msg.REPORT_SECTION_TWO_KEYS.format(count=1))
    two_keys: str = text.splitlines()[header + 1]
    assert mask_stream_key(SECOND_KEY) in two_keys and mask_stream_key(FIRST_KEY) in two_keys
    assert FIRST_KEY not in text and SECOND_KEY not in text
    [moved] = report_of(result).orphans
    assert MOVED_MARK in moved
    [replaced] = [line for line in log.messages() if line.startswith("broadcast_replaced")]
    assert f"previous_broadcast_id={first.broadcast_id}" in replaced
    assert f"previous_stream_key={mask_stream_key(FIRST_KEY)}" in replaced
    stored: SlotRecord | None = bench.stored(UK_SLOT)
    assert stored is not None and stored.results.broadcast_id == bench.platform.created[1].broadcast_id


def test_replaced_broadcast_without_a_confirmed_key_gives_no_two_keys_section(bench: BroadcastBench) -> None:
    bench.post_replies = (FORM_REFUSED,)
    bench.run(UK)
    [first] = bench.platform.created
    bench.platform.move_broadcast("yt_ua", first.broadcast_id, TOMORROW + timedelta(days=2))
    bench.post_replies = BroadcastBench(bench.paths).post_replies
    result: BroadcastPartResult = bench.run(UK)
    assert len(bench.platform.created) == 2
    assert msg.REPORT_SECTION_TWO_KEYS.format(count=1) not in report_text(result)
    [moved] = report_of(result).orphans
    assert MOVED_MARK in moved


def test_channel_config_of_the_bench_is_what_the_form_gets(bench: BroadcastBench) -> None:
    ua: ChannelConfig = bench.channels[0]
    bench.run(UK)
    assert ua.account_name in sent_values(bench.posts[0])
