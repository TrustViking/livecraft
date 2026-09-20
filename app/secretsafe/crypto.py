"""Шифрование файлов сейфа: AES-256-GCM, ключ из HKDF, привязка к имени поля (CLAUDE.md §7.3).

Что здесь есть и почему именно так:

- Шифр — **AES-256-GCM** (`AESGCM` из `cryptography`, уже в окружении, инвариант 11): аутентифицированный,
  подмена байта ломает расшифровку, а не даёт мусор.
- Ключ шифрования — `HKDF-SHA256(ikm = ключ сейфа, salt = 16 случайных байт файла, info = HKDF_INFO)`:
  сам ключ сейфа в шифровании не участвует, у каждого файла свой производный ключ (соль у файла своя).
- На каждое шифрование — свой `nonce` (12 случайных байт), никогда повторно: повтор нонса при одном ключе
  ломает GCM полностью.
- AAD = имя поля плюс версия формата. Из-за неё блоб из `sheets_id` нельзя переставить в `key_form_url`:
  расшифровка такого блоба падает, а не отдаёт значение чужого поля.

Записи на диск здесь нет: `VaultFile.render()` отдаёт текст, а пишет его `VaultStore` (задача 1.2) через
`paths.write_text_atomically`. Тексты ошибок называют поле и версию формата — ни значений, ни ключа (§7.4).
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from typing import Any, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.secretsafe.value import SecretField

FORMAT_VERSION: Final[int] = 1
HKDF_INFO: Final[bytes] = b"livecraft.vault.v1"
VAULT_KEY_BYTES: Final[int] = 32       # AES-256
FIELD_KEY_BYTES: Final[int] = 32       # столько же: HKDF выдаёт ключ поля под тот же шифр
SALT_BYTES: Final[int] = 16
NONCE_BYTES: Final[int] = 12           # рекомендованная длина нонса GCM
PLAINTEXT_ENCODING: Final[str] = "utf-8"

KEY_VERSION: Final[str] = "version"
KEY_SALT: Final[str] = "salt"
KEY_FIELDS: Final[str] = "fields"
KEY_NONCE: Final[str] = "nonce"
KEY_CIPHERTEXT: Final[str] = "ct"
KEY_WRAPPED: Final[str] = "key"      # завёрнутый DPAPI ключ файла; только у локального сейфа (§14, решение 9)


class VaultFormatError(Exception):
    """Файл сейфа не того формата: версия, структура или base64. Значений в тексте нет (§7.4)."""


class VaultDecryptError(Exception):
    """Блоб не расшифровался: подмена байта, чужой ключ сейфа или блоб другого поля."""


@dataclass(frozen=True)
class EncryptedField:
    """Зашифрованное значение одного поля: нонс и шифротекст с тегом GCM внутри."""

    nonce: bytes
    ciphertext: bytes

    def to_json(self) -> dict[str, str]:
        """Как поле выглядит в файле сейфа: два base64."""
        return {
            KEY_NONCE: base64.b64encode(self.nonce).decode("ascii"),
            KEY_CIPHERTEXT: base64.b64encode(self.ciphertext).decode("ascii"),
        }

    @classmethod
    def from_json(cls, name: str, data: Any) -> EncryptedField:
        """Разбор записи поля; не объект, не base64, пусто или не тот нонс — VaultFormatError с именем поля."""
        if not isinstance(data, dict):
            raise VaultFormatError(f"field {name!r}: expected an object with {KEY_NONCE!r} and {KEY_CIPHERTEXT!r}")
        nonce: bytes = cls._decode(name, data, KEY_NONCE)
        ciphertext: bytes = cls._decode(name, data, KEY_CIPHERTEXT)
        if len(nonce) != NONCE_BYTES:
            raise VaultFormatError(f"field {name!r}: {KEY_NONCE!r} must be {NONCE_BYTES} bytes, got {len(nonce)}")
        return cls(nonce=nonce, ciphertext=ciphertext)

    @staticmethod
    def _decode(name: str, data: dict[str, Any], key: str) -> bytes:
        raw: Any = data.get(key)
        if not isinstance(raw, str) or not raw:
            raise VaultFormatError(f"field {name!r}: {key!r} must be a non-empty base64 string")
        try:
            return base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VaultFormatError(f"field {name!r}: {key!r} is not valid base64: {error}") from error


@dataclass(frozen=True)
class VaultFile:
    """Содержимое файла сейфа как объект: версия формата, соль файла, зашифрованные поля и, может быть,
    завёрнутый ключ этого файла.

    `wrapped_key` — пятая запись `"key"` (§14, решение 9): 32 байта ключа файла, завёрнутые DPAPI. Она есть
    только у локального сейфа; у поставочного ключ приходит извне (`ProgramKey`), и записи `"key"` в нём
    нет и быть не должно. Кому какая запись положена, решает `VaultStore`; файл лишь умеет её нести.
    """

    version: int
    salt: bytes
    fields: dict[str, EncryptedField]
    wrapped_key: bytes | None = None

    @classmethod
    def empty(cls) -> VaultFile:
        """Новый файл: своя случайная соль, полей ещё нет, ключа в файле нет."""
        return cls(version=FORMAT_VERSION, salt=os.urandom(SALT_BYTES), fields={})

    @classmethod
    def parse(cls, text: str) -> VaultFile:
        """Разбор файла сейфа. Неизвестная версия формата — ошибка, а не тихое игнорирование (§7.3)."""
        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError as error:
            raise VaultFormatError(f"vault file is not valid JSON: {error}") from error
        if not isinstance(data, dict):
            raise VaultFormatError("vault file must be a JSON object")
        version: Any = data.get(KEY_VERSION)
        # Строго целое и строго не bool: в Python 1.0 == 1 и True == 1, поэтому «version»: 1.0 без этой
        # проверки прошла бы за версию 1 — то есть файл чужого формата приняли бы молча (§7.3).
        if not isinstance(version, int) or isinstance(version, bool) or version != FORMAT_VERSION:
            raise VaultFormatError(f"unsupported vault format version {version!r}, expected {FORMAT_VERSION}")
        salt: bytes = cls._decode_salt(data)
        raw_fields: Any = data.get(KEY_FIELDS)
        if not isinstance(raw_fields, dict):
            raise VaultFormatError(f"{KEY_FIELDS!r} must be an object")
        return cls(
            version=FORMAT_VERSION,
            salt=salt,
            fields={name: EncryptedField.from_json(name, blob) for name, blob in raw_fields.items()},
            wrapped_key=cls._decode_wrapped_key(data),
        )

    def render(self) -> str:
        """Текст файла сейфа; писать его на диск — дело VaultStore. Нет ключа — нет и записи «key»."""
        data: dict[str, Any] = {
            KEY_VERSION: self.version,
            KEY_SALT: base64.b64encode(self.salt).decode("ascii"),
            KEY_FIELDS: {name: blob.to_json() for name, blob in self.fields.items()},
        }
        if self.wrapped_key is not None:
            data[KEY_WRAPPED] = base64.b64encode(self.wrapped_key).decode("ascii")
        return json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True)

    @staticmethod
    def _decode_wrapped_key(data: dict[str, Any]) -> bytes | None:
        """Записи «key» нет — файл её и не несёт (так устроен поставочный сейф); есть, но не base64 — ошибка."""
        if KEY_WRAPPED not in data:
            return None
        raw: Any = data[KEY_WRAPPED]
        if not isinstance(raw, str) or not raw:
            raise VaultFormatError(f"{KEY_WRAPPED!r} must be a non-empty base64 string")
        try:
            return base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VaultFormatError(f"{KEY_WRAPPED!r} is not valid base64: {error}") from error

    @staticmethod
    def _decode_salt(data: dict[str, Any]) -> bytes:
        raw: Any = data.get(KEY_SALT)
        if not isinstance(raw, str) or not raw:
            raise VaultFormatError(f"{KEY_SALT!r} must be a non-empty base64 string")
        try:
            salt: bytes = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VaultFormatError(f"{KEY_SALT!r} is not valid base64: {error}") from error
        if len(salt) != SALT_BYTES:
            raise VaultFormatError(f"{KEY_SALT!r} must be {SALT_BYTES} bytes, got {len(salt)}")
        return salt


@dataclass(frozen=True)
class VaultCrypto:
    """Криптография сейфа: ключ сейфа плюс соль файла — и правила шифрования каждого поля."""

    key: bytes
    salt: bytes

    def __post_init__(self) -> None:
        """Объект с негодными полями дальше не идёт (§0): короткий ключ или соль — ошибка сразу."""
        if len(self.key) != VAULT_KEY_BYTES:
            raise VaultFormatError(f"vault key must be {VAULT_KEY_BYTES} bytes, got {len(self.key)}")
        if len(self.salt) != SALT_BYTES:
            raise VaultFormatError(f"vault salt must be {SALT_BYTES} bytes, got {len(self.salt)}")

    def encrypt(self, field: SecretField, plaintext: str) -> EncryptedField:
        """Свой нонс на каждое шифрование; AAD привязывает блоб к имени поля и версии формата."""
        nonce: bytes = os.urandom(NONCE_BYTES)
        ciphertext: bytes = AESGCM(self._field_key(field)).encrypt(
            nonce, plaintext.encode(PLAINTEXT_ENCODING), self._aad(field)
        )
        return EncryptedField(nonce=nonce, ciphertext=ciphertext)

    def decrypt(self, field: SecretField, blob: EncryptedField) -> str:
        """Подмена байта, чужой ключ сейфа или блоб другого поля — VaultDecryptError, а не мусор."""
        try:
            plaintext: bytes = AESGCM(self._field_key(field)).decrypt(
                blob.nonce, blob.ciphertext, self._aad(field)
            )
        except InvalidTag as error:
            raise VaultDecryptError(
                f"field {field.value!r} does not decrypt with this vault key, salt and format version "
                f"{FORMAT_VERSION}"
            ) from error
        try:
            return plaintext.decode(PLAINTEXT_ENCODING)
        except UnicodeDecodeError as error:
            raise VaultDecryptError(f"field {field.value!r} decrypted to non-{PLAINTEXT_ENCODING} bytes") from error

    def _field_key(self, field: SecretField) -> bytes:
        """Ключ шифрования по формуле §7.3: HKDF-SHA256 от ключа сейфа, соль файла, info HKDF_INFO.

        Поле в формулу не входит — так записано в §7.3, и разделение полей держит не ключ, а AAD (`_aad`):
        блоб чужого поля не расшифруется, даже если ключ тот же. `field` в подписи оставлен потому, что
        правило «ключ для поля» принадлежит полю и формула может от него зависеть; менять её без §7.3 нельзя.
        HKDF одноразовый — объект строится на каждый вызов.
        """
        return HKDF(
            algorithm=hashes.SHA256(),
            length=FIELD_KEY_BYTES,
            salt=self.salt,
            info=HKDF_INFO,
        ).derive(self.key)

    def _aad(self, field: SecretField) -> bytes:
        """Привязка блоба к месту: имя поля и версия формата. Переставить блоб в другое поле не выйдет."""
        return f"{field.value}|v{FORMAT_VERSION}".encode("ascii")
