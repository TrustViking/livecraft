"""Выбор варианта ответа: текст, дата по началу варианта, адрес потока без регистра и «/» в конце."""
from __future__ import annotations

from app.form.question import OptionChoice, PageQuestion, QuestionKind


def _choice(*options: str) -> PageQuestion:
    return PageQuestion("Вопрос", "entry.1", True, QuestionKind.CHOICE, options, 0)


TEXT: PageQuestion = PageQuestion("Вопрос", "entry.2", True, QuestionKind.TEXT, (), 0)


def test_text_option_is_taken_only_when_the_form_has_it() -> None:
    question: PageQuestion = _choice("Русский ( Russian)")
    assert question.option_for_text("Русский ( Russian)") == OptionChoice.of("Русский ( Russian)")
    assert question.option_for_text("Русский") == OptionChoice(chosen=None, wanted="Русский")
    assert question.option_for_text(None) == OptionChoice(chosen=None, wanted="-")
    assert TEXT.option_for_text("что угодно").chosen == "что угодно"


def test_date_option_is_the_first_option_starting_with_the_date() -> None:
    question: PageQuestion = _choice("16.03.2027 Дата", "17.03.2027 Дата стрима", "17.03.2027 ещё")
    assert question.date_option("17.03.2027").chosen == "17.03.2027 Дата стрима"
    assert question.date_option("18.03.2027") == OptionChoice(chosen=None, wanted="18.03.2027")
    assert TEXT.date_option("18.03.2027").chosen == "18.03.2027"


def test_url_option_ignores_case_edges_and_the_trailing_slash_and_sends_the_form_text() -> None:
    question: PageQuestion = _choice("rtmp://a.rtmp.youtube.com/live2/")
    assert question.url_option(" RTMP://A.rtmp.youtube.com/live2 ").chosen == "rtmp://a.rtmp.youtube.com/live2/"
    assert question.url_option("rtmp://b.rtmp.youtube.com/live2").chosen is None
    assert question.url_option("") == OptionChoice(chosen=None, wanted="-")
    assert TEXT.url_option("rtmp://x/").chosen == "rtmp://x/"
