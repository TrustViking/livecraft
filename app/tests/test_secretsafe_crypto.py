from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from app.secretsafe.crypto import (
    FORMAT_VERSION,
    HKDF_INFO,
    KEY_CIPHERTEXT,
    KEY_FIELDS,
    KEY_NONCE,
    KEY_SALT,
    KEY_VERSION,
    KEY_WRAPPED,
    NONCE_BYTES,
    SALT_BYTES,
    VAULT_KEY_BYTES,
    EncryptedField,
    VaultCrypto,
    VaultDecryptError,
    VaultFile,
    VaultFormatError,
    VaultFormatReason,
    VaultSource,
)
from app.secretsafe.value import SecretField
from app.ui import messages_ru as msg

VAULT_KEY: bytes = bytes(range(VAULT_KEY_BYTES))
OTHER_KEY: bytes = bytes(range(100, 100 + VAULT_KEY_BYTES))
SALT: bytes = bytes(range(SALT_BYTES))
OTHER_SALT: bytes = bytes(range(50, 50 + SALT_BYTES))
VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789dc7f",
    SecretField.SHEETS_ID: "1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.SHEETS_RANGE: "A:F",
    SecretField.KEY_FORM_URL: "https://docs.google.com/forms/d/e/1FAIpQLSf-secret/viewform",
}
ALL_FIELDS: list[SecretField] = list(SecretField)


@pytest.fixture
def crypto() -> VaultCrypto:
    return VaultCrypto(key=VAULT_KEY, salt=SALT)


def _flip_first_byte(data: bytes) -> bytes:
    return bytes([data[0] ^ 0x01]) + data[1:]


# --- круговой ход и нонсы


@pytest.mark.parametrize("field", ALL_FIELDS, ids=lambda item: item.value)
def test_a_field_encrypts_and_decrypts_back(crypto: VaultCrypto, field: SecretField) -> None:
    blob: EncryptedField = crypto.encrypt(field, VALUES[field])
    assert crypto.decrypt(field, blob) == VALUES[field]


@pytest.mark.parametrize("field", ALL_FIELDS, ids=lambda item: item.value)
def test_the_ciphertext_does_not_contain_the_value(crypto: VaultCrypto, field: SecretField) -> None:
    blob: EncryptedField = crypto.encrypt(field, VALUES[field])
    assert VALUES[field].encode("utf-8") not in blob.ciphertext
    assert len(blob.nonce) == NONCE_BYTES


def test_two_encryptions_of_one_value_differ_in_nonce_and_ciphertext(crypto: VaultCrypto) -> None:
    """Повтор нонса при одном ключе ломает GCM полностью — нонс обязан быть новым на каждое шифрование."""
    first: EncryptedField = crypto.encrypt(SecretField.SHEETS_ID, VALUES[SecretField.SHEETS_ID])
    second: EncryptedField = crypto.encrypt(SecretField.SHEETS_ID, VALUES[SecretField.SHEETS_ID])
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert crypto.decrypt(SecretField.SHEETS_ID, first) == crypto.decrypt(SecretField.SHEETS_ID, second)


def test_an_empty_value_survives_the_round_trip(crypto: VaultCrypto) -> None:
    assert crypto.decrypt(SecretField.SHEETS_RANGE, crypto.encrypt(SecretField.SHEETS_RANGE, "")) == ""


def test_a_russian_value_survives_the_round_trip(crypto: VaultCrypto) -> None:
    assert crypto.decrypt(SecretField.SHEETS_RANGE, crypto.encrypt(SecretField.SHEETS_RANGE, "Лист1!A:F")) == (
        "Лист1!A:F"
    )


# --- аутентификация: подмена ломает расшифровку, а не даёт мусор


def test_a_flipped_ciphertext_byte_breaks_decryption(crypto: VaultCrypto) -> None:
    blob: EncryptedField = crypto.encrypt(SecretField.KEY_FORM_URL, VALUES[SecretField.KEY_FORM_URL])
    tampered: EncryptedField = EncryptedField(nonce=blob.nonce, ciphertext=_flip_first_byte(blob.ciphertext))
    with pytest.raises(VaultDecryptError):
        crypto.decrypt(SecretField.KEY_FORM_URL, tampered)


def test_a_flipped_nonce_byte_breaks_decryption(crypto: VaultCrypto) -> None:
    blob: EncryptedField = crypto.encrypt(SecretField.KEY_FORM_URL, VALUES[SecretField.KEY_FORM_URL])
    tampered: EncryptedField = EncryptedField(nonce=_flip_first_byte(blob.nonce), ciphertext=blob.ciphertext)
    with pytest.raises(VaultDecryptError):
        crypto.decrypt(SecretField.KEY_FORM_URL, tampered)


