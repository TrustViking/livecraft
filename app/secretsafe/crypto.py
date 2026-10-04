"""Шифрование файлов сейфа: AES-256-GCM, ключ из HKDF, привязка к имени поля (CLAUDE.md §7.3).

Что здесь есть и почему именно так:

- Шифр — **AES-256-GCM** (`AESGCM` из `cryptography`, уже в окружении, инвариант 11): аутентифицированный,
  подмена байта ломает расшифровку, а не даёт мусор.
- Ключ шифрования — `HKDF-SHA256(ikm = ключ сейфа, salt = 16 случайных байт файла, info = HKDF_INFO)`:
  сам ключ сейфа в шифровании не участвует, у каждого файла свой производный ключ (соль у файла своя).
- На каждое шифрование — свой `nonce` (12 случайных байт), никогда повторно: повтор нонса при одном ключе
  ломает GCM полностью.
- AAD = имя поля плюс версия формата. Из-за неё блоб из `sheets_id` нельзя переставить в `telegram_bot_token`:
  расшифровка такого блоба падает, а не отдаёт значение чужого поля.

Секрета (`SecretValue`) шифр не знает: шифрует строку поля, которую ему передал сам секрет (`SecretValue.encrypt`).
Записи на диск здесь нет: `VaultFile.render()` отдаёт текст, а пишет его `VaultStore` через
`paths.write_text_atomically`.

Ошибки — по контракту (§11): причина для человека и английская подробность только для лога. Подробность
называет поле, запись и длину — ни значений, ни ключа (§7.4).
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogEvent
from app.secretsafe.field import SecretField, VaultOrigin
from app.ui.messages import msg

FORMAT_VERSION: Final[int] = 1
HKDF_INFO: Final[bytes] = b"livecraft.vault.v1"
VAULT_KEY_BYTES: Final[int] = 32       # AES-256
FIELD_KEY_BYTES: Final[int] = 32       # столько же: HKDF выдаёт ключ поля под тот же шифр
SALT_BYTES: Final[int] = 16
NONCE_BYTES: Final[int] = 12           # рекомендованная длина нонса GCM
BASE64_ALPHABET: Final[str] = "ascii"  # base64 и AAD — только ASCII
FILE_INDENT: Final[int] = 2
AAD_TEMPLATE: Final[str] = "{field}|v{version}"

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


class VaultFileKey(str, Enum):
    """Записи файла сейфа: верхнего уровня и внутри поля."""

    VERSION = "version"
    SALT = "salt"
    FIELDS = "fields"
    WRAPPED_KEY = "key"      # завёрнутый DPAPI ключ файла; только у личного сейфа (§14, решение 9)
    NONCE = "nonce"
    CIPHERTEXT = "ct"


class CryptoEvent(str, Enum):
    """События шифра в логе."""

    FORMAT_ERROR = "vault_format_error"
    DECRYPT_FAILED = "vault_decrypt_failed"


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
        """Причина словами — для строки человеку."""
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
        source: VaultOrigin | None = None,
    ) -> None:
        self.reason: VaultFormatReason = reason
        self.detail: str = detail
        self.file_name: str | None = file_name
        self.source: VaultOrigin | None = source
        super().__init__(self.human)

    def located(self, file_name: str, source: VaultOrigin) -> VaultFormatError:
        """Та же причина и подробность — с именем файла и тем, чей он: личный или слой токена."""
        return VaultFormatError(self.reason, self.detail, file_name=file_name, source=source)

    @property
    def problem(self) -> str:
        """Коротко: файл и причина; файл неизвестен — только причина."""
        if self.file_name is None:
            return self.reason.human
        return msg.VAULT_FILE_PROBLEM.format(file=self.file_name, reason=self.reason.human)

    @property
    def advice(self) -> str:
        """Одно точное действие для человека: свой файл заменит сохранение своих значений, файл токена — загрузка
        токена; оба — в окне настройщика."""
        return msg.VAULT_FILE_ADVICE_TOKEN if self.source is VaultOrigin.TOKEN else msg.VAULT_FILE_ADVICE_LOCAL

    @property
    def human(self) -> str:
        """Строка для человека: что не читается, почему и что сделать."""
        return msg.VAULT_FILE_BROKEN.format(problem=self.problem, advice=self.advice)

    def event(self, name: Enum) -> LogEvent:
        """Строка лога об этой ошибке под именем события вызывающего: файл, чей он, причина и подробность."""
        return LogEvent.of(name, file=self.file_name, source=self.source, reason=self.reason, detail=self.detail)

    @property
    def log_line(self) -> str:
        return self.event(CryptoEvent.FORMAT_ERROR).text

    def __str__(self) -> str:
        return self.human


class DecryptReason(str, Enum):
    """Почему блоб поля не расшифровался."""

    TAG_MISMATCH = "tag_mismatch"   # подмена байта, чужой ключ или соль, блоб другого поля
    NOT_TEXT = "not_text"           # расшифровалось, но это не текст UTF-8

    @property
    def human(self) -> str:
        return msg.VAULT_DECRYPT_REASON_TEXT[self.value]


class VaultDecryptError(Exception):
    """Блоб не расшифровался: подмена байта, чужой ключ сейфа или блоб другого поля. Значения в тексте нет."""

    DETAIL: ClassVar[str] = "blob does not decrypt with this vault key, salt and format version"

    def __init__(self, field: SecretField, reason: DecryptReason) -> None:
        self.field: SecretField = field
        self.reason: DecryptReason = reason
        super().__init__(self.human)

    @property
    def human(self) -> str:
        return msg.VAULT_DECRYPT_FAILED.format(field=self.field.human_label, reason=self.reason.human)

    @property
    def log_line(self) -> str:
        event: LogEvent = LogEvent.of(CryptoEvent.DECRYPT_FAILED, field=self.field.log_label, reason=self.reason)
        return event.extended(version=FORMAT_VERSION, detail=self.DETAIL).text

    def __str__(self) -> str:
        return self.human


@dataclass(frozen=True)
class EncryptedField:
    """Зашифрованное значение одного поля: нонс и шифротекст с тегом GCM внутри."""

    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True)
class Base64Field:
    """Запись файла сейфа в base64: чей ключ, где она лежит (для подробности ошибки) и сколько в ней байт."""

    key: VaultFileKey
    place: str | None = None       # имя поля, внутри которого запись; None — верхний уровень файла
    length: int | None = None      # None — длина любая, лишь бы не пусто

    @property
    def label(self) -> str:
        if self.place is None:
            return repr(self.key.value)
        return DETAIL_RECORD_IN_FIELD.format(name=self.place, key=self.key.value)

    def read(self, data: Mapping[str, Any]) -> bytes:
        """Непустая строка base64 нужной длины — её байты; иначе VaultFormatError «повреждён»."""
        raw: Any = data.get(self.key.value)
        if not isinstance(raw, str) or not raw:
            raise VaultFormatError(VaultFormatReason.DAMAGED, DETAIL_RECORD_NOT_STRING.format(record=self.label))
        try:
            value: bytes = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VaultFormatError(
                VaultFormatReason.DAMAGED, DETAIL_RECORD_NOT_BASE64.format(record=self.label, error=error)
            ) from error
        if self.length is not None and len(value) != self.length:
            detail: str = DETAIL_RECORD_LENGTH.format(record=self.label, expected=self.length, got=len(value))
            raise VaultFormatError(VaultFormatReason.DAMAGED, detail)
        return value

    def read_optional(self, data: Mapping[str, Any]) -> bytes | None:
        """Записи нет — None (так устроен сейф внутри токена доступа); есть — как у `read`."""
        return self.read(data) if self.key.value in data else None

    def render(self, value: bytes) -> str:
        return base64.b64encode(value).decode(BASE64_ALPHABET)


@dataclass(frozen=True)
class FieldSpec:
    """Поле в файле сейфа: его имя и две записи base64 — нонс ровно своей длины и шифротекст."""

    name: str

    @property
    def nonce(self) -> Base64Field:
        return Base64Field(VaultFileKey.NONCE, place=self.name, length=NONCE_BYTES)

    @property
    def ciphertext(self) -> Base64Field:
        return Base64Field(VaultFileKey.CIPHERTEXT, place=self.name)

    def parse(self, data: Any) -> EncryptedField:
        """Разбор записи поля; не объект, не base64, пусто или не тот нонс — VaultFormatError с именем поля."""
        if not isinstance(data, dict):
            detail: str = DETAIL_FIELD_NOT_OBJECT.format(
                name=self.name, nonce=VaultFileKey.NONCE.value, ciphertext=VaultFileKey.CIPHERTEXT.value
            )
            raise VaultFormatError(VaultFormatReason.DAMAGED, detail)
        return EncryptedField(nonce=self.nonce.read(data), ciphertext=self.ciphertext.read(data))

    def render(self, blob: EncryptedField) -> dict[str, str]:
        """Как поле выглядит в файле сейфа: два base64."""
        return {
            VaultFileKey.NONCE.value: self.nonce.render(blob.nonce),
            VaultFileKey.CIPHERTEXT.value: self.ciphertext.render(blob.ciphertext),
        }


@dataclass(frozen=True)
class VaultFile:
    """Содержимое файла сейфа как объект: версия формата, соль файла, зашифрованные поля и, может быть,
    завёрнутый ключ этого файла.

    `wrapped_key` — запись `"key"` (§14, решение 9): 32 байта ключа файла, завёрнутые DPAPI. Она есть у файлов сейфа на
    диске (личного и слоя токена); у сейфа внутри токена доступа ключ лежит в самом токене (`AccessToken`), и записи
    `"key"` там нет. Кому какая запись положена, решают `VaultStore` и `AccessToken`; файл лишь умеет её нести.
    """

    SALT: ClassVar[Base64Field] = Base64Field(VaultFileKey.SALT, length=SALT_BYTES)
    WRAPPED_KEY: ClassVar[Base64Field] = Base64Field(VaultFileKey.WRAPPED_KEY)

    version: int
    salt: bytes
    fields: dict[str, EncryptedField]
    wrapped_key: bytes | None = None

    @classmethod
    def new(cls, salt: bytes, fields: dict[str, EncryptedField], wrapped_key: bytes | None = None) -> VaultFile:
        """Новый файл нынешней версии формата: соль шифра, поля и, у личного сейфа, завёрнутый ключ."""
        return cls(version=FORMAT_VERSION, salt=salt, fields=fields, wrapped_key=wrapped_key)

    @classmethod
    def parse(cls, text: str) -> VaultFile:
        """Разбор файла сейфа. Неизвестная версия формата — ошибка, а не тихое игнорирование (§7.3)."""
        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError as error:
            raise VaultFormatError(VaultFormatReason.DAMAGED, DETAIL_NOT_JSON.format(error=error)) from error
        if not isinstance(data, dict):
            raise VaultFormatError(VaultFormatReason.DAMAGED, DETAIL_NOT_OBJECT)
        version: Any = data.get(VaultFileKey.VERSION.value)
        # Строго целое и строго не bool: в Python 1.0 == 1 и True == 1, поэтому «version»: 1.0 без этой
        # проверки прошла бы за версию 1 — то есть файл чужого формата приняли бы молча (§7.3).
        if not isinstance(version, int) or isinstance(version, bool) or version != FORMAT_VERSION:
            raise VaultFormatError(
                VaultFormatReason.UNSUPPORTED_VERSION, DETAIL_VERSION.format(version=version, expected=FORMAT_VERSION)
            )
        salt: bytes = cls.SALT.read(data)
        raw_fields: Any = data.get(VaultFileKey.FIELDS.value)
        if not isinstance(raw_fields, dict):
            detail: str = DETAIL_FIELDS_NOT_OBJECT.format(key=VaultFileKey.FIELDS.value)
            raise VaultFormatError(VaultFormatReason.DAMAGED, detail)
        fields: dict[str, EncryptedField] = {name: FieldSpec(name).parse(blob) for name, blob in raw_fields.items()}
        return cls.new(salt=salt, fields=fields, wrapped_key=cls.WRAPPED_KEY.read_optional(data))

    def render(self) -> str:
        """Текст файла сейфа; писать его на диск — дело VaultStore. Нет ключа — нет и записи «key»."""
        data: dict[str, Any] = {
            VaultFileKey.VERSION.value: self.version,
            VaultFileKey.SALT.value: self.SALT.render(self.salt),
            VaultFileKey.FIELDS.value: {name: FieldSpec(name).render(blob) for name, blob in self.fields.items()},
        }
        if self.wrapped_key is not None:
            data[VaultFileKey.WRAPPED_KEY.value] = self.WRAPPED_KEY.render(self.wrapped_key)
        return json.dumps(data, ensure_ascii=True, indent=FILE_INDENT, sort_keys=True)


class CryptoPart(str, Enum):
    """Часть шифра, чью длину проверяет `VaultCrypto`: для подробности ошибки."""

    KEY = "key"
    SALT = "salt"


@dataclass(frozen=True)
class VaultCrypto:
    """Криптография сейфа: ключ сейфа плюс соль файла — и правила шифрования каждого поля."""

    key: bytes
    salt: bytes

    @classmethod
    def new(cls) -> VaultCrypto:
        """Шифр нового файла: свой случайный ключ и своя случайная соль на каждую запись."""
        return cls(key=os.urandom(VAULT_KEY_BYTES), salt=os.urandom(SALT_BYTES))

    def __post_init__(self) -> None:
        """Объект с негодными полями дальше не идёт (§0): короткий ключ или соль — ошибка сразу."""
        lengths: tuple[tuple[CryptoPart, bytes, int], ...] = (
            (CryptoPart.KEY, self.key, VAULT_KEY_BYTES),
            (CryptoPart.SALT, self.salt, SALT_BYTES),
        )
        for part, value, expected in lengths:
            if len(value) != expected:
                detail: str = DETAIL_CRYPTO_LENGTH.format(what=part.value, expected=expected, got=len(value))
                raise VaultFormatError(VaultFormatReason.KEY_INVALID, detail)

    def encrypt(self, field: SecretField, plaintext: str) -> EncryptedField:
        """Свой нонс на каждое шифрование; AAD привязывает блоб к имени поля и версии формата."""
        nonce: bytes = os.urandom(NONCE_BYTES)
        ciphertext: bytes = AESGCM(self._field_key(field)).encrypt(
            nonce, plaintext.encode(TEXT_ENCODING), self._aad(field)
        )
        return EncryptedField(nonce=nonce, ciphertext=ciphertext)

    def decrypt(self, field: SecretField, blob: EncryptedField) -> str:
        """Подмена байта, чужой ключ сейфа или блоб другого поля — VaultDecryptError, а не мусор."""
        try:
            plaintext: bytes = AESGCM(self._field_key(field)).decrypt(blob.nonce, blob.ciphertext, self._aad(field))
        except InvalidTag as error:
            raise VaultDecryptError(field, DecryptReason.TAG_MISMATCH) from error
        try:
            return plaintext.decode(TEXT_ENCODING)
        except UnicodeDecodeError as error:
            raise VaultDecryptError(field, DecryptReason.NOT_TEXT) from error

    def _field_key(self, field: SecretField) -> bytes:
        """Ключ шифрования по формуле §7.3: HKDF-SHA256 от ключа сейфа, соль файла, info HKDF_INFO.

        Поле в формулу не входит — так записано в §7.3, и разделение полей держит не ключ, а AAD (`_aad`):
        блоб чужого поля не расшифруется, даже если ключ тот же. `field` в подписи оставлен потому, что
        правило «ключ для поля» принадлежит полю и формула может от него зависеть; менять её без §7.3 нельзя.
        HKDF одноразовый — объект строится на каждый вызов.
        """
        return HKDF(algorithm=hashes.SHA256(), length=FIELD_KEY_BYTES, salt=self.salt, info=HKDF_INFO).derive(self.key)

    def _aad(self, field: SecretField) -> bytes:
        """Привязка блоба к месту: имя поля и версия формата. Переставить блоб в другое поле не выйдет."""
        return AAD_TEMPLATE.format(field=field.value, version=FORMAT_VERSION).encode(BASE64_ALPHABET)
