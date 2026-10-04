"""Часть «объявления в Telegram» (app\\publish\\announce_stage.py, CLAUDE.md §13 задача 4.5, §14 решения 19, 31, 32):
порядок отправлений даты, ссылки на документы дат, пакет последним, пробный запуск, первый отказ бота и перенос группы
в супергруппу — на подделке Telegram и настоящем livecraft.json временного корня."""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from app.config.files import SettingsFile, ShippedSettings
from app.config.settings import FormSettings, LivecraftSettings
from app.config.telegram import ChatTarget, TelegramSettings
from app.observability.log_event import LogArea
from app.packages.package import PackagePeriod, PackageResult
from app.packages.package_slot import PackageSlot
from app.paths import LivecraftPaths
from app.publish.announce_stage import AnnounceResult, AnnounceStage
from app.publish.announce_texts import AnnounceTexts
from app.publish.day import PublishDay
from app.publish.doc_copy import DocCopySaved
from app.publish.doc_day import DocDay
from app.publish.doc_stage import DocDocument, DocResult
from app.run.exit_code import RunOutcome
from app.run.progress import StageProgress
from app.slots.slot import StreamSlot
from app.slots.texts import SlotTexts, SourceText
from app.tests.conftest import FORM_URL
from app.tests.fixtures.announce import (
    COVER, KYIV, OTHER_COVER, PACKAGE_BYTES, PACKAGE_NAME, stream_slot, written_package,
)
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.settings import with_form_url
from app.tests.fixtures.telegram import BOT_TOKEN, PRIVATE_CHAT_ID, BotCall, FakeTelegram
from app.ui import messages_ru as msg

TEXTS: AnnounceTexts = AnnounceTexts()
GROUP_ID: str = "-4000000001"
SUPERGROUP_ID: str = "-1001000000001"
DOC_URL: str = "https://docs.google.com/document/d/doc16/edit"
NUMBERED: SlotTexts = SlotTexts.numbered([SourceText("Видео 1", "Опис 1"), SourceText("Видео 2", "Опис 2")])
FIRST: StreamSlot = stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV), "uk", NUMBERED)
SECOND: StreamSlot = stream_slot(datetime(2026, 10, 16, 20, 0, tzinfo=KYIV), "en", previews=(COVER, OTHER_COVER))
NEXT_DAY: StreamSlot = stream_slot(datetime(2026, 10, 17, 19, 0, tzinfo=KYIV))
THIRD_DAY: StreamSlot = stream_slot(datetime(2026, 10, 18, 19, 0, tzinfo=KYIV))
POSTS_OF_ONE_SLOT_DAY: int = 7         # начало, шапка, флаги, блок, обложка, напоминание, конец


def _settings(telegram: TelegramSettings) -> LivecraftSettings:
    """Поставочные настройки с формой ключей и разделом telegram."""
    return with_form_url(ShippedSettings().settings, FORM_URL).with_telegram(telegram)


def _stage(
    paths: LivecraftPaths, fake: FakeTelegram, telegram: TelegramSettings, dry_run: bool = False
) -> AnnounceStage:
    """Часть на подделке Telegram; livecraft.json корня — те же настройки, что у части."""
    settings: LivecraftSettings = _settings(telegram)
    file: SettingsFile = SettingsFile.of(paths)
    file.save(settings)
    return AnnounceStage(settings=settings, dry_run=dry_run, bot=fake.bot, file=file)


def _private() -> TelegramSettings:
    return TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_CHAT_ID, "")


def _run(
    stage: AnnounceStage, paths: LivecraftPaths, *slots: StreamSlot, docs: DocResult | None = None,
    with_package: bool = True,
) -> AnnounceResult:
    """Часть по дням этих слотов (форма настроек) с пакетом из них (пакета нет — `with_package` ложь) — как у вывода
    запуска."""
    period: PackagePeriod = PackagePeriod.of([slot.start for slot in slots])
    previews: int = sum(len(slot.previews) for slot in slots)
    packages: tuple[PackageResult, ...] = (
        (written_package(paths.bcast_dir, len(slots), previews, period),) if with_package else ()
    )
    return stage.run(_days(*slots), docs, packages)


