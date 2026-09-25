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

# Официальные ссылки источников (`merge_links.py::_extract_official_links_from_sources`): оценка ссылки — https +20,
# контекст «official», «сайт» и т. п. в строке +20, частота домена по 5 за ссылку (не больше 20), query −5, короткая
# ссылка — до +15 (минус 1 за каждые 15 знаков); после повтора по ключу остаются не больше трёх лучших.
OFFICIAL_LINK_HTTPS_SCORE: Final[int] = 20
OFFICIAL_LINK_CONTEXT_SCORE: Final[int] = 20
OFFICIAL_LINK_DOMAIN_SCORE_STEP: Final[int] = 5
OFFICIAL_LINK_DOMAIN_SCORE_CAP: Final[int] = 20
OFFICIAL_LINK_QUERY_PENALTY: Final[int] = 5
OFFICIAL_LINK_LENGTH_SCORE: Final[int] = 15
OFFICIAL_LINK_LENGTH_STEP: Final[int] = 15
OFFICIAL_LINKS_KEPT_MAX: Final[int] = 3

# Проверка покрытия (`merge_validation.py`). Соседние строки — повтор: обе не короче 60 знаков и общее начало больше
# 65 % короткой; или в обеих не меньше 8 смысловых слов и доля общих (Жаккар) не меньше 0,75.
ADJACENT_LINE_MIN_CHARS: Final[int] = 60
ADJACENT_LINE_PREFIX_RATIO: Final[float] = 0.65
ADJACENT_LINE_MIN_TOKENS: Final[int] = 8
ADJACENT_LINE_JACCARD: Final[float] = 0.75
# Два любых абзаца — повтор: оба не короче 80 знаков и общее начало больше 70 % короткого.
PARAGRAPH_PREFIX_MIN_CHARS: Final[int] = 80
PARAGRAPH_PREFIX_RATIO: Final[float] = 0.7
# Призыв в начале: окно — первые три непустые строки первых двух абзацев.
OPENING_PARAGRAPHS: Final[int] = 2
OPENING_LINES: Final[int] = 3
# Пунктов при двух и больше источниках — не меньше max(источников + 1, 5).
MIN_BULLETS_FLOOR: Final[int] = 5
MIN_BULLETS_EXTRA_OVER_SOURCES: Final[int] = 1
MIN_BULLETS_MIN_SOURCES: Final[int] = 2
# Эмодзи вне маркеров пунктов — не больше десяти.
EMOJI_MAX: Final[int] = 10
# Перегруженных пунктов не меньше двух при списке от четырёх пунктов — отказ.
OVERLOADED_BULLETS_REJECT: Final[int] = 2
OVERLOADED_BULLETS_MIN_LIST: Final[int] = 4
# Тезис есть: первый абзац не короче 60 знаков и в нём «!», «?» или «:». Список есть: от трёх пунктов.
HOOK_MIN_CHARS: Final[int] = 60
HOOK_MARKS: Final[tuple[str, ...]] = ("!", "?", ":")
AGENDA_MIN_BULLETS: Final[int] = 3
# Восстановление форматирования (`merge_formatting.py::_attempt_expanded_formatting_recovery`) — от трёх источников.
FORMATTING_RECOVERY_MIN_SOURCES: Final[int] = 3
# Попыток merge на слот: две; три — если хоть одна отвергнутая попытка отказана по повторяемой причине
# (`merge_constants.py::PRIMARY_ATTEMPTS`, `PRIMARY_ATTEMPTS_EXTENDED`).
PRIMARY_ATTEMPTS: Final[int] = 2
PRIMARY_ATTEMPTS_EXTENDED: Final[int] = 3
# Merge делается, только когда непустых описаний у источников слота не меньше двух (`slot_processing.py`).
MIN_DESCRIBED_SOURCES: Final[int] = 2
# Предел абзацев тела при выравнивании принятого описания слота из нескольких источников: значение по умолчанию
# `merge_parser.py::separate_merge_body_and_tail`, с которым его зовёт `merge_executor.py::_enforce_description_structure`.
POST_ENFORCEMENT_MAX_BODY_PARAGRAPHS: Final[int] = 4
# Версия контракта стиля в строке лога `merge_style_coverage` (`merge_constants.py::STYLE_CONTRACT_VERSION`).
STYLE_CONTRACT_VERSION: Final[str] = "v4_merge_quality_hardening"
