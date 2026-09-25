"""Пороги merge со значениями донора (restreamer `app\\llm\\merges\\merge_constants.py`, `app\\core\\constants.py`).

Один источник для нормализации качества (эта задача), проверки покрытия (3.12b) и контракта промта (3.12):
у донора значения тоже жили в одном модуле, чтобы три места не разошлись.
"""
from __future__ import annotations

from typing import Final

# Перегруженный пункт: длиннее 500 знаков — всегда; длиннее 280 знаков — если в нём не меньше трёх имён собственных.
BULLET_OVERLOAD_CHAR_LIMIT: Final[int] = 280
BULLET_OVERLOAD_NAME_LIMIT: Final[int] = 3
BULLET_ABSOLUTE_MAX_CHAR_LIMIT: Final[int] = 500

# Компактный контракт (один-два источника): пунктов от 4 до 7.
COMPACT_BULLET_MIN: Final[int] = 4
COMPACT_BULLET_MAX: Final[int] = 7
COMPACT_MAX_SOURCES: Final[int] = 2

# Акцентных маркеров (📌, 🎤, …) в списке не больше трёх; лишние становятся нейтральными 🔹.
ACCENT_MARKER_CAP: Final[int] = 3
