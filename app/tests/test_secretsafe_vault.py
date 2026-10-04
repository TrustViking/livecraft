from __future__ import annotations

import pytest

from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault, VaultEntry
from app.ui import messages_ru as msg

VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789dc7f",
    SecretField.SHEETS_ID: "1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.TELEGRAM_BOT_TOKEN: "123456789:AAFsecret-Ab3dEfGhIjKlMnOpQrStUvWxYz_012",
    SecretField.DRIVE_FOLDER: "1secret-DrIvEfOlDeR_0123456789-abcd",
    SecretField.SUPPORT_BOT_TOKEN: "987654321:AAFsupport-Zy9xWvUtSrQpOnMlKjIhGfEdCbA_987",
}
ALL_FIELDS: tuple[SecretField, ...] = tuple(SecretField)


def _secret(field: SecretField) -> SecretValue:
    return SecretValue(field=field, value=VALUES[field])


def _vault(*fields: SecretField, origin: VaultOrigin = VaultOrigin.TOKEN) -> Vault:
    """Сейф с перечисленными полями — собирается тем же путём, которым его соберёт VaultStore."""
    vault: Vault = Vault.empty()
    for field in fields:
        vault = vault.with_field(field, _secret(field), origin)
    return vault


@pytest.fixture
def full_vault() -> Vault:
    return _vault(*ALL_FIELDS)


# --- поля сейфа


def test_the_fields_are_the_current_ones() -> None:
    """Устаревшие поля (диапазон таблицы, ссылка на форму) ушли на этапе «Токен доступа» (§13 задача 7.1); токен бота
    поддержки — своё поле, отдельное от бота объявлений (§14 решение 58)."""
    assert ALL_FIELDS == (
        SecretField.OPENAI_API_KEY, SecretField.SHEETS_ID, SecretField.TELEGRAM_BOT_TOKEN, SecretField.DRIVE_FOLDER,
        SecretField.SUPPORT_BOT_TOKEN,
    )


def test_an_empty_vault_has_no_entries() -> None:
    assert Vault.empty().entries == {}


def test_the_bot_token_goes_to_the_log_filter_and_not_into_the_log_line() -> None:
    """Токен бота стоит в адресе Bot API: фильтр логов обязан его вычёркивать, а строка сейфа — только ярлык (§7.4)."""
    vault: Vault = _vault(SecretField.TELEGRAM_BOT_TOKEN)
    assert [secret.field for secret in vault.secrets()] == [SecretField.TELEGRAM_BOT_TOKEN]
    assert VALUES[SecretField.TELEGRAM_BOT_TOKEN] not in vault.log_line
    assert SecretField.TELEGRAM_BOT_TOKEN.log_label in vault.log_line


# --- значение и происхождение поля


def test_get_returns_the_secret_object_and_none_for_an_absent_field() -> None:
    vault: Vault = _vault(SecretField.SHEETS_ID)
    secret: SecretValue | None = vault.get(SecretField.SHEETS_ID)
    assert secret == _secret(SecretField.SHEETS_ID)
    assert vault.get(SecretField.DRIVE_FOLDER) is None


def test_each_field_keeps_its_own_origin() -> None:
    """Часть полей пришла в токене, часть вписал пользователь — сейф помнит это по каждому полю (§7.3)."""
    vault: Vault = (
        Vault.empty()
        .with_field(SecretField.OPENAI_API_KEY, _secret(SecretField.OPENAI_API_KEY), VaultOrigin.TOKEN)
        .with_field(SecretField.SHEETS_ID, _secret(SecretField.SHEETS_ID), VaultOrigin.OWN)
    )
    assert vault.origin_of(SecretField.OPENAI_API_KEY) is VaultOrigin.TOKEN
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert vault.origin_of(SecretField.DRIVE_FOLDER) is None


def test_origin_labels_come_from_messages_ru() -> None:
    assert VaultOrigin.TOKEN.human_label == msg.VAULT_ORIGIN_TOKEN == "получено с токеном"
    assert VaultOrigin.OWN.human_label == msg.VAULT_ORIGIN_OWN == "введено в окне настройки"


def test_origin_values_are_english_identifiers() -> None:
    """Значение enum уходит в лог, поэтому английское; русское — только в human_label (§11)."""
    assert [origin.value for origin in VaultOrigin] == ["token", "own"]


def test_the_entry_shows_a_mask_and_a_log_label() -> None:
    entry: VaultEntry = VaultEntry(secret=_secret(SecretField.DRIVE_FOLDER), origin=VaultOrigin.OWN)
    assert entry.masked == _secret(SecretField.DRIVE_FOLDER).masked
    assert entry.log_label == _secret(SecretField.DRIVE_FOLDER).log_label
    assert VALUES[SecretField.DRIVE_FOLDER] not in entry.masked + entry.log_label


# --- сейф неизменяемый


