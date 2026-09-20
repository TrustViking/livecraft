"""Привязка локального сейфа к Windows-аккаунту: DPAPI через `ctypes` (CLAUDE.md §7.3).

`CryptProtectData` / `CryptUnprotectData` из `crypt32.dll`. Ноль зависимостей: ни pywin32, ни keyring —
`ctypes` входит в stdlib и разрешён инвариантом 11.

Флаг `CRYPTPROTECT_LOCAL_MACHINE` **не** ставится, и это главное здесь: без него ключ привязан к
пользователю Windows, а не к машине, поэтому `secrets\\vault.local.dat`, скопированный на другую машину
или открытый другим пользователем, бесполезен. Это единственная по-настоящему, а не декоративно защищённая
часть схемы (§7.2, третий абзац).

`argtypes` и `restype` задаются явно: на 64-битной Windows без них указатели в `DATA_BLOB` обрезаются до
32 бит (тот же урок, что в `app\\runtime\\single_instance.py`). Типы берутся из самого `ctypes`, а не из
`ctypes.wintypes`: `wintypes` существует только на Windows, а этот модуль должен импортироваться где угодно,
чтобы честно ответить `is_available == False`, а не упасть на импорте. Соответствие типов — в комментариях
у подписей. Память, которую выделил сам DPAPI (`pbData` результата и строка описания), освобождается через
`LocalFree` — иначе запуск течёт.

Не Windows или `crypt32.dll` не загрузилась — `is_available` ложно, а `protect` / `unprotect` дают
`DpapiUnavailable`. Молча возвращать данные как есть запрещено: незашифрованный «локальный сейф» выглядел
бы работающим и увёз бы секреты пользователя открытым текстом.
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Any, Final

from app.observability.logging_setup import get_logger

LOGGER = get_logger("vault")

DATA_DESCRIPTION: Final[str] = "Livecraft local vault"
CRYPT32_LIBRARY: Final[str] = "crypt32.dll"
KERNEL32_LIBRARY: Final[str] = "kernel32.dll"
WINDOWS_PLATFORM: Final[str] = "win32"
NO_FLAGS: Final[int] = 0      # CRYPTPROTECT_LOCAL_MACHINE не ставится: привязка к пользователю (§7.2)
PROTECT_ENTRY_POINT: Final[str] = "CryptProtectData"
UNPROTECT_ENTRY_POINT: Final[str] = "CryptUnprotectData"

_DWORD = ctypes.c_uint32          # DWORD
_BOOL = ctypes.c_int              # BOOL
_WIDE_STRING = ctypes.c_wchar_p   # LPCWSTR / LPWSTR
_HANDLE = ctypes.c_void_p         # HLOCAL


class DpapiUnavailable(Exception):
    """DPAPI недоступен: не Windows, crypt32.dll не загрузилась или вызов отказал."""


class _DataBlob(ctypes.Structure):
    """DATA_BLOB из wincrypt.h: длина и указатель на байты."""

    _fields_ = [("cbData", _DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


@dataclass(frozen=True)
class Dpapi:
    """Защита байтов ключом Windows-аккаунта: объект сам знает, доступен ли он, и сам зовёт crypt32.

    Библиотеки грузятся один раз, в `load()`; `None` в поле — и есть ответ «недоступен». Объект без
    библиотек строится штатно и честно отказывает в работе — так ветку недоступности можно проверить
    на любой машине, не подменяя внутренности.
    """

    crypt32: Any = None
    kernel32: Any = None

    @classmethod
    def load(cls) -> Dpapi:
        """Обычный способ получить объект: грузит библиотеки, на не-Windows отдаёт недоступный."""
        if sys.platform != WINDOWS_PLATFORM:
            LOGGER.info("dpapi_unavailable platform=%s", sys.platform)
            return cls()
        try:
            # use_last_error: без него ctypes.get_last_error() не вернёт код отказа вызова
            crypt32: Any = ctypes.WinDLL(CRYPT32_LIBRARY, use_last_error=True)
            kernel32: Any = ctypes.WinDLL(KERNEL32_LIBRARY, use_last_error=True)
        except OSError as error:
            LOGGER.warning("dpapi_library_failed library=%s error=%s", CRYPT32_LIBRARY, error)
            return cls()
        loaded: Dpapi = cls(crypt32=crypt32, kernel32=kernel32)
        loaded._declare_signatures()
        return loaded

    @property
    def is_available(self) -> bool:
        """Windows и библиотеки на месте. Ложно — настройщик прямо скажет, что локального сейфа не будет (§7.3)."""
        return self.crypt32 is not None and self.kernel32 is not None

    def protect(self, data: bytes) -> bytes:
        """Байты → блоб, который расшифрует только этот пользователь Windows."""
        return self._call(PROTECT_ENTRY_POINT, data)

    def unprotect(self, data: bytes) -> bytes:
        """Блоб → байты; блоб другого пользователя или другой машины не расшифруется."""
        return self._call(UNPROTECT_ENTRY_POINT, data)

    def _call(self, entry_point_name: str, data: bytes) -> bytes:
        """Один путь на защиту и снятие защиты: разница только в точке входа и в аргументе описания."""
        if not self.is_available:
            raise DpapiUnavailable(
                f"DPAPI is not available here: {CRYPT32_LIBRARY} did not load (platform={sys.platform})"
            )
        entry_point: Any = getattr(self.crypt32, entry_point_name)
        # Буфер держится этой переменной всё время вызова: без ссылки его собрал бы сборщик мусора,
        # и DPAPI прочитал бы освобождённую память.
        buffer: Any = ctypes.create_string_buffer(data, len(data))
        source: _DataBlob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        result: _DataBlob = _DataBlob()
        description: Any = _WIDE_STRING()
        # Описание: при защите его задаём мы, при снятии его возвращает DPAPI — в той же позиции аргумента.
        described: Any = (
            DATA_DESCRIPTION if entry_point_name == PROTECT_ENTRY_POINT else ctypes.byref(description)
        )
        succeeded: int = entry_point(
            ctypes.byref(source), described, None, None, None, NO_FLAGS, ctypes.byref(result)
        )
        if not succeeded:
            raise DpapiUnavailable(
                f"{entry_point_name} failed with Windows error {ctypes.get_last_error()}"
            )
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            self._release(result.pbData)
            self._release(description)

    def _release(self, pointer: Any) -> None:
        """Память, выделенную DPAPI, освобождает LocalFree; пустого указателя освобождать нечего."""
        if pointer:
            self.kernel32.LocalFree(pointer)

    def _declare_signatures(self) -> None:
        """argtypes и restype явно: на Win64 иначе указатели DATA_BLOB обрезаются до 32 бит."""
        blob_pointer: Any = ctypes.POINTER(_DataBlob)
        self.crypt32.CryptProtectData.argtypes = [
            blob_pointer,                     # pDataIn
            _WIDE_STRING,                     # szDataDescr
            blob_pointer,                     # pOptionalEntropy
            ctypes.c_void_p,                  # pvReserved
            ctypes.c_void_p,                  # pPromptStruct
            _DWORD,                           # dwFlags
            blob_pointer,                     # pDataOut
        ]
        self.crypt32.CryptProtectData.restype = _BOOL
        self.crypt32.CryptUnprotectData.argtypes = [
            blob_pointer,                     # pDataIn
            ctypes.POINTER(_WIDE_STRING),     # ppszDataDescr — строку выделяет сам DPAPI
            blob_pointer,                     # pOptionalEntropy
            ctypes.c_void_p,                  # pvReserved
            ctypes.c_void_p,                  # pPromptStruct
            _DWORD,                           # dwFlags
            blob_pointer,                     # pDataOut
        ]
        self.crypt32.CryptUnprotectData.restype = _BOOL
        self.kernel32.LocalFree.argtypes = [_HANDLE]
        self.kernel32.LocalFree.restype = _HANDLE
