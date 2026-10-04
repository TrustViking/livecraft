from __future__ import annotations

from datetime import date

from app.form.coverage import DateCoverage
from app.packages.package_line import PackageLine, PackageLines, PackageLineStatus
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.progress import BroadcastStep, RunProgress
from app.platforms.channel import Channel
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.form import TRAINING_FORM_TITLE
from app.tests.fixtures.pipeline import TOMORROW, channel_object, planned_of, slot_of
from app.tests.fixtures.platform import changed_channel, channel_of
from app.ui import messages_ru as msg


def _item() -> PlannedBroadcast:
    return planned_of(slot_of(TOMORROW, "uk"))


def _every_step(progress: RunProgress, item: PlannedBroadcast) -> None:
    progress.channel_read_started(item.channel)
    progress.channel_read_done(item.channel, 3)
    progress.broadcast_step_started(item, BroadcastStep.CREATE)
    progress.broadcast_step_started(item, BroadcastStep.FIX)
    progress.key_send_started(item)
    progress.report_started()


def _coverage(*, is_checkable: bool, missing: tuple[date, ...] = (), question: str = "Время стрима") -> DateCoverage:
    return DateCoverage(
        form_url="https://forms.gle/x",
        form_name=TRAINING_FORM_TITLE,
        question_title=question,
        is_checkable=is_checkable,
        wanted=("17.03.2027", "18.03.2027", "19.03.2027") if is_checkable else (),
        missing=tuple(value.strftime("%d.%m.%Y") for value in missing),
        missing_dates=missing,
        accepted_count=5,
    )


def test_progress_without_console_prints_nothing() -> None:
    record: ConsoleRecord = ConsoleRecord()
    _every_step(RunProgress(), _item())
    RunProgress().form_dates_checked(_coverage(is_checkable=True, missing=(date(2027, 3, 18),)))
    assert record.lines == []


def test_progress_prints_one_line_per_step_with_the_human_date() -> None:
    record: ConsoleRecord = ConsoleRecord()
    _every_step(RunProgress(record.console), _item())
    assert record.lines == [
        "Канал «yt_ua» @yt_ua: запрос запланированных эфиров.",
        "Канал «yt_ua» @yt_ua: запланированных эфиров — 3.",
        "Канал «yt_ua» @yt_ua: создание эфира 17.03.2027 19:00 uk.",
        "Канал «yt_ua» @yt_ua: исправление эфира 17.03.2027 19:00 uk.",
        "Канал «yt_ua» @yt_ua: отправка ключа в форму — эфир 17.03.2027 19:00 uk.",
        msg.PROGRESS_REPORT,
    ]


def test_broadcast_lines_name_the_channel_after_the_login_phase() -> None:
    """Канал, выровненный при входе, звучит новыми названием и ником (§14 решение 25)."""
    record: ConsoleRecord = ConsoleRecord()
    item: PlannedBroadcast = _item()
    renamed: Channel = channel_object(changed_channel(channel_of(), account_name="Новое название", handle="@new_ua"))
    item.admission.channel = renamed
    RunProgress(record.console).key_send_started(item)
    assert record.lines == ["Канал «Новое название» @new_ua: отправка ключа в форму — эфир 17.03.2027 19:00 uk."]


def test_form_dates_are_said_in_three_cases_and_not_without_a_date_question() -> None:
    record: ConsoleRecord = ConsoleRecord()
    progress: RunProgress = RunProgress(record.console)
    progress.form_dates_checked(_coverage(is_checkable=True))
    progress.form_dates_checked(_coverage(is_checkable=False))
    progress.form_dates_checked(_coverage(is_checkable=True, missing=(date(2027, 3, 18), date(2027, 3, 19))))
    progress.form_dates_checked(_coverage(is_checkable=False, question=""))
    form: str = TRAINING_FORM_TITLE
    assert record.lines == [
        msg.FORM_DATES_OK.format(form=form, wanted=3, accepted=5),
        msg.FORM_DATES_ANY.format(form=form),
        msg.FORM_DATES_MISSING.format(form=form, dates="18.03.2027, 19.03.2027"),
    ]


def test_the_packages_line_counts_the_accepted_packages() -> None:
    record: ConsoleRecord = ConsoleRecord()
    lines: PackageLines = PackageLines((
        PackageLine("a.bcast", PackageLineStatus.ACCEPTED, slots_total=3, slots_mine=2),
        PackageLine("b.bcast", PackageLineStatus.ALL_PAST),
        PackageLine("c.bcast", PackageLineStatus.DAMAGED, detail="не ZIP-архив (x)"),
    ))
    RunProgress(record.console).packages_read(lines)
    RunProgress().packages_read(lines)
    assert record.lines == ["Пакетов прочитано: 3; слотов — 3, из них языков каналов — 2."]
