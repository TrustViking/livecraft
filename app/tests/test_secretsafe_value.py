from __future__ import annotations

import hashlib
import logging
import traceback
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.observability.logging_setup import close_logging, get_logger, setup_logging
from app.secretsafe.crypto import (
    SALT_BYTES,
    VAULT_KEY_BYTES,
    EncryptedField,
    VaultCrypto,
    VaultDecryptError,
)
from app.secretsafe.value import (
    FINGERPRINT_CHARS,
    MASK_HIDDEN,
    MaskStyle,
    SecretField,
    SecretValue,
)
from app.ui import messages_ru as msg

OPENAI_KEY: str = "sk-proj-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789dc7f"
SHEETS_ID: str = "1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg"
FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-secret-part/viewform"
SHEETS_RANGE: str = "A:F"
SECRETS: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: OPENAI_KEY,
    SecretField.SHEETS_ID: SHEETS_ID,
    SecretField.SHEETS_RANGE: SHEETS_RANGE,
    SecretField.KEY_FORM_URL: FORM_URL,
}


@dataclass
class _Owner:
    """Объект-владелец секрета: его repr не должен раскрывать поле (боевой случай — dataclass в трассировке)."""

    name: str
    secret: SecretValue


@pytest.fixture(autouse=True)
def _closed_logging() -> Iterator[None]:
    yield
    close_logging()


@pytest.fixture(params=sorted(SECRETS, key=lambda item: item.value))
def secret(request: pytest.FixtureRequest) -> SecretValue:
    """По одному секрету на каждое поле сейфа: правило маскирования проверяется на всех четырёх."""
    field: SecretField = request.param
    return SecretValue(field=field, value=SECRETS[field])


# --- §7.4: значение не вытекает ни в один вывод


def test_an_f_string_shows_the_mask(secret: SecretValue) -> None:
    assert f"{secret}" == secret.masked
    assert secret.reveal() not in f"{secret}"


def test_a_format_specifier_does_not_break_out_of_the_mask(secret: SecretValue) -> None:
    """f"{secret:>40}" ушёл бы в str.__format__ и напечатал значение, если бы __format__ не был переопределён."""
    assert f"{secret:>40}" == secret.masked
    assert f"{secret:s}" == secret.masked
    assert secret.reveal() not in f"{secret:>40}"


def test_str_and_repr_show_the_mask(secret: SecretValue) -> None:
    assert str(secret) == secret.masked
    assert repr(secret) == secret.masked
    assert secret.reveal() not in repr(secret)


def test_repr_of_the_owning_object_shows_the_mask(secret: SecretValue) -> None:
    """dataclass владельца печатает свои поля; значение не должно всплыть через него."""
    owner: _Owner = _Owner(name="настройщик", secret=secret)
    assert secret.reveal() not in repr(owner)
    assert secret.masked in repr(owner)


def test_logging_writes_the_mask_and_not_the_value(secret: SecretValue, tmp_path: Path) -> None:
    """logging.info("%s", secret) зовёт __str__ при форматировании записи — в файле должна быть маска."""
    log_path: Path = setup_logging(tmp_path, debug=False)
    get_logger("vault").warning("vault_field_loaded %s", secret)
    get_logger("vault").warning("vault_field_labelled %s", secret.log_label)
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert secret.reveal() not in text
    assert secret.masked in text
    assert secret.log_label in text


def test_the_value_does_not_reach_a_traceback(secret: SecretValue) -> None:
    """Секрет в кадре упавшей функции: pytest и logging печатают локальные переменные через repr."""
    owner: _Owner = _Owner(name="конвейер", secret=secret)

    def _fail(carried: _Owner) -> None:
        raise RuntimeError(f"vault field unusable: {carried.secret}")

    try:
        _fail(owner)
    except RuntimeError as error:
        printed: str = "".join(traceback.format_exception(error)) + repr(error.args)
    assert secret.reveal() not in printed
    assert secret.masked in printed


# --- reveal и отпечаток


def test_reveal_returns_the_original_string(secret: SecretValue) -> None:
    assert secret.reveal() == SECRETS[secret.field]


def test_fingerprint_is_the_first_four_hex_of_sha256(secret: SecretValue) -> None:
    expected: str = hashlib.sha256(secret.reveal().encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]
    assert secret.fingerprint == expected
    assert len(secret.fingerprint) == FINGERPRINT_CHARS


def test_fingerprint_is_stable_between_calls_and_objects(secret: SecretValue) -> None:
    twin: SecretValue = SecretValue(field=secret.field, value=SECRETS[secret.field])
    assert secret.fingerprint == secret.fingerprint == twin.fingerprint


def test_different_values_get_different_fingerprints() -> None:
    first: SecretValue = SecretValue(field=SecretField.KEY_FORM_URL, value=FORM_URL)
    second: SecretValue = SecretValue(field=SecretField.KEY_FORM_URL, value=FORM_URL + "2")
    assert first.fingerprint != second.fingerprint      # две формы в одном запуске различимы (§7.4)