def test_a_changed_salt_breaks_decryption(crypto: VaultCrypto) -> None:
    """Соль файла входит в HKDF: подмена соли даёт другой ключ, и блоб не читается."""
    blob: EncryptedField = crypto.encrypt(SecretField.SHEETS_ID, VALUES[SecretField.SHEETS_ID])
    with pytest.raises(VaultDecryptError):
        VaultCrypto(key=VAULT_KEY, salt=OTHER_SALT).decrypt(SecretField.SHEETS_ID, blob)


def test_another_vault_key_does_not_decrypt(crypto: VaultCrypto) -> None:
    blob: EncryptedField = crypto.encrypt(SecretField.SHEETS_ID, VALUES[SecretField.SHEETS_ID])
    with pytest.raises(VaultDecryptError):
        VaultCrypto(key=OTHER_KEY, salt=SALT).decrypt(SecretField.SHEETS_ID, blob)


def test_a_blob_moved_to_another_field_does_not_decrypt(crypto: VaultCrypto) -> None:
    """Главная проверка привязки: блоб sheets_id, подставленный в key_form_url, не читается (§7.3, AAD)."""
    blob: EncryptedField = crypto.encrypt(SecretField.SHEETS_ID, VALUES[SecretField.SHEETS_ID])
    with pytest.raises(VaultDecryptError):
        crypto.decrypt(SecretField.KEY_FORM_URL, blob)


@pytest.mark.parametrize("field", ALL_FIELDS, ids=lambda item: item.value)
def test_no_field_accepts_a_blob_of_any_other_field(crypto: VaultCrypto, field: SecretField) -> None:
    blob: EncryptedField = crypto.encrypt(field, VALUES[field])
    for other in ALL_FIELDS:
        if other is field:
            continue
        with pytest.raises(VaultDecryptError):
            crypto.decrypt(other, blob)


def test_the_decrypt_error_text_carries_neither_value_nor_key(crypto: VaultCrypto) -> None:
    """§7.4: тексты исключений секретов не содержат — только имя поля и версию формата."""
    value: str = VALUES[SecretField.OPENAI_API_KEY]
    blob: EncryptedField = crypto.encrypt(SecretField.OPENAI_API_KEY, value)
    with pytest.raises(VaultDecryptError) as raised:
        crypto.decrypt(SecretField.KEY_FORM_URL, blob)
    text: str = str(raised.value)
    assert value not in text and value[:8] not in text
    assert VAULT_KEY.hex() not in text and base64.b64encode(VAULT_KEY).decode("ascii") not in text
    assert SALT.hex() not in text
    assert SecretField.KEY_FORM_URL.value in text and str(FORMAT_VERSION) in text


# --- объект с негодными полями дальше не идёт


@pytest.mark.parametrize("key", [b"", b"short", bytes(VAULT_KEY_BYTES - 1), bytes(VAULT_KEY_BYTES + 1)])
def test_a_vault_key_of_the_wrong_length_is_refused(key: bytes) -> None:
    with pytest.raises(VaultFormatError) as raised:
        VaultCrypto(key=key, salt=SALT)
    assert raised.value.reason is VaultFormatReason.KEY_INVALID
    assert str(VAULT_KEY_BYTES) in raised.value.detail


@pytest.mark.parametrize("salt", [b"", bytes(SALT_BYTES - 1), bytes(SALT_BYTES + 1)])
def test_a_salt_of_the_wrong_length_is_refused(salt: bytes) -> None:
    with pytest.raises(VaultFormatError) as raised:
        VaultCrypto(key=VAULT_KEY, salt=salt)
    assert raised.value.reason is VaultFormatReason.KEY_INVALID
    assert str(SALT_BYTES) in raised.value.detail


def test_the_refusal_text_carries_no_key_bytes() -> None:
    with pytest.raises(VaultFormatError) as raised:
        VaultCrypto(key=b"secret-but-too-short", salt=SALT)
    assert "secret-but-too-short" not in str(raised.value)
    assert "secret-but-too-short" not in raised.value.log_line


# --- файл сейфа: render и parse


def test_an_empty_file_gets_its_own_random_salt() -> None:
    first: VaultFile = VaultFile.empty()
    second: VaultFile = VaultFile.empty()
    assert len(first.salt) == SALT_BYTES and first.fields == {}
    assert first.version == FORMAT_VERSION
    assert first.salt != second.salt


