"""Алфавит livecraft: классы букв для шаблонов, буквы одного языка, двойники букв и свёртка «ё → е» (CLAUDE.md §11, E6).

Кроме `app\\ui\\messages_ru.py`, это единственный модуль кода с кириллицей: шаблон, которому нужны буквы, собирается
из классов отсюда, а не перечисляет буквы сам. Класс — часть `[...]` регулярного выражения; кириллица — русская и
украинская вместе (ё, і, ї, є, ґ). Основные языки описания — `CoreLanguage`: у них свои служебные строки и своя
проверка смеси алфавитов.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Final

LATIN_UPPER: Final[str] = "A-Z"
LATIN_LOWER: Final[str] = "a-z"
CYRILLIC_UPPER: Final[str] = "А-ЯЁІЇЄҐ"
CYRILLIC_LOWER: Final[str] = "а-яёіїєґ"
LATIN_LETTERS: Final[str] = LATIN_UPPER + LATIN_LOWER
CYRILLIC_LETTERS: Final[str] = "А-Яа-яЁёІіЇїЄєҐґ"
LETTERS: Final[str] = LATIN_LETTERS + CYRILLIC_LETTERS         # буквы латиницы и кириллицы
UPPER_LETTERS: Final[str] = LATIN_UPPER + CYRILLIC_UPPER       # заглавные обоих алфавитов
LOWER_LETTERS: Final[str] = LATIN_LOWER + CYRILLIC_LOWER       # строчные обоих алфавитов

LATIN_LETTER_PATTERN: Final[re.Pattern[str]] = re.compile(f"[{LATIN_LETTERS}]")
CYRILLIC_LETTER_PATTERN: Final[re.Pattern[str]] = re.compile(f"[{CYRILLIC_LETTERS}]")
# Буквы, которые есть только в одном из двух кириллических алфавитов: украинские і ї є ґ, русские ы э ъ.
UKRAINIAN_LETTER_PATTERN: Final[re.Pattern[str]] = re.compile("[іїєґ]")
RUSSIAN_LETTER_PATTERN: Final[re.Pattern[str]] = re.compile("[ыэъ]")

# «ё» сравнивается как «е»: в названиях и в шапке таблицы люди пишут её то так, то так.
YO_FOLD: Final[Mapping[int, str]] = MappingProxyType(str.maketrans({"ё": "е", "Ё": "Е"}))


class CoreLanguage(str, Enum):
    """Основной язык описания: у него свои служебные строки и проверка смеси алфавитов."""

    UK = "uk"
    EN = "en"
    RU = "ru"

    @classmethod
    def covers(cls, code: str) -> bool:
        """Код — один из основных языков."""
        return any(member.value == code for member in cls)


# Латинские буквы, у которых в обычных шрифтах есть неотличимый кириллический двойник. Остальные латинские буквы
# (b, d, f, g, …) двойника не имеют: слово с такой буквой — настоящая смесь алфавитов, её не трогают.
SAFE_HOMOGLYPHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "a": "а", "c": "с", "e": "е", "k": "к", "o": "о", "p": "р", "x": "х", "y": "у",
        "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
        "X": "Х", "Y": "У",
    }
)
# Латинская «i»: в украинском — «і», в русском — «и».
LANGUAGE_HOMOGLYPHS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        CoreLanguage.UK.value: MappingProxyType({"i": "і", "I": "І"}),
        CoreLanguage.RU.value: MappingProxyType({"i": "и", "I": "И"}),
    }
)
