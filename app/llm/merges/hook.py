"""Негодный первый абзац описания: самореклама канала, призыв, редакторская преамбула вместо факта.

Правило — `merge_validation_helpers.py::looks_like_bad_hook_paragraph` restreamer; список признаков донора
(`_BAD_HOOK_PATTERNS`, в коде) вынесен ресурсом `merge_bad_hook_patterns.txt` без правки строк
(CLAUDE.md §14 решение 23). Пользуется им проверка покрытия (задача 3.12b).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.resources.loader import TextResource

BAD_HOOK_PATTERNS_RESOURCE: Final[str] = "merge_bad_hook_patterns.txt"
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")


@dataclass(frozen=True)
class BadHookLexicon:
    """Признаки негодного первого абзаца: подстроки в нижнем регистре."""

    patterns: tuple[str, ...]

    @classmethod
    def load(cls) -> BadHookLexicon:
        return cls(patterns=TextResource(BAD_HOOK_PATTERNS_RESOURCE).lines)

    def matches(self, paragraph: str) -> bool:
        """Абзац (пробелы схлопнуты, нижний регистр) содержит хотя бы один признак."""
        normalized_text: str = WHITESPACE_RUN_PATTERN.sub(" ", str(paragraph or "").strip()).lower()
        if not normalized_text:
            return False
        return any(pattern in normalized_text for pattern in self.patterns)