def test_fingerprint_is_hex_of_a_fixed_length_whatever_the_value(secret: SecretValue) -> None:
    """Отпечаток — хеш, а не кусок значения: длина у всех одна, символы шестнадцатеричные."""
    assert len(secret.fingerprint) == FINGERPRINT_CHARS
    assert all(char in "0123456789abcdef" for char in secret.fingerprint)


# --- формы маски


def test_the_api_key_is_shown_by_its_tail() -> None:
    """Ключ API владелец должен узнать — показываем начало и хвост, и ничего между ними."""
    secret: SecretValue = SecretValue(field=SecretField.OPENAI_API_KEY, value=OPENAI_KEY)
    assert secret.field.mask_style is MaskStyle.TAIL
    assert secret.masked == "sk-…dc7f"
    assert OPENAI_KEY[3:-4] not in secret.masked


@pytest.mark.parametrize("value", ["", "s", "sk-", "sk-abcd", "1234567"])
def test_a_short_value_is_hidden_completely_under_the_tail_style(value: str) -> None:
    """Из трёх символов и хвоста короткого значения складывается всё значение — показывать нечего."""
    secret: SecretValue = SecretValue(field=SecretField.OPENAI_API_KEY, value=value)
    assert secret.masked == MASK_HIDDEN


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (SecretField.SHEETS_ID, SHEETS_ID),
        (SecretField.SHEETS_RANGE, SHEETS_RANGE),
        (SecretField.KEY_FORM_URL, FORM_URL),
    ],
)
def test_links_and_ids_are_shown_only_by_label_and_fingerprint(field: SecretField, value: str) -> None:
    """У ссылки и id даже хвост подсказывает лишнее: только название поля и отпечаток."""
    secret: SecretValue = SecretValue(field=field, value=value)
    assert field.mask_style is MaskStyle.FINGERPRINT
    assert secret.masked == msg.VAULT_MASK_FINGERPRINT.format(
        label=field.human_label, fingerprint=secret.fingerprint
    )
    assert field.human_label in secret.masked
    assert value not in secret.masked


def test_the_mask_of_a_link_carries_no_piece_of_it() -> None:
    secret: SecretValue = SecretValue(field=SecretField.KEY_FORM_URL, value=FORM_URL)
    assert "docs.google.com" not in secret.masked
    assert "1FAIpQLSf" not in secret.masked


# --- ярлык для лога и сами поля


def test_log_label_is_label_and_fingerprint(secret: SecretValue) -> None:
    assert secret.log_label == f"{secret.field.log_label}({secret.fingerprint})"
    assert secret.reveal() not in secret.log_label


def test_log_label_carries_no_piece_of_the_value() -> None:
    secret: SecretValue = SecretValue(field=SecretField.KEY_FORM_URL, value=FORM_URL)
    assert secret.log_label == f"key-form({secret.fingerprint})"
    assert "docs.google.com" not in secret.log_label and "viewform" not in secret.log_label


def test_log_labels_are_english_and_distinct() -> None:
    """Ярлык уходит в машинный след, поэтому английский; ни одно поле не путается с другим (§7.4)."""
    labels: list[str] = [field.log_label for field in SecretField]
    assert labels == ["openai-key", "sheets-plan", "sheets-range", "key-form"]
    assert len(set(labels)) == len(labels)
    assert all(label.isascii() for label in labels)


def test_the_four_fields_are_the_ones_section_seven_names() -> None:
    assert [field.value for field in SecretField] == [
        "openai_api_key",
        "sheets_id",
        "sheets_range",
        "key_form_url",
    ]


def test_human_labels_come_from_messages_ru() -> None:
    """Русские названия полей живут в messages_ru; enum только связывает поле с текстом (§11)."""
    assert SecretField.OPENAI_API_KEY.human_label == msg.VAULT_FIELD_OPENAI_API_KEY
    assert SecretField.SHEETS_ID.human_label == msg.VAULT_FIELD_SHEETS_ID
    assert SecretField.SHEETS_RANGE.human_label == msg.VAULT_FIELD_SHEETS_RANGE
    assert SecretField.KEY_FORM_URL.human_label == msg.VAULT_FIELD_KEY_FORM_URL


def test_the_secret_object_is_frozen(secret: SecretValue) -> None:
    """Значение не подменяется на ходу: сменить секрет — построить новый объект."""
    with pytest.raises(Exception):
        secret.value = "подмена"        # type: ignore[misc]


def test_percent_style_logging_of_the_owner_also_masks(secret: SecretValue, tmp_path: Path) -> None:
    """Чужая библиотека может записать в лог объект-владелец целиком — и там маска."""
    log_path: Path = setup_logging(tmp_path, debug=False)
    logging.getLogger("googleapiclient.discovery").warning("%r", _Owner(name="x", secret=secret))
    close_logging()
    assert secret.reveal() not in log_path.read_text(encoding="utf-8")


# --- scrub: вычёркивание значения из готовой строки (§7.4, страховка фильтра логов)


def test_scrub_replaces_the_value_with_the_log_label(secret: SecretValue) -> None:
    text: str = f"GET {secret.reveal()} returned 200"
    scrubbed: str = secret.scrub(text)
    assert secret.reveal() not in scrubbed
    assert secret.log_label in scrubbed
    assert scrubbed == f"GET {secret.log_label} returned 200"


