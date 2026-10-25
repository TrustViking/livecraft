from __future__ import annotations

import io
from datetime import date

import pytest

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
from app.ui.console import Console, StepCount


def _item() -> PlannedBroadcast:
    return planned_of(slot_of(TOMORROW, "uk"))


def _every_step(progress: RunProgress, item: PlannedBroadcast) -> None:
    progress.channel_read_started(item.channel, StepCount(1, 2))
    progress.channel_read_done(item.channel, 3, StepCount(1, 2))
    progress.plan_broadcasts((item,), (item,))
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
        "Эфиры на каналах 1 из 2: «yt_ua» @yt_ua — запрос запланированных",
        "Эфиры на каналах 1 из 2: «yt_ua» @yt_ua — запланировано 3",
        "Эфиры YouTube 1 из 1: «yt_ua» @yt_ua — создание 17.03.2027 19:00 uk",
        "Эфиры YouTube 1 из 1: «yt_ua» @yt_ua — исправление 17.03.2027 19:00 uk",
        "Эфиры YouTube 1 из 1: «yt_ua» @yt_ua — ключ в форму 17.03.2027 19:00 uk",
        msg.PROGRESS_REPORT,
    ]


def test_broadcast_lines_name_the_channel_after_the_login_phase() -> None:
    """Канал, выровненный при входе, звучит новыми названием и ником (§14 решение 25)."""
    record: ConsoleRecord = ConsoleRecord()
    item: PlannedBroadcast = _item()
    renamed: Channel = channel_object(changed_channel(channel_of(), account_name="Новое название", handle="@new_ua"))
    item.admission.channel = renamed
    progress: RunProgress = RunProgress(record.console)
    progress.plan_broadcasts((item,), (item,))
    progress.key_send_started(item)
    assert record.lines == ["Эфиры YouTube 1 из 1: «Новое название» @new_ua — ключ в форму 17.03.2027 19:00 uk"]


def test_broadcast_steps_count_the_objects_with_an_action() -> None:
    """Шаг этапа «эфиры» — объект с действием: последняя строка этапа читается как его итог."""
    record: ConsoleRecord = ConsoleRecord()
    first, second = _item(), planned_of(slot_of(TOMORROW, "ru"))
    progress: RunProgress = RunProgress(record.console)
    progress.plan_broadcasts((first, second), (first, second))
    progress.broadcast_step_started(second, BroadcastStep.FIX)
    assert record.lines == ["Эфиры YouTube 2 из 2: «yt_ua» @yt_ua — исправление 17.03.2027 19:00 ru"]


def test_an_object_whose_action_shows_up_on_the_way_joins_the_count_in_its_place() -> None:
    """Правка настроек видео открывается только по ходу: объект встаёт в счёт на своё место, «N» растёт."""
    record: ConsoleRecord = ConsoleRecord()
    first, middle, last = _item(), planned_of(slot_of(TOMORROW, "ru")), planned_of(slot_of(TOMORROW, "en"))
    progress: RunProgress = RunProgress(record.console)
    progress.plan_broadcasts((first, middle, last), (first, last))
    progress.broadcast_step_started(first, BroadcastStep.CREATE)
    progress.broadcast_step_started(middle, BroadcastStep.FIX)
    progress.broadcast_step_started(last, BroadcastStep.CREATE)
    counts: list[str] = [line.split(":")[0] for line in record.lines]
    assert counts == ["Эфиры YouTube 1 из 2", "Эфиры YouTube 2 из 3", "Эфиры YouTube 3 из 3"]


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
    assert record.lines == ["Пакетов прочитано: 3; эфиров — 3, из них языков каналов — 2."]


class TerminalStream(io.StringIO):
    """Поток-терминал: так консоль видит окно cmd или PowerShell."""

    def isatty(self) -> bool:
        return True


def test_in_a_terminal_steps_share_one_line_and_the_form_dates_stay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаги эфиров — одна строка хода поверх прежней; строка дат формы — сообщение и остаётся (§14 решение 78)."""
    monkeypatch.setenv("COLUMNS", "100")
    stream: TerminalStream = TerminalStream()
    progress: RunProgress = RunProgress(Console(out=stream, err=stream))
    item: PlannedBroadcast = _item()
    progress.channel_read_started(item.channel, StepCount(1, 1))
    progress.channel_read_done(item.channel, 3, StepCount(1, 1))
    progress.form_dates_checked(_coverage(is_checkable=True))
    rows: list[str] = stream.getvalue().split("\n")
    assert len(rows[0].split("\r")) == 3 and rows[1:] == [_coverage(is_checkable=True).line, ""]
