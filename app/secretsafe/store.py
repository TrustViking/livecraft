"""Сейф на диске: два файла, два разных ключа, приоритет личного над поставочным (CLAUDE.md §7.3).

| Файл | Ключ | Кто пишет |
|---|---|---|
| `secrets\\vault.local.dat` | 32 случайных байта, завёрнутые DPAPI и лежащие в самом файле записью «key» | настройщик |
| `secrets\\vault.dat` | `ProgramKey` из сборки | сборка Артура |

Поле берётся из личного файла, если оно там есть; иначе — из поставочного (`Vault.overlaid_by`). Поставочный
файл этот объект **никогда не открывает на запись**: `save_local` пишет только личный, и только поля, которые
пользователь вписал сам (`VaultOrigin.OWN`). Сброс поля к поставке — удаление его из личного слоя.

Ключ личного файла разворачивает только та учётная запись Windows, под которой он был создан (§14,
решение 9): копия файла на другой машине или под другим пользователем бесполезна.

Один нечитаемый файл не валит запуск: нет ключа, DPAPI не развернул, блоб подменён — полей этого файла
просто нет, причина уходит в лог, работа продолжается на втором файле. Наружу идёт только `VaultFormatError`
(файл чужого формата, повреждённый или не открывающийся — код 2; «файла нет» — только когда его
действительно нет) и `DpapiUnavailable` из `save_local`. Итог чтения для запуска — `VaultRead`: сейф или ошибка
файла одним значением.

Настройщик читает сейф через `load_for_setup`: повреждённый личный файл там — не тупик, а пустой личный
слой с состоянием BROKEN; первое сохранение заменит файл. Повреждённый поставочный файл — `VaultFormatError`.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.core.errors import os_error_reason
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths, write_text_atomically
from app.secretsafe.crypto import (
    VAULT_KEY_BYTES,
    EncryptedField,
    VaultCrypto,
    VaultDecryptError,
    VaultFile,
    VaultFormatError,
    VaultFormatReason,
)
from app.secretsafe.dpapi import Dpapi, DpapiUnavailable
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.supplied_key import ProgramKey
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.VAULT)


class StoreEvent(str, Enum):
    """События сейфа на диске в логе."""

    LOADED = "vault_loaded"
    LOCAL_SAVED = "vault_local_saved"
    LOCAL_BROKEN = "vault_local_broken"
    UNREADABLE = "vault_unreadable"
    UNKNOWN_FIELDS = "vault_unknown_fields"
    VAULT_ERROR = "vault_error"
    LOCAL_UNREADABLE = "vault_local_unreadable"


class UnreadableReason(str, Enum):
    """Почему целый файл сейфа не дал значений."""

    NO_PROGRAM_KEY = "no_program_key"     # поставочный: ключа сборки нет
    NO_WRAPPED_KEY = "no_wrapped_key"     # личный: нет записи «key»
    DPAPI = "dpapi"                       # личный: DPAPI не развернул ключ
    KEY_LENGTH = "key_length"             # личный: развёрнутый ключ не той длины
    DECRYPT = "decrypt"                   # блоб поля не расшифровался


class LocalVaultState(str, Enum):
    """Что с личным сейфом: его нет, он прочитан, он целый, но не наш, или он повреждён.

    Пустой, но прочитанный файл — READ: пользователь сбросил всё к поставке, это не поломка. UNREADABLE —
    файл целый, а значений из него нет (DPAPI не развернул ключ, блоб не расшифровался): оператор должен
    узнать об этом громко. BROKEN — файл есть, но повреждён или не открывается; бывает только у
    `VaultStore.load_for_setup`: запуск на таком файле останавливается `VaultFormatError`.
    """

    ABSENT = "absent"
    READ = "read"
    UNREADABLE = "unreadable"
    BROKEN = "broken"


@dataclass(frozen=True)
class VaultLoad:
    """Результат чтения сейфа: сам сейф и состояние личного файла — полем, а не только строкой в логе (§0).

    `vault` — то, с чем работает запуск: личный слой поверх поставочного. `supplied` — поставочный слой как он
    прочитан, без наложения: без него не узнать, что окажется под личным значением после сброса своего (§8.2).
    """

    vault: Vault
    local_state: LocalVaultState
    supplied: Vault

    @classmethod
    def from_layers(cls, supplied: Vault, own: Vault, local_state: LocalVaultState) -> VaultLoad:
        """Личный слой поверх поставочного: поле личного перекрывает поле поставочного (§7.3)."""
        return cls(vault=supplied.overlaid_by(own), local_state=local_state, supplied=supplied)

    @property
    def own(self) -> Vault:
        """Личный слой: только поля с происхождением «своё»."""
        return self.vault.only(VaultOrigin.OWN)

    @property
    def is_local_unreadable(self) -> bool:
        """Личный файл есть, но значения из него не прочитаны: работа идёт на поставочных."""
        return self.local_state is LocalVaultState.UNREADABLE

    @property
    def warnings(self) -> tuple[str, ...]:
        """Что сказать громко: личный сейф есть, но не прочитан (§16) — молча работать на поставке нельзя."""
        if not self.is_local_unreadable:
            return ()
        fields: str = msg.LIST_JOINER.join(field.human_label for field in SecretField.current())
        return (msg.VAULT_LOCAL_UNREADABLE.format(fields=fields),)


@dataclass(frozen=True)
class LocalRead:
    """Итог чтения личного файла: его поля и состояние."""

    vault: Vault
    state: LocalVaultState


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

    @property
    def can_save_local(self) -> bool:
        """Можно ли записать личный сейф: без DPAPI своих значений на этой машине не будет (§7.3, Dpapi)."""
        return self.dpapi.is_available

    def load(self) -> VaultLoad:
        """Оба файла в один сейф. Повреждённый любой из двух файлов — VaultFormatError наружу (код 2)."""
        return self._load(self._read_local)

    def load_for_setup(self) -> VaultLoad:
        """То же для настройщика: повреждённый личный файл — пустой личный слой и BROKEN, а не отказ."""
        return self._load(self._read_local_for_setup)

    def save_local(self, vault: Vault) -> None:
        """Записать личный сейф: только свои поля, новый ключ и новая соль на каждую запись.

        Поставочный файл не трогается. DPAPI недоступен — DpapiUnavailable наружу и файл не создаётся:
        «личный сейф» без привязки к учётной записи Windows был бы обманом (§7.2, третий абзац).
        """
        crypto: VaultCrypto = VaultCrypto.new()
        # Шифрует себя сам секрет: значение не выходит из SecretValue, сюда возвращается только шифротекст (§7.4).
        own: Vault = vault.only(VaultOrigin.OWN)
        fields: dict[str, EncryptedField] = {
            field.value: entry.secret.encrypt(crypto) for field, entry in own.entries.items()
        }
        file: VaultFile = VaultFile.new(salt=crypto.salt, fields=fields, wrapped_key=self.dpapi.protect(crypto.key))
        write_text_atomically(self.local_path, file.render(), TEXT_ENCODING)
        LogEvent.of(StoreEvent.LOCAL_SAVED, fields=len(fields)).emit(LOGGER)

    def _load(self, read_local: Callable[[], LocalRead]) -> VaultLoad:
        """Общий путь чтения: сначала поставочный слой, затем личный — тем способом, который задал вызывающий."""
        supplied: Vault = self._read_supplied()
        local: LocalRead = read_local()
        loaded: VaultLoad = VaultLoad.from_layers(supplied=supplied, own=local.vault, local_state=local.state)
        LogEvent.of(StoreEvent.LOADED, fields=loaded.vault.log_line, local=local.state).emit(LOGGER)
        return loaded

    def _read_supplied(self) -> Vault:
        """Поставочный сейф: ключ приходит извне, записи «key» в файле нет и быть не должно."""
        file: VaultFile | None = self._read_file(self.supplied_path, VaultOrigin.SUPPLIED)
        if file is None:
            return Vault.empty()
        key: bytes | None = self.program_key.material
        if key is None:
            self._unreadable(VaultOrigin.SUPPLIED, UnreadableReason.NO_PROGRAM_KEY, logging.INFO)
            return Vault.empty()
        decrypted: Vault | None = self._decrypt(VaultOrigin.SUPPLIED, file, key)
        return Vault.empty() if decrypted is None else decrypted

    def _read_local(self) -> LocalRead:
        """Личный сейф: ключ лежит в самом файле, завёрнутый DPAPI (§14, решение 9)."""
        file: VaultFile | None = self._read_file(self.local_path, VaultOrigin.OWN)
        if file is None:
            return LocalRead(vault=Vault.empty(), state=LocalVaultState.ABSENT)
        key: bytes | None = self._unwrap_local_key(file)
        decrypted: Vault | None = None if key is None else self._decrypt(VaultOrigin.OWN, file, key)
        if decrypted is None:
            return LocalRead(vault=Vault.empty(), state=LocalVaultState.UNREADABLE)
        return LocalRead(vault=decrypted, state=LocalVaultState.READ)

    def _read_local_for_setup(self) -> LocalRead:
        """Личный сейф для настройщика: повреждённый файл — пустой слой BROKEN; причина — в лог, не наружу."""
        try:
            return self._read_local()
        except VaultFormatError as error:
            error.event(StoreEvent.LOCAL_BROKEN).emit(LOGGER, logging.WARNING)
            return LocalRead(vault=Vault.empty(), state=LocalVaultState.BROKEN)

    def _unwrap_local_key(self, file: VaultFile) -> bytes | None:
        """Нет записи «key» или DPAPI её не развернул — файл нечитаем, работаем на поставочном (§14, решение 9)."""
        if file.wrapped_key is None:
            self._unreadable(VaultOrigin.OWN, UnreadableReason.NO_WRAPPED_KEY)
            return None
        try:
            key: bytes = self.dpapi.unprotect(file.wrapped_key)
        except DpapiUnavailable as error:
            self._unreadable(VaultOrigin.OWN, UnreadableReason.DPAPI, detail=error.detail)
            return None
        if len(key) != VAULT_KEY_BYTES:
            self._unreadable(VaultOrigin.OWN, UnreadableReason.KEY_LENGTH, got=len(key))
            return None
        return key

    def _unreadable(
        self, source: VaultOrigin, reason: UnreadableReason, level: int = logging.WARNING, **fields: object
    ) -> None:
        """Строка лога «файл целый, а значений нет»: чей файл, почему и подробности без значений (§7.4)."""
        LogEvent.of(StoreEvent.UNREADABLE, source=source, reason=reason).extended(**fields).emit(LOGGER, level)

    def _read_file(self, path: Path, source: VaultOrigin) -> VaultFile | None:
        """Нет файла — нет его полей; файл есть, но не открывается или не текст, и чужой формат —
        VaultFormatError с именем файла и тем, чей он (§7.3).

        «Не открылся» — это не «нет»: заблокированный антивирусом или синхронизацией личный файл иначе
        читался бы как отсутствующий, и работа молча шла бы на поставочных значениях (§16).
        """
        try:
            text: str = path.read_text(encoding=TEXT_ENCODING)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise VaultFormatError(
                VaultFormatReason.FILE_UNREADABLE, os_error_reason(error), file_name=path.name, source=source
            ) from error
        except UnicodeDecodeError as error:
            raise VaultFormatError(
                VaultFormatReason.NOT_TEXT, error.reason, file_name=path.name, source=source
            ) from error
        try:
            return VaultFile.parse(text)
        except VaultFormatError as error:
            # §7.3: ошибка с именем файла. Путь к файлу сейфа — не секрет, секрет — его содержимое.
            raise error.located(path.name, source) from error

    def _decrypt(self, source: VaultOrigin, file: VaultFile, key: bytes) -> Vault | None:
        """Поля файла в сейф с происхождением файла. Хоть одно не расшифровалось — файл нечитаем целиком: None.

        Пустой сейф — это прочитанный файл без полей; None — файл, из которого ничему нельзя верить.
        """
        crypto: VaultCrypto = VaultCrypto(key=key, salt=file.salt)
        vault: Vault = Vault.empty()
        for field in SecretField:
            blob: EncryptedField | None = file.fields.get(field.value)
            if blob is None:
                continue
            try:
                vault = vault.with_field(field, SecretValue(field=field, value=crypto.decrypt(field, blob)), source)
            except VaultDecryptError as error:
                self._unreadable(source, UnreadableReason.DECRYPT, field=error.field.log_label, cause=error.reason)
                return None
        unknown: tuple[str, ...] = tuple(sorted(name for name in file.fields if name not in SecretField.names()))
        if unknown:
            LogEvent.of(StoreEvent.UNKNOWN_FIELDS, source=source, names=unknown).emit(LOGGER)
        return vault


@dataclass(frozen=True)
class VaultRead:
    """Сейф для запуска одним значением: прочитанный сейф или ошибка файла сейфа (код 2), но не оба сразу."""

    load: VaultLoad | None
    error: VaultFormatError | None

    @classmethod
    def of(cls, store: VaultStore) -> VaultRead:
        """Прочитать оба файла; файл чужого формата или не открывающийся — ошибка вместо сейфа."""
        try:
            return cls(load=store.load(), error=None)
        except VaultFormatError as error:
            return cls(load=None, error=error)

    @property
    def vault(self) -> Vault | None:
        """Сейф, если он прочитан."""
        return None if self.load is None else self.load.vault

    @property
    def is_local_unreadable(self) -> bool:
        """Личный файл есть, но значения из него не прочитаны: сказать об этом громко (§16)."""
        return self.load is not None and self.load.is_local_unreadable

    @property
    def is_fixable_in_setup(self) -> bool:
        """Окно настройщика поможет: сейф прочитан или повреждён личный файл, который окно заменит сохранением."""
        return self.error is None or self.error.is_replaceable

    def log(self, logger: logging.Logger) -> None:
        """Ошибка файла сейфа и нечитаемый личный файл — в лог; значений сейфа нет нигде."""
        if self.error is not None:
            self.error.event(StoreEvent.VAULT_ERROR).emit(logger, logging.ERROR)
        if self.is_local_unreadable:
            LogEvent.of(StoreEvent.LOCAL_UNREADABLE, working_on=VaultOrigin.SUPPLIED).emit(logger, logging.WARNING)