def test_render_has_the_shape_section_seven_names(crypto: VaultCrypto) -> None:
    """{"version": 1, "salt": base64, "fields": {"<имя>": {"nonce": base64, "ct": base64}}} (§7.3)."""
    blob: EncryptedField = crypto.encrypt(SecretField.SHEETS_ID, VALUES[SecretField.SHEETS_ID])
    text: str = VaultFile(version=FORMAT_VERSION, salt=SALT, fields={SecretField.SHEETS_ID.value: blob}).render()
    data: Any = json.loads(text)
    assert data[KEY_VERSION] == FORMAT_VERSION
    assert base64.b64decode(data[KEY_SALT], validate=True) == SALT
    record: Any = data[KEY_FIELDS][SecretField.SHEETS_ID.value]
    assert sorted(record) == sorted((KEY_NONCE, KEY_CIPHERTEXT))
    assert base64.b64decode(record[KEY_NONCE], validate=True) == blob.nonce
    assert base64.b64decode(record[KEY_CIPHERTEXT], validate=True) == blob.ciphertext


def test_render_carries_no_plaintext(crypto: VaultCrypto) -> None:
    fields: dict[str, EncryptedField] = {
        field.value: crypto.encrypt(field, VALUES[field]) for field in ALL_FIELDS
    }
    text: str = VaultFile(version=FORMAT_VERSION, salt=SALT, fields=fields).render()
    for value in VALUES.values():
        assert value not in text


def test_parse_gives_back_the_same_object(crypto: VaultCrypto) -> None:
    fields: dict[str, EncryptedField] = {
        field.value: crypto.encrypt(field, VALUES[field]) for field in ALL_FIELDS
    }
    original: VaultFile = VaultFile(version=FORMAT_VERSION, salt=SALT, fields=fields)
    restored: VaultFile = VaultFile.parse(original.render())
    assert restored == original


def test_values_still_decrypt_after_a_round_trip_through_the_file(crypto: VaultCrypto) -> None:
    """То, ради чего файл существует: значения читаются после записи и разбора."""
    fields: dict[str, EncryptedField] = {
        field.value: crypto.encrypt(field, VALUES[field]) for field in ALL_FIELDS
    }
    restored: VaultFile = VaultFile.parse(VaultFile(version=FORMAT_VERSION, salt=SALT, fields=fields).render())
    reader: VaultCrypto = VaultCrypto(key=VAULT_KEY, salt=restored.salt)
    for field in ALL_FIELDS:
        assert reader.decrypt(field, restored.fields[field.value]) == VALUES[field]


def test_an_empty_file_round_trips() -> None:
    empty: VaultFile = VaultFile.empty()
    assert VaultFile.parse(empty.render()) == empty


# --- файл сейфа: отказы вместо тихого игнорирования


@pytest.mark.parametrize("version", [0, 2, 99, "1", None, 1.0, True, [1], {"v": 1}])
def test_an_unknown_format_version_is_an_error(version: Any) -> None:
    """§7.3: неизвестная версия формата — ошибка с именем файла и код 2, а не тихое игнорирование."""
    text: str = json.dumps(
        {KEY_VERSION: version, KEY_SALT: base64.b64encode(SALT).decode("ascii"), KEY_FIELDS: {}}
    )
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    assert raised.value.reason is VaultFormatReason.UNSUPPORTED_VERSION
    assert str(FORMAT_VERSION) in raised.value.detail


@pytest.mark.parametrize("text", ["", "не json", "[]", '"строка"', "42", "{"])
def test_a_file_that_is_not_a_json_object_is_an_error(text: str) -> None:
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    assert raised.value.reason is VaultFormatReason.DAMAGED


@pytest.mark.parametrize(
    "salt",
    ["не base64!", "", None, 42, base64.b64encode(bytes(SALT_BYTES - 1)).decode("ascii")],
)
def test_a_broken_salt_is_an_error(salt: Any) -> None:
    text: str = json.dumps({KEY_VERSION: FORMAT_VERSION, KEY_SALT: salt, KEY_FIELDS: {}})
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    assert raised.value.reason is VaultFormatReason.DAMAGED
    assert KEY_SALT in raised.value.detail


