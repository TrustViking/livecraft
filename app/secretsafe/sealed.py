"""Сейф в зашифрованном виде и обратно — одно правило для файлов сейфа на диске и для сейфа внутри токена доступа
(CLAUDE.md §7.3, §14 решения 16, 44).

`SealedVault` — содержимое файла сейфа (`VaultFile`: соль, поля, может быть, завёрнутый ключ). Запечатать сейф может
только сам секрет (`SecretValue.encrypt`): значение не выходит из `SecretValue`, сюда приходит только шифротекст (§7.4).
Вскрыть — значит расшифровать каждое известное поле ключом файла и отдать сейф с происхождением этого файла; хоть одно
поле не расшифровалось — `VaultDecryptError` наружу: файлу, в котором подменён байт, не верят целиком. Имена полей,
которых программа не знает (поля прежних версий), называет `unknown_fields`: они не мешают чтению и пропадают при
следующей записи.

Запись прежней версии, значение которой перешло в новые поля (`LegacyField`, §14 решение 60), расшифровывается под
своим прежним именем и даёт значение каждому полю-преемнику, которого в файле нет, с происхождением файла. Записать сейф
можно только полями этой версии: после первой записи прежней записи нет, перенос не повторяется, и значение, которое
человек убрал, не возвращается. Правило одно для личного файла, файла токена и сейфа внутри токена прежней версии.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.observability.log_event import LogArea, LogEvent, get_logger
from app.secretsafe.crypto import EncryptedField, VaultCrypto, VaultFile
from app.secretsafe.field import LegacyField, SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault

LOGGER = get_logger(LogArea.VAULT)


class SealedEvent(str, Enum):
    """События вскрытия сейфа в логе."""

    CARRIED = "vault_fields_carried"    # значение прежней записи перешло в новые поля


@dataclass(frozen=True)
class SealedVault:
    """Сейф в зашифрованном виде: файл сейфа как объект."""

    file: VaultFile

    @classmethod
    def seal(cls, vault: Vault, crypto: VaultCrypto, wrapped_key: bytes | None) -> SealedVault:
        """Все поля `vault` — шифром `crypto` (новая соль и свой нонс на каждое поле); `wrapped_key` — ключ файла,
        завёрнутый DPAPI, у сейфа внутри токена — None."""
        fields: dict[str, EncryptedField] = {
            field.value: entry.secret.encrypt(crypto) for field, entry in vault.entries.items()
        }
        return cls(VaultFile.new(salt=crypto.salt, fields=fields, wrapped_key=wrapped_key))

    def open(self, key: bytes, origin: VaultOrigin) -> Vault:
        """Известные поля, расшифрованные ключом `key`, — сейф с происхождением `origin`. Подменённый байт, чужой ключ
        или блоб другого поля — VaultDecryptError."""
        crypto: VaultCrypto = VaultCrypto(key=key, salt=self.file.salt)
        vault: Vault = Vault.empty()
        for field in SecretField:
            blob: EncryptedField | None = self.file.fields.get(field.value)
            if blob is not None:
                vault = vault.with_field(field, SecretValue(field=field, value=crypto.decrypt(field, blob)), origin)
        for legacy in LegacyField:
            vault = self._carried(vault, legacy, crypto, origin)
        return vault

    def _carried(self, vault: Vault, legacy: LegacyField, crypto: VaultCrypto, origin: VaultOrigin) -> Vault:
        """Значение прежней записи `legacy` — каждому её полю-преемнику, которого в файле нет; записи нет — сейф как
        есть. Строка лога — ярлыки, без значения (§7.4)."""
        blob: EncryptedField | None = self.file.fields.get(legacy.value)
        if blob is None:
            return vault
        value: str = crypto.decrypt(legacy, blob)
        targets: tuple[SecretField, ...] = tuple(
            field for field in legacy.successors if field.value not in self.file.fields
        )
        for field in targets:
            vault = vault.with_field(field, SecretValue(field=field, value=value), origin)
        labels: tuple[str, ...] = tuple(field.log_label for field in targets)
        LogEvent.of(SealedEvent.CARRIED, source=origin, legacy=legacy.log_label, fields=labels).emit(LOGGER)
        return vault

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        """Записи полей, которых программа не знает, — по алфавиту; прежние записи с преемниками она знает."""
        known: frozenset[str] = SecretField.names() | LegacyField.names()
        return tuple(sorted(name for name in self.file.fields if name not in known))
