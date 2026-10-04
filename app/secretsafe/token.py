"""Токен доступа: значения, которые человек внёс сам, — другому человеку одним файлом (CLAUDE.md §7.1, §7.3, §14
решения 11, 16, 44, 45).

Файл токена `*.lctoken` — двоичный: заголовок (магия, версия, id токена, момент создания, «действует до», нонс),
32 байта ключа, затем шифротекст AES-GCM содержимого. Заголовок — AAD шифра: подмена любого его байта ломает
расшифровку. Пароля нет: токен загрузит любой, у кого он окажется (§7.2 — защита от копирования, а не от специалиста).
Токен прежней версии (1: пара «токен + ключ» или один файл с байтом вида) не читается — причина VERSION: создать новый.

Содержимое (`TokenContent`) — сейф и открытые настройки. Сейф внутри — тот же файл сейфа (`SealedVault`) на ключе
токена: каждое поле шифрует сам секрет (`SecretValue.encrypt`), значения не раскрываются ни при создании, ни при
загрузке. Открытые настройки — пары «ключ настройки — значение»; какие это ключи, решает настройщик, токен их не знает.

Время создания и загрузки — время сети (`NetworkTime`), срок — в заголовке. Любой отказ чтения — `TokenError` с
причиной для человека; английская подробность — только в лог.
"""
from __future__ import annotations

import json
import os
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.errors import os_error_reason
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogEvent
from app.paths import AtomicFile
from app.secretsafe.crypto import (
    NONCE_BYTES,
    SALT_BYTES,
    VAULT_KEY_BYTES,
    VaultCrypto,
    VaultDecryptError,
    VaultFile,
    VaultFormatError,
)
from app.secretsafe.field import VaultOrigin
from app.secretsafe.sealed import SealedVault
from app.secretsafe.vault import Vault
from app.ui.messages import msg

TOKEN_MAGIC: Final[bytes] = b"LCTK"
TOKEN_VERSION: Final[int] = 2
TOKEN_ID_BYTES: Final[int] = 16
# Заголовок токена: магия, версия, id токена, создан и действует до (секунды UTC), нонс шифра содержимого.
TOKEN_HEADER: Final[struct.Struct] = struct.Struct(f">4sB{TOKEN_ID_BYTES}sqq{NONCE_BYTES}s")
TOKEN_HKDF_INFO: Final[bytes] = b"livecraft.token.v1"
TOKEN_SUFFIX: Final[str] = ".lctoken"
# Подробности отказов — для разработчика, только в лог.
DETAIL_SHORT: Final[str] = "file is {got} bytes, expected at least {expected}"
DETAIL_MAGIC: Final[str] = "magic {got!r}, expected {expected!r}"
DETAIL_VERSION: Final[str] = "version {got}, expected {expected}"
DETAIL_TAG: Final[str] = "content does not decrypt with this key and header"
DETAIL_CONTENT: Final[str] = "decrypted content is not the token content"
DETAIL_EXPIRED: Final[str] = "valid until {until}, network time {now}"
DETAIL_MOMENT: Final[str] = "header moments {created} and {until} are not calendar moments"


class TokenProblem(str, Enum):
    """Почему токен не создан или не загружен — причина для человека. Значение — идентификатор для лога."""

    NO_NETWORK = "no_network"            # время сети не получено: ни создания, ни загрузки
    FILE_UNREADABLE = "file_unreadable"  # файл не открылся
    NOT_TOKEN = "not_token"              # файл — не токен Livecraft
    VERSION = "version"                  # токен другой версии программы
    DAMAGED = "damaged"                  # файл повреждён или подменён
    EXPIRED = "expired"                  # срок токена истёк

    @property
    def human(self) -> str:
        return msg.TOKEN_PROBLEM_TEXT[self.value]


class TokenEvent(str, Enum):
    """События токена в логе."""

    REFUSED = "token_refused"


class TokenError(Exception):
    """Токен не прочитан: причина для человека (`human` — текст ошибки) и подробность для лога."""

    def __init__(self, reason: TokenProblem, detail: str) -> None:
        self.reason: TokenProblem = reason
        self.detail: str = detail
        super().__init__(self.human)

    @property
    def human(self) -> str:
        return self.reason.human

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(TokenEvent.REFUSED, reason=self.reason, detail=self.detail)

    @property
    def log_line(self) -> str:
        return self.event.text

    def __str__(self) -> str:
        return self.human


