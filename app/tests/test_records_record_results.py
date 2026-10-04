from __future__ import annotations

from app.form.answers import FormAnswer
from app.form.question import PageQuestion, QuestionKind
from app.records.record_results import ConfirmedAnswer, RecordResults, UnconfirmedSends
from app.tests.fixtures.records import ANSWERS, FORM_URL, KEY, OTHER_KEY


def test_a_confirmed_answer_is_taken_from_the_answer_the_form_confirmed() -> None:
    question: PageQuestion = PageQuestion(
        title="Время стрима ( Stream time )", entry_id="entry.7", is_required=True, kind=QuestionKind.CHOICE,
        options=("17.03.2027",), page_index=1,
    )
    answer: ConfirmedAnswer = ConfirmedAnswer.of(FormAnswer(question=question, value="17.03.2027"))
    assert answer == ConfirmedAnswer("entry.7", "Время стрима ( Stream time )", "17.03.2027")


def test_unconfirmed_sends_count_the_current_key_in_its_form() -> None:
    """Счёт неподтверждённых отправок (§14 решение 49) — про этот ключ в этой форме; другой ключ, другая форма, ключа
    нет — ни одной отправки; ещё одна отправка того же ключа — +1, другого — счёт заново."""
    once: RecordResults = RecordResults().with_unconfirmed_send(KEY, FORM_URL)
    twice: RecordResults = once.with_unconfirmed_send(KEY, FORM_URL)
    assert (once.unconfirmed_sends(KEY, FORM_URL), twice.unconfirmed_sends(KEY, FORM_URL)) == (1, 2)
    assert twice.unconfirmed_sends(OTHER_KEY, FORM_URL) == 0
    assert twice.unconfirmed_sends(KEY, "https://docs.google.com/forms/d/e/OTHER/formResponse") == 0
    assert twice.unconfirmed_sends(None, FORM_URL) == 0 and RecordResults().unconfirmed_sends(KEY, FORM_URL) == 0
    assert twice.with_unconfirmed_send(OTHER_KEY, FORM_URL).unconfirmed == UnconfirmedSends(OTHER_KEY, FORM_URL, 1)


def test_confirms_key_is_about_the_key_only() -> None:
    results: RecordResults = RecordResults(confirmed_stream_key=KEY)
    assert results.confirms_key(KEY)
    assert not results.confirms_key(OTHER_KEY) and not results.confirms_key(None)


def test_results_round_trip_through_data() -> None:
    results: RecordResults = RecordResults(
        broadcast_id="B1", stream_key=KEY, confirmed_stream_key=KEY, confirmed_form_url=FORM_URL,
        confirmed_answers=ANSWERS, thumbnail_broadcast_id="B1", thumbnail_set_at="17-09-2026 17:36",
        unconfirmed=UnconfirmedSends(OTHER_KEY, FORM_URL, 2),
    )
    data: dict[str, object] = results.to_data()
    assert data["confirmed_answers"] == [{"entry_id": "entry.1", "title": ANSWERS[0].title, "value": ANSWERS[0].value},
                                         {"entry_id": "entry.2", "title": ANSWERS[1].title, "value": ANSWERS[1].value},
                                         {"entry_id": "entry.5", "title": ANSWERS[2].title, "value": KEY}]
    assert data["unconfirmed"] == {"stream_key": OTHER_KEY, "form_url": FORM_URL, "count": 2}
    assert RecordResults.from_data(data) == results


def test_reading_is_tolerant_to_unknown_missing_and_wrong_values() -> None:
    raw: dict[str, object] = {
        "stream_key": KEY, "new_field": "x", "confirmed_at": 5, "is_bootstrap": True,
        "unconfirmed": {"stream_key": KEY, "form_url": FORM_URL, "count": "2"},
        "confirmed_answers": [{"entry_id": "entry.1", "value": "ru"}, {"entry_id": 2, "value": "x"}, "bad"],
    }
    assert RecordResults.from_data(raw) == RecordResults(
        stream_key=KEY, confirmed_answers=(ConfirmedAnswer("entry.1", "", "ru"),)
    )
    assert RecordResults.from_data({"confirmed_answers": "x"}) == RecordResults()
    assert RecordResults.from_data("x") == RecordResults() == RecordResults.from_data(None)
