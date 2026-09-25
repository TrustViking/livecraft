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
`paths.write_text_atomically`.

Ошибка формата несёт причину для человека (`VaultFormatReason`) и английскую подробность для разработчика:
человек видит русскую строку с именем файла и одним действием, подробность уходит только в лог. Подробность
называет поле, запись и длину — ни значений, ни ключа (§7.4).
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.secretsafe.value import SecretField
from app.ui import messages_ru as msg

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

# Подробности ошибок формата — для разработчика, только в лог: запись, поле и длина, без значений (§7.4).
DETAIL_NOT_JSON: Final[str] = "vault file is not valid JSON: {error}"
DETAIL_NOT_OBJECT: Final[str] = "vault file must be a JSON object"
DETAIL_VERSION: Final[str] = "unsupported vault format version {version!r}, expected {expected}"
DETAIL_FIELDS_NOT_OBJECT: Final[str] = "{key!r} must be an object"
DETAIL_FIELD_NOT_OBJECT: Final[str] = "field {name!r}: expected an object with {nonce!r} and {ciphertext!r}"
DETAIL_RECORD_IN_FIELD: Final[str] = "field {name!r}: {key!r}"
DETAIL_RECORD_NOT_STRING: Final[str] = "{record} must be a non-empty base64 string"
DETAIL_RECORD_NOT_BASE64: Final[str] = "{record} is not valid base64: {error}"
DETAIL_RECORD_LENGTH: Final[str] = "{record} must be {expected} bytes, got {got}"
DETAIL_CRYPTO_LENGTH: Final[str] = "vault {what} must be {expected} bytes, got {got}"
CRYPTO_PART_KEY: Final[str] = "key"
CRYPTO_PART_SALT: Final[str] = "salt"
ERROR_LOG_LINE_TEMPLATE: Final[str] = "file={file} source={source} reason={reason} detail={detail}"
ERROR_LOG_ABSENT: Final[str] = "-"


class VaultSource(str, Enum):
    """Какой файл сейфа имеется в виду. Значение уходит в лог вместо пути: путь секретов не печатаем."""

    SUPPLIED = "supplied"
    LOCAL = "local"


class VaultFormatReason(str, Enum):
    """Почему файл сейфа не читается — причина для человека, а не для разработчика.

    FILE_UNREADABLE — файл не открылся; NOT_TEXT — не UTF-8; DAMAGED — не JSON, не та структура, битый base64,
    нонс или соль не той длины; UNSUPPORTED_VERSION — чужая версия формата; KEY_INVALID — ключ или соль
    `VaultCrypto` не той длины (нарушение инварианта кода, а не поломка файла).
    """

    FILE_UNREADABLE = "file_unreadable"
    NOT_TEXT = "not_text"
    DAMAGED = "damaged"
    UNSUPPORTED_VERSION = "unsupported_version"
    KEY_INVALID = "key_invalid"

    @property
    def human(self) -> str:
        """Причина по-русски — для строки человеку."""
        return msg.VAULT_FORMAT_REASON_TEXT[self.value]


class VaultFormatError(Exception):
    """Файл сейфа не читается: причина, подробность для лога и, когда известно, какой это файл.

    Текст ошибки (`str`) — строка для человека: имя файла, причина и одно действие. Английская подробность
    в текст не входит — только в `log_line`. Значений и ключа нет ни там, ни там (§7.4).
    """

    def __init__(
        self,
        reason: VaultFormatReason,
        detail: str,
        file_name: str | None = None,
        source: VaultSource | None = None,
    ) -> None:
        super().__init__(reason, detail)
        self.reason: VaultFormatReason = reason
        self.detail: str = detail
        self.file_name: str | None = file_name
        self.source: VaultSource | None = source

    def located(self, file_name: str, source: VaultSource) -> VaultFormatError:
        """Та же причина и подробность — с именем файла и тем, чей он: личный или пришедший с программой."""
        return VaultFormatError(self.reason, self.detail, file_name=file_name, source=source)

    @property
    def problem(self) -> str:
        """Коротко: файл и причина; файл неизвестен — только причина."""
        if self.file_name is None:
            return self.reason.human
        return msg.VAULT_FILE_PROBLEM.format(file=self.file_name, reason=self.reason.human)

    @property
    def is_replaceable(self) -> bool:
        """Файл личный: настройщик заменит его первым сохранением. Файл программы заменяет только установка."""
        return self.source is VaultSource.LOCAL

    @property
    def advice(self) -> str:
        """Одно точное действие для человека."""
        return msg.VAULT_FILE_ADVICE_LOCAL if self.is_replaceable else msg.VAULT_FILE_ADVICE_SUPPLIED

    @property
    def human(self) -> str:
        """Строка для человека: что не читается, почему и что сделать."""
        return msg.VAULT_FILE_BROKEN.format(problem=self.problem, advice=self.advice)

    @property
    def log_line(self) -> str:
        """Строка для лога: файл, чей он, причина и английская подробность."""
        return ERROR_LOG_LINE_TEMPLATE.format(
            file=self.file_name or ERROR_LOG_ABSENT,
            source=ERROR_LOG_ABSENT if self.source is None else self.source.value,
            reason=self.reason.value,
            detail=self.detail,
        )

    def __str__(self) -> str:
        return self.human


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
            raise VaultFormatError(
                VaultFormatReason.DAMAGED,
                DETAIL_FIELD_NOT_OBJECT.format(name=name, nonce=KEY_NONCE, ciphertext=KEY_CIPHERTEXT),
            )
        nonce_record: Base64Record = Base64Record.in_field(name, KEY_NONCE)
        nonce: bytes = nonce_record.decode(data.get(KEY_NONCE))
        ciphertext: bytes = Base64Record.in_field(name, KEY_CIPHERTEXT).decode(data.get(KEY_CIPHERTEXT))
        return cls(nonce=nonce_record.exact(nonce, NONCE_BYTES), ciphertext=ciphertext)