@dataclass(frozen=True)
class TokenBytes:
    """Байты файла токена и правило «прочитать с диска»: не открылся — отказ с причиной."""

    data: bytes

    @classmethod
    def read(cls, path: Path) -> TokenBytes:
        try:
            return cls(path.read_bytes())
        except OSError as error:
            raise TokenError(TokenProblem.FILE_UNREADABLE, os_error_reason(error)) from error

    def check(self) -> None:
        """Заголовок токена в начале файла на месте: короче заголовка или не та магия — не токен, другая версия —
        VERSION (у токенов всех версий магия и версия — в начале, а заголовок прежней версии длиннее нынешнего)."""
        if len(self.data) < TOKEN_HEADER.size:
            detail: str = DETAIL_SHORT.format(got=len(self.data), expected=TOKEN_HEADER.size)
            raise TokenError(TokenProblem.NOT_TOKEN, detail)
        found_magic, version, *_rest = TOKEN_HEADER.unpack_from(self.data)
        if found_magic != TOKEN_MAGIC:
            raise TokenError(TokenProblem.NOT_TOKEN, DETAIL_MAGIC.format(got=found_magic, expected=TOKEN_MAGIC))
        if version != TOKEN_VERSION:
            raise TokenError(TokenProblem.VERSION, DETAIL_VERSION.format(got=version, expected=TOKEN_VERSION))


@dataclass(frozen=True)
class TokenKey:
    """Ключ токена: id токена и 32 случайных байта; лежит в самом файле токена, после заголовка."""

    token_id: bytes
    material: bytes

    @classmethod
    def new(cls) -> TokenKey:
        return cls(token_id=os.urandom(TOKEN_ID_BYTES), material=os.urandom(VAULT_KEY_BYTES))

    @property
    def cipher(self) -> AESGCM:
        """Шифр содержимого: ключ из HKDF-SHA256 от ключа токена, соль — id токена."""
        derive: HKDF = HKDF(algorithm=hashes.SHA256(), length=VAULT_KEY_BYTES, salt=self.token_id, info=TOKEN_HKDF_INFO)
        return AESGCM(derive.derive(self.material))


@dataclass(frozen=True)
class TokenHeader:
    """Заголовок токена: id токена, когда создан и до какого момента его можно загрузить, нонс шифра содержимого."""

    token_id: bytes
    created: datetime
    valid_until: datetime
    nonce: bytes

    @classmethod
    def parse(cls, data: TokenBytes) -> TokenHeader:
        """Заголовок файла; момент, которого нет в календаре (изменённый байт), — токен повреждён: подмену остальных
        байтов заголовка поймает шифр (заголовок — его AAD)."""
        data.check()
        _magic, _version, token_id, created, valid_until, nonce = TOKEN_HEADER.unpack_from(data.data)
        try:
            start, end = (datetime.fromtimestamp(value, tz=UTC) for value in (created, valid_until))
        except (OverflowError, ValueError, OSError) as error:
            raise TokenError(TokenProblem.DAMAGED, DETAIL_MOMENT.format(created=created, until=valid_until)) from error
        return cls(token_id=token_id, created=start, valid_until=end, nonce=nonce)

    def render(self) -> bytes:
        """Заголовок как в файле — он же AAD шифра содержимого."""
        created: int = int(self.created.timestamp())
        until: int = int(self.valid_until.timestamp())
        return TOKEN_HEADER.pack(TOKEN_MAGIC, TOKEN_VERSION, self.token_id, created, until, self.nonce)


class ContentKey(str, Enum):
    """Записи содержимого токена."""

    VAULT = "vault"
    SETTINGS = "settings"


