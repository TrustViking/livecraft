"""Ключ поставочного сейфа `ProgramKey` (CLAUDE.md §7.3). Уходит вместе с поставочным сейфом на этапе «Токен доступа».

В git ключа нет. В собранной программе его даёт сгенерированный сборкой модуль (несколько частей, а не одна
строка — это не криптография, а повышение цены разбора), в dev-режиме — файл `secrets\\program.key`.
Отсутствие модуля и файла — штатный исход: поставочный сейф просто не читается.
"""
from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.core.errors import os_error_reason
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.secretsafe.crypto import VAULT_KEY_BYTES, VaultFormatError, VaultFormatReason
from app.secretsafe.field import VaultOrigin

LOGGER = get_logger(LogArea.VAULT)

# Сгенерированный сборкой модуль (build_release.bat, этап 8): несколько частей ключа, а не одна строка.
GENERATED_KEY_MODULE: Final[str] = "app.secretsafe.program_key"
GENERATED_KEY_PARTS: Final[str] = "PARTS"


class ProgramKeyEvent(str, Enum):
    """События ключа поставочного сейфа в логе."""

    MODULE_MALFORMED = "program_key_module_malformed"
    WRONG_LENGTH = "program_key_wrong_length"


@dataclass(frozen=True)
class KeyMaterial:
    """Найденные байты ключа и откуда они (модуль сборки или файл) — для строки лога, без самих байтов."""

    raw: bytes
    origin: str

    @property
    def decoded(self) -> KeyMaterial:
        """Ровно столько байт, сколько нужно ключу, — как есть; иначе байты читаются как base64."""
        if len(self.raw) == VAULT_KEY_BYTES:
            return self
        try:
            return KeyMaterial(raw=base64.b64decode(self.raw.strip(), validate=True), origin=self.origin)
        except (binascii.Error, ValueError):
            return self

    @property
    def key(self) -> bytes | None:
        """Ключ негодной длины — считается отсутствующим: причина в лог, самих байтов в логе нет (§7.4)."""
        if len(self.raw) == VAULT_KEY_BYTES:
            return self.raw
        wrong: LogEvent = LogEvent.of(ProgramKeyEvent.WRONG_LENGTH, origin=self.origin, expected=VAULT_KEY_BYTES)
        wrong.extended(got=len(self.raw)).emit(LOGGER, logging.WARNING)
        return None


@dataclass(frozen=True)
class ProgramKey:
    """Ключ поставочного сейфа. Нет его — поставочный сейф просто не читается (§7.3, абзац про ProgramKey)."""

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
            LogEvent.of(ProgramKeyEvent.MODULE_MALFORMED, module=GENERATED_KEY_MODULE).emit(LOGGER, logging.WARNING)
            return None
        return KeyMaterial(raw=b"".join(parts), origin=GENERATED_KEY_MODULE).key

    @classmethod
    def _from_dev_file(cls, path: Path) -> bytes | None:
        """Файл разработчика: 32 байта либо base64 от них — лишь бы длина совпала.

        Файла нет — ключа нет, это штатно. Файл есть, но не открывается (папка на его месте, блокировка,
        нет прав) — VaultFormatError с именем файла и короткой причиной, исходная ошибка через from: «не
        открылся» — это не «нет», иначе оператор получил бы неверную причину «не хватает полей» (§16, тот же
        приём, что в `VaultStore`). Содержимого файла и полного пути в тексте ошибки нет.
        """
        try:
            raw: bytes = path.read_bytes()
        except FileNotFoundError:
            return None      # обычная установка без своего ключа
        except OSError as error:
            reason: str = os_error_reason(error)
            raise VaultFormatError(
                VaultFormatReason.FILE_UNREADABLE, reason, file_name=path.name, source=VaultOrigin.SUPPLIED
            ) from error
        return KeyMaterial(raw=raw, origin=str(path)).decoded.key
