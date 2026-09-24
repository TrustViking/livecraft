from __future__ import annotations

import pytest

from app.secretsafe.value import SecretField, SecretValue
from app.setup.fields.secret_input import OPENAI_KEY_MIN_LENGTH, SHEETS_ID_MIN_LENGTH, SecretInput
from app.setup.validators import extract_spreadsheet_id, is_a1_range
from app.ui import messages_ru as msg

OPENAI_KEY: str = "sk-proj-own-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789"
SHEET_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ_own"
SHEET_URL: str = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
FORM_LONG: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-own-form/viewform"


def _input(field: SecretField, raw: str) -> SecretInput:
    return SecretInput(field=field, raw=raw)


def _assert_valid(entered: SecretInput, expected: str) -> None:
    assert entered.problem is None
    assert entered.normalized == expected
    secret: SecretValue | None = entered.secret
    assert secret is not None
    assert secret.field is entered.field
    assert secret.reveal() == expected      # эталон теста, а не вызов в коде


def _assert_invalid(entered: SecretInput) -> None:
    assert entered.problem is not None
    assert entered.normalized is None
    assert entered.secret is None


# --- общее для всех полей


@pytest.mark.parametrize("field", SecretField.current())
@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_empty_input_is_a_problem_in_every_field(field: SecretField, raw: str) -> None:
    entered: SecretInput = _input(field, raw)
    _assert_invalid(entered)
    assert entered.problem == msg.SETUP_INPUT_EMPTY


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (SecretField.OPENAI_API_KEY, OPENAI_KEY),
        (SecretField.SHEETS_ID, SHEET_ID),
        (SecretField.SHEETS_RANGE, "A:F"),
    ],
)
def test_spaces_around_the_input_are_trimmed(field: SecretField, value: str) -> None:
    _assert_valid(_input(field, f"  \t{value} \r\n"), value)


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        (SecretField.OPENAI_API_KEY, "sk-short"),
        (SecretField.SHEETS_ID, "short"),
        (SecretField.SHEETS_RANGE, "Тайный лист без границ"),
    ],
)
def test_the_problem_never_carries_the_input(field: SecretField, raw: str) -> None:
    """Введённое — секрет: в текст проблемы оно не подставляется (§7.4)."""
    problem: str | None = _input(field, raw).problem
    assert problem is not None
    assert raw not in problem


def test_the_input_does_not_show_in_repr() -> None:
    """Ввод — открытый секрет: в трассировку объект поля его не отдаёт."""
    entered: SecretInput = _input(SecretField.OPENAI_API_KEY, OPENAI_KEY)
    assert OPENAI_KEY not in repr(entered)
    assert OPENAI_KEY not in str(entered)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (SecretField.OPENAI_API_KEY, OPENAI_KEY),
        (SecretField.SHEETS_ID, SHEET_ID),
        (SecretField.SHEETS_RANGE, "'План стримов'!A2:F"),
    ],
)
def test_the_secret_prints_as_a_mask(field: SecretField, value: str) -> None:
    secret: SecretValue | None = _input(field, value).secret
    assert secret is not None
    assert str(secret) == secret.masked
    assert repr(secret) == secret.masked
    assert f"{secret}" == secret.masked
    assert value not in str(secret)
    assert value not in repr(secret)


# --- ключ OpenAI


@pytest.mark.parametrize("raw", [OPENAI_KEY, "sk-" + "a" * (OPENAI_KEY_MIN_LENGTH - 3)])
def test_a_good_openai_key_is_accepted(raw: str) -> None:
    _assert_valid(_input(SecretField.OPENAI_API_KEY, raw), raw)


@pytest.mark.parametrize(
    "raw",
    [
        "pk-proj-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",       # не с sk-
        "SK-proj-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",       # регистр префикса важен
        "sk-proj-Ab3dEf GhIjKlMnOpQrStUvWxYz0123456789",      # пробел внутри
        "sk-proj-Ab3dEf\tGhIjKlMnOpQrStUvWxYz0123456789",     # табуляция внутри
        "sk-proj-Ab3dEf\nGhIjKlMnOpQrStUvWxYz0123456789",     # перевод строки внутри
        "sk-" + "a" * (OPENAI_KEY_MIN_LENGTH - 4),            # на символ короче минимума
    ],
)
def test_a_bad_openai_key_is_rejected(raw: str) -> None:
    entered: SecretInput = _input(SecretField.OPENAI_API_KEY, raw)
    _assert_invalid(entered)
    assert entered.problem == msg.SETUP_INPUT_OPENAI_API_KEY.format(minimum=OPENAI_KEY_MIN_LENGTH)


