"""Отказ формы: текст для человека называет форму и не содержит английской подробности лога."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import requests

from app.core.retry import AttemptFailure
from app.form.answers import AnswerValues, FormAnswers
from app.form.failure import FormEvent, FormFailure, FormProblem
from app.form.key_form import KeyForm
from app.form.structure import FormStructure
from app.tests.fixtures.form import KYIV_WINTER, SHORT_URL, STREAM_KEY, FakeFormResponse, FakeForms, build_html
from app.tests.fixtures.form import form_settings
from app.ui.messages import msg

FORM_NAME: str = "Регистрация стрима"


def _answer_failures(tmp_path: Path) -> list[FormFailure]:
    """Отказы ответов: варианта нет, обязательные без ответа, ключ ещё не опубликован."""
    form: KeyForm | FormFailure = FakeForms.answering(build_html()).book(tmp_path).form_for(form_settings())
    assert isinstance(form, KeyForm)
    late: datetime = datetime(2027, 3, 25, 19, 0, tzinfo=KYIV_WINTER)
    covered: datetime = datetime(2027, 3, 17, 19, 0, tzinfo=KYIV_WINTER)
    values: list[AnswerValues] = [
        AnswerValues("ru", late, "yt_ru", STREAM_KEY, "rtmp://a.rtmp.youtube.com/live2"),
        AnswerValues("ru", covered, "yt_ru", None, None),
    ]
    answers: list[FormAnswers] = [form.answers(value) for value in values]
    return [failure for failure in (item.failure for item in answers) if failure is not None]


def _read_failures(tmp_path: Path) -> list[FormFailure]:
    """Отказы чтения: нет структуры, 404, обрыв связи."""
    pages: list[FakeFormResponse | Exception | str] = [
        "<html></html>", FakeFormResponse("", status_code=404), requests.ConnectionError("x")
    ]
    failures: list[FormFailure] = []
    for page in pages:
        read: FormStructure | FormFailure = FakeForms.answering(page).reader(tmp_path).read(SHORT_URL)
        assert isinstance(read, FormFailure)
        failures.append(read)
    return failures


def test_no_human_text_holds_the_log_detail(tmp_path: Path) -> None:
    failures: list[FormFailure] = [
        *_answer_failures(tmp_path),
        *_read_failures(tmp_path),
        FormFailure.of_status(FormProblem.NOT_CONFIRMED, FORM_NAME, 400),
        FormFailure.of_attempt(FORM_NAME, AttemptFailure(FormProblem.TRANSPORT_FAILED, True, error_name="Timeout")),
    ]
    assert {failure.problem for failure in failures} == set(FormProblem)
    for failure in failures:
        assert failure.log_detail and failure.log_detail not in failure.human
        assert failure.form in failure.human


@pytest.mark.parametrize("problem", list(FormProblem))
def test_every_problem_names_the_form_and_its_detail(problem: FormProblem) -> None:
    failure: FormFailure = FormFailure(problem=problem, form=FORM_NAME, detail="деталь", log_detail="detail")
    assert failure.human == msg.FORM_PROBLEMS[problem.value].format(
        form=FORM_NAME, detail=msg.FORM_PROBLEM_DETAIL.format(detail="деталь")
    )
    assert "«Регистрация стрима»" in failure.human and "(деталь)" in failure.human


def test_status_is_named_to_people_and_the_error_only_in_the_log() -> None:
    by_status: FormFailure = FormFailure.of_status(FormProblem.TRANSPORT_FAILED, FORM_NAME, 404)
    assert by_status.human == "Форма ключей «Регистрация стрима» недоступна (код ответа 404)."
    network: FormFailure = FormFailure.of_attempt(
        FORM_NAME, AttemptFailure(FormProblem.TRANSPORT_FAILED, True, error_name="ConnectTimeout")
    )
    assert network.human == "Форма ключей «Регистрация стрима» недоступна."
    assert network.event(FormEvent.UNREADABLE).text == (
        'form_unreadable problem=transport_failed form="Регистрация стрима" '
        'detail="request failed: ConnectTimeout" saved=-'
    )
