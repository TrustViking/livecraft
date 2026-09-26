"""Общее для ошибок livecraft (CLAUDE.md §11, контракт ошибок).

Исключение, которое может дойти до человека, несёт три поля: `reason` — член перечисления причин, `human` —
русский текст из `app\\ui\\messages_ru.py` и `log_line` — строку для лога; `str(error) == error.human`.
Английская подробность пишется только в лог; текст для разработчика — константа класса ошибки. Общего базового
класса и Protocol нет: одинаковый вид ошибок держат тесты.
"""
from __future__ import annotations

from typing import Final

DETAIL_MAX_CHARS: Final[int] = 200     # подробность чужой ошибки в строке лога — не длиннее стольких символов


def os_error_reason(error: OSError) -> str:
    """Причина сбоя файловой системы для лога: текст ОС, а если его нет — имя исключения."""
    return error.strerror or type(error).__name__
