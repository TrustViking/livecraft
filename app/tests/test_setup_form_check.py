"""Проверка формы ключей без окна (app\\setup\\panels\\form_check.py, CLAUDE.md §8.2, §6 инвариант 2): форма читается
тем же кодом, что у запуска, покрытие дат таблицы плана — тем же правилом. К Google тесты не ходят: страница формы —
тренировочная форма в раскладке FB_PUBLIC_LOAD_DATA_ (даты 17.03.2027 и 18.03.2027), таблица — подделка читателя."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config.files import SettingsFile
from app.config.settings import FormQuestion
from app.form.failure import FormFailure
from app.form.key_form import KeyForm
from app.paths import LivecraftPaths
from app.run.mode import RunPart
from app.setup.panels.form_check import FormCheck, FormVerdict
from app.setup.panels.table_check import TableCheck
from app.sheets.client import SheetsReadError, SheetsReadReason
from app.tests.fixtures.broadcasts import FORM_TITLE_GAP
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.form import (
    KYIV_WINTER,
    SHORT_URL,
    TRAINING_FORM_TITLE,
    FakeForms,
    build_html,
    build_payload,
    default_items,
    question,
)
from app.tests.fixtures.settings import lines_without, set_form_url, set_lines
from app.tests.fixtures.sheets import OPERATOR_EMAIL, FakeSheetsReader
from app.ui import messages_ru as msg

HEADER: list[str] = ["№", "Ссылка", "Дата", "Время"]
LINK: str = "https://youtu.be/dQw4w9WgXcQ"
TODAY: datetime = datetime(2027, 3, 16, 12, 0, tzinfo=KYIV_WINTER)
DATE_TITLE: str = "Время стрима ( Stream time )"
TABLE_ACCOUNT: str = "table@example.com"
CHANNEL_ACCOUNT: str = "channel@example.com"
QUESTIONS: tuple[str, ...] = (
    "Язык стрима ( Language of stream)",
    "Название канала ( Channel name)",
    DATE_TITLE,
    "Платформа (Platform)",
    "You Tube Stream Key",
    "Stream-URL (YT)",
)


def _page(items: list[Any] | None = None) -> str:
    """Страница тренировочной формы с заголовком: вопросы — `items` (по умолчанию все)."""
    payload: list[Any] = build_payload(items if items is not None else default_items())
    payload[1].extend([None] * FORM_TITLE_GAP + [TRAINING_FORM_TITLE])
    return build_html(payload)


def _quoted(*titles: str) -> str:
    return msg.LIST_JOINER.join(msg.SETUP_FORM_QUESTION.format(title=title) for title in titles)


def _rows(*dates: str) -> list[list[str]]:
    return [HEADER, *([str(index), LINK, day, "19:00"] for index, day in enumerate(dates, 1))]


def _check(paths: LivecraftPaths, forms: FakeForms, reader: FakeSheetsReader) -> FormCheck:
    table: TableCheck = TableCheck(paths=paths, door=reader, clock=StoppedClock.at(TODAY))
    return FormCheck(table=table, open_forms=lambda clock: forms.book(paths.logs_dir))


def _run(paths: LivecraftPaths, page: str, reader: FakeSheetsReader) -> FormVerdict:
    set_form_url(paths, SHORT_URL)
    return _check(paths, FakeForms.answering(page), reader).run(lambda: None)


def _read_form(paths: LivecraftPaths, page: str) -> KeyForm:
    form: KeyForm | FormFailure = FakeForms.answering(page).book(paths.logs_dir).form_for(
        SettingsFile.of(paths).load().form
    )
    assert isinstance(form, KeyForm)
    return form


def _without(item_id: int) -> list[Any]:
    return [item for item in default_items() if item[0] != item_id]


def test_a_form_with_every_question_and_the_table_dates_is_good(ready_paths: LivecraftPaths) -> None:
    verdict: FormVerdict = _run(ready_paths, _page(), FakeSheetsReader(values=_rows("17.03.2027", "18.03.2027")))
    dates_ok: str = msg.FORM_DATES_OK.format(form=TRAINING_FORM_TITLE, wanted=2, accepted=2)
    coverage: str = msg.CHECK_OK_LINE.format(line=dates_ok)
    assert verdict == FormVerdict(
        is_ok=True,
        lines=(
            msg.SETUP_FORM_OK.format(form=TRAINING_FORM_TITLE, questions=_quoted(*QUESTIONS)),
            msg.SETUP_FORM_DATES.format(question=DATE_TITLE, dates="17.03.2027, 18.03.2027"),
            coverage,
        ),
    )


def test_a_missing_question_is_named(ready_paths: LivecraftPaths) -> None:
    page: str = _page(_without(6))
    verdict: FormVerdict = _run(ready_paths, page, FakeSheetsReader(values=_rows("17.03.2027")))
    assert not verdict.is_ok
    assert verdict.lines[:2] == (
        msg.SETUP_FORM_OK.format(form=TRAINING_FORM_TITLE, questions=_quoted(*QUESTIONS[:-1])),
        msg.SETUP_FORM_QUESTIONS_MISSING.format(form=TRAINING_FORM_TITLE, questions=_quoted(QUESTIONS[-1])),
    )


def test_table_dates_without_a_form_option_are_named(ready_paths: LivecraftPaths) -> None:
    """Дата эфира таблицы без варианта «Время стрима» — строка запуска о недостающих датах со знаком проблемы, форма не
    годится."""
    verdict: FormVerdict = _run(ready_paths, _page(), FakeSheetsReader(values=_rows("17.03.2027", "19.03.2027")))
    form: KeyForm = _read_form(ready_paths, _page())
    starts: list[datetime] = [datetime(2027, 3, day, 19, 0, tzinfo=KYIV_WINTER) for day in (17, 19)]
    assert not verdict.is_ok
    assert verdict.lines[-1] == msg.CHECK_PROBLEM_LINE.format(line=form.date_coverage(starts).line)
    missing: str = msg.FORM_DATES_MISSING.format(form=TRAINING_FORM_TITLE, dates="19.03.2027")
    assert verdict.lines[-1] == msg.CHECK_PROBLEM_LINE.format(line=missing)


def test_past_form_dates_are_not_listed(ready_paths: LivecraftPaths) -> None:
    items: list[Any] = default_items()
    items[2] = question(3, DATE_TITLE, 2, [["11.09.2026 Дата стрима"], ["17.03.2027 Дата стрима"]])
    verdict: FormVerdict = _run(ready_paths, _page(items), FakeSheetsReader(values=_rows()))
    assert msg.SETUP_FORM_DATES.format(question=DATE_TITLE, dates="17.03.2027") in verdict.lines


def test_a_form_without_dates_from_today_says_so(ready_paths: LivecraftPaths) -> None:
    items: list[Any] = default_items()
    items[2] = question(3, DATE_TITLE, 2, [["11.09.2026 Дата стрима"]])
    verdict: FormVerdict = _run(ready_paths, _page(items), FakeSheetsReader(values=_rows()))
    assert msg.SETUP_FORM_NO_DATES.format(question=DATE_TITLE) in verdict.lines


def test_a_text_date_question_takes_any_date_and_the_table_is_not_read(ready_paths: LivecraftPaths) -> None:
    items: list[Any] = default_items()
    items[2] = question(3, DATE_TITLE, 0)
    reader: FakeSheetsReader = FakeSheetsReader(values=_rows("19.03.2027"))
    verdict: FormVerdict = _run(ready_paths, _page(items), reader)
    assert verdict.is_ok
    assert verdict.lines[-1] == msg.SETUP_FORM_DATE_ANY.format(question=DATE_TITLE)
    assert reader.vaults == []


def test_a_table_without_future_streams_has_nothing_to_cover(ready_paths: LivecraftPaths) -> None:
    verdict: FormVerdict = _run(ready_paths, _page(), FakeSheetsReader(values=_rows("10.03.2027")))
    assert verdict.is_ok and verdict.lines[-1] == msg.SETUP_FORM_TABLE_EMPTY


def test_an_unread_table_is_named_and_the_form_is_not_good(ready_paths: LivecraftPaths) -> None:
    error: SheetsReadError = SheetsReadError(SheetsReadReason.NOT_FOUND, "sheets-plan(ab12)", status=404)
    verdict: FormVerdict = _run(ready_paths, _page(), FakeSheetsReader(error=error))
    assert not verdict.is_ok
    assert verdict.lines[-1] == msg.SETUP_FORM_TABLE_UNREAD.format(problem=error.human)


def test_a_table_closed_to_the_account_logs_in_again_by_the_operator_rule(ready_paths: LivecraftPaths) -> None:
    """Таблица читается по правилу входа оператора, как её проверка (§13 задача 9.6): аккаунту входа она не открыта
    (403) — строка с его почтой, повторный вход в браузере и строка, каким аккаунтом вошли; обе — перед строкой
    покрытия дат."""
    set_form_url(ready_paths, SHORT_URL)
    refused: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "sheets-plan(ab12)", status=403)
    table: FakeSheetsReader = FakeSheetsReader(values=_rows("17.03.2027"), account_email=TABLE_ACCOUNT)
    reader: FakeSheetsReader = FakeSheetsReader(error=refused, account_email=CHANNEL_ACCOUNT, relogin=table)
    said: list[str] = []
    verdict: FormVerdict = _check(ready_paths, FakeForms.answering(_page()), reader).run(lambda: said.append("login"))
    starts: list[datetime] = [datetime(2027, 3, 17, 19, 0, tzinfo=KYIV_WINTER)]
    coverage: str = msg.CHECK_OK_LINE.format(line=_read_form(ready_paths, _page()).date_coverage(starts).line)
    assert verdict.is_ok and said == ["login"] and reader.login_announced == 1
    assert verdict.lines[-3:] == (
        msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT),
        msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT),
        coverage,
    )


def test_a_table_closed_to_the_new_account_too_names_the_account(ready_paths: LivecraftPaths) -> None:
    """Не открыта и аккаунту повторного входа — причина с его почтой и действием, форма не годится."""
    refused: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "sheets-plan(ab12)", status=403)
    again: FakeSheetsReader = FakeSheetsReader(error=refused, account_email=TABLE_ACCOUNT)
    verdict: FormVerdict = _run(ready_paths, _page(), FakeSheetsReader(error=refused, relogin=again))
    account_refused: SheetsReadError = SheetsReadError(
        SheetsReadReason.ACCOUNT_REFUSED, "sheets-plan(ab12)", 403, TABLE_ACCOUNT
    )
    assert not verdict.is_ok
    assert verdict.lines[-3:] == (
        msg.OPERATOR_ACCESS_REFUSED.format(account=OPERATOR_EMAIL),
        msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT),
        msg.SETUP_FORM_TABLE_UNREAD.format(problem=account_refused.human),
    )


def test_without_the_plan_line_the_table_is_not_read(ready_paths: LivecraftPaths) -> None:
    set_lines(ready_paths, lines_without(RunPart.PLAN))
    reader: FakeSheetsReader = FakeSheetsReader(values=_rows("19.03.2027"), announce_login=True)
    verdict: FormVerdict = _run(ready_paths, _page(), reader)
    assert verdict.is_ok and len(verdict.lines) == 2
    assert reader.vaults == [] and reader.login_announced == 0


def test_the_browser_line_goes_to_the_caller(ready_paths: LivecraftPaths) -> None:
    set_form_url(ready_paths, SHORT_URL)
    said: list[str] = []
    reader: FakeSheetsReader = FakeSheetsReader(values=_rows("17.03.2027"), announce_login=True)
    _check(ready_paths, FakeForms.answering(_page()), reader).run(lambda: said.append("login"))
    assert said == ["login"]


def test_an_unreadable_form_is_the_ready_refusal_text(ready_paths: LivecraftPaths) -> None:
    page: str = "<html><body>нет формы</body></html>"
    set_form_url(ready_paths, SHORT_URL)
    failure: KeyForm | FormFailure = FakeForms.answering(page).book(ready_paths.logs_dir).form_for(
        SettingsFile.of(ready_paths).load().form
    )
    assert isinstance(failure, FormFailure)
    reader: FakeSheetsReader = FakeSheetsReader(values=_rows("17.03.2027"))
    verdict: FormVerdict = _run(ready_paths, page, reader)
    assert verdict == FormVerdict.failed(failure.human)
    assert reader.vaults == []


def test_without_a_form_link_the_form_is_not_asked(ready_paths: LivecraftPaths) -> None:
    forms: FakeForms = FakeForms.answering(_page())
    verdict: FormVerdict = _check(ready_paths, forms, FakeSheetsReader()).run(lambda: None)
    assert verdict == FormVerdict.failed(msg.SETUP_FORM_NOT_SET)
    assert forms.gets == []


def test_the_questions_are_those_of_the_settings(ready_paths: LivecraftPaths) -> None:
    """Вопрос без названия в настройках формы не нужен — его нет ни среди найденных, ни среди недостающих."""
    file: SettingsFile = SettingsFile.of(ready_paths)
    assert file.load().form.fields[FormQuestion.TIME.value] is None
    verdict: FormVerdict = _run(ready_paths, _page(), FakeSheetsReader(values=_rows("17.03.2027")))
    assert verdict.lines[0] == msg.SETUP_FORM_OK.format(form=TRAINING_FORM_TITLE, questions=_quoted(*QUESTIONS))
