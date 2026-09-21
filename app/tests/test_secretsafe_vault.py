from __future__ import annotations

import pytest

from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultEntry, VaultOrigin
from app.ui import messages_ru as msg

VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789dc7f",
    SecretField.SHEETS_ID: "1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.SHEETS_RANGE: "A:F",
    SecretField.KEY_FORM_URL: "https://docs.google.com/forms/d/e/1FAIpQLSf-secret/viewform",
}
ALL_FIELDS: tuple[SecretField, ...] = tuple(SecretField)


def _secret(field: SecretField) -> SecretValue:
    return SecretValue(field=field, value=VALUES[field])


def _vault(*fields: SecretField, origin: VaultOrigin = VaultOrigin.SUPPLIED) -> Vault:
    """Сейф с перечисленными полями — собирается тем же путём, которым его соберёт VaultStore."""
    vault: Vault = Vault.empty()
    for field in fields:
        vault = vault.with_field(field, _secret(field), origin)
    return vault


@pytest.fixture
def full_vault() -> Vault:
    return _vault(*ALL_FIELDS)


# --- чего не хватает для запуска


def test_an_empty_vault_is_not_ready_and_lists_every_field() -> None:
    """Порядок перечисления — порядок объявления SecretField, а не случайный порядок словаря."""
    empty: Vault = Vault.empty()
    assert not empty.is_ready
    assert empty.missing == ALL_FIELDS
    assert empty.entries == {}


def test_a_vault_with_three_fields_names_exactly_the_absent_one() -> None:
    vault: Vault = _vault(SecretField.OPENAI_API_KEY, SecretField.SHEETS_ID, SecretField.SHEETS_RANGE)
    assert not vault.is_ready
    assert vault.missing == (SecretField.KEY_FORM_URL,)


@pytest.mark.parametrize("absent", ALL_FIELDS, ids=lambda item: item.value)
def test_any_single_absent_field_keeps_the_vault_not_ready(absent: SecretField) -> None:
    vault: Vault = _vault(*(field for field in ALL_FIELDS if field is not absent))
    assert not vault.is_ready and vault.missing == (absent,)


def test_a_full_vault_is_ready(full_vault: Vault) -> None:
    assert full_vault.is_ready
    assert full_vault.missing == ()
    assert full_vault.admission_reason is None


def test_the_missing_order_follows_the_field_order() -> None:
    """Поля добавлены в обратном порядке — перечень недостающих всё равно в порядке объявления."""
    vault: Vault = _vault(SecretField.KEY_FORM_URL, SecretField.SHEETS_RANGE)
    assert vault.missing == (SecretField.OPENAI_API_KEY, SecretField.SHEETS_ID)


# --- причину недопуска строит сам сейф


def test_the_admission_reason_names_the_absent_fields_in_russian() -> None:
    vault: Vault = _vault(SecretField.OPENAI_API_KEY, SecretField.SHEETS_RANGE)
    reason: str | None = vault.admission_reason
    assert reason == msg.VAULT_NOT_READY.format(
        fields=f"{msg.VAULT_FIELD_SHEETS_ID}, {msg.VAULT_FIELD_KEY_FORM_URL}"
    )
    assert msg.VAULT_FIELD_OPENAI_API_KEY not in reason      # это поле на месте, о нём не говорим
    assert "--setup" not in reason      # что делать, говорит main один раз — SETUP_REQUIRED


def test_the_admission_reason_of_an_empty_vault_lists_all_four_labels() -> None:
    reason: str | None = Vault.empty().admission_reason
    assert reason is not None
    for field in ALL_FIELDS:
        assert field.human_label in reason


def test_the_admission_reason_carries_no_value(full_vault: Vault) -> None:
    """Причина рассказывает, чего нет; про то, что есть, она не проговаривается (§7.4)."""
    vault: Vault = full_vault.without_field(SecretField.KEY_FORM_URL)
    reason: str | None = vault.admission_reason
    assert reason is not None
    for value in VALUES.values():
        assert value not in reason


# --- значение и происхождение поля


def test_get_returns_the_secret_object_and_none_for_an_absent_field() -> None:
    vault: Vault = _vault(SecretField.SHEETS_ID)
    secret: SecretValue | None = vault.get(SecretField.SHEETS_ID)
    assert secret == _secret(SecretField.SHEETS_ID)
    assert vault.get(SecretField.KEY_FORM_URL) is None


def test_each_field_keeps_its_own_origin() -> None:
    """Часть полей пришла со сборкой, часть вписал пользователь — сейф помнит это по каждому полю (§7.3)."""
    vault: Vault = (
        Vault.empty()
        .with_field(SecretField.OPENAI_API_KEY, _secret(SecretField.OPENAI_API_KEY), VaultOrigin.SUPPLIED)
        .with_field(SecretField.SHEETS_ID, _secret(SecretField.SHEETS_ID), VaultOrigin.OWN)
    )
    assert vault.origin_of(SecretField.OPENAI_API_KEY) is VaultOrigin.SUPPLIED
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert vault.origin_of(SecretField.KEY_FORM_URL) is None


