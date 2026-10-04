from __future__ import annotations

import base64
import json
import os
from typing import Any

import pytest

from app.core.text_format import TEXT_ENCODING
from app.paths import FileName, LivecraftPaths
from app.secretsafe.crypto import (
    FORMAT_VERSION,
    SALT_BYTES,
    VAULT_KEY_BYTES,
    EncryptedField,
    VaultCrypto,
    VaultFile,
    VaultFileKey,
    VaultFormatError,
    VaultFormatReason,
)
from app.secretsafe.dpapi import Dpapi, DpapiUnavailable
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultLayerState, VaultLoad, VaultRead, VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.tests.fixtures.vault import vault_of
from app.ui import messages_ru as msg

KEY_VERSION: str = VaultFileKey.VERSION.value
KEY_SALT: str = VaultFileKey.SALT.value
KEY_FIELDS: str = VaultFileKey.FIELDS.value
KEY_CIPHERTEXT: str = VaultFileKey.CIPHERTEXT.value
KEY_WRAPPED: str = VaultFileKey.WRAPPED_KEY.value

TOKEN_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-fromtoken-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1fromtoken-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.TELEGRAM_BOT_TOKEN: "123456789:AAFfromtoken-B3c4D5e6F7g8H9i0JkLmNoPqRsTu",
    SecretField.DRIVE_FOLDER: "1fromtoken-DrIvEfOlDeR_0123456789-abcd",
    SecretField.SUPPORT_BOT_TOKEN: "987654321:AAFfromtoken-SuPpOrT0123456789abcdefghij",
}
OWN_VALUES: dict[SecretField, str] = {
    SecretField.SHEETS_ID: "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table",
    SecretField.DRIVE_FOLDER: "1own-DrIvEfOlDeR_0123456789-own",
}
ALL_FIELDS: tuple[SecretField, ...] = tuple(SecretField)
NOT_UTF8_BYTES: bytes = b"\xff\xfe\x00vault\x80\x81"


def _secret(field: SecretField, value: str) -> SecretValue:
    return SecretValue(field=field, value=value)


@pytest.fixture
def store(livecraft_paths: LivecraftPaths) -> VaultStore:
    """Сейф на временном корне — собирается боевым путём."""
    return VaultStore.open(livecraft_paths)


def _write_token(store: VaultStore, values: dict[SecretField, str]) -> bytes:
    """Слой токена так пишет загрузка токена: `save_token`."""
    store.save_token(vault_of(values, VaultOrigin.TOKEN))
    return store.token_path.read_bytes()


def _own_vault(values: dict[SecretField, str]) -> Vault:
    return vault_of(values, VaultOrigin.OWN)


def _json(path: Any) -> dict[str, Any]:
    return json.loads(path.read_text(encoding=TEXT_ENCODING))


def _local_json(store: VaultStore) -> dict[str, Any]:
    return _json(store.local_path)


def _rewrite_local(store: VaultStore, data: dict[str, Any]) -> None:
    store.local_path.write_text(json.dumps(data), encoding=TEXT_ENCODING)


def _values_of(vault: Vault) -> dict[SecretField, str]:
    return {field: entry.secret.reveal() for field, entry in vault.entries.items()}


def _flip_ciphertext(data: dict[str, Any], field: SecretField) -> None:
    record: dict[str, Any] = data[KEY_FIELDS][field.value]
    blob: bytes = base64.b64decode(record[KEY_CIPHERTEXT], validate=True)
    record[KEY_CIPHERTEXT] = base64.b64encode(bytes([blob[0] ^ 0x01]) + blob[1:]).decode("ascii")


def _break(path: Any, how: str) -> None:
    """Повредить файл слоя: не текст, не JSON или папка на его месте."""
    if how == "not_utf8":
        path.write_bytes(NOT_UTF8_BYTES)
    elif how == "not_json":
        path.write_text("{", encoding=TEXT_ENCODING)
    else:
        path.mkdir()


# --- приоритет: своё поверх значения из токена (§7.3)


