"""Чистые разборы введённого текста для настройщика (CLAUDE.md §5, §8.2).

Здесь только преобразования строки в строку или в «да/нет» — без знания о сейфе, полях и секретах (§0:
свободная функция допустима лишь как чистое преобразование). Какое правило к какому полю применить и что
сказать человеку, решает объект поля (`app\\setup\\fields\\secret_input.py::SecretInput`), а не этот модуль.
"""
from __future__ import annotations

import re
from typing import Final

SPREADSHEET_PATH_MARKER: Final[str] = "/spreadsheets/d/"
SPREADSHEET_ID_TERMINATORS: Final[str] = "/?#"
# Нотация A1: необязательное имя листа с «!» (в одинарных кавычках — любое, кавычка внутри удваивается;
# без кавычек — без «'» и «!»), затем «колонки[строка]:колонки[строка]», колонки — от 1 до 3 латинских букв.
A1_RANGE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:(?:'(?:[^']|'')+'|[^'!]+)!)?[A-Za-z]{1,3}[0-9]*:[A-Za-z]{1,3}[0-9]*"
)


def extract_spreadsheet_id(text: str) -> str:
    """id таблицы из ссылки (отрезок после «/spreadsheets/d/» до «/», «?» или «#»); не ссылка — весь текст."""
    marker_at: int = text.find(SPREADSHEET_PATH_MARKER)
    if marker_at < 0:
        return text
    tail: str = text[marker_at + len(SPREADSHEET_PATH_MARKER):]
    for position, char in enumerate(tail):
        if char in SPREADSHEET_ID_TERMINATORS:
            return tail[:position]
    return tail


def is_a1_range(text: str) -> bool:
    """Диапазон в нотации A1 с обеими границами: «A:F», «A1:F200», «Лист!A:F», «'Мой лист'!A2:F»."""
    return A1_RANGE_PATTERN.fullmatch(text) is not None