def test_with_field_returns_a_new_vault_and_leaves_the_old_one_alone() -> None:
    before: Vault = _vault(SecretField.SHEETS_ID)
    after: Vault = before.with_field(SecretField.DRIVE_FOLDER, _secret(SecretField.DRIVE_FOLDER), VaultOrigin.OWN)
    assert after is not before
    assert before.get(SecretField.DRIVE_FOLDER) is None
    assert after.get(SecretField.DRIVE_FOLDER) is not None
    assert before.missing_of(ALL_FIELDS) == (
        SecretField.OPENAI_API_KEY, SecretField.TELEGRAM_BOT_TOKEN, SecretField.DRIVE_FOLDER,
        SecretField.SUPPORT_BOT_TOKEN,
    )


def test_with_field_replaces_a_field_it_already_has() -> None:
    """Настройщик заменяет значение из токена своим: новое поле и новое происхождение."""
    from_token: Vault = _vault(SecretField.SHEETS_ID, origin=VaultOrigin.TOKEN)
    own_secret: SecretValue = SecretValue(field=SecretField.SHEETS_ID, value="своя-таблица-1234567890")
    replaced: Vault = from_token.with_field(SecretField.SHEETS_ID, own_secret, VaultOrigin.OWN)
    assert replaced.get(SecretField.SHEETS_ID) == own_secret
    assert replaced.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert from_token.origin_of(SecretField.SHEETS_ID) is VaultOrigin.TOKEN


def test_without_field_returns_a_new_vault_and_leaves_the_old_one_alone(full_vault: Vault) -> None:
    reduced: Vault = full_vault.without_field(SecretField.SHEETS_ID)
    assert reduced is not full_vault
    assert reduced.missing_of(ALL_FIELDS) == (SecretField.SHEETS_ID,)
    assert full_vault.missing_of(ALL_FIELDS) == ()


def test_without_an_absent_field_is_quiet() -> None:
    vault: Vault = _vault(SecretField.SHEETS_ID)
    assert vault.without_field(SecretField.DRIVE_FOLDER) == vault


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
    vault: Vault = _vault(SecretField.DRIVE_FOLDER, SecretField.OPENAI_API_KEY)
    assert [secret.field for secret in vault.secrets()] == [SecretField.OPENAI_API_KEY, SecretField.DRIVE_FOLDER]


def test_the_log_line_carries_labels_fingerprints_and_origins(full_vault: Vault) -> None:
    vault: Vault = full_vault.with_field(SecretField.SHEETS_ID, _secret(SecretField.SHEETS_ID), VaultOrigin.OWN)
    line: str = vault.log_line
    for field in ALL_FIELDS:
        secret: SecretValue = _secret(field)
        assert f"{field.log_label}({secret.fingerprint})" in line
    assert f"sheets-plan({_secret(SecretField.SHEETS_ID).fingerprint})=own" in line
    assert f"openai-key({_secret(SecretField.OPENAI_API_KEY).fingerprint})=token" in line


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


# --- один поиск поля, наложение слоёв и слой одного происхождения


def test_an_entry_is_the_secret_with_its_origin() -> None:
    vault: Vault = _vault(SecretField.SHEETS_ID, origin=VaultOrigin.OWN)
    assert vault.entry(SecretField.SHEETS_ID) == VaultEntry(secret=_secret(SecretField.SHEETS_ID), origin=VaultOrigin.OWN)
    assert vault.entry(SecretField.OPENAI_API_KEY) is None
    assert vault.get(SecretField.SHEETS_ID) == _secret(SecretField.SHEETS_ID)
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN


def test_the_own_layer_laid_over_the_token_one_wins() -> None:
    """Правило §7.3 одно: поле своего слоя перекрывает поле из токена, остальные поля токена остаются."""
    from_token: Vault = _vault(SecretField.OPENAI_API_KEY, SecretField.SHEETS_ID)
    own: Vault = _vault(SecretField.SHEETS_ID, SecretField.DRIVE_FOLDER, origin=VaultOrigin.OWN)
    vault: Vault = from_token.overlaid_by(own)
    assert vault.origin_of(SecretField.OPENAI_API_KEY) is VaultOrigin.TOKEN
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert vault.origin_of(SecretField.DRIVE_FOLDER) is VaultOrigin.OWN
    assert from_token.origin_of(SecretField.SHEETS_ID) is VaultOrigin.TOKEN       # прежний сейф не меняется


def test_only_one_origin_is_a_layer() -> None:
    vault: Vault = _vault(SecretField.OPENAI_API_KEY).overlaid_by(_vault(SecretField.SHEETS_ID, origin=VaultOrigin.OWN))
    assert tuple(vault.only(VaultOrigin.OWN).entries) == (SecretField.SHEETS_ID,)
    assert tuple(vault.only(VaultOrigin.TOKEN).entries) == (SecretField.OPENAI_API_KEY,)


def test_missing_of_names_the_absent_fields_in_the_given_order() -> None:
    vault: Vault = _vault(SecretField.SHEETS_ID)
    wanted: tuple[SecretField, ...] = (SecretField.DRIVE_FOLDER, SecretField.SHEETS_ID, SecretField.OPENAI_API_KEY)
    assert vault.missing_of(wanted) == (SecretField.DRIVE_FOLDER, SecretField.OPENAI_API_KEY)