def test_a_local_field_overrides_the_token_one(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    vault: Vault = store.load().vault
    for field in ALL_FIELDS:
        secret: SecretValue | None = vault.get(field)
        assert secret is not None
        assert secret.reveal() == OWN_VALUES.get(field, TOKEN_VALUES[field])


def test_each_field_carries_the_origin_of_the_file_it_came_from(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    vault: Vault = store.load().vault
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert vault.origin_of(SecretField.DRIVE_FOLDER) is VaultOrigin.OWN
    assert vault.origin_of(SecretField.OPENAI_API_KEY) is VaultOrigin.TOKEN
    assert vault.origin_of(SecretField.TELEGRAM_BOT_TOKEN) is VaultOrigin.TOKEN


def test_without_a_local_file_the_vault_is_the_token_one(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    vault: Vault = store.load().vault
    assert _values_of(vault) == TOKEN_VALUES
    assert all(vault.origin_of(field) is VaultOrigin.TOKEN for field in ALL_FIELDS)


def test_without_a_token_file_the_vault_is_the_local_one(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    vault: Vault = store.load().vault
    assert not store.token_path.exists()
    assert vault.missing_of(ALL_FIELDS) == (
        SecretField.OPENAI_API_KEY, SecretField.TELEGRAM_BOT_TOKEN, SecretField.SUPPORT_BOT_TOKEN
    )
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN


def test_without_both_files_the_vault_is_empty(store: VaultStore) -> None:
    """Чистая установка до настройщика: сейф пуст (§8)."""
    assert store.load().vault.entries == {}


# --- каждая запись трогает только свой файл


def test_saving_the_local_vault_does_not_touch_the_token_file(store: VaultStore) -> None:
    """Сверка побайтно и по времени правки: своё сохранение файл токена не меняет."""
    before: bytes = _write_token(store, TOKEN_VALUES)
    stat_before: os.stat_result = store.token_path.stat()
    store.save_local(_own_vault(OWN_VALUES))
    store.save_local(_own_vault(OWN_VALUES))
    assert store.token_path.read_bytes() == before
    assert store.token_path.stat().st_mtime_ns == stat_before.st_mtime_ns


def test_saving_the_token_layer_does_not_touch_the_local_file(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    before: bytes = store.local_path.read_bytes()
    _write_token(store, TOKEN_VALUES)
    assert store.local_path.read_bytes() == before


def test_saving_writes_only_the_local_file(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    assert store.local_path.is_file()
    assert not store.token_path.exists()      # файл токена пишет только загрузка токена


def test_a_new_token_replaces_the_previous_token_values_whole(store: VaultStore) -> None:
    """Прежние значения из токена заменяются целиком: поля, которого в новом токене нет, больше нет."""
    _write_token(store, TOKEN_VALUES)
    _write_token(store, {SecretField.SHEETS_ID: TOKEN_VALUES[SecretField.SHEETS_ID]})
    assert tuple(store.load().token.entries) == (SecretField.SHEETS_ID,)


def test_saving_the_token_layer_writes_only_token_fields(store: VaultStore) -> None:
    mixed: Vault = vault_of(TOKEN_VALUES, VaultOrigin.TOKEN).with_field(
        SecretField.SHEETS_ID, _secret(SecretField.SHEETS_ID, OWN_VALUES[SecretField.SHEETS_ID]), VaultOrigin.OWN
    )
    store.save_token(mixed)
    assert sorted(_json(store.token_path)[KEY_FIELDS]) == sorted(
        field.value for field in TOKEN_VALUES if field is not SecretField.SHEETS_ID
    )


# --- оба файла: ключ в самом файле, завёрнутый DPAPI (§14, решение 9)


@pytest.mark.parametrize("layer", ["local", "token"])
def test_each_file_carries_its_wrapped_key(store: VaultStore, layer: str) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    _write_token(store, TOKEN_VALUES)
    data: dict[str, Any] = _json(store.local_path if layer == "local" else store.token_path)
    assert sorted(data) == sorted((KEY_VERSION, KEY_SALT, KEY_FIELDS, KEY_WRAPPED))
    wrapped: bytes = base64.b64decode(data[KEY_WRAPPED], validate=True)
    assert len(wrapped) > VAULT_KEY_BYTES                       # DPAPI добавляет свою обвязку
    assert len(Dpapi.load().unprotect(wrapped)) == VAULT_KEY_BYTES


def test_the_files_carry_no_plaintext(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    _write_token(store, TOKEN_VALUES)
    text: str = store.local_path.read_text(encoding=TEXT_ENCODING) + store.token_path.read_text(encoding=TEXT_ENCODING)
    for value in (*OWN_VALUES.values(), *TOKEN_VALUES.values()):
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
    _write_token(store, TOKEN_VALUES)
    loaded: VaultLoad = store.load()
    assert _values_of(loaded.own) == OWN_VALUES
    assert _values_of(loaded.token) == TOKEN_VALUES


def test_a_russian_value_survives_the_round_trip(store: VaultStore) -> None:
    store.save_local(Vault.empty().with_field(SecretField.DRIVE_FOLDER, _secret(SecretField.DRIVE_FOLDER, "Лист1"), VaultOrigin.OWN))
    restored: SecretValue | None = store.load().vault.get(SecretField.DRIVE_FOLDER)
    assert restored is not None and restored.reveal() == "Лист1"


# --- save_local пишет только свои поля


def test_saving_writes_own_fields_and_skips_token_ones(store: VaultStore) -> None:
    """Значение из токена в личный файл не переезжает: иначе «вернуть значение из токена» стало бы невозможным."""
    mixed: Vault = (
        Vault.empty()
        .with_field(
            SecretField.OPENAI_API_KEY,
            _secret(SecretField.OPENAI_API_KEY, TOKEN_VALUES[SecretField.OPENAI_API_KEY]),
            VaultOrigin.TOKEN,
        )
        .with_field(SecretField.SHEETS_ID, _secret(SecretField.SHEETS_ID, OWN_VALUES[SecretField.SHEETS_ID]), VaultOrigin.OWN)
    )
    store.save_local(mixed)
    assert sorted(_local_json(store)[KEY_FIELDS]) == [SecretField.SHEETS_ID.value]


def test_saving_an_empty_vault_writes_a_file_without_fields(store: VaultStore) -> None:
    """Так настройщик убирает все свои значения: файл есть, ключ есть, полей нет."""
    store.save_local(Vault.empty())
    data: dict[str, Any] = _local_json(store)
    assert data[KEY_FIELDS] == {} and KEY_WRAPPED in data
    assert store.load().vault.entries == {}


def test_removing_an_own_field_returns_the_token_value(store: VaultStore) -> None:
    """«Удалить» своё — удаление поля из личного сейфа: под ним снова значение из токена (§7.3, §8.2)."""
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    store.save_local(store.load().vault.without_field(SecretField.SHEETS_ID))
    vault: Vault = store.load().vault
    secret: SecretValue | None = vault.get(SecretField.SHEETS_ID)
    assert secret is not None and secret.reveal() == TOKEN_VALUES[SecretField.SHEETS_ID]
    assert vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.TOKEN


# --- нечитаемый файл не валит запуск


def test_a_tampered_local_field_leaves_the_run_alive_on_the_token_values(store: VaultStore) -> None:
    """Подменённый байт в шифротексте: личного сейфа как будто нет, значения из токена работают."""
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    _flip_ciphertext(data, SecretField.SHEETS_ID)
    _rewrite_local(store, data)
    vault: Vault = store.load().vault
    assert _values_of(vault) == TOKEN_VALUES
    assert all(vault.origin_of(field) is VaultOrigin.TOKEN for field in ALL_FIELDS)


def test_a_tampered_token_field_leaves_the_run_alive_on_the_own_values(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _json(store.token_path)
    _flip_ciphertext(data, SecretField.OPENAI_API_KEY)
    store.token_path.write_text(json.dumps(data), encoding=TEXT_ENCODING)
    loaded: VaultLoad = store.load()
    assert _values_of(loaded.vault) == OWN_VALUES
    assert loaded.token_state is VaultLayerState.UNREADABLE
    assert loaded.warnings == (msg.VAULT_TOKEN_UNREADABLE,)


def test_a_tampered_wrapped_key_leaves_the_run_alive(store: VaultStore) -> None:
    """DPAPI сам проверяет целостность: подменённая запись «key» не разворачивается."""
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    wrapped: bytes = base64.b64decode(data[KEY_WRAPPED], validate=True)
    data[KEY_WRAPPED] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    _rewrite_local(store, data)
    vault: Vault = store.load().vault
    assert all(vault.origin_of(field) is VaultOrigin.TOKEN for field in ALL_FIELDS)


def test_a_local_file_without_a_wrapped_key_is_unreadable(store: VaultStore) -> None:
    """Файлу слоя запись «key» обязательна: нечем разворачивать — файл нечитаем (§14, решение 9)."""
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data.pop(KEY_WRAPPED)
    _rewrite_local(store, data)
    vault: Vault = store.load().vault
    assert all(vault.origin_of(field) is VaultOrigin.TOKEN for field in ALL_FIELDS)


def test_a_file_read_by_another_windows_account_is_unreadable(store: VaultStore) -> None:
    """Файл с чужого профиля: ключ завёрнут не нашим DPAPI, развернуть его нельзя — работаем на втором файле."""
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data[KEY_WRAPPED] = base64.b64encode(b"blob from another windows account").decode("ascii")
    _rewrite_local(store, data)
    assert all(store.load().vault.origin_of(field) is VaultOrigin.TOKEN for field in ALL_FIELDS)


@pytest.mark.parametrize("version", [0, 2, "1", None])
def test_an_unknown_format_version_goes_out_as_an_error(store: VaultStore, version: Any) -> None:
    """§7.3: чужой формат — ошибка наружу (код 2 решает main), а не тихое игнорирование."""
    _rewrite_local(
        store, {KEY_VERSION: version, KEY_SALT: base64.b64encode(bytes(SALT_BYTES)).decode("ascii"), KEY_FIELDS: {}}
    )
    with pytest.raises(VaultFormatError):
        store.load()


def test_an_unknown_format_version_of_the_token_file_goes_out_too(store: VaultStore) -> None:
    store.token_path.write_text(
        json.dumps({KEY_VERSION: 99, KEY_SALT: base64.b64encode(bytes(SALT_BYTES)).decode("ascii"), KEY_FIELDS: {}}),
        encoding=TEXT_ENCODING,
    )
    with pytest.raises(VaultFormatError):
        store.load()


def test_old_fields_in_the_file_do_not_stop_reading_and_go_on_the_next_save(store: VaultStore) -> None:
    """Устаревшие поля (диапазон таблицы, ссылка на форму) в старом файле не мешают чтению и пропадают при следующей
    записи (§13 задача 7.1)."""
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data[KEY_FIELDS]["sheets_range"] = data[KEY_FIELDS][SecretField.SHEETS_ID.value]
    data[KEY_FIELDS]["key_form_url"] = data[KEY_FIELDS][SecretField.DRIVE_FOLDER.value]
    _rewrite_local(store, data)
    loaded: VaultLoad = store.load()
    assert _values_of(loaded.own) == OWN_VALUES
    store.save_local(loaded.own)
    assert sorted(_local_json(store)[KEY_FIELDS]) == sorted(field.value for field in OWN_VALUES)


def test_the_unknown_fields_are_logged_by_name_without_values(
    store: VaultStore, caplog: pytest.LogCaptureFixture
) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data[KEY_FIELDS]["key_form_url"] = data[KEY_FIELDS][SecretField.SHEETS_ID.value]
    _rewrite_local(store, data)
    with caplog.at_level("INFO", logger="livecraft"):
        store.load()
    lines: list[str] = [record.getMessage() for record in caplog.records]
    assert "vault_unknown_fields source=own names=key_form_url" in lines


# --- без DPAPI файлы сейфа не пишутся


def test_saving_without_dpapi_refuses_and_creates_no_file(livecraft_paths: LivecraftPaths) -> None:
    """DpapiUnavailable наружу, файла нет: «сейф» без привязки к аккаунту был бы обманом (§7.2)."""
    without_dpapi: VaultStore = VaultStore(
        local_path=livecraft_paths.file(FileName.VAULT_LOCAL),
        token_path=livecraft_paths.file(FileName.VAULT_TOKEN),
        dpapi=Dpapi(),
    )
    assert not without_dpapi.can_save
    with pytest.raises(DpapiUnavailable):
        without_dpapi.save_local(_own_vault(OWN_VALUES))
    with pytest.raises(DpapiUnavailable):
        without_dpapi.save_token(vault_of(TOKEN_VALUES, VaultOrigin.TOKEN))
    assert not without_dpapi.local_path.exists() and not without_dpapi.token_path.exists()


def test_a_failed_save_leaves_the_previous_local_file_untouched(store: VaultStore) -> None:
    """Запись атомарная: сорвавшаяся вторая запись не рвёт первую."""
    store.save_local(_own_vault(OWN_VALUES))
    before: bytes = store.local_path.read_bytes()
    broken: VaultStore = VaultStore(local_path=store.local_path, token_path=store.token_path, dpapi=Dpapi())
    with pytest.raises(DpapiUnavailable):
        broken.save_local(_own_vault(OWN_VALUES))
    assert store.local_path.read_bytes() == before


def test_can_save_with_windows_dpapi(store: VaultStore) -> None:
    assert Dpapi.load().is_available
    assert store.can_save


# --- файл, записанный прежним путём, читается


def test_a_local_file_written_the_old_way_still_reads(store: VaultStore) -> None:
    """Формат не менялся: файл, чьи поля зашифрованы вызовом VaultCrypto напрямую, читается как свой."""
    key: bytes = bytes(range(VAULT_KEY_BYTES))
    salt: bytes = VaultCrypto.new().salt
    crypto: VaultCrypto = VaultCrypto(key=key, salt=salt)
    fields: dict[str, EncryptedField] = {field.value: crypto.encrypt(field, value) for field, value in OWN_VALUES.items()}
    store.local_path.write_text(
        VaultFile(version=FORMAT_VERSION, salt=salt, fields=fields, wrapped_key=store.dpapi.protect(key)).render(),
        encoding=TEXT_ENCODING,
    )
    vault: Vault = store.load().vault
    assert _values_of(vault) == OWN_VALUES
    assert all(vault.origin_of(field) is VaultOrigin.OWN for field in OWN_VALUES)


# --- состояния файлов: полями результата, а не только строкой в логе (§0)


def test_without_files_the_states_are_absent(store: VaultStore) -> None:
    load: VaultLoad = store.load()
    assert (load.local_state, load.token_state) == (VaultLayerState.ABSENT, VaultLayerState.ABSENT)
    assert not load.is_local_unreadable


def test_read_files_have_the_read_state(store: VaultStore) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    _write_token(store, TOKEN_VALUES)
    load: VaultLoad = store.load()
    assert (load.local_state, load.token_state) == (VaultLayerState.READ, VaultLayerState.READ)


def test_an_empty_but_readable_local_file_is_read_not_unreadable(store: VaultStore) -> None:
    """Пустой прочитанный файл — человек убрал все свои значения; это не поломка и не повод кричать."""
    _write_token(store, TOKEN_VALUES)
    store.save_local(Vault.empty())
    load: VaultLoad = store.load()
    assert load.local_state is VaultLayerState.READ
    assert _values_of(load.vault) == TOKEN_VALUES


def test_a_tampered_ciphertext_is_unreadable_state(store: VaultStore) -> None:
    """Хоть одно поле не расшифровалось — файл нечитаем целиком; это UNREADABLE, а не пустой READ."""
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    _flip_ciphertext(data, SecretField.SHEETS_ID)
    _rewrite_local(store, data)
    load: VaultLoad = store.load()
    assert load.local_state is VaultLayerState.UNREADABLE and load.is_local_unreadable
    assert load.vault.entries == {}


def test_the_layer_states_are_the_four_named_ones() -> None:
    assert [state.value for state in VaultLayerState] == ["absent", "read", "unreadable", "broken"]


# --- ошибка формата называет файл (§7.3)


def test_a_format_error_of_the_local_file_names_the_file(store: VaultStore) -> None:
    _rewrite_local(store, {KEY_VERSION: 9, KEY_SALT: base64.b64encode(bytes(SALT_BYTES)).decode("ascii"), KEY_FIELDS: {}})
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.local_path.name in str(raised.value)
    assert isinstance(raised.value.__cause__, VaultFormatError)     # причина сохранена через from
    assert (raised.value.reason, raised.value.source) == (VaultFormatReason.UNSUPPORTED_VERSION, VaultOrigin.OWN)
    assert raised.value.advice == msg.VAULT_FILE_ADVICE_LOCAL


def test_a_format_error_of_the_token_file_names_the_file_and_asks_to_load_the_token(store: VaultStore) -> None:
    store.token_path.write_text("не json", encoding=TEXT_ENCODING)
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.token_path.name in str(raised.value)
    assert str(store.token_path.parent) not in str(raised.value)
    assert (raised.value.reason, raised.value.source) == (VaultFormatReason.DAMAGED, VaultOrigin.TOKEN)
    assert raised.value.advice == msg.VAULT_FILE_ADVICE_TOKEN


@pytest.mark.parametrize("broken", ["not_utf8", "folder"])
def test_a_file_that_is_not_text_or_does_not_open_is_a_format_error_not_absent(store: VaultStore, broken: str) -> None:
    """Иначе личный файл читался бы как отсутствующий и работа молча шла бы без своих значений (§16)."""
    _write_token(store, TOKEN_VALUES)
    _break(store.local_path, broken)
    with pytest.raises(VaultFormatError) as raised:
        store.load()
    assert store.local_path.name in str(raised.value)
    assert str(store.local_path.parent) not in str(raised.value)
    assert raised.value.source is VaultOrigin.OWN
    assert raised.value.reason in (VaultFormatReason.NOT_TEXT, VaultFormatReason.FILE_UNREADABLE)


# --- чтение для настройщика: повреждённый файл — не тупик


@pytest.mark.parametrize("broken", ["not_utf8", "not_json", "folder"])
def test_load_for_setup_gives_the_token_layer_over_an_empty_broken_own_one(store: VaultStore, broken: str) -> None:
    _write_token(store, TOKEN_VALUES)
    _break(store.local_path, broken)
    load: VaultLoad = store.load_for_setup()
    assert load.local_state is VaultLayerState.BROKEN and not load.is_local_unreadable
    assert load.own.entries == {}
    assert _values_of(load.token) == TOKEN_VALUES == _values_of(load.vault)


@pytest.mark.parametrize("broken", ["not_utf8", "not_json", "folder"])
def test_load_for_setup_gives_an_empty_broken_token_layer_under_the_own_one(store: VaultStore, broken: str) -> None:
    """Повреждённый файл токена окну не мешает: загрузка токена его заменит."""
    store.save_local(_own_vault(OWN_VALUES))
    _break(store.token_path, broken)
    load: VaultLoad = store.load_for_setup()
    assert load.token_state is VaultLayerState.BROKEN and load.token == Vault.empty()
    assert _values_of(load.vault) == OWN_VALUES


def test_load_for_setup_logs_the_broken_file_without_values(store: VaultStore, caplog: pytest.LogCaptureFixture) -> None:
    _write_token(store, TOKEN_VALUES)
    _break(store.local_path, "not_json")
    with caplog.at_level("INFO", logger="livecraft"):
        store.load_for_setup()
    lines: list[str] = [record.getMessage() for record in caplog.records]
    broken: list[str] = [line for line in lines if line.startswith("vault_layer_broken")]
    assert len(broken) == 1
    assert "source=own" in broken[0] and f"reason={VaultFormatReason.DAMAGED.value}" in broken[0]
    assert any(line.startswith("vault_loaded") and "local=broken" in line and "token=read" in line for line in lines)
    assert all(value not in line for line in lines for value in TOKEN_VALUES.values())


def test_load_for_setup_reads_whole_files_as_load_does(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    assert store.load_for_setup() == store.load()


def test_saving_over_a_broken_local_file_replaces_it(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    _break(store.local_path, "not_json")
    store.save_local(_own_vault(OWN_VALUES))
    load: VaultLoad = store.load()
    assert load.local_state is VaultLayerState.READ
    assert load.own.get(SecretField.SHEETS_ID) == _secret(SecretField.SHEETS_ID, OWN_VALUES[SecretField.SHEETS_ID])


# --- VaultStore.open собирает объект из путей установки


def test_open_builds_the_store_from_paths(livecraft_paths: LivecraftPaths) -> None:
    opened: VaultStore = VaultStore.open(livecraft_paths)
    assert opened.local_path == livecraft_paths.file(FileName.VAULT_LOCAL)
    assert opened.token_path == livecraft_paths.file(FileName.VAULT_TOKEN)
    assert opened.dpapi.is_available


# --- слои сейфа: слой токена как прочитан и личный отдельно (настройщик, §8.2)


def test_own_over_token_keeps_the_token_layer_whole(store: VaultStore) -> None:
    """Под своим значением значение из токена не теряется: без него не посчитать «Вернуть значение из токена»."""
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    loaded: VaultLoad = store.load()
    assert _values_of(loaded.token) == TOKEN_VALUES
    assert _values_of(loaded.own) == OWN_VALUES
    assert loaded.vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert loaded.vault.origin_of(SecretField.OPENAI_API_KEY) is VaultOrigin.TOKEN


def test_an_unreadable_local_file_leaves_no_own_layer(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    del data[KEY_WRAPPED]
    _rewrite_local(store, data)
    loaded: VaultLoad = store.load()
    assert loaded.own == Vault.empty()
    assert _values_of(loaded.token) == TOKEN_VALUES


# --- сейф для запуска одним значением: прочитан или ошибка файла


def test_a_vault_read_is_the_vault_or_the_file_error(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    read: VaultRead = VaultRead.of(store)
    assert read.error is None and read.vault is not None and _values_of(read.vault) == TOKEN_VALUES
    store.token_path.write_text("не json", encoding=TEXT_ENCODING)
    broken: VaultRead = VaultRead.of(store)
    assert broken.vault is None and broken.error is not None and broken.error.source is VaultOrigin.TOKEN


def test_an_unreadable_own_file_is_said_loudly_with_the_field_names(store: VaultStore) -> None:
    """Молча работать без своих значений нельзя (§16); поля называются их названиями."""
    _write_token(store, TOKEN_VALUES)
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    data.pop(KEY_WRAPPED)
    _rewrite_local(store, data)
    read: VaultRead = VaultRead.of(store)
    fields: str = msg.LIST_JOINER.join(field.human_label for field in SecretField)
    assert read.is_local_unreadable
    assert read.load is not None and read.load.warnings == (msg.VAULT_LOCAL_UNREADABLE.format(fields=fields),)


def test_a_readable_vault_says_nothing_loudly(store: VaultStore) -> None:
    _write_token(store, TOKEN_VALUES)
    assert store.load().warnings == ()


def test_the_unreadable_line_names_the_reason_without_values(store: VaultStore, caplog: pytest.LogCaptureFixture) -> None:
    store.save_local(_own_vault(OWN_VALUES))
    data: dict[str, Any] = _local_json(store)
    _flip_ciphertext(data, SecretField.SHEETS_ID)
    _rewrite_local(store, data)
    with caplog.at_level("INFO", logger="livecraft"):
        store.load()
    lines: list[str] = [record.getMessage() for record in caplog.records if record.getMessage().startswith("vault_unreadable")]
    assert lines == [f"vault_unreadable source=own reason=decrypt field={SecretField.SHEETS_ID.log_label} cause=tag_mismatch"]


def test_the_source_names_are_english_identifiers() -> None:
    """Значение уходит в лог вместо пути к секретам (§7.4)."""
    assert [origin.value for origin in VaultOrigin] == ["token", "own"]
