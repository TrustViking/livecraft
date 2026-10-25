"""Предстартовая проверка дат формы: в тренировочной форме есть 11.09.2026, 12.09.2026, 13.09.2026 и 17.03.2027."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.config.settings import FormQuestion
from app.form.answers import AnswerValues
from app.form.coverage import DateCoverage
from app.form.failure import FormFailure, FormProblem
from app.form.key_form import KeyForm
from app.form.question import PageQuestion
from app.form.structure import FormStructure
from app.observability.log_event import LogArea
from app.tests.fixtures.form import (
    REFUSAL_PAGE,
    SHORT_URL,
    STREAM_KEY,
    TRAINING_FORM_TITLE,
    FakeForms,
    as_text_question,
    build_html,
    build_payload,
    default_items,
    form_settings,
    question,
    with_question,
)
from app.tests.fixtures.logs import LogCapture
from app.ui.messages import msg

KYIV: timezone = timezone(timedelta(hours=3))


@pytest.fixture
def form(tmp_path: Path) -> KeyForm:
    structure: FormStructure | FormFailure = FakeForms.answering(REFUSAL_PAGE).reader(tmp_path).read(SHORT_URL)
    assert isinstance(structure, FormStructure)
    return KeyForm.build(form_settings(), structure)


def _start(day: int, month: int = 9, year: int = 2026, hour: int = 19) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=KYIV)


def test_coverage_is_complete_when_every_date_has_an_option(form: KeyForm) -> None:
    coverage: DateCoverage = form.date_coverage([_start(13), _start(11), _start(17, 3, 2027)])
    assert coverage.is_checkable and coverage.is_complete
    assert coverage.wanted == ("11.09.2026", "13.09.2026", "17.03.2027")
    assert coverage.missing == () and coverage.missing_dates == () and coverage.missing_text == ""
    assert coverage.accepted_count == len(form.accepted_dates)
    assert coverage.question_title == form_settings().fields["date"]
    assert (coverage.form_url, coverage.form_name) == (SHORT_URL, TRAINING_FORM_TITLE)


def test_coverage_lists_missing_dates_in_order_for_people(form: KeyForm) -> None:
    coverage: DateCoverage = form.date_coverage([_start(20), _start(13), _start(14)])
    assert not coverage.is_complete
    assert coverage.wanted == ("13.09.2026", "14.09.2026", "20.09.2026")
    assert coverage.missing == ("14.09.2026", "20.09.2026")
    assert coverage.missing_dates == (date(2026, 9, 14), date(2026, 9, 20))
    assert coverage.missing_text == "14.09.2026, 20.09.2026"


def test_one_date_of_several_slots_counts_once(form: KeyForm) -> None:
    coverage: DateCoverage = form.date_coverage([_start(14, hour=19), _start(14, hour=21), _start(13)])
    assert coverage.wanted == ("13.09.2026", "14.09.2026")
    assert coverage.missing == ("14.09.2026",)


def test_text_date_question_accepts_any_date(form: KeyForm) -> None:
    date_question: PageQuestion | None = form.questions[FormQuestion.DATE]
    assert date_question is not None
    structure: FormStructure = with_question(form.structure, date_question, as_text_question(date_question))
    coverage: DateCoverage = KeyForm.build(form.settings, structure).date_coverage([_start(20)])
    assert not coverage.is_checkable and coverage.is_complete and coverage.missing == ()
    assert coverage.question_title == date_question.title
    assert coverage.line == msg.FORM_DATES_ANY.format(form=TRAINING_FORM_TITLE)


def test_without_date_question_nothing_is_checked(form: KeyForm) -> None:
    fields: dict[str, str | None] = {**form.settings.fields, "date": None}
    without_date: KeyForm = KeyForm.build(form_settings(fields=fields), form.structure)
    coverage: DateCoverage = without_date.date_coverage([_start(20)])
    assert coverage.question_title == "" and not coverage.is_checkable and coverage.missing == ()
    assert coverage.line is None
    assert coverage.event.text == f"form_dates_not_checked url={SHORT_URL} reason=no_date_question"


def test_coverage_agrees_with_answers(form: KeyForm) -> None:
    """Проверка и отправка сопоставляют даты одним правилом: недостающая дата — «варианта нет», и наоборот."""
    starts: list[datetime] = [_start(11), _start(14), _start(17, 3, 2027), _start(18, 3, 2027)]
    coverage: DateCoverage = form.date_coverage(starts)
    for start in starts:
        values: AnswerValues = AnswerValues("uk", start, "Kanal.X", STREAM_KEY, "rtmp://a.rtmp.youtube.com/live2")
        is_missing: bool = any(
            item.field is FormQuestion.DATE and item.problem is FormProblem.MISSING_OPTION
            for item in form.answers(values).missing
        )
        assert is_missing == (start.strftime(form.settings.date_format) in coverage.missing)
    assert coverage.missing == ("14.09.2026", "18.03.2027")


def test_console_line_names_the_form_and_missing_dates_for_people(form: KeyForm) -> None:
    coverage: DateCoverage = form.date_coverage([_start(17, 3, 2027), _start(18, 3, 2027)])
    assert coverage.line == msg.FORM_DATES_MISSING.format(form=TRAINING_FORM_TITLE, dates="18.03.2027")
    complete: DateCoverage = form.date_coverage([_start(17, 3, 2027)])
    accepted: int = len(form.accepted_dates)
    assert complete.line == msg.FORM_DATES_OK.format(form=TRAINING_FORM_TITLE, wanted=1, accepted=accepted)


def test_missing_date_in_the_console_line_is_written_for_people(tmp_path: Path) -> None:
    """Формат даты формы — %d.%m.%Y, в строке консоли — тоже 17.03.2027 (решение 31), а не 17-03-2027."""
    items: list[Any] = default_items()
    items[2] = question(3, "Время стрима ( Stream time )", 2, [["18.03.2027 Дата стрима"]])
    structure: FormStructure | FormFailure = (
        FakeForms.answering(build_html(build_payload(items))).reader(tmp_path).read(SHORT_URL)
    )
    assert isinstance(structure, FormStructure)
    coverage: DateCoverage = KeyForm.build(form_settings(), structure).date_coverage([_start(17, 3, 2027)])
    assert coverage.missing_dates == (date(2027, 3, 17),)
    assert coverage.line == (
        f"Форма ключей «{SHORT_URL}»: нет дат 17.03.2027 — эфиры на эти даты не создаются, "
        "ключи стримеру не уйдут."
    )


def test_checked_dates_are_logged(form: KeyForm) -> None:
    coverage: DateCoverage = form.date_coverage([_start(13), _start(14)])
    with LogCapture.on(LogArea.FORM) as capture:
        coverage.log()
    assert capture.messages() == [
        f'form_dates_checked url={SHORT_URL} title="{TRAINING_FORM_TITLE}" '
        'question="Время стрима ( Stream time )" wanted=2 missing=1 dates=14.09.2026'
    ]
