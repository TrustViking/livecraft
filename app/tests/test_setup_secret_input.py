from __future__ import annotations

import pytest

from app.secretsafe.value import SecretField, SecretValue
from app.setup.fields.secret_input import (
    OPENAI_KEY_MIN_LENGTH,
    SHEETS_ID_MIN_LENGTH,
    TELEGRAM_BOT_SECRET_MIN_LENGTH,
    SecretInput,
)
from app.setup.validators import extract_spreadsheet_id
from app.ui import messages_ru as msg

OPENAI_KEY: str = "sk-proj-own-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789"
SHEET_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ_own"
SHEET_URL: str = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
BOT_TOKEN: str = "7000000001:AAHown-Ab3dEfGhIjKlMnOpQrStUvWxYz_0123"


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


@pytest.mark.parametrize("field", tuple(SecretField))
@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_empty_input_is_a_problem_in_every_field(field: SecretField, raw: str) -> None:
    entered: SecretInput = _input(field, raw)
    _assert_invalid(entered)
    assert entered.is_empty
    assert entered.problem == msg.SETUP_INPUT_EMPTY


@pytest.mark.parametrize("raw", ["sk-1", "  x  ", "x"])
def test_input_with_text_is_not_empty(raw: str) -> None:
    assert not _input(SecretField.OPENAI_API_KEY, raw).is_empty


def test_the_empty_input_text_names_no_button() -> None:
    """Без своего значения сбросить нечего: текст просит ввод и не называет кнопку, которой у строки нет."""
    assert "«" not in msg.SETUP_INPUT_EMPTY


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (SecretField.OPENAI_API_KEY, OPENAI_KEY),
        (SecretField.SHEETS_ID, SHEET_ID),
        (SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN),
    ],
)
def test_spaces_around_the_input_are_trimmed(field: SecretField, value: str) -> None:
    _assert_valid(_input(field, f"  \t{value} \r\n"), value)


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        (SecretField.OPENAI_API_KEY, "sk-short"),
        (SecretField.SHEETS_ID, "short"),
        (SecretField.TELEGRAM_BOT_TOKEN, "7000000001:short"),
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
        (SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN),
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


# --- чистые разборы validators.py


def test_extract_spreadsheet_id_leaves_a_bare_id_as_is() -> None:
    assert extract_spreadsheet_id(SHEET_ID) == SHEET_ID


def test_extract_spreadsheet_id_stops_at_the_first_terminator() -> None:
    assert extract_spreadsheet_id(f"{SHEET_URL}#gid=0/edit") == SHEET_ID
    assert extract_spreadsheet_id(f"{SHEET_URL}?a=/b") == SHEET_ID


# --- токен бота Telegram (§13 задача 4.1)


@pytest.mark.parametrize("raw", [BOT_TOKEN, "1:" + "a" * TELEGRAM_BOT_SECRET_MIN_LENGTH])
def test_a_good_bot_token_is_accepted(raw: str) -> None:
    _assert_valid(_input(SecretField.TELEGRAM_BOT_TOKEN, raw), raw)


@pytest.mark.parametrize(
    "raw",
    [
        "1:" + "a" * (TELEGRAM_BOT_SECRET_MIN_LENGTH - 1),       # секрет короче предела
        "AAHown-Ab3dEfGhIjKlMnOpQrStUvWxYz_0123456",             # нет id бота и двоеточия
        "bot7000000001:AAHown-Ab3dEfGhIjKlMnOpQrStUvWxYz_0123",  # id не число
        "7000000001:AAHown Ab3dEfGhIjKlMnOpQrStUvWxYz_0123",     # пробел внутри
        "7000000001:AAHown-Ab3dEfGhIjKlMnOpQrStUvWxYz_0123!",    # чужой знак
        "https://api.telegram.org/bot" + BOT_TOKEN,              # адрес, а не токен
    ],
)
def test_a_bad_bot_token_is_rejected_without_the_value(raw: str) -> None:
    entered: SecretInput = _input(SecretField.TELEGRAM_BOT_TOKEN, raw)
    _assert_invalid(entered)
    assert entered.problem == msg.SETUP_INPUT_TELEGRAM_BOT_TOKEN.format(minimum=TELEGRAM_BOT_SECRET_MIN_LENGTH)


def test_the_bot_token_is_masked_by_fingerprint() -> None:
    """Токен целиком — ключ к боту: даже хвост не показывается, только название поля и отпечаток."""
    secret: SecretValue | None = _input(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN).secret
    assert secret is not None
    assert secret.masked.startswith(msg.VAULT_FIELD_TELEGRAM_BOT_TOKEN)
    assert BOT_TOKEN[-4:] not in secret.masked and BOT_TOKEN[:4] not in secret.masked


# --- папка материалов на Google Диске (§14 решения 27, 39): в сейф ложится id папки


@pytest.mark.parametrize(
    "raw",
    [
        "https://drive.google.com/drive/folders/1AbC_d-9",
        "https://drive.google.com/drive/folders/1AbC_d-9?usp=sharing",
        "https://drive.google.com/drive/u/0/folders/1AbC_d-9",
        "1AbC_d-9",
        "  https://drive.google.com/drive/folders/1AbC_d-9  ",
    ],
)
def test_a_folder_link_or_the_bare_id_gives_the_folder_id(raw: str) -> None:
    _assert_valid(_input(SecretField.DRIVE_FOLDER, raw), "1AbC_d-9")


@pytest.mark.parametrize(
    "raw",
    [
        "https://docs.google.com/document/d/1AbC/edit",
        "https://drive.google.com/file/d/1AbC/view",
        "http://drive.google.com/drive/folders/1AbC",
        "https://drive.google.com@evil.example/drive/folders/1AbC",
        "https://drive.google.com/drive/folders/1AbC more",
        "папка",
        "https://[bad",
    ],
)
def test_a_link_that_is_not_a_drive_folder_is_rejected(raw: str) -> None:
    entered: SecretInput = _input(SecretField.DRIVE_FOLDER, raw)
    _assert_invalid(entered)
    assert entered.problem == msg.SETUP_INPUT_DRIVE_FOLDER


def test_the_drive_folder_is_masked_by_fingerprint_and_logged_by_label() -> None:
    secret: SecretValue | None = _input(SecretField.DRIVE_FOLDER, "1AbC_d-9").secret
    assert secret is not None
    assert "1AbC_d-9" not in f"{secret}" and "1AbC_d-9" not in repr(secret)
    assert secret.short_mask == "…" + secret.fingerprint
    assert secret.log_label == f"drive-folder({secret.fingerprint})"
