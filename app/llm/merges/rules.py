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

# Контракт промта (`merge_prompt.py::_select_merge_contract_mode`): расширенный — от трёх источников, пунктов 4-6 при
# трёх, 5-7 при четырёх-пяти, 6-9 при шести и больше; тело — не больше 7 абзацев. «Одно событие» — от двух источников,
# когда не меньше пяти имён встречаются хотя бы в двух источниках; тело — не больше 5 абзацев. Компактный — не больше 4.
EXPANDED_MIN_SOURCES: Final[int] = 3
EXPANDED_BULLET_RANGES: Final[tuple[tuple[int, int, int], ...]] = ((3, 4, 6), (5, 5, 7))   # (до стольких источников, min, max)
EXPANDED_BULLET_RANGE_LARGE: Final[tuple[int, int]] = (6, 9)
EXPANDED_MAX_BODY_PARAGRAPHS: Final[int] = 7
NARRATIVE_MIN_SOURCES: Final[int] = 2
NARRATIVE_MIN_SHARED_ENTITIES: Final[int] = 5
NARRATIVE_MAX_BODY_PARAGRAPHS: Final[int] = 5
COMPACT_MAX_BODY_PARAGRAPHS: Final[int] = 4

# Строка-якорь спикеров: от четырёх источников, не больше восьми имён, самые длинные первыми.
SPEAKER_ANCHOR_MIN_SOURCES: Final[int] = 4
SPEAKER_NAMES_MAX: Final[int] = 8
