"""Отправка ответа в форму: тело POST, отказ без POST, повторы, подтверждение и страница ответа в logs\\."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.config.settings import FormSettings
from app.form.answers import AnswerValues
from app.form.book import FormBook
from app.form.failure import FormFailure, FormProblem
from app.form.key_form import KeyForm
from app.form.question import SectionJump
from app.form.route import PageRoute
from app.form.sender import FormConfirmation
from app.form.structure import FormStructure
from app.form.submission import FormSubmission
from app.observability.log_event import LogArea
from app.tests.fixtures.form import (
    FBZX,
    KYIV_WINTER,
    REFUSAL_PAGE,
    RESPONSE_URL,
    SHORT_URL,
    STREAM_KEY,
    SUCCESS_PAGE,
    YOUTUBE_SECTION_ID,
    FakeFormResponse,
    FakeForms,
    build_html,
    build_payload,
    default_items,
    form_settings,
    with_navigation,
)
from app.tests.fixtures.logs import LogCapture

START: datetime = datetime(2027, 3, 17, 19, 0, tzinfo=KYIV_WINTER)
STREAM_URL: str = "rtmp://A.rtmp.youtube.com/live2"
ENGLISH_CONFIRMATION: str = "Your response has been recorded."
LEGACY_CLASS_BODY: str = '<html><div class="freebirdFormviewerViewResponseConfirmationMessage"></div></html>'
EXPECTED_BODY: list[tuple[str, list[str]]] = [
    ("entry.1", ["Русский ( Russian)"]),
    ("entry.2", ["yt_ru"]),
    ("entry.3", ["17.03.2027 Дата стрима (время стрима указано в объявлении)"]),
    ("entry.4", ["You Tube"]),
    ("entry.5", [STREAM_KEY]),
    ("entry.6", ["rtmp://a.rtmp.youtube.com/live2/"]),
    ("fvv", ["1"]),
    ("pageHistory", ["0,1"]),
    ("fbzx", [FBZX]),
]


def _forms(*responses: str | FakeFormResponse, items: list[Any] | None = None) -> FakeForms:
    """Первый ответ — страница формы, дальше — ответы на POST."""
    return FakeForms.answering(build_html(build_payload(items)), *responses)


def _form(book: FormBook, settings: FormSettings | None = None) -> KeyForm:
    form: KeyForm | FormFailure = book.form_for(settings or form_settings())
    assert isinstance(form, KeyForm)
    return form


def _submission(form: KeyForm, start: datetime = START, stream_url: str | None = STREAM_URL) -> FormSubmission:
    values: AnswerValues = AnswerValues("ru", start, "yt_ru", STREAM_KEY if stream_url else None, stream_url)
    return FormSubmission(form=form, answers=form.answers(values), slot_id="17-03-2027_1900_ru", handle="yt_ru")


def _send(fake: FakeForms, tmp_path: Path, **options: Any) -> FormConfirmation | FormFailure:
    book: FormBook = fake.book(tmp_path / "logs")
    return book.sender.send(_submission(_form(book), **options))


def _failure(result: FormConfirmation | FormFailure) -> FormFailure:
    assert isinstance(result, FormFailure)
    return result


def test_body_contains_expected_entries_in_order(tmp_path: Path) -> None:
    fake: FakeForms = _forms(SUCCESS_PAGE)
    assert isinstance(_send(fake, tmp_path), FormConfirmation)
    [call] = fake.posts
    assert call.url == RESPONSE_URL                                     # язык страницы ответа просит программа
    assert list(call.body.items()) == EXPECTED_BODY                     # раздел Facebook (entry.7) не проходим
    assert call.options["headers"] == {"Accept-Language": "en"}
    assert [get.url for get in fake.gets] == [SHORT_URL]               # страница формы читается без hl=en


def test_stream_url_matches_ignoring_case_and_slash(tmp_path: Path) -> None:
    fake: FakeForms = _forms(SUCCESS_PAGE)
    assert isinstance(_send(fake, tmp_path, stream_url="RTMP://a.RTMP.youtube.com/live2/"), FormConfirmation)
    assert fake.posts[0].body["entry.6"] == ["rtmp://a.rtmp.youtube.com/live2/"]


def test_missing_date_option_stops_the_send(tmp_path: Path) -> None:
    """Нет варианта на дату — не отправляется ничего: значение вне вариантов запрещено."""
    fake: FakeForms = _forms(SUCCESS_PAGE)
    failure: FormFailure = _failure(_send(fake, tmp_path, start=datetime(2027, 3, 25, 19, 0, tzinfo=KYIV_WINTER)))
    assert failure.problem is FormProblem.MISSING_OPTION and "25.03.2027" in failure.detail
    assert fake.posts == []


def test_required_question_without_value_stops_the_send(tmp_path: Path) -> None:
    items: list[Any] = default_items()
    items.insert(7, [8, "Ещё один обязательный", None, 0, [[8, None, 1]]])   # раздел YouTube; программа не заполняет
    fake: FakeForms = _forms(SUCCESS_PAGE, items=items)
    failure: FormFailure = _failure(_send(fake, tmp_path))
    assert failure.problem is FormProblem.REQUIRED_MISSING and "Ещё один обязательный" in failure.detail
    assert fake.posts == []


def test_incomplete_answers_are_refused_without_post(tmp_path: Path) -> None:
    """Ответы без ключа и адреса (не опубликованы) и с адресом не из вариантов — отказ, POST нет."""
    fake: FakeForms = _forms(SUCCESS_PAGE)
    book: FormBook = fake.book(tmp_path)
    form: KeyForm = _form(book)
    assert _failure(book.sender.send(_submission(form, stream_url=None))).problem is FormProblem.REQUIRED_MISSING
    wrong_url: FormSubmission = _submission(form, stream_url="rtmp://b.rtmp.youtube.com/live2")
    assert _failure(book.sender.send(wrong_url)).problem is FormProblem.MISSING_OPTION
    assert fake.posts == []


def test_response_that_is_not_a_form_page_is_not_confirmed(tmp_path: Path) -> None:
    """Ответ 200, но это не страница формы — доставкой ключа не считается."""
    failure: FormFailure = _failure(_send(_forms("<html>что-то пошло не так</html>"), tmp_path))
    assert failure.problem is FormProblem.NOT_CONFIRMED
    assert failure.diagnostic is not None and "что-то пошло не так" in failure.diagnostic.read_text(encoding="utf-8")


def test_legacy_confirmation_class_is_not_a_confirmation(tmp_path: Path) -> None:
    """Класса freebirdFormviewerViewResponseConfirmationMessage в вёрстке Google больше нет."""
    assert _failure(_send(_forms(LEGACY_CLASS_BODY), tmp_path)).problem is FormProblem.NOT_CONFIRMED


def test_server_error_is_retried_by_the_policy(tmp_path: Path) -> None:
    """5xx: первое обращение и 4 повтора с паузами RetryPolicy, затем «форма недоступна»."""
    fake: FakeForms = _forms(FakeFormResponse("", status_code=500))
    assert _failure(_send(fake, tmp_path)).problem is FormProblem.TRANSPORT_FAILED
    assert len(fake.posts) == 5
    assert [int(delay) for delay in fake.sleeps] == [2, 4, 8, 16]


def test_server_error_then_success_is_confirmed(tmp_path: Path) -> None:
    fake: FakeForms = _forms(FakeFormResponse("", status_code=503), SUCCESS_PAGE)
    assert isinstance(_send(fake, tmp_path), FormConfirmation)
    assert len(fake.posts) == 2


def test_client_error_is_not_retried(tmp_path: Path) -> None:
    fake: FakeForms = _forms(FakeFormResponse("<html>нет</html>", status_code=400))
    failure: FormFailure = _failure(_send(fake, tmp_path))
    assert (failure.problem, failure.log_detail) == (FormProblem.NOT_CONFIRMED, "HTTP 400")
    assert len(fake.posts) == 1 and fake.sleeps == []


def test_structure_is_read_once_for_two_submissions(tmp_path: Path) -> None:
    fake: FakeForms = _forms(SUCCESS_PAGE)
    book: FormBook = fake.book(tmp_path)
    for start in (START, datetime(2027, 3, 18, 19, 0, tzinfo=KYIV_WINTER)):
        assert isinstance(book.sender.send(_submission(_form(book), start=start)), FormConfirmation)
    assert len(fake.gets) == 1 and len(fake.posts) == 2


def test_page_history_uses_page_index_not_section_id(tmp_path: Path) -> None:
    """Регрессия живого прогона planers 13-09-2026: было pageHistory=0,1281939289 и HTTP 400."""
    fake: FakeForms = _forms(SUCCESS_PAGE)
    _send(fake, tmp_path)
    assert str(YOUTUBE_SECTION_ID) not in fake.posts[0].body["pageHistory"][0]
    assert fake.posts[0].body["pageHistory"] == ["0,1"]


def test_unknown_section_id_falls_back_to_answered_pages(tmp_path: Path) -> None:
    items: list[Any] = default_items()
    items[3][4][0][1] = [["You Tube", None, 555], ["Facebook", None, 777]]
    fake: FakeForms = _forms(SUCCESS_PAGE, items=items)
    assert isinstance(_send(fake, tmp_path), FormConfirmation)
    assert fake.posts[0].body["pageHistory"] == ["0,1"]


def test_out_of_range_page_is_never_sent(tmp_path: Path) -> None:
    """Даже если разбор формы ошибся, номер вне 0..page_count-1 в pageHistory не попадает."""
    fake: FakeForms = _forms(SUCCESS_PAGE)
    book: FormBook = fake.book(tmp_path)
    parsed: KeyForm = _form(book)
    jumps: dict[str, dict[str, SectionJump]] = {
        "entry.4": {"You Tube": SectionJump(section_id=YOUTUBE_SECTION_ID, page_index=YOUTUBE_SECTION_ID)}
    }
    broken: FormStructure = with_navigation(parsed.structure, jumps)
    form: KeyForm = KeyForm.on_route(parsed.settings, PageRoute(broken))
    assert isinstance(book.sender.send(_submission(form)), FormConfirmation)
    assert fake.posts[0].body["pageHistory"] == ["0,1"]


@pytest.mark.parametrize(
    "visible_text",
    ["Вашу відповідь було записано.", "Ваш ответ записан.", "Válaszát rögzítettük."],
    ids=["ukrainian_live_03_01", "russian", "no_marker_matches"],
)
def test_success_page_is_confirmed_whatever_its_language(tmp_path: Path, visible_text: str) -> None:
    """Регрессия planers 13-09-2026 03:01: форма ответ записала, а страница пришла не на том языке."""
    assert SUCCESS_PAGE.count(ENGLISH_CONFIRMATION) == 1
    fake: FakeForms = _forms(SUCCESS_PAGE.replace(ENGLISH_CONFIRMATION, visible_text))
    with LogCapture.on(LogArea.FORM) as capture:
        result: FormConfirmation | FormFailure = _send(fake, tmp_path)
    assert isinstance(result, FormConfirmation)
    [line] = [message for message in capture.messages() if message.startswith("form_confirmed")]
    assert "entry_fields=0 fbzx=no form_page=yes" in line


def test_success_is_logged_with_the_signals_of_the_page(tmp_path: Path) -> None:
    with LogCapture.on(LogArea.FORM) as capture:
        _send(_forms(SUCCESS_PAGE), tmp_path)
    [line] = [message for message in capture.messages() if message.startswith("form_confirmed")]
    assert line == (
        "form_confirmed slot_id=17-03-2027_1900_ru handle=yt_ru http_status=200 entry_fields=0 fbzx=no form_page=yes "
        'marker="your response has been recorded"'
    )


def test_refusal_page_is_not_confirmed_and_logged_with_both_signals(tmp_path: Path) -> None:
    with LogCapture.on(LogArea.FORM) as capture:
        failure: FormFailure = _failure(_send(_forms(FakeFormResponse(REFUSAL_PAGE, status_code=400)), tmp_path))
    assert (failure.problem, failure.log_detail) == (FormProblem.NOT_CONFIRMED, "HTTP 400")
    assert failure.diagnostic is not None
    assert "This is a required question" in failure.diagnostic.read_text(encoding="utf-8")
    [line] = [message for message in capture.messages() if message.startswith("form_not_confirmed")]
    assert "http_status=400" in line and "fbzx=yes" in line and "marker=-" in line
    assert "TEST_Регистрация стрима (Stream registration)" in line
    assert any(message.startswith("form_send_failed problem=not_confirmed") for message in capture.messages())


def test_saved_response_page_and_log_hold_the_masked_key_not_the_key(tmp_path: Path) -> None:
    """Страница отказа повторяет введённые ответы, а logs\\ уходят в архив «Отправить логи»: ключ — только маской."""
    page: str = f"<html><script>FB_PUBLIC_LOAD_DATA_</script><input name=entry.5 value={STREAM_KEY}></html>"
    with LogCapture.on(LogArea.FORM) as capture:
        failure: FormFailure = _failure(_send(_forms(FakeFormResponse(page, status_code=400)), tmp_path))
    assert failure.diagnostic is not None
    saved: str = failure.diagnostic.read_text(encoding="utf-8")
    assert STREAM_KEY not in saved and "value=****-abcd" in saved
    assert not any(STREAM_KEY in message for message in capture.messages())
    assert any("stream_key=****-abcd" in message for message in capture.messages())
