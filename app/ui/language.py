"""Язык окна и консоли — по языку отображения Windows, один на процесс (CLAUDE.md §14 решение 24).

`UiLanguage` сам решает язык: переменная `LIVECRAFT_UI_LANGUAGE` (только тесты и отладка, по образцу
`app\\paths.py::ROOT_ENV_VAR`), иначе на Windows — основной язык LANGID из kernel32 `GetUserDefaultUILanguage`:
русский → ru, украинский → uk, любой другой → en; не Windows — en. `ctypes.windll` трогается только на Windows:
модуль импортируется где угодно. LANGID — это WORD, поэтому `restype` — 16 бит без знака.
"""
from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable, Mapping
from enum import Enum
from typing import Final

from app.core.system import WINDOWS_PLATFORM

LANGUAGE_ENV_VAR: Final[str] = "LIVECRAFT_UI_LANGUAGE"   # подмена языка — только для тестов и отладки
PRIMARY_LANGUAGE_MASK: Final[int] = 0x3FF               # основной язык — младшие 10 бит LANGID
RUSSIAN_PRIMARY_LANGUAGE: Final[int] = 0x19             # LANG_RUSSIAN
UKRAINIAN_PRIMARY_LANGUAGE: Final[int] = 0x22           # LANG_UKRAINIAN


class UiLanguage(str, Enum):
    """Язык текстов для людей; значение — код каталога `app\\ui\\messages_<код>.py`."""

    RU = "ru"
    UK = "uk"
    EN = "en"

    @classmethod
    def of_langid(cls, langid: int) -> UiLanguage:
        """Язык по LANGID Windows: русский и украинский — свои каталоги, остальные — английский."""
        return PRIMARY_LANGUAGES.get(langid & PRIMARY_LANGUAGE_MASK, cls.EN)

    @classmethod
    def choose(cls, env: Mapping[str, str], platform: str, read_langid: Callable[[], int]) -> UiLanguage:
        """Переменная окружения с кодом каталога решает; пустая или чужая — как будто её нет."""
        chosen: str = env.get(LANGUAGE_ENV_VAR, "")
        if chosen in {language.value for language in cls}:
            return cls(chosen)
        if platform == WINDOWS_PLATFORM:
            return cls.of_langid(read_langid())
        return cls.EN

    @classmethod
    def current(cls) -> UiLanguage:
        """Язык этого процесса: окружение, платформа и язык отображения Windows."""
        return cls.choose(os.environ, sys.platform, cls._windows_langid)

    @classmethod
    def _windows_langid(cls) -> int:
        """kernel32 `GetUserDefaultUILanguage`: argtypes и restype явно, как у остальных вызовов ctypes (Win64)."""
        read = ctypes.windll.kernel32.GetUserDefaultUILanguage
        read.argtypes = []
        read.restype = ctypes.c_uint16
        return int(read())


PRIMARY_LANGUAGES: Final[dict[int, UiLanguage]] = {
    RUSSIAN_PRIMARY_LANGUAGE: UiLanguage.RU,
    UKRAINIAN_PRIMARY_LANGUAGE: UiLanguage.UK,
}
