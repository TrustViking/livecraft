"""Объект-форма на настоящей странице тренировочной формы (app\\tests\\data\\form\\form_response_refusal.html).

Страница отказа — перерисованная форма целиком: в ней тот же FB_PUBLIC_LOAD_DATA_, что у viewform.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config.settings import FormQuestion
from app.form.answers import AnswerValues, FormAnswers, MissingAnswer
from app.form.failure import FormFailure, FormProblem
from app.form.key_form import KeyForm
from app.form.question import PageQuestion
from app.form.structure import FormStructure
from app.observability.log_event import LogArea
from app.tests.fixtures.form import REFUSAL_PAGE, SHORT_URL, STREAM_KEY, TRAINING_FORM_TITLE, FakeForms, build_html
from app.tests.fixtures.form import form_settings
from app.tests.fixtures.logs import LogCapture

KYIV: timezone = timezone(timedelta(hours=3))
START: datetime = datetime(2026, 9, 13, 19, 0, tzinfo=KYIV)
STREAM_URL: str = "rtmp://a.rtmp.youtube.com/live2"
LANGUAGE_ENTRY: str = "entry.1596786721"
NAME_ENTRY: str = "entry.861880560"
DATE_ENTRY: str = "entry.1569784614"
PLATFORM_ENTRY: str = "entry.777814017"
KEY_ENTRY: str = "entry.1403158871"
URL_ENTRY: str = "entry.721693817"


@pytest.fixture
def structure(tmp_path: Path) -> FormStructure:
    read: FormStructure | FormFailure = FakeForms.answering(REFUSAL_PAGE).reader(tmp_path).read(SHORT_URL)
    assert isinstance(read, FormStructure)
    return read


@pytest.fixture
def form(structure: FormStructure) -> KeyForm:
    return KeyForm.build(form_settings(), structure)


def _values(
    language: str = "uk",
    start: datetime = START,
    stream_key: str | None = STREAM_KEY,
    stream_url: str | None = STREAM_URL,
) -> AnswerValues:
    return AnswerValues(language, start, "Kanal.X", stream_key, stream_url)


def _sent(answers: FormAnswers) -> dict[str, str]:
    return {answer.entry_id: answer.value for answer in answers.answers}


def test_questions_are_matched_once_by_the_titles_of_the_settings(form: KeyForm) -> None:
    language: PageQuestion | None = form.questions[FormQuestion.LANGUAGE]
    assert language is not None and language.entry_id == LANGUAGE_ENTRY
    assert set(form.questions) == {
        FormQuestion.LANGUAGE,
        FormQuestion.ACCOUNT_NAME,
        FormQuestion.DATE,
        FormQuestion.PLATFORM,
        FormQuestion.STREAM_KEY,
        FormQuestion.STREAM_URL,
    }
    assert "13.09.2026" in form.accepted_dates and "11.09.2026" in form.accepted_dates
    assert form.accepted_languages[:3] == ("uk", "ru", "en")
    assert len(form.stream_url_options) == 2


def test_full_answer_for_the_youtube_branch(form: KeyForm) -> None:
    answers: FormAnswers = form.answers(_values())
    assert answers.is_complete and answers.failure is None
    assert _sent(answers) == {
        LANGUAGE_ENTRY: "Украинский ( Ukranian)",
        NAME_ENTRY: "Kanal.X",                                  # текстовый вопрос — как есть
        DATE_ENTRY: "13.09.2026 Дата стрима (время стрима указано в объявлении)",
        PLATFORM_ENTRY: "You Tube",
        KEY_ENTRY: STREAM_KEY,
        URL_ENTRY: "rtmp://A.rtmp.youtube.com/live2/",           # другой регистр и слэш — вариант формы
    }
    assert answers.pages == (0, 1)                               # раздел YouTube; Facebook и прочие — нет
    assert [(answer.entry_id, answer.title) for answer in answers.answers][0] == (
        LANGUAGE_ENTRY, "Язык стрима ( Language of stream)"
    )


def test_date_without_option_is_missing(form: KeyForm) -> None:
    answers: FormAnswers = form.answers(_values(start=datetime(2027, 3, 18, 19, 0, tzinfo=KYIV)))
    [missing] = answers.missing
    assert (missing.field, missing.problem, missing.detail) == (
        FormQuestion.DATE, FormProblem.MISSING_OPTION, "Время стрима ( Stream time ): 18.03.2027"
    )
    assert (missing.question, missing.value) == ("Время стрима ( Stream time )", "18.03.2027")
    failure: FormFailure | None = answers.failure
    assert failure is not None and failure.problem is FormProblem.MISSING_OPTION
    assert failure.form == TRAINING_FORM_TITLE
    assert DATE_ENTRY not in _sent(answers)


def test_pages_by_navigation_are_logged_once_per_form(form: KeyForm) -> None:
    """Прогон planers 18-09-2026: 57 одинаковых строк за запуск — теперь одна, DEBUG; разделы у всех ответов те же."""
    with LogCapture.on(LogArea.FORM) as capture:
        pages: set[tuple[int, ...]] = {form.answers(_values()).pages for _ in range(5)}
        pages.add(form.answers(_values(stream_key=None, stream_url=None)).pages)
    assert pages == {(0, 1)}
    records: list[logging.LogRecord] = [
        record for record in capture.records if record.getMessage().startswith("form_pages_by_navigation ")
    ]
    assert len(records) == 1 and records[0].levelno == logging.DEBUG


def test_same_link_for_other_settings_does_not_repeat_the_pages_line(form: KeyForm) -> None:
    other: KeyForm = form.for_settings(form_settings(date_format="%d.%m.%y"))
    with LogCapture.on(LogArea.FORM) as capture:
        form.answers(_values())
        other.answers(_values())
        form.for_settings(form.settings).answers(_values())
    assert sum(1 for message in capture.messages() if message.startswith("form_pages_by_navigation ")) == 1


def test_other_settings_get_their_own_option_texts_on_the_same_structure(form: KeyForm) -> None:
    """Пакет с той же ссылкой, но своими текстами вариантов: структура одна, ответ — по его текстам."""
    values: dict[str, dict[str, str]] = {**form.settings.values, "language": {"uk": "Русский ( Russian)"}}
    other: KeyForm = form.for_settings(form_settings(values=values))
    assert other.structure is form.structure and other.route is form.route
    assert _sent(other.answers(_values()))[LANGUAGE_ENTRY] == "Русский ( Russian)"
    assert _sent(form.answers(_values()))[LANGUAGE_ENTRY] == "Украинский ( Ukranian)"


def test_time_is_not_a_missing_field(form: KeyForm) -> None:
    """Времени в форме нет: 13.09.2026 23:30 и 00:10 — один вариант даты, незаполненных полей нет."""
    late: FormAnswers = form.answers(_values(start=datetime(2026, 9, 13, 23, 30, tzinfo=KYIV)))
    assert late.is_complete and _sent(late)[DATE_ENTRY].startswith("13.09.2026")


def test_language_without_option_text_in_the_settings_is_missing(form: KeyForm) -> None:
    answers: FormAnswers = form.answers(_values(language="de"))
    assert [(item.field, item.detail) for item in answers.missing] == [
        (FormQuestion.LANGUAGE, "Язык стрима ( Language of stream): -")
    ]


def test_stream_url_not_in_options_is_missing(form: KeyForm) -> None:
    answers: FormAnswers = form.answers(_values(stream_url="rtmp://b.rtmp.youtube.com/live2"))
    assert [(item.field, item.problem) for item in answers.missing] == [
        (FormQuestion.STREAM_URL, FormProblem.MISSING_OPTION)
    ]


def test_key_and_url_before_publication_are_pending_not_missing(form: KeyForm) -> None:
    answers: FormAnswers = form.answers(_values(stream_key=None, stream_url=None))
    assert answers.missing == ()
    assert answers.pending == ("You Tube Stream Key", "Stream-URL (YT)")
    assert not answers.is_complete
    assert answers.pages == (0, 1)
    assert KEY_ENTRY not in _sent(answers) and URL_ENTRY not in _sent(answers)
    failure: FormFailure | None = answers.failure
    assert failure is not None and failure.problem is FormProblem.REQUIRED_MISSING
    assert failure.detail == "You Tube Stream Key, Stream-URL (YT)"


def test_required_question_without_answer(structure: FormStructure) -> None:
    """Вопрос «Название канала» в настройках не назван — в форме он обязательный: обязательный без ответа."""
    fields: dict[str, str | None] = {**form_settings().fields, "account_name": None}
    form: KeyForm = KeyForm.build(form_settings(fields=fields), structure)
    answers: FormAnswers = form.answers(_values())
    missing: list[MissingAnswer] = list(answers.missing)
    assert [(item.problem, item.detail) for item in missing] == [
        (FormProblem.REQUIRED_MISSING, "Название канала ( Channel name)")
    ]


def test_display_name_is_the_title_or_else_the_link(tmp_path: Path, form: KeyForm) -> None:
    assert form.display_name == TRAINING_FORM_TITLE
    untitled: FormStructure | FormFailure = FakeForms.answering(build_html()).reader(tmp_path).read(SHORT_URL)
    assert isinstance(untitled, FormStructure)
    assert KeyForm.build(form_settings(), untitled).display_name == SHORT_URL


def test_ready_line_names_dates_languages_and_stream_urls(tmp_path: Path) -> None:
    structure: FormStructure | FormFailure = FakeForms.answering(build_html()).reader(tmp_path).read(SHORT_URL)
    assert isinstance(structure, FormStructure)
    line: str = KeyForm.build(form_settings(), structure).ready_event.text
    assert line == (
        'form_ready url=https://docs.google.com/forms/d/e/ABC/viewform title=- questions=7 pages=3 '
        "dates=17.03.2027,18.03.2027 languages=ru,en stream_urls=2"
    )