def test_origin_labels_come_from_messages_ru() -> None:
    assert VaultOrigin.SUPPLIED.human_label == msg.VAULT_ORIGIN_SUPPLIED
    assert VaultOrigin.OWN.human_label == msg.VAULT_ORIGIN_OWN


def test_origin_values_are_english_identifiers() -> None:
    """Значение enum уходит в лог, поэтому английское; русское — только в human_label (§11)."""
    assert [origin.value for origin in VaultOrigin] == ["supplied", "own"]


def test_the_entry_shows_a_mask_and_a_log_label() -> None:
    entry: VaultEntry = VaultEntry(secret=_secret(SecretField.KEY_FORM_URL), origin=VaultOrigin.OWN)
    assert entry.masked == _secret(SecretField.KEY_FORM_URL).masked
    assert entry.log_label == _secret(SecretField.KEY_FORM_URL).log_label
    assert VALUES[SecretField.KEY_FORM_URL] not in entry.masked + entry.log_label


# --- сейф неизменяемый


def test_with_field_returns_a_new_vault_and_leaves_the_old_one_alone() -> None:
    before: Vault = _vault(SecretField.SHEETS_ID)
    after: Vault = before.with_field(
        SecretField.KEY_FORM_URL, _secret(SecretField.KEY_FORM_URL), VaultOrigin.OWN
    )
    assert after is not before
    assert before.get(SecretField.KEY_FORM_URL) is None
    assert after.get(SecretField.KEY_FORM_URL) is not None
    assert before.missing == (SecretField.OPENAI_API_KEY, SecretField.SHEETS_RANGE, SecretField.KEY_FORM_URL)


def test_with_field_replaces_a_field_it_already_has() -> None:
    """Настройщик заменяет поставочное значение своим: новое поле и новое происхождение."""
    supplied: Vault = _vault(SecretField.SHEETS_ID, origin=VaultOrigin.SUPPLIED)
    own_secret: SecretValue = SecretValue(field=SecretField.SHEETS_ID, value="своя-таблица-1234567890")
    replaced: Vault = supplied.with_field(SecretField.SHEETS_ID, own_secret, VaultOrigin.OWN)
    assert replaced.get(SecretField.SHEETS_ID) == own_secret
    assert replaced.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert supplied.origin_of(SecretField.SHEETS_ID) is VaultOrigin.SUPPLIED


def test_without_field_returns_a_new_vault_and_leaves_the_old_one_alone(full_vault: Vault) -> None:
    reduced: Vault = full_vault.without_field(SecretField.SHEETS_RANGE)
    assert reduced is not full_vault
    assert reduced.missing == (SecretField.SHEETS_RANGE,)
    assert full_vault.is_ready


def test_without_an_absent_field_is_quiet() -> None:
    vault: Vault = _vault(SecretField.SHEETS_ID)
    assert vault.without_field(SecretField.KEY_FORM_URL).missing == vault.missing


def test_the_vault_object_is_frozen(full_vault: Vault) -> None:
    with pytest.raises(Exception):
        full_vault.entries = {}          # type: ignore[misc]


# --- что сейф отдаёт фильтру логов и что пишет о себе


def test_secrets_returns_objects_whose_text_is_a_mask(full_vault: Vault) -> None:
    secrets: tuple[SecretValue, ...] = full_vault.secrets()
    assert len(secrets) == len(ALL_FIELDS)
    assert all(isinstance(secret, SecretValue) for secret in secrets)
    for secret in secrets:
        assert f"{secret}" == secret.masked
        assert VALUES[secret.field] not in f"{secret}"


def test_secrets_of_an_empty_vault_is_empty() -> None:
    assert Vault.empty().secrets() == ()


def test_secrets_follow_the_field_order() -> None:
    vault: Vault = _vault(SecretField.KEY_FORM_URL, SecretField.OPENAI_API_KEY)
    assert [secret.field for secret in vault.secrets()] == [
        SecretField.OPENAI_API_KEY,
        SecretField.KEY_FORM_URL,
    ]


def test_the_log_line_carries_labels_fingerprints_and_origins(full_vault: Vault) -> None:
    vault: Vault = full_vault.with_field(
        SecretField.SHEETS_ID, _secret(SecretField.SHEETS_ID), VaultOrigin.OWN
    )
    line: str = vault.log_line
    for field in ALL_FIELDS:
        secret: SecretValue = _secret(field)
        assert f"{field.log_label}({secret.fingerprint})" in line
    assert f"sheets-plan({_secret(SecretField.SHEETS_ID).fingerprint})=own" in line
    assert f"openai-key({_secret(SecretField.OPENAI_API_KEY).fingerprint})=supplied" in line


def test_the_log_line_carries_no_value_and_no_russian(full_vault: Vault) -> None:
    """Строка машинная: ни значения, ни русского названия поля (§7.4, §11)."""
    line: str = full_vault.log_line
    for value in VALUES.values():
        assert value not in line
    for field in ALL_FIELDS:
        assert field.human_label not in line
    assert line.isascii()


def test_the_log_line_of_an_empty_vault_is_a_dash() -> None:
    assert Vault.empty().log_line == "-"