@dataclass(frozen=True)
class Base64Record:
    """Запись файла сейфа в base64 и правила её разбора; `label` — где она лежит, для подробности ошибки."""

    label: str

    @classmethod
    def top(cls, key: str) -> Base64Record:
        """Запись верхнего уровня файла: соль, завёрнутый ключ."""
        return cls(label=repr(key))

    @classmethod
    def in_field(cls, name: str, key: str) -> Base64Record:
        """Запись внутри поля: нонс или шифротекст."""
        return cls(label=DETAIL_RECORD_IN_FIELD.format(name=name, key=key))

    def decode(self, raw: Any) -> bytes:
        """Непустая строка base64 — её байты; иначе VaultFormatError «повреждён»."""
        if not isinstance(raw, str) or not raw:
            raise VaultFormatError(VaultFormatReason.DAMAGED, DETAIL_RECORD_NOT_STRING.format(record=self.label))
        try:
            return base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VaultFormatError(
                VaultFormatReason.DAMAGED, DETAIL_RECORD_NOT_BASE64.format(record=self.label, error=error)
            ) from error

    def exact(self, value: bytes, length: int) -> bytes:
        """Байты записи ровно нужной длины; иначе VaultFormatError «повреждён»."""
        if len(value) != length:
            raise VaultFormatError(
                VaultFormatReason.DAMAGED,
                DETAIL_RECORD_LENGTH.format(record=self.label, expected=length, got=len(value)),
            )
        return value


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
            raise VaultFormatError(VaultFormatReason.DAMAGED, DETAIL_NOT_JSON.format(error=error)) from error
        if not isinstance(data, dict):
            raise VaultFormatError(VaultFormatReason.DAMAGED, DETAIL_NOT_OBJECT)
        version: Any = data.get(KEY_VERSION)
        # Строго целое и строго не bool: в Python 1.0 == 1 и True == 1, поэтому «version»: 1.0 без этой
        # проверки прошла бы за версию 1 — то есть файл чужого формата приняли бы молча (§7.3).
        if not isinstance(version, int) or isinstance(version, bool) or version != FORMAT_VERSION:
            raise VaultFormatError(
                VaultFormatReason.UNSUPPORTED_VERSION, DETAIL_VERSION.format(version=version, expected=FORMAT_VERSION)
            )
        salt_record: Base64Record = Base64Record.top(KEY_SALT)
        salt: bytes = salt_record.exact(salt_record.decode(data.get(KEY_SALT)), SALT_BYTES)
        raw_fields: Any = data.get(KEY_FIELDS)
        if not isinstance(raw_fields, dict):
            raise VaultFormatError(VaultFormatReason.DAMAGED, DETAIL_FIELDS_NOT_OBJECT.format(key=KEY_FIELDS))
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
        return Base64Record.top(KEY_WRAPPED).decode(data[KEY_WRAPPED])


@dataclass(frozen=True)
class VaultCrypto:
    """Криптография сейфа: ключ сейфа плюс соль файла — и правила шифрования каждого поля."""

    key: bytes
    salt: bytes

    def __post_init__(self) -> None:
        """Объект с негодными полями дальше не идёт (§0): короткий ключ или соль — ошибка сразу."""
        if len(self.key) != VAULT_KEY_BYTES:
            raise VaultFormatError(
                VaultFormatReason.KEY_INVALID,
                DETAIL_CRYPTO_LENGTH.format(what=CRYPTO_PART_KEY, expected=VAULT_KEY_BYTES, got=len(self.key)),
            )
        if len(self.salt) != SALT_BYTES:
            raise VaultFormatError(
                VaultFormatReason.KEY_INVALID,
                DETAIL_CRYPTO_LENGTH.format(what=CRYPTO_PART_SALT, expected=SALT_BYTES, got=len(self.salt)),
            )

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
