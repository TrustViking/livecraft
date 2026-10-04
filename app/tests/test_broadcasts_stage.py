"""Прогон части «эфиры» целиком (planers runner e299a6d): создание, ключ в форму, ошибки, допуск, входы, dry-run,
прогресс, память."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

from app.broadcasts.run import BroadcastSlots
from app.broadcasts.stage import BroadcastPartResult
from app.config.channel import ChannelConfig
from app.observability.log_event import LogArea
from app.output.report import ReportKind, RunReport
from app.output.result import BroadcastResult, KeyState, OutcomeKind
from app.output.skipped import SkipKind
from app.packages.package_line import PackageLine, PackageLines, PackageLineStatus
from app.packages.package_slot import PackageSlot
from app.paths import FileName, LivecraftPaths
from app.platforms.error import PlatformError
from app.records.slot_record import SlotRecord, SlotStage
from app.run.exit_code import RunOutcome
from app.slots.slot import SlotEntry, StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.fixtures.broadcasts import FORM_REFUSED, BroadcastBench, form_page, report_of, report_text, sent_values
from app.tests.fixtures.form import SUCCESS_PAGE, TRAINING_FORM_TITLE, FakeFormResponse
from app.tests.fixtures.packages import manifest, slot_record, write_package
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.pipeline import FORM, NOT_IN_FORM, NOW, PREVIEW, SOURCE, TEXTS, TOMORROW, slot_of
from app.tests.fixtures.platform import FakePlatform, channel_info, channel_of, token_path
from app.ui import messages_ru as msg

UK_SLOT: str = "17-03-2027_1900_uk"
PLATFORM_KEY: str = "abcd-abcd-abcd-abcd-abcd"
FIRST_KEY: str = "fake-0001-0000-0000-0000"
UK: StreamSlot = slot_of(TOMORROW, "uk", TEXTS, (PREVIEW,))
RU_LATER: StreamSlot = slot_of(NOT_IN_FORM, "ru")
EN_SLOTS: tuple[StreamSlot, ...] = (
    slot_of(TOMORROW, "en"),
    slot_of(NOT_IN_FORM, "en"),
    slot_of(TOMORROW.replace(hour=21), "en"),
)


@pytest.fixture
def bench(livecraft_paths: LivecraftPaths) -> BroadcastBench:
    """Два канала с токенами: yt_ua (uk) и yt_ru (ru)."""
    return BroadcastBench.with_tokens(livecraft_paths)


@pytest.fixture
def nick(livecraft_paths: LivecraftPaths) -> BroadcastBench:
    """Один канал nick (en) с токеном."""
    return BroadcastBench.with_tokens(livecraft_paths, channel_of("@nick", "nick", "en"))


def _results(result: BroadcastPartResult) -> tuple[BroadcastResult, ...]:
    return report_of(result).results


def _seed_uk(bench: BroadcastBench, title: str = TEXTS.title, marker: str | None = UK_SLOT) -> str:
    return bench.platform.seed_broadcast(
        "yt_ua", TOMORROW, title, TEXTS.description, marker=marker, stream_key=PLATFORM_KEY
    ).broadcast_id


def test_full_create_registers_and_confirms_form(bench: BroadcastBench) -> None:
    result: BroadcastPartResult = bench.run(UK)
    assert result.outcome is RunOutcome.DONE
    [created] = bench.platform.created
    [thumbnail] = bench.platform.thumbnails                  # обложка — отдельным шагом, превью слота
    assert thumbnail.preview == PREVIEW.data
    assert bench.platform.languages == {created.broadcast_id: "uk"}
    [post] = bench.posts
    assert FIRST_KEY in sent_values(post) and "yt_ua" in sent_values(post)
    assert FIRST_KEY in bench.keys_text and msg.KEY_FORM_SENT.format(sent_at="16.03.2027 12:00") in bench.keys_text
    [item] = _results(result)
    assert (item.kind, item.key_state) == (OutcomeKind.CREATED, KeyState.SENT)
    assert not list(bench.paths.logs_dir.glob("*_report.md"))         # файл отчёта пишет запуск


def test_without_the_keys_line_the_broadcast_is_made_and_the_key_stays_in_the_keys_file(bench: BroadcastBench) -> None:
    """Линия «Ключи в форму» не идёт (§14 решение 37): эфир создаётся, форма не читается и в неё ничего не уходит,
    допуск — только по каналу, ключ — в keys.txt со строкой «не отправлялся»; повторной передачи нет, код 0."""
    result: BroadcastPartResult = bench.run(UK, to_form=False)
    assert result.outcome is RunOutcome.DONE and result.resend is None
    [created] = bench.platform.created
    assert created.broadcast_id
    assert [forms.gets for forms in bench.forms] == [[]] and bench.posts == []
    assert FIRST_KEY in bench.keys_text
    assert "  форма  не отправлялся: линия «Ключи в форму» выключена" in bench.keys_text
    [item] = _results(result)
    assert item.kind is OutcomeKind.CREATED and item.key_state is not KeyState.SENT


def test_create_failure_is_an_error_and_sends_nothing(bench: BroadcastBench) -> None:
    bench.platform.fail_create[UK_SLOT] = PlatformError("liveStreamingNotEnabled", "на канале не включены трансляции")
    result: BroadcastPartResult = bench.run(UK)
    assert result.outcome is RunOutcome.FAILED
    [item] = _results(result)
    assert item.kind is OutcomeKind.ERROR
    assert msg.YOUTUBE_REASON_TEXT["liveStreamingNotEnabled"] in report_text(result)
    assert bench.posts == []


def test_failed_form_is_reported_and_retried_next_run(bench: BroadcastBench) -> None:
    """Новый ключ не дошёл — код 1; подтверждения в памяти нет — следующий запуск отправляет его снова."""
    bench.post_replies = (FORM_REFUSED,)
    first: BroadcastPartResult = bench.run(UK)
    assert first.outcome is RunOutcome.FAILED
    assert _results(first)[0].key_state is KeyState.FAILED
    assert "форма  НЕ отправлен" in bench.keys_text
    second: BroadcastPartResult = bench.run(UK)
    assert [FIRST_KEY in sent_values(post) for post in bench.posts] == [True, True]
    assert second.outcome is RunOutcome.FAILED
    assert (_results(second)[0].kind, _results(second)[0].key_state) == (OutcomeKind.MATCHED, KeyState.FAILED)


def test_missing_broadcast_is_a_plain_create(bench: BroadcastBench) -> None:
    """Эфира на площадке нет: обычное создание, без «заново»."""
    result: BroadcastPartResult = bench.run(UK)
    assert "recreate" not in {decision.value for decision in OutcomeKind}
    [post] = bench.posts
    assert FIRST_KEY in sent_values(post)
    assert _results(result)[0].kind is OutcomeKind.CREATED


def test_matched_key_comes_from_the_platform(bench: BroadcastBench) -> None:
    """Эфир с меткой уже стоял — ключ с площадки в keys.txt; при «новые» в форму ничего (§14 решение 49)."""
    _seed_uk(bench)
    result: BroadcastPartResult = bench.run(UK)
    assert result.outcome is RunOutcome.DONE
    assert PLATFORM_KEY in bench.keys_text and msg.KEY_FORM_UNKNOWN in bench.keys_text
    assert bench.posts == [] and bench.platform.created == []
    [item] = _results(result)
    assert (item.kind, item.key_state) == (OutcomeKind.MATCHED, None)


def test_a_dry_run_writes_no_memory(bench: BroadcastBench) -> None:
    """--dry-run: память только читается — записи стоявшего эфира нет; её пишет полный запуск."""
    _seed_uk(bench)
    bench.run(UK, dry_run=True)
    assert bench.stored(UK_SLOT) is None
    bench.run(UK)
    assert bench.stored(UK_SLOT) is not None


def test_broadcast_without_stream_gets_a_stream_and_its_key(bench: BroadcastBench) -> None:
    """Эфир есть, потока нет: программа привязывает поток и получает ключ."""
    found: str = _seed_uk(bench, marker=None)
    result: BroadcastPartResult = bench.run(UK)
    assert result.outcome is RunOutcome.DONE
    assert bench.platform.created == []
    assert [call.broadcast_id for call in bench.platform.attached] == [found]
    assert len(bench.posts) == 1
    assert _results(result)[0].kind is OutcomeKind.STREAM_ATTACHED


def test_too_late_slot_reads_its_key_from_the_platform_and_writes_nothing(bench: BroadcastBench) -> None:
    """Слот внутри min_lead_minutes: ключ с площадки остаётся в keys.txt, действий нет."""
    soon: StreamSlot = slot_of(NOW.replace(minute=30), "uk")
    bench.platform.seed_broadcast(
        "yt_ua", soon.start, "Другое название", "", marker=soon.slot_id, stream_key="soon-soon-soon-soon-soon"
    )
    result: BroadcastPartResult = bench.run(soon)
    assert result.outcome is RunOutcome.DONE
    assert "soon-soon-soon-soon-soon" in bench.keys_text
    platform: FakePlatform = bench.platform
    assert platform.created == [] and platform.updated == [] and platform.attached == []
    assert platform.settings_calls == [] and platform.facts_calls == [] and platform.thumbnails == []
    assert bench.posts == [] and platform.stream_calls
    assert _results(result) == ()


def test_too_late_slot_without_broadcast_has_no_key_row(bench: BroadcastBench) -> None:
    bench.run(slot_of(NOW.replace(minute=30), "uk"))
    assert bench.platform.created == [] and bench.posts == []
    assert all(line.startswith("# ") for line in bench.keys_text.splitlines())


def test_second_run_matches_without_writes(bench: BroadcastBench) -> None:
    bench.run(UK)
    result: BroadcastPartResult = bench.run(UK)
    assert len(bench.platform.created) == 1 and bench.platform.updated == []
    assert _results(result)[0].kind is OutcomeKind.MATCHED
    assert len(bench.posts) == 1                           # ключ прежний — повторной отправки нет
    assert result.outcome is RunOutcome.DONE


def test_fix_keeps_key_and_url(bench: BroadcastBench) -> None:
    """Исправили — ключ прежний; эфир стоял — при «новые» он в форму не уходит (§14 решение 49)."""
    bench.memory_since(NOW.replace(year=2025))
    found: str = _seed_uk(bench, title="Старое название")
    result: BroadcastPartResult = bench.run(UK)
    assert [call.broadcast_id for call in bench.platform.updated] == [found]
    assert PLATFORM_KEY in bench.keys_text and found in bench.keys_text
    [item] = _results(result)
    assert (item.kind, item.key_state) == (OutcomeKind.FIXED, None)
    assert bench.posts == []


def test_one_failed_object_does_not_block_the_others(bench: BroadcastBench) -> None:
    bench.platform.fail_create[UK_SLOT] = PlatformError("liveStreamingNotEnabled", "выключены")
    result: BroadcastPartResult = bench.run(UK, slot_of(TOMORROW, "ru"))
    assert result.outcome is RunOutcome.FAILED
    assert [call.marker for call in bench.platform.created] == ["17-03-2027_1900_ru"]


def test_unconfirmed_form_of_one_object_keeps_the_key_and_exits_1(bench: BroadcastBench) -> None:
    """Одному объекту форма подтвердила, другому нет: код 1, ключ второго — «НЕ отправлен» в keys.txt."""
    bench.post_replies = (bench.post_replies[0], FORM_REFUSED)
    result: BroadcastPartResult = bench.run(UK, slot_of(TOMORROW, "ru"))
    assert result.outcome is RunOutcome.FAILED
    assert [item.key_state for item in _results(result)] == [KeyState.SENT, KeyState.FAILED]
    assert "форма  НЕ отправлен" in bench.keys_text and "форма  отправлен в форму" in bench.keys_text


def test_dry_run_changes_nothing_but_writes_the_report(bench: BroadcastBench) -> None:
    result: BroadcastPartResult = bench.run(UK, dry_run=True)
    assert result.outcome is RunOutcome.DONE
    assert not bench.has_keys_file
    assert not bench.paths.file(FileName.RECORDS).exists()          # память — только на чтение, файла нет
    assert bench.platform.created == [] and bench.posts == []
    assert bench.platform.settings_calls == [] and bench.platform.thumbnail_attempts == []
    assert _results(result)[0].kind is OutcomeKind.CREATED
    assert report_of(result).is_dry_run and result.part_report.lines


def test_no_slot_for_youtube_leaves_youtube_alone(bench: BroadcastBench) -> None:
    """Слот «по номерам» на YouTube не идёт: к площадке не обращаемся, отчёта нет."""
    numbered: StreamSlot = slot_of(TOMORROW, "uk", SlotTexts("1) Эфир", "", SlotTextOrigin.NUMBERED))
    result: BroadcastPartResult = bench.run(numbered)
    assert result.console_lines == (msg.BROADCASTS_NO_SLOTS,) and result.outcome is RunOutcome.DONE
    assert bench.platform.describe_calls == [] and bench.platform.list_calls == []
    assert not bench.paths.file(FileName.RECORDS).exists()


def test_logins_happen_before_any_channel_is_listed(bench: BroadcastBench) -> None:
    """Каналы без токена входят подряд, до первого чтения эфиров; в сверке браузер не открывается."""
    for channel in bench.channels:
        token_path(bench.paths, channel.handle).unlink()
    result: BroadcastPartResult = bench.run(UK, slot_of(TOMORROW, "ru"))
    assert bench.platform.logins == ["yt_ua", "yt_ru"]
    assert bench.platform.list_calls == ["yt_ua", "yt_ru"]
    lines: list[str] = bench.record.lines
    first_read: int = lines.index(msg.PROGRESS_CHANNEL_READ_STARTED.format(account_name="yt_ua", handle="@yt_ua"))
    assert all("yt_" not in line or index < first_read for index, line in enumerate(lines) if "браузер" in line)
    assert result.outcome is RunOutcome.DONE and len(bench.platform.created) == 2


def test_channel_that_failed_to_log_in_is_isolated(bench: BroadcastBench) -> None:
    """Канал, который в фазе входов не вошёл: его объекты не допущены, сбой — одной строкой; другой канал работает."""
    token_path(bench.paths, "@yt_ua").unlink()
    bench.platform.fail_login["yt_ua"] = PlatformError("authFailed", "flow_failed: browser closed")
    result: BroadcastPartResult = bench.run(UK, slot_of(TOMORROW, "ru"))
    assert bench.platform.logins == ["yt_ua"]
    assert bench.platform.list_calls == ["yt_ru"]
    report: RunReport = report_of(result)
    assert len(report.failures) == 1 and result.outcome is RunOutcome.FAILED
    assert [item.kind for item in report.results] == [OutcomeKind.NOT_ADMITTED, OutcomeKind.CREATED]
    assert [call.channel_id for call in bench.platform.created] == ["yt_ru"]


def test_channel_aligned_at_login_answers_the_form_with_its_new_name(bench: BroadcastBench) -> None:
    """Название канала сменилось на YouTube: вход выравнивает его, и форма получает новое название (§14 решение 25)."""
    ua: ChannelConfig = bench.channels[0]
    token_path(bench.paths, "@yt_ua").unlink()
    bench.platform.login_answers["yt_ua"] = [channel_info(ua, title="Новое название")]
    bench.run(UK)
    [post] = bench.posts
    assert "Новое название" in sent_values(post) and "yt_ua" not in sent_values(post)


def test_form_dates_are_checked_before_logins_and_the_platform(nick: BroadcastBench) -> None:
    """Даты формы — одной строкой до входов и до площадки; дата без варианта — не допущенный объект, не ошибка."""
    token_path(nick.paths, "@nick").unlink()
    result: BroadcastPartResult = nick.run(*EN_SLOTS)
    lines: list[str] = nick.record.lines
    dates_line: str = msg.FORM_DATES_MISSING.format(form=TRAINING_FORM_TITLE, dates="18.03.2027")
    assert lines.count(dates_line) == 1
    first_read: int = lines.index(msg.PROGRESS_CHANNEL_READ_STARTED.format(account_name="nick", handle="@nick"))
    assert lines.index(dates_line) < first_read
    assert [call.marker for call in nick.platform.created] == ["17-03-2027_1900_en", "17-03-2027_2100_en"]
    assert [item.kind for item in _results(result)].count(OutcomeKind.NOT_ADMITTED) == 1
    assert result.outcome is RunOutcome.DONE                   # не допущенный объект — не ошибка
    assert "18.03.2027" not in nick.keys_text                   # эфира нет — и ключа нет


def test_keys_go_to_the_form_right_after_the_actions_of_their_object(nick: BroadcastBench) -> None:
    nick.run(*EN_SLOTS)
    steps: list[str] = [line for line in nick.record.lines if "создание эфира" in line or "отправка ключа" in line]
    assert steps == [
        "Канал «nick» @nick: создание эфира 17.03.2027 19:00 en.",
        "Канал «nick» @nick: отправка ключа в форму — эфир 17.03.2027 19:00 en.",
        "Канал «nick» @nick: создание эфира 17.03.2027 21:00 en.",
        "Канал «nick» @nick: отправка ключа в форму — эфир 17.03.2027 21:00 en.",
    ]


def test_existing_broadcast_of_a_not_admitted_slot_keeps_its_key_out_of_the_form(nick: BroadcastBench) -> None:
    """Эфир 18.03 уже стоит, а в форме нет даты: ключ — в keys.txt с причиной, в форму ничего, ничего не правится."""
    found: str = nick.platform.seed_broadcast(
        "nick", NOT_IN_FORM, "Другое название", "", marker="18-03-2027_2000_en", stream_key=PLATFORM_KEY
    ).broadcast_id
    result: BroadcastPartResult = nick.run(*EN_SLOTS)
    assert all(PLATFORM_KEY not in sent_values(post) for post in nick.posts) and len(nick.posts) == 2
    assert nick.platform.updated == [] and found not in nick.platform.settings_calls
    assert found not in nick.platform.facts_calls
    block: str = nick.keys_text.split("18.03.2027 20:00  en  nick @nick\n", 1)[1].split("\n\n", 1)[0]
    assert f"  ключ   {PLATFORM_KEY}" in block and "НЕ отправлен: не допущено" in block
    assert result.outcome is RunOutcome.DONE


def test_incomplete_answers_after_publication_skip_the_post(nick: BroadcastBench) -> None:
    """Адреса потока нет среди вариантов формы: эфир создан, POST нет, причина — в keys.txt и в логе."""
    nick.form_page = form_page("17.03.2027", stream_urls=("rtmp://x.rtmp.youtube.com/live2/",))
    with LogCapture.on(LogArea.BROADCASTS) as log:
        result: BroadcastPartResult = nick.run(EN_SLOTS[0])
    assert len(nick.platform.created) == 1 and nick.posts == []
    assert any(line.startswith("form_send_skipped slot_id=17-03-2027_1900_en") for line in log.messages(logging.WARNING))
    assert result.outcome is RunOutcome.FAILED
    assert "НЕ отправлен" in nick.keys_text


def test_dry_run_shows_admission_and_sends_nothing(nick: BroadcastBench) -> None:
    with LogCapture.on(LogArea.BROADCASTS) as log:
        result: BroadcastPartResult = nick.run(*EN_SLOTS, dry_run=True)
    assert nick.posts == [] and nick.platform.created == []
    kinds: list[OutcomeKind] = [item.kind for item in _results(result)]
    assert kinds.count(OutcomeKind.NOT_ADMITTED) == 1 and kinds.count(OutcomeKind.CREATED) == 2
    assert result.outcome is RunOutcome.DONE
    messages: list[str] = log.messages()
    assert any(
        line.startswith(
            'slot_not_admitted_reason slot_id=18-03-2027_2000_en channel="nick" handle=@nick '
            "kind=form_field code=missing_option field=date"
        )
        for line in messages
    )
    assert sum(1 for line in messages if line.startswith("slot_admitted ")) == 2


def test_full_run_reports_progress_in_step_order(bench: BroadcastBench) -> None:
    """Проверка каналов → даты формы → чтение каналов → по объекту: действие и сразу его ключ (у стоявшего эфира при
    «новые» — нет) → отчёт."""
    bench.memory_since(NOW.replace(year=2025))
    ru: StreamSlot = slot_of(TOMORROW, "ru")
    bench.platform.seed_broadcast(
        "yt_ru", TOMORROW, "Старое название", ru.description, marker=ru.slot_id, stream_key=PLATFORM_KEY
    )
    result: BroadcastPartResult = bench.run(UK, ru)
    assert result.outcome is RunOutcome.DONE
    assert bench.record.lines == [
        "Проверка каналов YouTube по сохранённым входам: 2.",
        "Канал «yt_ua» @yt_ua: проверка по сохранённому входу.",
        "Канал «yt_ru» @yt_ru: проверка по сохранённому входу.",
        msg.FORM_DATES_OK.format(form=TRAINING_FORM_TITLE, wanted=1, accepted=4),
        "Канал «yt_ua» @yt_ua: запрос запланированных эфиров.",
        "Канал «yt_ua» @yt_ua: запланированных эфиров — 0.",
        "Канал «yt_ru» @yt_ru: запрос запланированных эфиров.",
        "Канал «yt_ru» @yt_ru: запланированных эфиров — 1.",
        "Канал «yt_ua» @yt_ua: создание эфира 17.03.2027 19:00 uk.",
        "Канал «yt_ua» @yt_ua: отправка ключа в форму — эфир 17.03.2027 19:00 uk.",
        "Канал «yt_ru» @yt_ru: исправление эфира 17.03.2027 19:00 ru.",
        msg.PROGRESS_REPORT,
    ]


def test_dry_run_progress_has_no_action_steps(bench: BroadcastBench) -> None:
    bench.run(UK, dry_run=True)
    assert not [line for line in bench.record.lines if "создание" in line or "отправка" in line]
    assert bench.record.lines[-1] == msg.PROGRESS_REPORT


def test_console_after_the_run_is_the_summary_blocks_and_youtube_usage(bench: BroadcastBench) -> None:
    """Подвал путей печатает запуск; часть отдаёт ему путь keys.txt своей частью отчёта."""
    result: BroadcastPartResult = bench.run(UK)
    lines: tuple[str, ...] = result.console_lines
    assert lines[0] == "" and lines[1] == report_of(result).summary_lines[0]
    assert lines[-1] == bench.platform.gateway.usage.line
    assert not any(line.startswith("  " + msg.CONSOLE_LABEL_KEYS) for line in lines)
    assert result.part_report.keys_file == "keystreams\\keys.txt"
    assert result.part_report.lines[0] == "## Эфиры YouTube"
    assert bench.platform.gateway.usage.line in result.part_report.body


def test_the_total_of_the_part_goes_to_the_log(bench: BroadcastBench) -> None:
    with LogCapture.on(LogArea.BROADCASTS) as log:
        bench.run(UK)
    assert "broadcasts_report kind=full results=1 failures=0 exit_code=0 reason=-" in log.messages()


def test_memory_is_closed_when_the_run_breaks_off(bench: BroadcastBench) -> None:
    """Обрыв посреди отправки ключа: память закрыта (её файл можно удалить), запись с ключом — PUBLISHED; следующий
    запуск отправляет ключ ровно раз."""
    bench.post_replies = (KeyboardInterrupt(),)
    with pytest.raises(KeyboardInterrupt):
        bench.run(UK)
    after: SlotRecord | None = bench.stored(UK_SLOT)
    assert after is not None and after.stage is SlotStage.PUBLISHED and after.results.stream_key == FIRST_KEY
    bench.post_replies = (FakeFormResponse(SUCCESS_PAGE),)
    result: BroadcastPartResult = bench.run(UK)
    assert (_results(result)[0].kind, _results(result)[0].key_state) == (OutcomeKind.MATCHED, KeyState.SENT)
    confirmed: SlotRecord | None = bench.stored(UK_SLOT)
    assert confirmed is not None and confirmed.stage is SlotStage.KEY_CONFIRMED
    bench.run(UK)
    assert len(bench.posts) == 2 and len(bench.platform.created) == 1


def test_memory_is_closed_when_the_platform_crashes(bench: BroadcastBench) -> None:
    bench.platform.fail_create[UK_SLOT] = RuntimeError("crash")   # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        bench.run(UK)
    bench.paths.file(FileName.RECORDS).unlink()                  # открытый файл Windows удалить не даст


def test_channels_with_one_title_and_other_handles_do_not_mix(livecraft_paths: LivecraftPaths) -> None:
    """Два канала «Українка» с разными никами: свои эфиры, свои потоки, свой отказ."""
    twin_a, twin_b = channel_of("@twin_a", "Українка"), channel_of("@twin_b", "Українка")
    bench: BroadcastBench = BroadcastBench.with_tokens(livecraft_paths, twin_a, twin_b)
    later: StreamSlot = slot_of(NOT_IN_FORM.replace(hour=19), "uk")
    bench.form_page = form_page("17.03.2027", "18.03.2027")
    bench.platform.seed_broadcast("@twin_a", TOMORROW, TEXTS.title, TEXTS.description, marker=UK_SLOT)
    bench.platform.fail_list["twin_b"] = PlatformError("liveStreamingNotEnabled", "выключены")
    result: BroadcastPartResult = bench.run(UK, later)
    kinds: list[tuple[str, str, str]] = sorted((item.channel.handle, item.key.human_date, item.kind.value) for item in _results(result))
    assert kinds == [
        ("@twin_a", "17.03.2027", OutcomeKind.MATCHED.value),
        ("@twin_a", "18.03.2027", OutcomeKind.CREATED.value),
        ("@twin_b", "17.03.2027", OutcomeKind.ERROR.value),
        ("@twin_b", "18.03.2027", OutcomeKind.ERROR.value),
    ]
    assert [call.channel_id for call in bench.platform.created] == ["twin_a"]
    assert {channel for channel, _stream in bench.platform.stream_calls} == {"twin_a"}
    assert bench.platform.list_calls == ["twin_a", "twin_b"]


# --- режим Б: слоты пакетов, прошедшие слоты и строки пакетов


def test_mode_b_slots_bring_their_past_slots_and_package_lines_into_the_report(bench: BroadcastBench) -> None:
    """Прошедший слот пакета — в «Пропущено» (язык канала), строки пакетов — в отчёт; эфир будущего слота создан."""
    yesterday: StreamSlot = slot_of(NOW - timedelta(days=1), "uk")
    past: SlotEntry = SlotEntry(yesterday.key, TEXTS, (), (SOURCE,))
    lines: PackageLines = PackageLines((PackageLine("plan.bcast", PackageLineStatus.ACCEPTED, 2, 2),))
    known: dict[str, datetime] = {UK.slot_id: UK.start, past.slot_id: past.start}
    result: BroadcastPartResult = bench.run_slots(
        BroadcastSlots((PackageSlot(UK, FORM),), known, (past,), lines)
    )
    report: RunReport = report_of(result)
    assert [(line.kind, line.key) for line in report.skipped.lines] == [(SkipKind.PAST, past.key)]
    assert report.packages == lines and result.outcome is RunOutcome.DONE
    assert "- plan.bcast — принят, слотов 2, из них языков каналов 2" in report_text(result)
    assert [call.marker for call in bench.platform.created] == [UK_SLOT]


def test_mode_b_with_an_unreadable_package_is_code_1(bench: BroadcastBench) -> None:
    broken: PackageLine = PackageLine("broken.bcast", PackageLineStatus.DAMAGED, detail="не ZIP-архив (x)")
    slots: BroadcastSlots = BroadcastSlots((PackageSlot(UK, FORM),), {UK.slot_id: UK.start}, (), PackageLines((broken,)))
    result: BroadcastPartResult = bench.run_slots(slots)
    assert result.outcome is RunOutcome.FAILED
    assert msg.CONSOLE_ATTENTION_PACKAGE.format(text=broken.text) in result.console_lines


# --- --status: эфиры программы на каналах, keys.txt и отчёт


def test_status_lists_the_program_broadcasts_and_writes_the_keys(bench: BroadcastBench) -> None:
    """Ключ и адрес — с площадки, «отправлен в форму» — из памяти; в форму --status ничего не шлёт."""
    bench.run(UK)
    bench.paths.file(FileName.KEYS).unlink()
    result: BroadcastPartResult = bench.status()
    report: RunReport = report_of(result)
    assert report.kind is ReportKind.STATUS and [item.kind for item in report.results] == [OutcomeKind.MATCHED]
    assert FIRST_KEY in bench.keys_text and msg.KEY_FORM_SENT_LEAD in bench.keys_text
    assert len(bench.posts) == 1 and result.outcome is RunOutcome.DONE
    assert msg.REPORT_SECTION_SCHEDULED.format(count=1) in report_text(result)


def test_status_of_a_failing_channel_is_code_1_and_keeps_the_others(bench: BroadcastBench) -> None:
    bench.run(UK)
    bench.platform.fail_list["yt_ru"] = PlatformError("liveStreamingNotEnabled", "выключены")
    result: BroadcastPartResult = bench.status()
    assert result.outcome is RunOutcome.FAILED
    assert [item.kind for item in report_of(result).results] == [OutcomeKind.MATCHED]
    assert len(report_of(result).failures) == 1


def test_status_does_not_write_the_memory(bench: BroadcastBench) -> None:
    result: BroadcastPartResult = bench.status()
    assert result.outcome is RunOutcome.DONE and report_of(result).results == ()
    assert not bench.paths.file(FileName.RECORDS).exists() and bench.has_keys_file


# --- известные слоты сверки (§13 этап 6): при работающей таблице — и слоты таблицы, и слоты папки пакетов

PACKAGED_START: datetime = TOMORROW.replace(hour=21)
PACKAGED_SLOT: str = "17-03-2027_2100_uk"


def _seed_packaged(bench: BroadcastBench) -> None:
    """Эфир программы на канале для слота 21:00, которого нет в таблице этого запуска."""
    bench.platform.seed_broadcast("yt_ua", PACKAGED_START, TEXTS.title, TEXTS.description, marker=PACKAGED_SLOT)


def test_a_broadcast_of_a_slot_from_the_packages_folder_is_not_an_orphan(bench: BroadcastBench) -> None:
    """Слот 21:00 есть в пакете папки пакетов: его эфир известен сверке и в «Перенесён или отменён?» не попадает."""
    write_package(bench.paths.bcast_dir, manifest(slot_record(time="21:00")))
    _seed_packaged(bench)
    result: BroadcastPartResult = bench.run(UK)
    assert report_of(result).orphans == ()


def test_without_the_package_the_same_broadcast_is_an_orphan(bench: BroadcastBench) -> None:
    _seed_packaged(bench)
    result: BroadcastPartResult = bench.run(UK)
    [orphan] = report_of(result).orphans
    assert orphan.startswith("17.03.2027 21:00 uk")
