"""Сейф на диске: два файла одного формата и одного устройства, приоритет своего над значением из токена (CLAUDE.md
§7.3, §14 решения 16, 44).

| Файл | Что в нём | Кто пишет |
|---|---|---|
| `secrets\\vault.local.dat` | значения, которые человек ввёл сам (`VaultOrigin.OWN`) | настройщик |
| `secrets\\vault.token.dat` | значения из загруженного токена доступа (`VaultOrigin.TOKEN`) | загрузка токена |

Ключ каждого файла — 32 случайных байта, завёрнутые DPAPI и лежащие в самом файле записью «key» (§14, решение 9): его
разворачивает только та учётная запись Windows, под которой он был создан, — копия файла на другой машине или под другим
пользователем бесполезна. Код у обоих файлов один; различаются путь и происхождение полей.

Поле берётся из личного файла, если оно там есть; иначе — из файла токена (`Vault.overlaid_by`). `save_local` пишет
только свои поля, `save_token` — только поля из токена, и каждая запись заменяет свой файл целиком. Сброс своего поля —
удаление его из личного слоя: под ним снова видно значение из токена.

Один нечитаемый файл не валит запуск: нет ключа, DPAPI не развернул, блоб подменён — полей этого файла просто нет,
причина уходит в лог, работа продолжается на втором файле. Наружу идёт только `VaultFormatError` (файл чужого формата,
повреждённый или не открывающийся — код 2; «файла нет» — только когда его действительно нет) и `DpapiUnavailable` из
записи. Итог чтения для запуска — `VaultRead`: сейф или ошибка файла одним значением.

Настройщик читает сейф через `load_for_setup`: повреждённый файл там — не тупик, а пустой слой с состоянием BROKEN;
своё сохранение заменит личный файл, загрузка токена — файл токена.
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
from app.paths import FileName, LivecraftPaths, write_text_atomically
from app.secretsafe.crypto import (
    VAULT_KEY_BYTES,
    VaultCrypto,
    VaultDecryptError,
    VaultFile,
    VaultFormatError,
    VaultFormatReason,
)
from app.secretsafe.dpapi import Dpapi, DpapiUnavailable
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.sealed import SealedVault
from app.secretsafe.vault import Vault
from app.ui.messages import msg

LOGGER = get_logger(LogArea.VAULT)


class StoreEvent(str, Enum):
    """События сейфа на диске в логе."""

    LOADED = "vault_loaded"
    SAVED = "vault_saved"
    LAYER_BROKEN = "vault_layer_broken"
    UNREADABLE = "vault_unreadable"
    UNKNOWN_FIELDS = "vault_unknown_fields"
    VAULT_ERROR = "vault_error"
    LOCAL_UNREADABLE = "vault_local_unreadable"


class UnreadableReason(str, Enum):
    """Почему целый файл сейфа не дал значений."""

    NO_WRAPPED_KEY = "no_wrapped_key"     # нет записи «key»
    DPAPI = "dpapi"                       # DPAPI не развернул ключ
    KEY_LENGTH = "key_length"             # развёрнутый ключ не той длины
    DECRYPT = "decrypt"                   # блоб поля не расшифровался


class VaultLayerState(str, Enum):
    """Что с файлом слоя сейфа: его нет, он прочитан, он целый, но не наш, или он повреждён.

    Пустой, но прочитанный файл — READ: пользователь убрал все свои значения, это не поломка. UNREADABLE — файл целый,
    а значений из него нет (DPAPI не развернул ключ, блоб не расшифровался): оператор должен узнать об этом громко.
    BROKEN — файл есть, но повреждён или не открывается; бывает только у `VaultStore.load_for_setup`: запуск на таком
    файле останавливается `VaultFormatError`.
    """

    ABSENT = "absent"
    READ = "read"
    UNREADABLE = "unreadable"
    BROKEN = "broken"


@dataclass(frozen=True)
class LayerRead:
    """Итог чтения файла одного слоя: его поля и состояние."""

    vault: Vault
    state: VaultLayerState


@dataclass(frozen=True)
class VaultLoad:
    """Результат чтения сейфа: сам сейф и состояния обоих файлов — полями, а не только строкой в логе (§0).

    `vault` — то, с чем работает запуск: личный слой поверх слоя токена. `token` — слой токена как он прочитан, без
    наложения: без него не узнать, что окажется под своим значением после его сброса (§8.2).
    """

    vault: Vault
    local_state: VaultLayerState
    token: Vault
    token_state: VaultLayerState

    @classmethod
    def from_layers(cls, token: LayerRead, own: LayerRead) -> VaultLoad:
        """Личный слой поверх слоя токена: своё поле перекрывает поле из токена (§7.3)."""
        return cls(
            vault=token.vault.overlaid_by(own.vault), local_state=own.state, token=token.vault, token_state=token.state
        )

    @property
    def own(self) -> Vault:
        """Личный слой: только поля с происхождением «своё»."""
        return self.vault.only(VaultOrigin.OWN)

    @property
    def is_local_unreadable(self) -> bool:
        """Личный файл есть, но значения из него не прочитаны: работа идёт на значениях из токена, если они есть."""
        return self.local_state is VaultLayerState.UNREADABLE

    @property
    def warnings(self) -> tuple[str, ...]:
        """Что сказать громко: файл слоя есть, но не прочитан (§16) — молча работать без своих значений или без значений
        токена нельзя."""
        lines: list[str] = []
        if self.is_local_unreadable:
            fields: str = msg.LIST_JOINER.join(field.human_label for field in SecretField)
            lines.append(msg.VAULT_LOCAL_UNREADABLE.format(fields=fields))
        if self.token_state is VaultLayerState.UNREADABLE:
            lines.append(msg.VAULT_TOKEN_UNREADABLE)
        return tuple(lines)


# Как читается файл слоя: путь и происхождение его полей → поля и состояние.
LayerReader = Callable[[Path, VaultOrigin], LayerRead]


@dataclass(frozen=True)
class VaultStore:
    """Чтение и запись файлов сейфа: личного и слоя токена — одним кодом."""

    local_path: Path
    token_path: Path
    dpapi: Dpapi

    @classmethod
    def open(cls, paths: LivecraftPaths) -> VaultStore:
        """Сейф этой установки: оба файла из paths, DPAPI машины."""
        return cls(
            local_path=paths.file(FileName.VAULT_LOCAL), token_path=paths.file(FileName.VAULT_TOKEN), dpapi=Dpapi.load()
        )

    @property
    def can_save(self) -> bool:
        """Можно ли записать файл сейфа: без DPAPI ни своих значений, ни значений из токена на этой машине не будет
        (§7.3, Dpapi)."""
        return self.dpapi.is_available

    def load(self) -> VaultLoad:
        """Оба файла в один сейф. Повреждённый любой из двух файлов — VaultFormatError наружу (код 2)."""
        return self._load(self._read_layer)

    def load_for_setup(self) -> VaultLoad:
        """То же для настройщика: повреждённый файл — пустой слой и BROKEN, а не отказ."""
        return self._load(self._read_layer_for_setup)

    def save_local(self, vault: Vault) -> None:
        """Записать личный файл: только свои поля, новый ключ и новая соль на каждую запись. Файл токена не трогается.

        DPAPI недоступен — DpapiUnavailable наружу и файл не создаётся: «личный сейф» без привязки к учётной записи
        Windows был бы обманом (§7.2, третий абзац).
        """
        self._save(self.local_path, vault.only(VaultOrigin.OWN), VaultOrigin.OWN)

    def save_token(self, vault: Vault) -> None:
        """Записать файл токена: только поля из токена — прежние значения из токена заменяются целиком. Личный файл не
        трогается. DPAPI недоступен — DpapiUnavailable наружу."""
        self._save(self.token_path, vault.only(VaultOrigin.TOKEN), VaultOrigin.TOKEN)

    def _save(self, path: Path, layer: Vault, origin: VaultOrigin) -> None:
        """Слой — своим ключом, завёрнутым DPAPI; шифрует себя сам каждый секрет (§7.4)."""
        crypto: VaultCrypto = VaultCrypto.new()
        sealed: SealedVault = SealedVault.seal(layer, crypto, self.dpapi.protect(crypto.key))
        write_text_atomically(path, sealed.file.render(), TEXT_ENCODING)
        LogEvent.of(StoreEvent.SAVED, source=origin, fields=len(layer.entries)).emit(LOGGER)

    def _load(self, read: LayerReader) -> VaultLoad:
        """Общий путь чтения: слой токена, затем личный — тем способом, который задал вызывающий."""
        token: LayerRead = read(self.token_path, VaultOrigin.TOKEN)
        own: LayerRead = read(self.local_path, VaultOrigin.OWN)
        loaded: VaultLoad = VaultLoad.from_layers(token=token, own=own)
        LogEvent.of(StoreEvent.LOADED, fields=loaded.vault.log_line, local=own.state, token=token.state).emit(LOGGER)
        return loaded

    def _read_layer(self, path: Path, origin: VaultOrigin) -> LayerRead:
        """Файл слоя: ключ лежит в самом файле, завёрнутый DPAPI (§14, решение 9)."""
        file: VaultFile | None = self._read_file(path, origin)
        if file is None:
            return LayerRead(vault=Vault.empty(), state=VaultLayerState.ABSENT)
        key: bytes | None = self._unwrap_key(file, origin)
        decrypted: Vault | None = None if key is None else self._decrypt(origin, file, key)
        if decrypted is None:
            return LayerRead(vault=Vault.empty(), state=VaultLayerState.UNREADABLE)
        return LayerRead(vault=decrypted, state=VaultLayerState.READ)

    def _read_layer_for_setup(self, path: Path, origin: VaultOrigin) -> LayerRead:
        """Файл слоя для настройщика: повреждённый файл — пустой слой BROKEN; причина — в лог, не наружу."""
        try:
            return self._read_layer(path, origin)
        except VaultFormatError as error:
            error.event(StoreEvent.LAYER_BROKEN).emit(LOGGER, logging.WARNING)
            return LayerRead(vault=Vault.empty(), state=VaultLayerState.BROKEN)

    def _unwrap_key(self, file: VaultFile, origin: VaultOrigin) -> bytes | None:
        """Нет записи «key» или DPAPI её не развернул — файл нечитаем, работаем на втором (§14, решение 9)."""
        if file.wrapped_key is None:
            self._unreadable(origin, UnreadableReason.NO_WRAPPED_KEY)
            return None
        try:
            key: bytes = self.dpapi.unprotect(file.wrapped_key)
        except DpapiUnavailable as error:
            self._unreadable(origin, UnreadableReason.DPAPI, detail=error.detail)
            return None
        if len(key) != VAULT_KEY_BYTES:
            self._unreadable(origin, UnreadableReason.KEY_LENGTH, got=len(key))
            return None
        return key

    def _unreadable(self, source: VaultOrigin, reason: UnreadableReason, **fields: object) -> None:
        """Строка лога «файл целый, а значений нет»: чей файл, почему и подробности без значений (§7.4)."""
        event: LogEvent = LogEvent.of(StoreEvent.UNREADABLE, source=source, reason=reason)
        event.extended(**fields).emit(LOGGER, logging.WARNING)

    def _read_file(self, path: Path, source: VaultOrigin) -> VaultFile | None:
        """Нет файла — нет его полей; файл есть, но не открывается или не текст, и чужой формат —
        VaultFormatError с именем файла и тем, чей он (§7.3).

        «Не открылся» — это не «нет»: заблокированный антивирусом или синхронизацией личный файл иначе
        читался бы как отсутствующий, и работа молча шла бы без своих значений (§16).
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

        Пустой сейф — это прочитанный файл без полей; None — файл, из которого ничему нельзя верить. Поля прежних
        версий (их имён программа не знает) не мешают чтению: строка лога, и при следующей записи их не будет.
        """
        sealed: SealedVault = SealedVault(file)
        try:
            vault: Vault = sealed.open(key, source)
        except VaultDecryptError as error:
            self._unreadable(source, UnreadableReason.DECRYPT, field=error.field.log_label, cause=error.reason)
            return None
        if sealed.unknown_fields:
            LogEvent.of(StoreEvent.UNKNOWN_FIELDS, source=source, names=sealed.unknown_fields).emit(LOGGER)
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

    def log(self, logger: logging.Logger) -> None:
        """Ошибка файла сейфа и нечитаемый личный файл — в лог; значений сейфа нет нигде."""
        if self.error is not None:
            self.error.event(StoreEvent.VAULT_ERROR).emit(logger, logging.ERROR)
        if self.is_local_unreadable:
            LogEvent.of(StoreEvent.LOCAL_UNREADABLE, working_on=VaultOrigin.TOKEN).emit(logger, logging.WARNING)