def _days(*slots: StreamSlot) -> tuple[PublishDay, ...]:
    """Дни слотов с формой настроек."""
    return PublishDay.days(PackageSlot.with_form(slots, _settings(_private()).form))


def _docs(*dated: tuple[str, str]) -> DocResult:
    """Итог части документа: документы дней DD-MM-YYYY (форма настроек) по ссылкам."""
    form: FormSettings = _settings(_private()).form
    days: tuple[PublishDay, ...] = tuple(PublishDay(when, form, (), 1) for when, _ in dated)
    documents: tuple[DocDocument, ...] = tuple(
        DocDocument(DocDay(day, ()), day.date, url, 0, 0, DocCopySaved(Path(day.date), day.date))
        for day, (_, url) in zip(days, dated)
    )
    return DocResult(dry_run=False, days=days, documents=documents)


def _text(call: BotCall) -> str:
    return str(call.body["text"])


def _file_name(call: BotCall) -> str:
    files: object = call.options["files"]
    assert isinstance(files, dict)
    return str(files["document"][0])


def test_one_date_goes_out_in_order_with_covers_as_documents(livecraft_paths: LivecraftPaths) -> None:
    """Дата с двумя слотами (первый — «по номерам», у второго две обложки): начало, шапка со ссылкой на документ, по
    слоту — флаги, блок, обложки файлами, напоминание о форме; конец; пакет — последним, документом с подписью."""
    fake: FakeTelegram = FakeTelegram.delivering()
    result: AnnounceResult = _run(
        _stage(livecraft_paths, fake, _private()), livecraft_paths, FIRST, SECOND, docs=_docs(("16-10-2026", DOC_URL))
    )
    [day] = _days(FIRST, SECOND)
    reminder: str = TEXTS.form_reminder(FORM_URL)
    assert fake.methods == [
        "sendMessage", "sendMessage",                                   # начало, шапка
        "sendMessage", "sendMessage", "sendDocument", "sendMessage",    # первый слот: флаги, блок, обложка, форма
        "sendMessage", "sendMessage", "sendDocument", "sendDocument", "sendMessage",   # второй: две обложки
        "sendMessage",                                                  # конец дня
        "sendDocument",                                                 # пакет
    ]
    texts: list[str] = [_text(call) for call in fake.calls if call.method == "sendMessage"]
    assert texts == [
        TEXTS.day_start, TEXTS.header(day.times, FORM_URL, DOC_URL),
        TEXTS.flags("uk"), TEXTS.slot(FIRST), reminder,
        TEXTS.flags("en"), TEXTS.slot(SECOND), reminder,
        TEXTS.day_end,
    ]
    assert "1) Видео 1" in TEXTS.slot(FIRST)
    documents: list[BotCall] = [call for call in fake.calls if call.method == "sendDocument"]
    assert [_file_name(call) for call in documents] == [
        "16-10-2026_1900_uk_1.jpg", "16-10-2026_2000_en_1.jpg", "16-10-2026_2000_en_2.jpg", PACKAGE_NAME,
    ]
    assert documents[1].options["files"]["document"][1:] == (COVER.data, "image/jpeg")
    assert "caption" not in documents[0].body and "parse_mode" not in documents[-1].body
    assert documents[-1].options["files"]["document"][1:] == (PACKAGE_BYTES, "application/zip")
    period: PackagePeriod = PackagePeriod(first=date(2026, 10, 16), last=date(2026, 10, 16))
    assert documents[-1].body["caption"] == TEXTS.package_caption(period, 2, 3)
    assert {call.body["chat_id"] for call in fake.calls} == {PRIVATE_CHAT_ID}
    assert result.outcome is RunOutcome.DONE and result.packages == (PACKAGE_NAME,)
    assert result.console_lines == (
        msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=2, previews=3),
        msg.ANNOUNCE_PACKAGE_LINE.format(name=PACKAGE_NAME),
    )


