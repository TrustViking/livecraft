"""Чистые разборы введённого текста для настройщика (CLAUDE.md §5, §8.2).

Здесь только преобразования строки в строку или в «да/нет» — без знания о сейфе, полях и секретах (§0:
свободная функция допустима лишь как чистое преобразование). Какое правило к какому полю применить и что
сказать человеку, решает объект поля (`app\\setup\\fields\\secret_input.py::SecretInput`), а не этот модуль.
"""
from __future__ import annotations

from typing import Final

SPREADSHEET_PATH_MARKER: Final[str] = "/spreadsheets/d/"
SPREADSHEET_ID_TERMINATORS: Final[str] = "/?#"


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
