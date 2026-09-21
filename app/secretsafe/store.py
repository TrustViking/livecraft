"""Сейф на диске: два файла, два разных ключа, приоритет личного над поставочным (CLAUDE.md §7.3).

| Файл | Ключ | Кто пишет |
|---|---|---|
| `secrets\\vault.local.dat` | 32 случайных байта, завёрнутые DPAPI и лежащие в самом файле записью «key» | настройщик |
| `secrets\\vault.dat` | `ProgramKey` из сборки | сборка Артура |

Поле берётся из локального файла, если оно там есть; иначе — из поставочного (§7.3, таблица приоритета).
Поставочный файл этот объект **никогда не открывает на запись**: `save_local` пишет только локальный, и
только поля, которые пользователь вписал сам (`VaultOrigin.OWN`). Сброс поля к поставке — удаление его из
локального сейфа (`Vault.without_field`), а не правка поставочного.

Ключ локального файла разворачивает только та учётная запись Windows, под которой он был создан (§14,
решение 9): копия файла на другой машине или под другим пользователем бесполезна. Потеря профиля Windows
делает локальный сейф нечитаемым — лечится повторным `--setup`, поставочный сейф при этом не страдает.

Один нечитаемый файл не валит запуск: нет ключа, DPAPI не развернул, блоб подменён — полей этого файла
просто нет, причина уходит в лог, работа продолжается на втором файле. Наружу идёт только `VaultFormatError`
(файл чужого формата, повреждённый или не открывающийся — по §7.3 это код 2; решение о коде принимает
`main`, не этот объект; «файла нет» — только когда его действительно нет) и
`DpapiUnavailable` из `save_local` (записать локальный сейф без DPAPI нельзя, и делать вид, что записали,
запрещено).
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.observability.logging_setup import get_logger
from app.paths import LivecraftPaths, write_text_atomically
from app.secretsafe.crypto import (
    FORMAT_VERSION,
    VAULT_KEY_BYTES,
    EncryptedField,
    VaultCrypto,
    VaultDecryptError,
    VaultFile,
    VaultFormatError,
)
from app.secretsafe.dpapi import Dpapi, DpapiUnavailable
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin

LOGGER = get_logger("vault")

VAULT_FILE_ENCODING: Final[str] = "utf-8"
# Сгенерированный сборкой модуль (build_release.bat, этап 6): несколько частей ключа, а не одна строка.
# Собираются они здесь, в момент использования. Это не криптография, а повышение цены разбора (§7.3).
GENERATED_KEY_MODULE: Final[str] = "app.secretsafe.program_key"
GENERATED_KEY_PARTS: Final[str] = "PARTS"


class VaultSource(str, Enum):
    """Какой файл сейфа имеется в виду. Значение уходит в лог вместо пути: путь секретов не печатаем."""

    SUPPLIED = "supplied"
    LOCAL = "local"


class LocalVaultState(str, Enum):
    """Что с личным сейфом: его нет, он прочитан, или он есть, но не читается.

    Пустой, но прочитанный файл — READ: пользователь сбросил всё к поставке, это не поломка. UNREADABLE —
    файл есть, а значений из него нет: оператор должен узнать об этом громко (§16, требование к связке с main).
    """

    ABSENT = "absent"
    READ = "read"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class VaultLoad:
    """Результат чтения сейфа: сам сейф и состояние личного файла — полем, а не только строкой в логе (§0)."""

    vault: Vault
    local_state: LocalVaultState

    @property
    def is_local_unreadable(self) -> bool:
        """Личный файл есть, но значения из него не прочитаны: работа идёт на поставочных."""
        return self.local_state is LocalVaultState.UNREADABLE


@dataclass(frozen=True)
class ProgramKey:
    """Ключ поставочного сейфа. Нет его — поставочный сейф просто не читается (§7.3, абзац про ProgramKey).

    В git ключа нет. В собранной программе его даёт сгенерированный сборкой модуль, в dev-режиме — файл
    `secrets\\program.key`. Отсутствие модуля в dev-режиме — штатный исход, а не ошибка.
    """

    material: bytes | None

    @classmethod
    def load(cls, dev_key_path: Path) -> ProgramKey:
        """Сначала сгенерированный сборкой модуль, затем файл разработчика; нет ни того ни другого — None."""
        from_module: bytes | None = cls._from_generated_module()
        if from_module is not None:
            return cls(material=from_module)
        return cls(material=cls._from_dev_file(dev_key_path))

    @property
    def is_available(self) -> bool:
        """Есть ли чем открывать поставочный сейф."""
        return self.material is not None

    @classmethod
    def _from_generated_module(cls) -> bytes | None:
        """Части ключа из модуля сборки склеиваются здесь, а не лежат готовой строкой в модуле."""
        try:
            module = __import__(GENERATED_KEY_MODULE, fromlist=[GENERATED_KEY_PARTS])
        except ImportError:
            return None      # dev-режим: модуля нет, и это нормально
        parts: object = getattr(module, GENERATED_KEY_PARTS, None)
        if not isinstance(parts, tuple) or not all(isinstance(part, bytes) for part in parts):
            LOGGER.warning("program_key_module_malformed module=%s", GENERATED_KEY_MODULE)
            return None
        return cls._checked(b"".join(parts), GENERATED_KEY_MODULE)

    @classmethod
    def _from_dev_file(cls, path: Path) -> bytes | None:
        """Файл разработчика: 32 байта либо base64 от них — лишь бы длина совпала."""
        try:
            raw: bytes = path.read_bytes()
        except FileNotFoundError:
            return None      # обычная установка без своего ключа
        except OSError as error:
            LOGGER.warning("program_key_file_unreadable error=%s", error)
            return None
        return cls._checked(cls._as_key_bytes(raw), str(path))

    @staticmethod
    def _as_key_bytes(raw: bytes) -> bytes:
        """Ровно столько байт, сколько нужно ключу, — как есть; иначе пробуем прочитать как base64."""
        if len(raw) == VAULT_KEY_BYTES:
            return raw
        try:
            return base64.b64decode(raw.strip(), validate=True)
        except (ValueError, TypeError):
            return raw

    @staticmethod
    def _checked(material: bytes, origin: str) -> bytes | None:
        """Ключ негодной длины — считается отсутствующим: причина в лог, самих байтов в логе нет (§7.4)."""
        if len(material) != VAULT_KEY_BYTES:
            LOGGER.warning(
                "program_key_wrong_length origin=%s expected=%d got=%d", origin, VAULT_KEY_BYTES, len(material)
            )
            return None
        return material


@dataclass(frozen=True)
class VaultStore:
    """Чтение и запись файлов сейфа. Поставочный файл открывается только на чтение — во всех методах."""

    supplied_path: Path
    local_path: Path
    program_key: ProgramKey
    dpapi: Dpapi

    @classmethod
    def open(cls, paths: LivecraftPaths) -> VaultStore:
        """Сейф этой установки: оба файла из paths, ключ поставки из сборки или program.key, DPAPI машины."""
        return cls(
            supplied_path=paths.vault_file,
            local_path=paths.vault_local_file,
            program_key=ProgramKey.load(paths.program_key_file),
            dpapi=Dpapi.load(),
        )

    def load(self) -> VaultLoad:
        """Оба файла в один сейф: поле локального перекрывает поле поставочного (§7.3)."""
        vault: Vault = self._read_supplied()
        local: VaultLoad = self._read_local()
        for field in SecretField:
            secret: SecretValue | None = local.vault.get(field)
            if secret is None:
                continue
            vault = vault.with_field(field, secret, VaultOrigin.OWN)
        LOGGER.info("vault_loaded fields=%s local=%s", vault.log_line, local.local_state.value)
        return VaultLoad(vault=vault, local_state=local.local_state)

    def save_local(self, vault: Vault) -> None:
        """Записать локальный сейф: только свои поля, новый ключ и новая соль на каждую запись.

        Поставочный файл не трогается. DPAPI недоступен — DpapiUnavailable наружу и файл не создаётся:
        «локальный сейф» без привязки к учётной записи Windows был бы обманом (§7.2, третий абзац).
        """
        key: bytes = os.urandom(VAULT_KEY_BYTES)
        salt: bytes = VaultFile.empty().salt
        crypto: VaultCrypto = VaultCrypto(key=key, salt=salt)
        fields: dict[str, EncryptedField] = {}
        for field in SecretField:
            secret: SecretValue | None = self._own_secret(vault, field)
            if secret is None:
                continue
            # Шифрует себя сам секрет: значение не выходит из SecretValue, сюда возвращается только
            # шифротекст, и своё поле (а с ним привязку блоба к месту) секрет называет сам (§7.4, §0).
            fields[field.value] = secret.encrypt(crypto)
        wrapped_key: bytes = self.dpapi.protect(key)
        text: str = VaultFile(
            version=FORMAT_VERSION, salt=salt, fields=fields, wrapped_key=wrapped_key
        ).render()
        write_text_atomically(self.local_path, text, VAULT_FILE_ENCODING)
        LOGGER.info("vault_local_saved fields=%d", len(fields))

    def _own_secret(self, vault: Vault, field: SecretField) -> SecretValue | None:
        """В локальный файл идут только поля, которые вписал сам пользователь."""
        if vault.origin_of(field) is not VaultOrigin.OWN:
            return None
        return vault.get(field)

    def _read_supplied(self) -> Vault:
        """Поставочный сейф: ключ приходит извне, записи «key» в файле нет и быть не должно."""
        file: VaultFile | None = self._read_file(self.supplied_path)
        if file is None:
            return Vault.empty()
        key: bytes | None = self.program_key.material
        if key is None:
            LOGGER.info("vault_unreadable source=%s reason=no_program_key", VaultSource.SUPPLIED.value)
            return Vault.empty()
        decrypted: Vault | None = self._decrypt(VaultSource.SUPPLIED, file, key, VaultOrigin.SUPPLIED)
        return Vault.empty() if decrypted is None else decrypted

    def _read_local(self) -> VaultLoad:
        """Локальный сейф: ключ лежит в самом файле, завёрнутый DPAPI (§14, решение 9).

        Состояние решается здесь, где оно известно, а не догадкой по пустоте сейфа снаружи.
        """
        file: VaultFile | None = self._read_file(self.local_path)
        if file is None:
            return VaultLoad(vault=Vault.empty(), local_state=LocalVaultState.ABSENT)
        key: bytes | None = self._unwrap_local_key(file)
        if key is None:
            return VaultLoad(vault=Vault.empty(), local_state=LocalVaultState.UNREADABLE)
        decrypted: Vault | None = self._decrypt(VaultSource.LOCAL, file, key, VaultOrigin.OWN)
        if decrypted is None:
            return VaultLoad(vault=Vault.empty(), local_state=LocalVaultState.UNREADABLE)
        return VaultLoad(vault=decrypted, local_state=LocalVaultState.READ)

    def _unwrap_local_key(self, file: VaultFile) -> bytes | None:
        """Нет записи «key» или DPAPI её не развернул — файл нечитаем, работаем на поставочном (§14, решение 9)."""
        if file.wrapped_key is None:
            LOGGER.warning("vault_unreadable source=%s reason=no_wrapped_key", VaultSource.LOCAL.value)
            return None
        try:
            key: bytes = self.dpapi.unprotect(file.wrapped_key)
        except DpapiUnavailable as error:
            LOGGER.warning("vault_unreadable source=%s reason=dpapi error=%s", VaultSource.LOCAL.value, error)
            return None
        if len(key) != VAULT_KEY_BYTES:
            LOGGER.warning(
                "vault_unreadable source=%s reason=key_length got=%d", VaultSource.LOCAL.value, len(key)
            )
            return None
        return key

    def _read_file(self, path: Path) -> VaultFile | None:
        """Нет файла — нет его полей; файл есть, но не открывается или не текст, и чужой формат —
        VaultFormatError с именем файла (§7.3).

        «Не открылся» — это не «нет»: заблокированный антивирусом или синхронизацией личный файл иначе
        читался бы как отсутствующий, и работа молча шла бы на поставочных значениях (§16). В тексте
        ошибки — имя файла и короткая причина, без полного пути; исходная ошибка сохраняется через from.
        """
        try:
            text: str = path.read_text(encoding=VAULT_FILE_ENCODING)
        except FileNotFoundError:
            return None
        except OSError as error:
            reason: str = error.strerror or type(error).__name__
            raise VaultFormatError(f"{path.name}: {reason}") from error
        except UnicodeDecodeError as error:
            raise VaultFormatError(f"{path.name}: {error.reason}") from error
        try:
            return VaultFile.parse(text)
        except VaultFormatError as error:
            # §7.3: ошибка с именем файла. Путь к файлу сейфа — не секрет, секрет — его содержимое.
            raise VaultFormatError(f"{path.name}: {error}") from error

    def _decrypt(
        self,
        source: VaultSource,
        file: VaultFile,
        key: bytes,
        origin: VaultOrigin,
    ) -> Vault | None:
        """Поля файла в сейф. Хоть одно не расшифровалось — файл нечитаем целиком: None, а не пустой сейф.

        Пустой сейф — это прочитанный файл без полей; None — файл, из которого ничему нельзя верить.
        """
        crypto: VaultCrypto = VaultCrypto(key=key, salt=file.salt)
        vault: Vault = Vault.empty()
        for field in SecretField:
            blob: EncryptedField | None = file.fields.get(field.value)
            if blob is None:
                continue
            try:
                secret: SecretValue = SecretValue(field=field, value=crypto.decrypt(field, blob))
                vault = vault.with_field(field, secret, origin)
            except VaultDecryptError as error:
                LOGGER.warning("vault_unreadable source=%s reason=decrypt error=%s", source.value, error)
                return None
        unknown: tuple[str, ...] = tuple(
            name for name in file.fields if name not in {field.value for field in SecretField}
        )
        if unknown:
            LOGGER.info("vault_unknown_fields source=%s names=%s", source.value, ",".join(sorted(unknown)))
        return vault
