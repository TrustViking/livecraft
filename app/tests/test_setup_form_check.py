"""Проверка формы ключей без окна (app\\setup\\panels\\form_check.py, CLAUDE.md §8.2 п.9, §14 решение 68): форма
читается тем же кодом, что у запуска; проверяется только сама форма — читается ли и есть ли в ней нужные вопросы.
К Google тесты не ходят: страница формы — тренировочная форма в раскладке FB_PUBLIC_LOAD_DATA_."""
from __future__ import annotations

from typing import Any

from app.config.files import SettingsFile
from app.config.settings import FormQuestion
from app.form.failure import FormFailure
from app.form.key_form import KeyForm
from app.paths import LivecraftPaths
from app.run.mode import RunPart
from app.setup.panels.form_check import FormCheck, FormVerdict
from app.tests.fixtures.broadcasts import FORM_TITLE_GAP
from app.tests.fixtures.form import (
    SHORT_URL,
    TRAINING_FORM_TITLE,
    FakeForms,
    build_html,
    build_payload,
    default_items,
    question,
)
from app.tests.fixtures.settings import set_form_url
from app.ui import messages_ru as msg

DATE_TITLE: str = "Время стрима ( Stream time )"
STREAM_URL_TITLE: str = "Stream-URL (YT)"


def _page(items: list[Any] | None = None) -> str:
    """Страница тренировочной формы с заголовком: вопросы — `items` (по умолчанию все)."""
    payload: list[Any] = build_payload(items if items is not None else default_items())
    payload[1].extend([None] * FORM_TITLE_GAP + [TRAINING_FORM_TITLE])
    return build_html(payload)


def _check(paths: LivecraftPaths, forms: FakeForms) -> FormCheck:
    return FormCheck(paths=paths, open_forms=lambda clock: forms.book(paths.logs_dir))


def _run(paths: LivecraftPaths, page: str, said: list[str] | None = None) -> FormVerdict:
    set_form_url(paths, SHORT_URL)
    logins: list[str] = said if said is not None else []
    return _check(paths, FakeForms.answering(page)).run(lambda: logins.append("login"))


def _without(item_id: int) -> list[Any]:
    return [item for item in default_items() if item[0] != item_id]


def test_a_form_with_every_question_is_one_good_line_and_nothing_else_is_read(ready_paths: LivecraftPaths) -> None:
    """Линия «Таблица плана» работает, а проверка формы таблицу не читает и браузер не открывает: строка одна."""
    assert SettingsFile.of(ready_paths).load().lines.line_plan.works(RunPart.PLAN)
    said: list[str] = []
    verdict: FormVerdict = _run(ready_paths, _page(), said)
    assert verdict == FormVerdict(is_ok=True, lines=(msg.SETUP_FORM_OK.format(form=TRAINING_FORM_TITLE),))
    assert said == []


def test_a_missing_question_is_named(ready_paths: LivecraftPaths) -> None:
    verdict: FormVerdict = _run(ready_paths, _page(_without(6)))
    quoted: str = msg.SETUP_FORM_QUESTION.format(title=STREAM_URL_TITLE)
    assert verdict == FormVerdict(
        is_ok=False,
        lines=(msg.SETUP_FORM_QUESTIONS_MISSING.format(form=TRAINING_FORM_TITLE, questions=quoted),),
    )


def test_form_dates_are_not_compared_with_anything(ready_paths: LivecraftPaths) -> None:
    """Даты «Время стрима» только в прошлом — форме это не в укор: хватает ли дат, решает запуск при допуске."""
    items: list[Any] = default_items()
    items[2] = question(3, DATE_TITLE, 2, [["11.09.2026 Дата стрима"]])
    verdict: FormVerdict = _run(ready_paths, _page(items))
    assert verdict == FormVerdict(is_ok=True, lines=(msg.SETUP_FORM_OK.format(form=TRAINING_FORM_TITLE),))


def test_an_unreadable_form_is_the_ready_refusal_text(ready_paths: LivecraftPaths) -> None:
    page: str = "<html><body>нет формы</body></html>"
    set_form_url(ready_paths, SHORT_URL)
    failure: KeyForm | FormFailure = FakeForms.answering(page).book(ready_paths.logs_dir).form_for(
        SettingsFile.of(ready_paths).load().form
    )
    assert isinstance(failure, FormFailure)
    assert _run(ready_paths, page) == FormVerdict.failed(failure.human)


def test_without_a_form_link_the_form_is_not_asked(ready_paths: LivecraftPaths) -> None:
    forms: FakeForms = FakeForms.answering(_page())
    verdict: FormVerdict = _check(ready_paths, forms).run(lambda: None)
    assert verdict == FormVerdict.failed(msg.SETUP_FORM_NOT_SET)
    assert forms.gets == []


def test_a_question_without_a_title_in_the_settings_is_not_needed(ready_paths: LivecraftPaths) -> None:
    """Вопрос без названия в настройках формы не нужен: его нет среди недостающих."""
    assert SettingsFile.of(ready_paths).load().form.fields[FormQuestion.TIME.value] is None
    assert _run(ready_paths, _page()).is_ok