@dataclass(frozen=True)
class TokenContent:
    """Что несёт токен: значения сейфа (при создании — свои, при загрузке — «из токена») и открытые настройки."""

    vault: Vault
    settings: Mapping[str, str]

    def seal(self, key: TokenKey, header: TokenHeader) -> bytes:
        """Шифротекст содержимого: сейф — файлом сейфа на ключе токена, всё вместе — AES-GCM с заголовком в AAD."""
        crypto: VaultCrypto = VaultCrypto(key=key.material, salt=os.urandom(SALT_BYTES))
        sealed: SealedVault = SealedVault.seal(self.vault, crypto, None)
        payload: str = json.dumps(
            {ContentKey.VAULT.value: sealed.file.render(), ContentKey.SETTINGS.value: dict(self.settings)}
        )
        return key.cipher.encrypt(header.nonce, payload.encode(TEXT_ENCODING), header.render())

    @classmethod
    def opened(cls, ciphertext: bytes, key: TokenKey, header: TokenHeader) -> TokenContent:
        """Содержимое, расшифрованное ключом: подменённый байт токена — токен повреждён."""
        try:
            payload: bytes = key.cipher.decrypt(header.nonce, ciphertext, header.render())
        except InvalidTag as error:
            raise TokenError(TokenProblem.DAMAGED, DETAIL_TAG) from error
        data: object = json.loads(payload.decode(TEXT_ENCODING))
        vault_text: object = data.get(ContentKey.VAULT.value) if isinstance(data, dict) else None
        settings: object = data.get(ContentKey.SETTINGS.value) if isinstance(data, dict) else None
        if not isinstance(vault_text, str) or not isinstance(settings, dict):
            raise TokenError(TokenProblem.DAMAGED, DETAIL_CONTENT)
        try:
            vault: Vault = SealedVault(VaultFile.parse(vault_text)).open(key.material, VaultOrigin.TOKEN)
        except (VaultFormatError, VaultDecryptError) as error:
            raise TokenError(TokenProblem.DAMAGED, DETAIL_CONTENT) from error
        return cls(vault=vault, settings={str(name): str(value) for name, value in settings.items()})


@dataclass(frozen=True)
class TokenOrder:
    """Какой токен создать: срок в сутках (§14 решение 44)."""

    days: int

    def valid_until(self, created: datetime) -> datetime:
        return created + timedelta(days=self.days)


@dataclass(frozen=True)
class AccessToken:
    """Токен доступа: заголовок, ключ (он в самом файле) и шифротекст содержимого."""

    header: TokenHeader
    key: TokenKey
    ciphertext: bytes

    @classmethod
    def read(cls, path: Path) -> AccessToken:
        """Файл токена: не токен, другая версия, повреждён или не открылся — TokenError."""
        data: TokenBytes = TokenBytes.read(path)
        header: TokenHeader = TokenHeader.parse(data)
        rest: bytes = data.data[TOKEN_HEADER.size:]
        key: TokenKey = TokenKey(token_id=header.token_id, material=rest[:VAULT_KEY_BYTES])
        return cls(header=header, key=key, ciphertext=rest[VAULT_KEY_BYTES:])

    def open(self, now: datetime) -> TokenContent:
        """Содержимое токена на время сети `now`: токен повреждён или срок истёк — TokenError."""
        content: TokenContent = TokenContent.opened(self.ciphertext, self.key, self.header)
        if now > self.header.valid_until:
            detail: str = DETAIL_EXPIRED.format(until=self.header.valid_until.isoformat(), now=now.isoformat())
            raise TokenError(TokenProblem.EXPIRED, detail)
        return content

    def render(self) -> bytes:
        """Файл токена: заголовок, ключ, шифротекст."""
        return self.header.render() + self.key.material + self.ciphertext


@dataclass(frozen=True)
class IssuedToken:
    """Только что созданный токен: ключ — в нём самом, файл один."""

    token: AccessToken

    @classmethod
    def of(cls, content: TokenContent, order: TokenOrder, created: datetime) -> IssuedToken:
        """Новый токен срока `order` на новом ключе; момент создания — время сети."""
        key: TokenKey = TokenKey.new()
        header: TokenHeader = TokenHeader(
            token_id=key.token_id, created=created, valid_until=order.valid_until(created),
            nonce=os.urandom(NONCE_BYTES),
        )
        return cls(AccessToken(header=header, key=key, ciphertext=content.seal(key, header)))

    def write(self, stem: Path) -> Path:
        """`<stem>.lctoken` — атомарно; путь файла. Сбой — OSError."""
        path: Path = stem.with_name(stem.name + TOKEN_SUFFIX)
        data: bytes = self.token.render()
        AtomicFile.at(path).write(lambda temp: temp.write_bytes(data))
        return path