# --- таблица плана: в сейф уходит id, а не ссылка (§7.5)


@pytest.mark.parametrize(
    "raw",
    [
        SHEET_URL,
        f"{SHEET_URL}/",
        f"{SHEET_URL}/edit",
        f"{SHEET_URL}/edit?gid=0",
        f"{SHEET_URL}/edit#gid=123456",
        f"{SHEET_URL}/edit?usp=sharing#gid=0",
        f"{SHEET_URL}?gid=0",
        f"{SHEET_URL}#gid=0",
        f"https://docs.google.com/a/example.com/spreadsheets/d/{SHEET_ID}/edit",
        SHEET_ID,
    ],
)
def test_every_form_of_the_sheet_link_gives_the_same_id(raw: str) -> None:
    _assert_valid(_input(SecretField.SHEETS_ID, raw), SHEET_ID)


@pytest.mark.parametrize(
    "raw",
    [
        "a" * (SHEETS_ID_MIN_LENGTH - 1),                     # короче минимума
        "https://docs.google.com/spreadsheets/d/short/edit",  # id из ссылки короче минимума
        "https://docs.google.com/spreadsheets/d//edit",       # id в ссылке пуст
        "1own-B3c4D5e6F7g8H9i0Jk.LmNoPqRsTuVwXyZ",            # точка
        "1own-B3c4D5e6F7g8H9i0Jk LmNoPqRsTuVwXyZ",            # пробел внутри
        "1own-B3c4D5e6F7g8H9i0ЖкLmNoPqRsTuVwXyZ",             # не латиница
        "https://example.com/table/1own-B3c4D5e6F7g8H9i0Jk",  # ссылка, но не на таблицу
    ],
)
def test_a_bad_sheet_id_is_rejected(raw: str) -> None:
    entered: SecretInput = _input(SecretField.SHEETS_ID, raw)
    _assert_invalid(entered)
    assert entered.problem == msg.SETUP_INPUT_SHEETS_ID.format(minimum=SHEETS_ID_MIN_LENGTH)


def test_a_sheet_id_of_exactly_the_minimum_length_is_accepted() -> None:
    raw: str = "a" * SHEETS_ID_MIN_LENGTH
    _assert_valid(_input(SecretField.SHEETS_ID, raw), raw)


# --- диапазон таблицы: нотация A1


@pytest.mark.parametrize(
    "raw", ["A:F", "A1:F200", "План!A:F", "'План стримов'!A2:F", "a:f", "AA1:ZZZ9", "'It''s'!B:C"]
)
def test_a_good_range_is_accepted(raw: str) -> None:
    _assert_valid(_input(SecretField.SHEETS_RANGE, raw), raw)


@pytest.mark.parametrize(
    "raw", ["A", "F:A1:B", "1:5", "A:", ":F", "AAAA:F", "A1", "!A:F", "'План!A:F", "План!", "A:F!"]
)
def test_a_bad_range_is_rejected(raw: str) -> None:
    entered: SecretInput = _input(SecretField.SHEETS_RANGE, raw)
    _assert_invalid(entered)
    assert entered.problem == msg.SETUP_INPUT_SHEETS_RANGE


# --- ссылка на форму: устаревшее поле сейфа (§14 решение 15), правило — в FormSettings.url_problem


@pytest.mark.parametrize("raw", ["", FORM_LONG, "http://forms.gle/secret-code-xyz"])
def test_the_legacy_form_url_is_never_accepted(raw: str) -> None:
    """Ссылку на форму на вкладке ключей больше не вводят: она задаётся в настройках запуска."""
    entered: SecretInput = _input(SecretField.KEY_FORM_URL, raw)
    _assert_invalid(entered)
    assert entered.problem == msg.SETUP_INPUT_LEGACY_FIELD


# --- чистые разборы validators.py


def test_extract_spreadsheet_id_leaves_a_bare_id_as_is() -> None:
    assert extract_spreadsheet_id(SHEET_ID) == SHEET_ID


def test_extract_spreadsheet_id_stops_at_the_first_terminator() -> None:
    assert extract_spreadsheet_id(f"{SHEET_URL}#gid=0/edit") == SHEET_ID
    assert extract_spreadsheet_id(f"{SHEET_URL}?a=/b") == SHEET_ID


def test_is_a1_range_requires_both_bounds() -> None:
    assert is_a1_range("A1:F200")
    assert not is_a1_range("A1")
