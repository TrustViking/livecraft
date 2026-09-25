from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.paths import LivecraftPaths
from app.secretsafe.crypto import (
    FORMAT_VERSION,
    KEY_CIPHERTEXT,
    KEY_FIELDS,
    KEY_SALT,
    KEY_VERSION,
    KEY_WRAPPED,
    SALT_BYTES,
    VAULT_KEY_BYTES,
    EncryptedField,
    VaultCrypto,
    VaultFile,
    VaultFormatError,
    VaultFormatReason,
)
from app.secretsafe.dpapi import Dpapi, DpapiUnavailable
from app.secretsafe.store import (
    VAULT_FILE_ENCODING,
    LocalVaultState,
    ProgramKey,
    VaultLoad,
    VaultSource,
    VaultStore,
)
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.ui import messages_ru as msg

SUPPLIED_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-supplied-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1supplied-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.SHEETS_RANGE: "A:F",
    SecretField.KEY_FORM_URL: "https://docs.google.com/forms/d/e/1FAIpQLSf-supplied/viewform",
}
OWN_VALUES: dict[SecretField, str] = {
    SecretField.SHEETS_ID: "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table",
    SecretField.KEY_FORM_URL: "https://docs.google.com/forms/d/e/1FAIpQLSf-own/viewform",
}
PROGRAM_KEY: bytes = bytes(range(VAULT_KEY_BYTES))
ALL_FIELDS: tuple[SecretField, ...] = tuple(SecretField)


def _secret(field: SecretField, value: str) -> SecretValue:
    return SecretValue(field=field, value=value)


@pytest.fixture
def program_key_file(livecraft_paths: LivecraftPaths) -> Path:
    """Ключ поставочного сейфа в dev-режиме: файл secrets\\program.key (§7.3)."""
    livecraft_paths.program_key_file.write_bytes(PROGRAM_KEY)
    return livecraft_paths.program_key_file


@pytest.fixture
def store(livecraft_paths: LivecraftPaths, program_key_file: Path) -> VaultStore:
    """Сейф на временном корне с известным поставочным ключом — собирается боевым путём."""
    return VaultStore(
        supplied_path=livecraft_paths.vault_file,
        local_path=livecraft_paths.vault_local_file,
        program_key=ProgramKey.load(program_key_file),
        dpapi=Dpapi.load(),
    )


def _write_supplied(store: VaultStore, values: dict[SecretField, str]) -> bytes:
    """Поставочный файл так пишет сборка Артура: ключ снаружи, записи «key» в файле нет.

    Программа этот файл писать не умеет и не должна — поэтому в тесте он собирается напрямую из VaultFile.
    """
    salt: bytes = VaultFile.empty().salt
    crypto: VaultCrypto = VaultCrypto(key=PROGRAM_KEY, salt=salt)
    fields: dict[str, EncryptedField] = {
        field.value: crypto.encrypt(field, value) for field, value in values.items()
    }
    store.supplied_path.write_text(
        VaultFile(version=FORMAT_VERSION, salt=salt, fields=fields).render(), encoding=VAULT_FILE_ENCODING
    )
    return store.supplied_path.read_bytes()


def _own_vault(values: dict[SecretField, str]) -> Vault:
    vault: Vault = Vault.empty()
    for field, value in values.items():
        vault = vault.with_field(field, _secret(field, value), VaultOrigin.OWN)
    return vault


def _local_json(store: VaultStore) -> dict[str, Any]:
    return json.loads(store.local_path.read_text(encoding=VAULT_FILE_ENCODING))


def _rewrite_local(store: VaultStore, data: dict[str, Any]) -> None:
    store.local_path.write_text(json.dumps(data), encoding=VAULT_FILE_ENCODING)


# --- приоритет: локальное поверх поставочного (§7.3, таблица приоритета)


def test_a_local_field_overrides_the_supplied_one(store: VaultStore) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    vault: Vault = store.load().vault
    assert vault.is_ready
    for field in ALL_FIELDS:
        secret: SecretValue | None = vault.get(field)
        assert secret is not None
        expected: str = OWN_VALUES.get(field, SUPPLIED_VALUES[field])
        assert secret.reveal() == expected


