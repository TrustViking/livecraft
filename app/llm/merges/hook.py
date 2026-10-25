"""Негодный первый абзац описания: самореклама канала, призыв, редакторская преамбула вместо факта.

Абзац негоден, если в нём есть хотя бы один признак — подстрока ресурса `merge_bad_hook_patterns.txt` (стартовые
данные, CLAUDE.md §14 решение 23). Им пользуются начало описания (`opening.py`) и проверка перед публикацией
(`merge_rules.py::PublishGate`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.resources.loader import TextResource
from app.texts.paragraphs import collapse_spaces
from app.texts.phrase_lexicon import PhraseLexicon

BAD_HOOK_PATTERNS_RESOURCE: Final[str] = "merge_bad_hook_patterns.txt"


@dataclass(frozen=True)
class BadHookLexicon:
    """Признаки негодного первого абзаца: подстроки в нижнем регистре."""

    patterns: PhraseLexicon

    @classmethod
    def load(cls) -> BadHookLexicon:
        return cls(patterns=PhraseLexicon(TextResource(BAD_HOOK_PATTERNS_RESOURCE).lines))

    def matches(self, paragraph: str) -> bool:
        """Абзац (пробелы схлопнуты, нижний регистр) содержит хотя бы один признак."""
        normalized_text: str = collapse_spaces(paragraph).lower()
        return bool(normalized_text) and self.patterns.found_in(normalized_text)