def test_scrub_replaces_every_occurrence_not_just_the_first(secret: SecretValue) -> None:
    value: str = secret.reveal()
    scrubbed: str = secret.scrub(f"{value} -> {value} -> {value}")
    assert value not in scrubbed
    assert scrubbed.count(secret.log_label) == 3


def test_scrub_leaves_a_text_without_the_value_alone(secret: SecretValue) -> None:
    text: str = r"run_started version=0.1.0 root=D:\_exe\Livecraft"
    assert secret.scrub(text) == text


def test_scrub_of_an_empty_secret_changes_nothing() -> None:
    """Пустая подстрока нашлась бы в любом тексте — пустое значение вычёркивать нечем."""
    empty: SecretValue = SecretValue(field=SecretField.SHEETS_RANGE, value="")
    text: str = "form_ready questions=6"
    assert empty.scrub(text) == text
    assert empty.scrub("") == ""


def test_scrub_works_on_a_value_glued_to_other_text(secret: SecretValue) -> None:
    """Секрет в логе чужой библиотеки редко стоит отдельным словом — чаще внутри URL или JSON."""
    scrubbed: str = secret.scrub(f'{{"url":"{secret.reveal()}","code":200}}')
    assert secret.reveal() not in scrubbed and secret.log_label in scrubbed


def test_scrub_does_not_touch_other_secrets() -> None:
    """Каждый секрет вычёркивает только своё: чужое значение остаётся делом чужого объекта."""
    key: SecretValue = SecretValue(field=SecretField.OPENAI_API_KEY, value=OPENAI_KEY)
    form: SecretValue = SecretValue(field=SecretField.KEY_FORM_URL, value=FORM_URL)
    scrubbed: str = key.scrub(f"{OPENAI_KEY} {FORM_URL}")
    assert OPENAI_KEY not in scrubbed
    assert FORM_URL in scrubbed
    assert form.scrub(scrubbed) == f"{key.log_label} {form.log_label}"


# --- encrypt: шифрование — правило самого секрета (§0, §7.4)


VAULT_KEY: bytes = bytes(range(VAULT_KEY_BYTES))
SALT: bytes = bytes(range(SALT_BYTES))


@pytest.fixture
def crypto() -> VaultCrypto:
    return VaultCrypto(key=VAULT_KEY, salt=SALT)


def test_encrypt_gives_what_the_cipher_would_give_directly(secret: SecretValue, crypto: VaultCrypto) -> None:
    """Нонс случайный, поэтому сверяем не байты, а то, что расшифровывается: результат тот же."""
    by_secret: EncryptedField = secret.encrypt(crypto)
    by_cipher: EncryptedField = crypto.encrypt(secret.field, SECRETS[secret.field])
    assert by_secret.nonce != by_cipher.nonce
    assert crypto.decrypt(secret.field, by_secret) == crypto.decrypt(secret.field, by_cipher)


def test_an_encrypted_field_decrypts_back_into_the_value(secret: SecretValue, crypto: VaultCrypto) -> None:
    assert crypto.decrypt(secret.field, secret.encrypt(crypto)) == SECRETS[secret.field]


def test_the_ciphertext_carries_no_value(secret: SecretValue, crypto: VaultCrypto) -> None:
    blob: EncryptedField = secret.encrypt(crypto)
    assert SECRETS[secret.field].encode("utf-8") not in blob.ciphertext


def test_two_encryptions_of_one_secret_differ(secret: SecretValue, crypto: VaultCrypto) -> None:
    """Нонс новый на каждое шифрование — за это отвечает VaultCrypto, а секрет ему не мешает."""
    first: EncryptedField = secret.encrypt(crypto)
    second: EncryptedField = secret.encrypt(crypto)
    assert first.nonce != second.nonce and first.ciphertext != second.ciphertext


def test_the_secret_names_its_own_field_so_the_binding_holds(crypto: VaultCrypto) -> None:
    """Поле берётся из самого секрета: блоб чужого поля не расшифруется, перепутать привязку нельзя."""
    sheets: SecretValue = SecretValue(field=SecretField.SHEETS_ID, value=SHEETS_ID)
    blob: EncryptedField = sheets.encrypt(crypto)
    assert crypto.decrypt(SecretField.SHEETS_ID, blob) == SHEETS_ID
    with pytest.raises(VaultDecryptError):
        crypto.decrypt(SecretField.KEY_FORM_URL, blob)


def test_every_field_keeps_its_own_binding(crypto: VaultCrypto) -> None:
    for field, value in SECRETS.items():
        blob: EncryptedField = SecretValue(field=field, value=value).encrypt(crypto)
        for other in SecretField:
            if other is field:
                continue
            with pytest.raises(VaultDecryptError):
                crypto.decrypt(other, blob)


def test_an_empty_value_encrypts_and_comes_back_empty(crypto: VaultCrypto) -> None:
    empty: SecretValue = SecretValue(field=SecretField.SHEETS_RANGE, value="")
    assert crypto.decrypt(SecretField.SHEETS_RANGE, empty.encrypt(crypto)) == ""