def test_each_field_carries_the_origin_of_the_file_it_came_from(store: VaultStore) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    vault: Vault = store.load().vault
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert vault.origin_of(SecretField.KEY_FORM_URL) is VaultOrigin.OWN
    assert vault.origin_of(SecretField.OPENAI_API_KEY) is VaultOrigin.SUPPLIED
    assert vault.origin_of(SecretField.SHEETS_RANGE) is VaultOrigin.SUPPLIED


def test_without_a_local_file_the_vault_is_the_supplied_one(store: VaultStore) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    vault: Vault = store.load().vault
    assert vault.is_ready
    assert all(vault.origin_of(field) is VaultOrigin.SUPPLIED for field in ALL_FIELDS)


def test_without_a_supplied_file_the_vault_is_the_local_one(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    vault: Vault = store.load().vault
    assert not store.supplied_path.exists()
    assert vault.missing == (SecretField.OPENAI_API_KEY, SecretField.SHEETS_RANGE)
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN


def test_without_both_files_the_vault_is_empty_and_not_ready(store: VaultStore) -> None:
    """Чистая установка до настройщика: сейф пуст, запускаться не с чем (§8)."""
    vault: Vault = store.load().vault
    assert vault.entries == {}
    assert not vault.is_ready
    assert vault.missing == SecretField.current()      # устаревшая ссылка на форму не требуется
    assert vault.admission_reason is not None


# --- поставочный файл не переписывается никогда (§7.3)


def test_saving_the_local_vault_does_not_touch_the_supplied_file(store: VaultStore) -> None:
    """Сверка побайтно и по времени правки — обещание §7.4 «поставочный файл не изменился»."""
    before: bytes = _write_supplied(store, SUPPLIED_VALUES)
    stat_before: os.stat_result = store.supplied_path.stat()
    store.save_local(_own_vault(OWN_VALUES))
    store.save_local(_own_vault(OWN_VALUES))
    assert store.supplied_path.read_bytes() == before
    stat_after: os.stat_result = store.supplied_path.stat()
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns
    assert stat_after.st_size == stat_before.st_size


def test_saving_writes_only_the_local_file(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    assert store.local_path.is_file()
    assert not store.supplied_path.exists()      # поставочный файл программа не создаёт


def test_the_supplied_file_never_gets_a_wrapped_key_record(store: VaultStore) -> None:
    """Записи «key» в поставочном файле быть не должно (§14, решение 9)."""
    _write_supplied(store, SUPPLIED_VALUES)
    assert KEY_WRAPPED not in json.loads(store.supplied_path.read_text(encoding=VAULT_FILE_ENCODING))


# --- локальный файл: ключ в самом файле, завёрнутый DPAPI


def test_the_local_file_carries_its_wrapped_key(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    assert sorted(data) == sorted((KEY_VERSION, KEY_SALT, KEY_FIELDS, KEY_WRAPPED))
    wrapped: bytes = base64.b64decode(data[KEY_WRAPPED], validate=True)
    assert len(wrapped) > VAULT_KEY_BYTES                       # DPAPI добавляет свою обвязку
    assert len(Dpapi.load().unprotect(wrapped)) == VAULT_KEY_BYTES


def test_the_local_file_carries_no_plaintext(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    text: str = store.local_path.read_text(encoding=VAULT_FILE_ENCODING)
    for value in OWN_VALUES.values():
        assert value not in text


def test_a_second_save_gets_a_new_key_and_a_new_salt(store: VaultStore) -> None:
    """Новый ключ и новая соль на каждую запись: два файла одного сейфа не совпадают побайтно."""
    store.save_local(_own_vault(OWN_VALUES))
    first: dict[str, Any] = _local_json(store)
    store.save_local(_own_vault(OWN_VALUES))
    second: dict[str, Any] = _local_json(store)
    assert first[KEY_SALT] != second[KEY_SALT]
    assert first[KEY_WRAPPED] != second[KEY_WRAPPED]
    assert first[KEY_FIELDS] != second[KEY_FIELDS]
    assert store.load().vault.get(SecretField.SHEETS_ID) is not None      # и всё равно читается


def test_the_round_trip_returns_the_same_values(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    vault: Vault = store.load().vault
    for field, value in OWN_VALUES.items():
        secret: SecretValue | None = vault.get(field)
        assert secret is not None and secret.reveal() == value


def test_a_russian_value_survives_the_round_trip(store: VaultStore) -> None:
    vault: Vault = Vault.empty().with_field(
        SecretField.SHEETS_RANGE, _secret(SecretField.SHEETS_RANGE, "Лист1!A:F"), VaultOrigin.OWN
    )
    store.save_local(vault)
    restored: SecretValue | None = store.load().vault.get(SecretField.SHEETS_RANGE)
    assert restored is not None and restored.reveal() == "Лист1!A:F"


# --- save_local пишет только свои поля


def test_saving_writes_own_fields_and_skips_supplied_ones(store: VaultStore) -> None:
    """Поставочное значение в локальный файл не переезжает: иначе «сброс к поставке» стал бы невозможен."""
    mixed: Vault = (
        Vault.empty()
        .with_field(
            SecretField.OPENAI_API_KEY,
            _secret(SecretField.OPENAI_API_KEY, SUPPLIED_VALUES[SecretField.OPENAI_API_KEY]),
            VaultOrigin.SUPPLIED,
        )
        .with_field(SecretField.SHEETS_ID, _secret(SecretField.SHEETS_ID, OWN_VALUES[SecretField.SHEETS_ID]), VaultOrigin.OWN)
    )
    store.save_local(mixed)
    fields: dict[str, Any] = _local_json(store)[KEY_FIELDS]
    assert sorted(fields) == [SecretField.SHEETS_ID.value]


def test_saving_an_empty_vault_writes_a_file_without_fields(store: VaultStore) -> None:
    """Так настройщик сбрасывает к поставке всё: файл есть, ключ есть, полей нет."""
    store.save_local(Vault.empty())
    data: dict[str, Any] = _local_json(store)
    assert data[KEY_FIELDS] == {} and KEY_WRAPPED in data
    assert store.load().vault.entries == {}


def test_removing_a_field_returns_the_supplied_value(store: VaultStore) -> None:
    """Сброс к поставке — удаление поля из локального сейфа, а не правка поставочного (§7.3)."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    store.save_local(store.load().vault.without_field(SecretField.SHEETS_ID))
    vault: Vault = store.load().vault
    secret: SecretValue | None = vault.get(SecretField.SHEETS_ID)
    assert secret is not None and secret.reveal() == SUPPLIED_VALUES[SecretField.SHEETS_ID]
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.SUPPLIED


# --- нечитаемый файл не валит запуск


def test_a_tampered_local_field_leaves_the_run_alive_on_the_supplied_vault(store: VaultStore) -> None:
    """Подменённый байт в шифротексте: локального сейфа как будто нет, поставочный работает."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    record: dict[str, Any] = data[KEY_FIELDS][SecretField.SHEETS_ID.value]
    blob: bytes = base64.b64decode(record[KEY_CIPHERTEXT], validate=True)
    record[KEY_CIPHERTEXT] = base64.b64encode(bytes([blob[0] ^ 0x01]) + blob[1:]).decode("ascii")
    _rewrite_local(store, data)
    vault: Vault = store.load().vault
    assert vault.is_ready
    for field in ALL_FIELDS:
        secret: SecretValue | None = vault.get(field)
        assert secret is not None and secret.reveal() == SUPPLIED_VALUES[field]
        assert vault.origin_of(field) is VaultOrigin.SUPPLIED


def test_a_tampered_wrapped_key_leaves_the_run_alive(store: VaultStore) -> None:
    """DPAPI сам проверяет целостность: подменённая запись «key» не разворачивается."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    wrapped: bytes = base64.b64decode(data[KEY_WRAPPED], validate=True)
    data[KEY_WRAPPED] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    _rewrite_local(store, data)
    vault: Vault = store.load().vault
    assert all(vault.origin_of(field) is VaultOrigin.SUPPLIED for field in ALL_FIELDS)


def test_a_local_file_without_a_wrapped_key_is_unreadable(store: VaultStore) -> None:
    """Локальному файлу запись «key» обязательна: нечем разворачивать — файл нечитаем (§14, решение 9)."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data.pop(KEY_WRAPPED)
    _rewrite_local(store, data)
    vault: Vault = store.load().vault
    assert all(vault.origin_of(field) is VaultOrigin.SUPPLIED for field in ALL_FIELDS)


def test_a_local_file_read_by_another_windows_account_is_unreadable(store: VaultStore) -> None:
    """Файл с чужого профиля: ключ завёрнут не нашим DPAPI, развернуть его нельзя — работаем на поставочном."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data[KEY_WRAPPED] = base64.b64encode(b"blob from another windows account").decode("ascii")
    _rewrite_local(store, data)
    assert all(store.load().vault.origin_of(field) is VaultOrigin.SUPPLIED for field in ALL_FIELDS)


def test_a_supplied_file_without_a_program_key_is_unreadable(livecraft_paths: LivecraftPaths) -> None:
    """Нет ProgramKey — поставочный сейф просто не читается, программа работает на локальном (§7.3)."""
    keyless: VaultStore = VaultStore(
        supplied_path=livecraft_paths.vault_file,
        local_path=livecraft_paths.vault_local_file,
        program_key=ProgramKey(material=None),
        dpapi=Dpapi.load(),
    )
    _write_supplied(keyless, SUPPLIED_VALUES)
    keyless.save_local(_own_vault(OWN_VALUES))
    vault: Vault = keyless.load().vault
    assert vault.missing == (SecretField.OPENAI_API_KEY, SecretField.SHEETS_RANGE)
    assert all(vault.origin_of(field) is VaultOrigin.OWN for field in OWN_VALUES)


def test_a_supplied_file_under_a_foreign_program_key_is_unreadable(store: VaultStore) -> None:
    """Чужой ProgramKey: блоб не расшифровался — полей этого файла нет, запуск продолжается."""
    _write_supplied(store, SUPPLIED_VALUES)
    foreign: VaultStore = VaultStore(
        supplied_path=store.supplied_path,
        local_path=store.local_path,
        program_key=ProgramKey(material=bytes(VAULT_KEY_BYTES)),
        dpapi=store.dpapi,
    )
    assert foreign.load().vault.entries == {}


@pytest.mark.parametrize("version", [0, 2, "1", None])
def test_an_unknown_format_version_goes_out_as_an_error(store: VaultStore, version: Any) -> None:
    """§7.3: чужой формат — ошибка наружу (код 2 решает main), а не тихое игнорирование."""
    _rewrite_local(
        store,
        {
            KEY_VERSION: version,
            KEY_SALT: base64.b64encode(bytes(SALT_BYTES)).decode("ascii"),
            KEY_FIELDS: {},
        },
    )
    with pytest.raises(VaultFormatError):
        store.load().vault


def test_an_unknown_format_version_of_the_supplied_file_goes_out_too(store: VaultStore) -> None:
    store.supplied_path.write_text(
        json.dumps({KEY_VERSION: 99, KEY_SALT: base64.b64encode(bytes(SALT_BYTES)).decode("ascii"), KEY_FIELDS: {}}),
        encoding=VAULT_FILE_ENCODING,
    )
    with pytest.raises(VaultFormatError):
        store.load().vault


def test_an_unknown_field_name_in_the_file_is_ignored(store: VaultStore) -> None:
    """Поле, которого в этой версии программы нет, не мешает читать остальные."""
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data[KEY_FIELDS]["telegram_token"] = data[KEY_FIELDS][SecretField.SHEETS_ID.value]
    _rewrite_local(store, data)
    vault: Vault = store.load().vault
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN


# --- без DPAPI локальный сейф не пишется


def test_saving_without_dpapi_refuses_and_creates_no_file(livecraft_paths: LivecraftPaths) -> None:
    """DpapiUnavailable наружу, файла нет: «локальный сейф» без привязки к аккаунту был бы обманом (§7.2)."""
    without_dpapi: VaultStore = VaultStore(
        supplied_path=livecraft_paths.vault_file,
        local_path=livecraft_paths.vault_local_file,
        program_key=ProgramKey(material=PROGRAM_KEY),
        dpapi=Dpapi(),
    )
    with pytest.raises(DpapiUnavailable):
        without_dpapi.save_local(_own_vault(OWN_VALUES))
    assert not without_dpapi.local_path.exists()


def test_a_failed_save_leaves_the_previous_local_file_untouched(store: VaultStore) -> None:
    """Запись атомарная: сорвавшаяся вторая запись не рвёт первую."""
    store.save_local(_own_vault(OWN_VALUES))
    before: bytes = store.local_path.read_bytes()
    broken: VaultStore = VaultStore(
        supplied_path=store.supplied_path,
        local_path=store.local_path,
        program_key=store.program_key,
        dpapi=Dpapi(),
    )
    with pytest.raises(DpapiUnavailable):
        broken.save_local(_own_vault(OWN_VALUES))
    assert store.local_path.read_bytes() == before


# --- имена файлов в логе, а не пути


def test_the_source_names_are_english_identifiers() -> None:
    """Значение уходит в лог вместо пути к секретам (§7.4)."""
    assert [source.value for source in VaultSource] == ["supplied", "local"]


def test_a_local_file_written_the_old_way_still_reads(store: VaultStore) -> None:
    """Формат не менялся: файл, чьи поля зашифрованы вызовом VaultCrypto напрямую, читается как свой.

    Так локальный сейф писался до того, как шифрование стало правилом самого секрета (задача 1.3a) —
    и так его пишет сборка Артура для поставочного файла.
    """
    key: bytes = bytes(range(VAULT_KEY_BYTES))
    salt: bytes = VaultFile.empty().salt
    crypto: VaultCrypto = VaultCrypto(key=key, salt=salt)
    fields: dict[str, EncryptedField] = {
        field.value: crypto.encrypt(field, value) for field, value in OWN_VALUES.items()
    }
    store.local_path.write_text(
        VaultFile(
            version=FORMAT_VERSION, salt=salt, fields=fields, wrapped_key=store.dpapi.protect(key)
        ).render(),
        encoding=VAULT_FILE_ENCODING,
    )
    vault: Vault = store.load().vault
    for field, value in OWN_VALUES.items():
        secret: SecretValue | None = vault.get(field)
        assert secret is not None and secret.reveal() == value
        assert vault.origin_of(field) is VaultOrigin.OWN


def test_a_file_written_now_and_one_written_the_old_way_have_the_same_shape(store: VaultStore) -> None:
    """Набор записей в файле тот же: поменялось, кто зовёт шифратор, а не что ложится на диск."""
    store.save_local(_own_vault(OWN_VALUES))
    now: dict[str, Any] = _local_json(store)
    salt: bytes = VaultFile.empty().salt
    crypto: VaultCrypto = VaultCrypto(key=PROGRAM_KEY, salt=salt)
    old: dict[str, Any] = json.loads(
        VaultFile(
            version=FORMAT_VERSION,
            salt=salt,
            fields={field.value: crypto.encrypt(field, value) for field, value in OWN_VALUES.items()},
            wrapped_key=b"wrapped",
        ).render()
    )
    assert sorted(now) == sorted(old)
    assert sorted(now[KEY_FIELDS]) == sorted(old[KEY_FIELDS])
    for name in now[KEY_FIELDS]:
        assert sorted(now[KEY_FIELDS][name]) == sorted(old[KEY_FIELDS][name])


# --- состояние личного сейфа: полем результата, а не только строкой в логе (§0)


def test_without_a_local_file_the_state_is_absent(store: VaultStore) -> None:
    load: VaultLoad = store.load()
    assert load.local_state is LocalVaultState.ABSENT and not load.is_local_unreadable


def test_a_read_local_file_has_the_read_state(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    load: VaultLoad = store.load()
    assert load.local_state is LocalVaultState.READ and not load.is_local_unreadable


def test_an_empty_but_readable_local_file_is_read_not_unreadable(store: VaultStore) -> None:
    """Пустой прочитанный файл — пользователь сбросил всё к поставке; это не поломка и не повод кричать."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(Vault.empty())
    load: VaultLoad = store.load()
    assert load.local_state is LocalVaultState.READ
    assert load.vault.is_ready


def test_a_local_file_without_the_key_record_is_unreadable_state(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data.pop(KEY_WRAPPED)
    _rewrite_local(store, data)
    load: VaultLoad = store.load()
    assert load.local_state is LocalVaultState.UNREADABLE and load.is_local_unreadable


def test_a_tampered_key_record_is_unreadable_state(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    wrapped: bytes = base64.b64decode(data[KEY_WRAPPED], validate=True)
    data[KEY_WRAPPED] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    _rewrite_local(store, data)
    assert store.load().local_state is LocalVaultState.UNREADABLE


def test_a_tampered_ciphertext_is_unreadable_state(store: VaultStore) -> None:
    """Хоть одно поле не расшифровалось — файл нечитаем целиком; это UNREADABLE, а не пустой READ."""
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    record: dict[str, Any] = data[KEY_FIELDS][SecretField.SHEETS_ID.value]
    blob: bytes = base64.b64decode(record[KEY_CIPHERTEXT], validate=True)
    record[KEY_CIPHERTEXT] = base64.b64encode(bytes([blob[0] ^ 0x01]) + blob[1:]).decode("ascii")
    _rewrite_local(store, data)
    load: VaultLoad = store.load()
    assert load.local_state is LocalVaultState.UNREADABLE
    assert load.vault.entries == {}


def test_the_state_does_not_depend_on_the_supplied_file(store: VaultStore) -> None:
    """Поставочный файл к состоянию личного отношения не имеет: сломанный личный — UNREADABLE и рядом с поставкой."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data.pop(KEY_WRAPPED)
    _rewrite_local(store, data)
    load: VaultLoad = store.load()
    assert load.is_local_unreadable and load.vault.is_ready


# --- ошибка формата называет файл (§7.3)


def test_a_format_error_of_the_local_file_names_the_file(store: VaultStore) -> None:
    _rewrite_local(
        store, {KEY_VERSION: 9, KEY_SALT: base64.b64encode(bytes(SALT_BYTES)).decode("ascii"), KEY_FIELDS: {}}
    )
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.local_path.name in str(raised.value)
    assert isinstance(raised.value.__cause__, VaultFormatError)     # причина сохранена через from
    assert (raised.value.reason, raised.value.source) == (VaultFormatReason.UNSUPPORTED_VERSION, VaultSource.LOCAL)
    assert raised.value.detail == raised.value.__cause__.detail
    assert raised.value.advice == msg.VAULT_FILE_ADVICE_LOCAL


def test_a_format_error_of_the_supplied_file_names_the_file(store: VaultStore) -> None:
    store.supplied_path.write_text("не json", encoding=VAULT_FILE_ENCODING)
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.supplied_path.name in str(raised.value)
    assert (raised.value.reason, raised.value.source) == (VaultFormatReason.DAMAGED, VaultSource.SUPPLIED)
    assert raised.value.advice == msg.VAULT_FILE_ADVICE_SUPPLIED


def test_the_format_error_names_only_the_file_not_the_folder(store: VaultStore) -> None:
    """Имя файла — да; путь к папке сейфа в тексте не нужен и не печатается."""
    store.supplied_path.write_text("не json", encoding=VAULT_FILE_ENCODING)
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert str(store.supplied_path.parent) not in str(raised.value)


# --- повреждённый или не открывающийся файл — не «файла нет» (§7.3, §16)

NOT_UTF8_BYTES: bytes = b"\xff\xfe\x00vault\x80\x81"


def test_a_local_file_that_is_not_utf8_is_a_format_error(store: VaultStore) -> None:
    """Иначе личный файл читался бы как отсутствующий и работа молча шла бы на поставке (§16)."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.local_path.write_bytes(NOT_UTF8_BYTES)
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.local_path.name in str(raised.value)
    assert str(store.local_path.parent) not in str(raised.value)
    assert isinstance(raised.value.__cause__, UnicodeDecodeError)
    assert (raised.value.reason, raised.value.source) == (VaultFormatReason.NOT_TEXT, VaultSource.LOCAL)


def test_a_supplied_file_that_is_not_utf8_is_a_format_error(store: VaultStore) -> None:
    store.supplied_path.write_bytes(NOT_UTF8_BYTES)
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.supplied_path.name in str(raised.value)
    assert str(store.supplied_path.parent) not in str(raised.value)


def test_a_local_file_that_does_not_open_is_a_format_error_not_absent(store: VaultStore) -> None:
    """Папка на месте файла: на Windows открытие даёт PermissionError — как файл под замком антивируса."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.local_path.mkdir()
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.local_path.name in str(raised.value)
    assert str(store.local_path.parent) not in str(raised.value)
    assert isinstance(raised.value.__cause__, OSError)
    assert (raised.value.reason, raised.value.source) == (VaultFormatReason.FILE_UNREADABLE, VaultSource.LOCAL)
    assert raised.value.detail not in str(raised.value)


def test_a_supplied_file_that_does_not_open_is_a_format_error(store: VaultStore) -> None:
    store.supplied_path.mkdir()
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.supplied_path.name in str(raised.value)


def test_a_missing_local_file_is_still_absent(store: VaultStore) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    assert not store.local_path.exists()
    assert store.load().local_state is LocalVaultState.ABSENT


# --- чтение для настройщика: повреждённый личный файл — не тупик (D9)


def test_the_local_states_are_the_four_named_ones() -> None:
    assert [state.value for state in LocalVaultState] == ["absent", "read", "unreadable", "broken"]


@pytest.mark.parametrize("broken", ["not_utf8", "not_json", "folder"])
def test_load_still_refuses_a_broken_local_file(store: VaultStore, broken: str) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    _break_local(store, broken)
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert raised.value.source is VaultSource.LOCAL and raised.value.is_replaceable


@pytest.mark.parametrize("broken", ["not_utf8", "not_json", "folder"])
def test_load_for_setup_gives_the_supplied_layer_over_an_empty_broken_own_one(
    store: VaultStore, broken: str
) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    _break_local(store, broken)
    load: VaultLoad = store.load_for_setup()
    assert load.local_state is LocalVaultState.BROKEN
    assert not load.is_local_unreadable
    assert load.own.entries == {}
    assert load.vault.is_ready
    for field, value in SUPPLIED_VALUES.items():
        assert load.vault.origin_of(field) is VaultOrigin.SUPPLIED
        assert load.supplied.get(field) == _secret(field, value)


def test_load_for_setup_logs_the_broken_local_file_without_values(
    store: VaultStore, caplog: pytest.LogCaptureFixture
) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    _break_local(store, "not_json")
    with caplog.at_level("INFO", logger="livecraft"):
        store.load_for_setup()
    lines: list[str] = [record.getMessage() for record in caplog.records]
    broken: list[str] = [line for line in lines if line.startswith("vault_local_broken")]
    assert len(broken) == 1
    assert "source=local" in broken[0] and f"reason={VaultFormatReason.DAMAGED.value}" in broken[0]
    assert any(line.startswith("vault_loaded") and "local=broken" in line for line in lines)
    assert all(value not in line for line in lines for value in SUPPLIED_VALUES.values())


def test_load_for_setup_reads_a_whole_local_file_as_load_does(store: VaultStore) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    assert store.load_for_setup() == store.load()


def test_load_for_setup_refuses_a_broken_supplied_file(store: VaultStore) -> None:
    store.supplied_path.write_text("не json", encoding=VAULT_FILE_ENCODING)
    with pytest.raises(VaultFormatError) as raised:
        store.load_for_setup()
    assert raised.value.source is VaultSource.SUPPLIED and not raised.value.is_replaceable
    assert raised.value.advice == msg.VAULT_FILE_ADVICE_SUPPLIED


def test_saving_over_a_broken_local_file_replaces_it(store: VaultStore) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    _break_local(store, "not_json")
    store.save_local(_own_vault(OWN_VALUES))
    load: VaultLoad = store.load()
    assert load.local_state is LocalVaultState.READ
    assert load.own.get(SecretField.SHEETS_ID) == _secret(SecretField.SHEETS_ID, OWN_VALUES[SecretField.SHEETS_ID])


def _break_local(store: VaultStore, how: str) -> None:
    """Повредить личный файл: не текст, не JSON или папка на его месте."""
    if how == "not_utf8":
        store.local_path.write_bytes(NOT_UTF8_BYTES)
    elif how == "not_json":
        store.local_path.write_text("{", encoding=VAULT_FILE_ENCODING)
    else:
        store.local_path.mkdir()


# --- VaultStore.open собирает объект из путей установки


def test_open_builds_the_store_from_paths(livecraft_paths: LivecraftPaths) -> None:
    livecraft_paths.program_key_file.write_bytes(PROGRAM_KEY)
    opened: VaultStore = VaultStore.open(livecraft_paths)
    assert opened.supplied_path == livecraft_paths.vault_file
    assert opened.local_path == livecraft_paths.vault_local_file
    assert opened.program_key.material == PROGRAM_KEY
    assert opened.dpapi.is_available


def test_open_without_a_program_key_still_opens(livecraft_paths: LivecraftPaths) -> None:
    """Нет ключа поставки — объект строится, поставочный сейф просто не читается (§7.3)."""
    opened: VaultStore = VaultStore.open(livecraft_paths)
    assert not opened.program_key.is_available
    assert opened.load().vault.entries == {}


# --- слои сейфа: поставочный как прочитан и личный отдельно (настройщик, §8.2)


def _values_of(vault: Vault) -> dict[SecretField, str]:
    return {field: entry.secret.reveal() for field, entry in vault.entries.items()}


def test_only_supplied_gives_a_supplied_layer_and_no_own(store: VaultStore) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    loaded: VaultLoad = store.load()
    assert _values_of(loaded.supplied) == SUPPLIED_VALUES
    assert all(loaded.supplied.origin_of(field) is VaultOrigin.SUPPLIED for field in ALL_FIELDS)
    assert loaded.own == Vault.empty()


def test_only_own_gives_an_own_layer_and_an_empty_supplied_one(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    loaded: VaultLoad = store.load()
    assert loaded.supplied == Vault.empty()
    assert _values_of(loaded.own) == OWN_VALUES
    assert all(loaded.own.origin_of(field) is VaultOrigin.OWN for field in OWN_VALUES)


def test_own_over_supplied_keeps_the_supplied_layer_whole(store: VaultStore) -> None:
    """Под личным значением поставочное не теряется: без него не посчитать «Вернуть значение программы»."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    loaded: VaultLoad = store.load()
    assert _values_of(loaded.supplied) == SUPPLIED_VALUES
    assert _values_of(loaded.own) == OWN_VALUES
    assert tuple(loaded.own.entries) == (SecretField.SHEETS_ID, SecretField.KEY_FORM_URL)
    assert loaded.vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert loaded.vault.origin_of(SecretField.OPENAI_API_KEY) is VaultOrigin.SUPPLIED


def test_the_supplied_layer_is_empty_without_a_program_key(livecraft_paths: LivecraftPaths) -> None:
    opened: VaultStore = VaultStore.open(livecraft_paths)
    livecraft_paths.vault_file.write_text(
        VaultFile.empty().render(), encoding=VAULT_FILE_ENCODING
    )
    assert opened.load().supplied == Vault.empty()


def test_the_layers_rebuild_the_same_vault(store: VaultStore) -> None:
    """Наложение — одно правило: из двух слоёв собирается тот же сейф, что прочитан с диска."""
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    loaded: VaultLoad = store.load()
    rebuilt: VaultLoad = VaultLoad.from_layers(
        supplied=loaded.supplied, own=loaded.own, local_state=loaded.local_state
    )
    assert rebuilt == loaded


def test_an_unreadable_local_file_leaves_no_own_layer(store: VaultStore) -> None:
    _write_supplied(store, SUPPLIED_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    del data[KEY_WRAPPED]
    _rewrite_local(store, data)
    loaded: VaultLoad = store.load()
    assert loaded.own == Vault.empty()
    assert _values_of(loaded.supplied) == SUPPLIED_VALUES


# --- можно ли писать личный сейф


def test_can_save_local_with_windows_dpapi(store: VaultStore) -> None:
    assert Dpapi.load().is_available
    assert store.can_save_local


def test_cannot_save_local_without_dpapi(livecraft_paths: LivecraftPaths) -> None:
    no_dpapi: VaultStore = VaultStore(
        supplied_path=livecraft_paths.vault_file,
        local_path=livecraft_paths.vault_local_file,
        program_key=ProgramKey.load(livecraft_paths.program_key_file),
        dpapi=Dpapi(),
    )
    assert not no_dpapi.can_save_local