def test_a_missing_fields_key_is_an_error() -> None:
    text: str = json.dumps({KEY_VERSION: FORMAT_VERSION, KEY_SALT: base64.b64encode(SALT).decode("ascii")})
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    assert raised.value.reason is VaultFormatReason.DAMAGED
    assert KEY_FIELDS in raised.value.detail


@pytest.mark.parametrize(
    "record",
    [
        {},
        {KEY_NONCE: base64.b64encode(bytes(NONCE_BYTES)).decode("ascii")},
        {KEY_CIPHERTEXT: base64.b64encode(b"x").decode("ascii")},
        {KEY_NONCE: "не base64!", KEY_CIPHERTEXT: base64.b64encode(b"x").decode("ascii")},
        {KEY_NONCE: base64.b64encode(bytes(NONCE_BYTES)).decode("ascii"), KEY_CIPHERTEXT: "мусор!"},
        {KEY_NONCE: "", KEY_CIPHERTEXT: ""},
        {KEY_NONCE: 42, KEY_CIPHERTEXT: 42},
        {KEY_NONCE: base64.b64encode(bytes(NONCE_BYTES - 1)).decode("ascii"), KEY_CIPHERTEXT: "eHg="},
        "строка вместо записи",
        None,
    ],
)
def test_a_broken_field_record_is_an_error_naming_the_field(record: Any) -> None:
    text: str = json.dumps(
        {
            KEY_VERSION: FORMAT_VERSION,
            KEY_SALT: base64.b64encode(SALT).decode("ascii"),
            KEY_FIELDS: {SecretField.KEY_FORM_URL.value: record},
        }
    )
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    assert raised.value.reason is VaultFormatReason.DAMAGED
    assert SecretField.KEY_FORM_URL.value in raised.value.detail


def test_the_format_error_text_carries_no_secret_material(crypto: VaultCrypto) -> None:
    """Даже когда ломается разбор, в тексте нет ни ключа сейфа, ни соли, ни значения."""
    text: str = json.dumps(
        {KEY_VERSION: 7, KEY_SALT: base64.b64encode(SALT).decode("ascii"), KEY_FIELDS: {}}
    )
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    for message in (str(raised.value), raised.value.log_line):
        assert VAULT_KEY.hex() not in message
        assert base64.b64encode(SALT).decode("ascii") not in message
        assert all(value not in message for value in VALUES.values())


# --- константы формата


def test_the_format_constants_are_the_ones_section_seven_names() -> None:
    assert FORMAT_VERSION == 1
    assert HKDF_INFO == b"livecraft.vault.v1"
    assert (VAULT_KEY_BYTES, SALT_BYTES, NONCE_BYTES) == (32, 16, 12)


# --- запись «key»: завёрнутый ключ файла (§14, решение 9)


WRAPPED_KEY: bytes = b"blob, \x00\xff\x01 which DPAPI would have produced"


def test_a_file_without_a_key_record_renders_without_it(crypto: VaultCrypto) -> None:
    """Так выглядит поставочный файл: ключ приходит извне, записи «key» в нём нет и быть не должно."""
    text: str = VaultFile(version=FORMAT_VERSION, salt=SALT, fields={}).render()
    assert KEY_WRAPPED not in text
    assert KEY_WRAPPED not in json.loads(text)


def test_a_file_with_a_key_record_renders_and_parses_back() -> None:
    """Так выглядит локальный файл: свой ключ лежит в нём пятой записью."""
    original: VaultFile = VaultFile(
        version=FORMAT_VERSION, salt=SALT, fields={}, wrapped_key=WRAPPED_KEY
    )
    text: str = original.render()
    assert base64.b64decode(json.loads(text)[KEY_WRAPPED], validate=True) == WRAPPED_KEY
    assert VaultFile.parse(text) == original


def test_a_file_without_a_key_record_parses_with_none() -> None:
    text: str = json.dumps(
        {KEY_VERSION: FORMAT_VERSION, KEY_SALT: base64.b64encode(SALT).decode("ascii"), KEY_FIELDS: {}}
    )
    assert VaultFile.parse(text).wrapped_key is None


def test_an_empty_file_carries_no_key() -> None:
    assert VaultFile.empty().wrapped_key is None


def test_fields_and_a_key_record_live_together(crypto: VaultCrypto) -> None:
    fields: dict[str, EncryptedField] = {
        field.value: crypto.encrypt(field, VALUES[field]) for field in ALL_FIELDS
    }
    original: VaultFile = VaultFile(
        version=FORMAT_VERSION, salt=SALT, fields=fields, wrapped_key=WRAPPED_KEY
    )
    restored: VaultFile = VaultFile.parse(original.render())
    assert restored == original
    reader: VaultCrypto = VaultCrypto(key=VAULT_KEY, salt=restored.salt)
    for field in ALL_FIELDS:
        assert reader.decrypt(field, restored.fields[field.value]) == VALUES[field]