def test_each_date_links_its_own_document_and_a_date_without_one_has_no_document_lines(
    livecraft_paths: LivecraftPaths,
) -> None:
    fake: FakeTelegram = FakeTelegram.delivering()
    docs: DocResult = _docs(("16-10-2026", DOC_URL), ("17-10-2026", "https://docs.google.com/document/d/doc17/edit"))
    _run(_stage(livecraft_paths, fake, _private()), livecraft_paths, FIRST, NEXT_DAY, THIRD_DAY, docs=docs)
    days: tuple[PublishDay, ...] = _days(FIRST, NEXT_DAY, THIRD_DAY)
    headers: list[str] = [_text(call) for call in fake.calls if _text_or_empty(call).startswith("Ежедневные")]
    assert headers == [
        TEXTS.header(days[0].times, FORM_URL, DOC_URL),
        TEXTS.header(days[1].times, FORM_URL, "https://docs.google.com/document/d/doc17/edit"),
        TEXTS.header(days[2].times, FORM_URL, None),
    ]
    assert "Description" not in headers[2]


def _text_or_empty(call: BotCall) -> str:
    return str(call.body.get("text", ""))


def test_without_a_document_part_the_headers_have_no_document_lines(livecraft_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.delivering()
    _run(_stage(livecraft_paths, fake, _private()), livecraft_paths, FIRST)
    [day] = _days(FIRST)
    assert _text(fake.calls[1]) == TEXTS.header(day.times, FORM_URL, None)


def test_without_a_written_package_nothing_follows_the_last_date(livecraft_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.delivering()
    result: AnnounceResult = _run(_stage(livecraft_paths, fake, _private()), livecraft_paths, FIRST, with_package=False)
    assert len(fake.calls) == POSTS_OF_ONE_SLOT_DAY and _text(fake.calls[-1]) == TEXTS.day_end
    assert result.packages == () and result.outcome is RunOutcome.DONE


def test_a_dry_run_sends_nothing(livecraft_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.delivering()
    result: AnnounceResult = _run(_stage(livecraft_paths, fake, _private(), dry_run=True), livecraft_paths, FIRST)
    assert fake.calls == []
    assert result.console_lines == (msg.ANNOUNCE_DRY_RUN_LINE,) and result.outcome is RunOutcome.DONE


def test_a_refusal_on_the_second_date_stops_the_part(livecraft_paths: LivecraftPaths) -> None:
    """Отказ бота на второй дате: третья дата и пакет не отправляются, строки консоли, announce_failed в логе, код 1."""
    fake: FakeTelegram = FakeTelegram.answering(*["send_message_private"] * POSTS_OF_ONE_SLOT_DAY, "forbidden")
    with LogCapture.on(LogArea.PUBLISH) as capture:
        stage: AnnounceStage = _stage(livecraft_paths, fake, _private())
        result: AnnounceResult = _run(stage, livecraft_paths, FIRST, NEXT_DAY, THIRD_DAY)
    assert len(fake.calls) == POSTS_OF_ONE_SLOT_DAY + 1 and "sendDocument" not in fake.methods[-1:]
    assert result.outcome is RunOutcome.FAILED and result.skipped == 1 and result.packages == ()
    assert result.console_lines == (
        msg.ANNOUNCE_DAY_LINE.format(date="16.10.2026", slots=1, previews=1),
        msg.ANNOUNCE_FAILED_LINE.format(date="17.10.2026", reason=msg.TELEGRAM_PROBLEMS["forbidden"]),
        msg.ANNOUNCE_SKIPPED_LINE.format(count=1),
    )
    [failed] = capture.messages(logging.ERROR)
    assert failed.startswith("announce_failed date=17-10-2026 method=sendMessage reason=forbidden status=403 ")
    assert "announce_day_sent date=16-10-2026 slots=1 previews=1 doc=no" in capture.messages(logging.INFO)
    assert capture.messages()[-1].startswith("announce_finished dry_run=no dates=3 days=1 ")


def test_a_refusal_on_the_package_is_its_own_line(livecraft_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.answering(*["send_message_private"] * POSTS_OF_ONE_SLOT_DAY, "forbidden")
    result: AnnounceResult = _run(_stage(livecraft_paths, fake, _private()), livecraft_paths, FIRST)
    assert fake.methods[-1] == "sendDocument"
    assert result.outcome is RunOutcome.FAILED and result.skipped == 0
    assert result.console_lines[-1] == msg.ANNOUNCE_PACKAGE_FAILED_LINE.format(
        reason=msg.TELEGRAM_PROBLEMS["forbidden"]
    )


def test_a_group_that_became_a_supergroup_is_written_and_used_next(livecraft_paths: LivecraftPaths) -> None:
    """Перенос в супергруппу: новый id — в livecraft.json, следующие отправления — в него, строка консоли."""
    fake: FakeTelegram = FakeTelegram.delivering("migrated", "send_message_supergroup")
    group: TelegramSettings = TelegramSettings(ChatTarget.GROUP, GROUP_ID, "", "")
    with LogCapture.on(LogArea.PUBLISH) as capture:
        result: AnnounceResult = _run(_stage(livecraft_paths, fake, group), livecraft_paths, FIRST)
    chats: list[object] = [call.body["chat_id"] for call in fake.calls]
    assert chats[:2] == [GROUP_ID, SUPERGROUP_ID] and set(chats[2:]) == {SUPERGROUP_ID}
    assert SettingsFile.of(livecraft_paths).load().telegram.group_chat_id == SUPERGROUP_ID
    line: str = msg.TELEGRAM_CHAT_MIGRATED.format(old_chat_id=GROUP_ID, new_chat_id=SUPERGROUP_ID)
    assert result.console_lines[0] == line and result.outcome is RunOutcome.DONE
    assert f"telegram_chat_migrated old_chat_id={GROUP_ID} new_chat_id={SUPERGROUP_ID}" in capture.messages()


def test_the_log_carries_no_token_and_no_slot_texts(livecraft_paths: LivecraftPaths) -> None:
    fake: FakeTelegram = FakeTelegram.delivering()
    with LogCapture.on(LogArea.PUBLISH) as capture:
        _run(_stage(livecraft_paths, fake, _private()), livecraft_paths, FIRST, SECOND)
    text: str = "\n".join(capture.messages())
    assert f"announce_package_sent file={PACKAGE_NAME}" in text
    for value in (FIRST.title, SECOND.title, SECOND.description, FORM_URL, BOT_TOKEN):
        assert value not in text


# --- дни по дате и форме, все пакеты запуска (§14 решение 51)


def test_two_forms_on_one_date_are_two_announcements_each_with_its_form(livecraft_paths: LivecraftPaths) -> None:
    """Слоты одной даты из пакетов двух форм: два объявления дня, в каждом — форма своих слотов; затем все пакеты
    запуска по порядку."""
    fake: FakeTelegram = FakeTelegram.delivering()
    stage: AnnounceStage = _stage(livecraft_paths, fake, _private())
    form: FormSettings = stage.settings.form
    other: FormSettings = FormSettings(
        url="https://docs.google.com/forms/d/e/OTHER/viewform", fields=form.fields, values=form.values,
        date_format=form.date_format,
    )
    days: tuple[PublishDay, ...] = PublishDay.days((PackageSlot(FIRST, form), PackageSlot(SECOND, other)))
    assert [(day.date, day.number) for day in days] == [("16-10-2026", 1), ("16-10-2026", 2)]
    period: PackagePeriod = PackagePeriod.of([FIRST.start])
    first: PackageResult = written_package(livecraft_paths.bcast_dir, 1, 1, period)
    second_path: Path = livecraft_paths.bcast_dir / "plan_16-10-2026_16-10-2026_gen28-09-2026-1005-2.bcast"
    second_path.write_bytes(PACKAGE_BYTES)
    second: PackageResult = PackageResult(second_path, None, 1, 2, len(PACKAGE_BYTES), period)
    result: AnnounceResult = stage.run(days, None, (first, second))
    headers: list[str] = [_text(call) for call in fake.calls if call.method == "sendMessage"][1::6]
    assert headers[0] == TEXTS.header(days[0].times, form.url, None)
    assert TEXTS.header(days[1].times, other.url, None) in [_text(call) for call in fake.calls if "text" in call.body]
    assert result.packages == (PACKAGE_NAME, second_path.name) and result.outcome is RunOutcome.DONE
    assert [_file_name(call) for call in fake.calls if call.method == "sendDocument"][-2:] == [
        PACKAGE_NAME, second_path.name
    ]


# --- строки хода в консоли (CLAUDE.md §13 задача 9.5)


def _progress_run(
    stage: AnnounceStage, paths: LivecraftPaths, record: ConsoleRecord, *slots: StreamSlot
) -> AnnounceResult:
    """Часть по дням этих слотов с пакетом из них и строками хода на консоль теста."""
    period: PackagePeriod = PackagePeriod.of([slot.start for slot in slots])
    package: PackageResult = written_package(paths.bcast_dir, len(slots), len(slots), period)
    return stage.run(_days(*slots), None, (package,), StageProgress(record.console))


def test_a_progress_line_names_each_date_and_then_the_package(livecraft_paths: LivecraftPaths) -> None:
    """Две даты и пакет — три строки хода по порядку: место дня и его дата для людей, затем имя пакета."""
    record: ConsoleRecord = ConsoleRecord()
    fake: FakeTelegram = FakeTelegram.delivering()
    stage: AnnounceStage = _stage(livecraft_paths, fake, _private())
    result: AnnounceResult = _progress_run(stage, livecraft_paths, record, FIRST, NEXT_DAY)
    assert result.outcome is RunOutcome.DONE and result.packages == (PACKAGE_NAME,)
    assert record.lines == [
        "Отправка объявлений в Telegram 1 из 2: 16.10.2026.",
        "Отправка объявлений в Telegram 2 из 2: 17.10.2026.",
        f"Отправка пакета в Telegram: {PACKAGE_NAME}.",
    ]


def test_after_a_refusal_of_the_bot_no_more_progress_lines_follow(livecraft_paths: LivecraftPaths) -> None:
    """Отказ бота на второй дате из трёх: строки хода — первой и второй дат; третьей даты и пакета нет."""
    record: ConsoleRecord = ConsoleRecord()
    fake: FakeTelegram = FakeTelegram.answering(*["send_message_private"] * POSTS_OF_ONE_SLOT_DAY, "forbidden")
    stage: AnnounceStage = _stage(livecraft_paths, fake, _private())
    result: AnnounceResult = _progress_run(stage, livecraft_paths, record, FIRST, NEXT_DAY, THIRD_DAY)
    assert result.outcome is RunOutcome.FAILED
    assert record.lines == [
        msg.PROGRESS_ANNOUNCE.format(place=place, total=3, date=date)
        for place, date in ((1, "16.10.2026"), (2, "17.10.2026"))
    ]


def test_a_package_that_is_not_written_has_no_progress_line(livecraft_paths: LivecraftPaths) -> None:
    record: ConsoleRecord = ConsoleRecord()
    stage: AnnounceStage = _stage(livecraft_paths, FakeTelegram.delivering(), _private())
    stage.run(_days(FIRST), None, (), StageProgress(record.console))
    assert record.lines == [msg.PROGRESS_ANNOUNCE.format(place=1, total=1, date="16.10.2026")]


def test_a_dry_run_has_no_announce_progress_lines(livecraft_paths: LivecraftPaths) -> None:
    record: ConsoleRecord = ConsoleRecord()
    fake: FakeTelegram = FakeTelegram.delivering()
    stage: AnnounceStage = _stage(livecraft_paths, fake, _private(), dry_run=True)
    assert _progress_run(stage, livecraft_paths, record, FIRST, NEXT_DAY).dry_run
    assert record.lines == [] and fake.calls == []


def test_without_a_console_the_announcements_say_nothing(
    livecraft_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(_stage(livecraft_paths, FakeTelegram.delivering(), _private()), livecraft_paths, FIRST, NEXT_DAY)
    assert capsys.readouterr().out == ""