@pytest.mark.parametrize("wrapped", ["не base64!", "", None, 42, [], {}])
def test_a_broken_key_record_is_an_error(wrapped: Any) -> None:
    """Запись есть, но прочитать её нельзя — ошибка формата, а не «ключа нет»."""
    text: str = json.dumps(
        {
            KEY_VERSION: FORMAT_VERSION,
            KEY_SALT: base64.b64encode(SALT).decode("ascii"),
            KEY_FIELDS: {},
            KEY_WRAPPED: wrapped,
        }
    )
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    assert raised.value.reason is VaultFormatReason.DAMAGED
    assert repr(KEY_WRAPPED) in raised.value.detail


def test_the_key_record_error_carries_no_key_material() -> None:
    text: str = json.dumps(
        {
            KEY_VERSION: FORMAT_VERSION,
            KEY_SALT: base64.b64encode(SALT).decode("ascii"),
            KEY_FIELDS: {},
            KEY_WRAPPED: "секретный мусор!",
        }
    )
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    assert "секретный мусор" not in str(raised.value)
    assert "секретный мусор" not in raised.value.log_line


# --- ошибка формата: причина для человека, подробность — только в лог (D4)


def _parse_error(text: str) -> VaultFormatError:
    with pytest.raises(VaultFormatError) as raised:
        VaultFile.parse(text)
    return raised.value


def test_every_reason_has_a_russian_text() -> None:
    assert set(msg.VAULT_FORMAT_REASON_TEXT) == {reason.value for reason in VaultFormatReason}
    for reason in VaultFormatReason:
        assert reason.human == msg.VAULT_FORMAT_REASON_TEXT[reason.value]


def test_the_text_of_the_error_is_the_human_line_without_the_detail() -> None:
    error: VaultFormatError = _parse_error("не json")
    assert str(error) == error.human
    assert error.detail and error.detail not in str(error)
    assert error.reason.human in str(error)


def test_an_unlocated_error_names_only_the_reason_and_the_supplied_advice() -> None:
    error: VaultFormatError = _parse_error("[]")
    assert (error.file_name, error.source) == (None, None)
    assert error.problem == VaultFormatReason.DAMAGED.human
    assert not error.is_replaceable
    assert error.human == msg.VAULT_FILE_BROKEN.format(
        problem=VaultFormatReason.DAMAGED.human, advice=msg.VAULT_FILE_ADVICE_SUPPLIED
    )


@pytest.mark.parametrize(
    ("source", "advice", "is_replaceable"),
    [
        (VaultSource.LOCAL, msg.VAULT_FILE_ADVICE_LOCAL, True),
        (VaultSource.SUPPLIED, msg.VAULT_FILE_ADVICE_SUPPLIED, False),
    ],
)
def test_located_keeps_the_reason_and_detail_and_names_the_file(
    source: VaultSource, advice: str, is_replaceable: bool
) -> None:
    original: VaultFormatError = _parse_error(json.dumps({KEY_VERSION: 7, KEY_SALT: "", KEY_FIELDS: {}}))
    located: VaultFormatError = original.located("vault.local.dat", source)
    assert (located.reason, located.detail) == (original.reason, original.detail)
    assert (located.file_name, located.source) == ("vault.local.dat", source)
    assert located.is_replaceable is is_replaceable
    assert located.advice == advice
    assert located.problem == msg.VAULT_FILE_PROBLEM.format(
        file="vault.local.dat", reason=VaultFormatReason.UNSUPPORTED_VERSION.human
    )
    assert str(located) == msg.VAULT_FILE_BROKEN.format(problem=located.problem, advice=advice)


def test_the_log_line_carries_file_source_reason_and_detail() -> None:
    error: VaultFormatError = _parse_error("{").located("vault.dat", VaultSource.SUPPLIED)
    line: str = error.log_line
    assert "file=vault.dat" in line and "source=supplied" in line
    assert f"reason={VaultFormatReason.DAMAGED.value}" in line
    assert f"detail={error.detail}" in line


def test_the_log_line_of_an_unlocated_error_marks_file_and_source_absent() -> None:
    error: VaultFormatError = _parse_error("{")
    assert error.log_line.startswith("file=- source=- reason=damaged detail=")
