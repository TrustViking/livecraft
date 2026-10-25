"""Похожесть двух текстов: доля общего начала и доля общих слов — одна формула на всю программу (CLAUDE.md §11).

`WordRule` — что считать словом: смысловое слово (не короче трёх букв или цифр латиницы и кириллицы) или всё,
что стоит между пробелами. `TextPair` сравнивает два текста по выбранному правилу слова: доля общих слов —
Жаккар (общие слова к словам обоих текстов; слов нет ни в одном — сравнивать нечего, None), доля общего начала —
длина общего начала к длине более короткого текста.

`StopWords` — частые слова (английские, русские, украинские), которые ничего не говорят о теме текста; тема текста —
его смысловые слова без них (`StopWords.topic_words`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.alphabet import LETTERS
from app.resources.loader import TextResource

SEMANTIC_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(f"[0-9{LETTERS}]{{3,}}")
STOP_WORDS_RESOURCE: Final[str] = "lexicon_semantic_stopwords.txt"


class WordRule(str, Enum):
    """Что считать словом при сравнении текстов."""

    SEMANTIC = "semantic"    # смысловое слово: три и больше букв или цифр подряд, знаки — границы
    SPACED = "spaced"        # всё между пробелами, со знаками

    def words(self, text: str) -> list[str]:
        """Слова текста в нижнем регистре по порядку."""
        if self is WordRule.SEMANTIC:
            return [token.lower() for token in SEMANTIC_TOKEN_PATTERN.findall(text)]
        return text.lower().split()


@dataclass(frozen=True)
class TextPair:
    """Два текста, которые сравнивают, и правило слова для доли общих слов."""

    first: str
    second: str
    rule: WordRule = WordRule.SEMANTIC

    @property
    def jaccard(self) -> float | None:
        """Доля общих слов среди слов обоих текстов; слов нет ни в одном — None."""
        first: set[str] = set(self.rule.words(self.first))
        second: set[str] = set(self.rule.words(self.second))
        union: set[str] = first | second
        return len(first & second) / len(union) if union else None

    @property
    def prefix_ratio(self) -> float:
        """Длина общего начала к длине более короткого текста; пустой текст — 0."""
        shorter: int = min(len(self.first), len(self.second))
        if shorter <= 0:
            return 0.0
        common: int = 0
        for first_char, second_char in zip(self.first, self.second):
            if first_char != second_char:
                break
            common += 1
        return common / shorter


@dataclass(frozen=True)
class StopWords:
    """Частые слова в нижнем регистре: по ним нельзя судить, о чём текст."""

    words: frozenset[str]

    @classmethod
    def load(cls) -> StopWords:
        return cls(frozenset(TextResource(STOP_WORDS_RESOURCE).lines))

    def topic_words(self, text: str) -> frozenset[str]:
        """О чём текст: его смысловые слова в нижнем регистре без частых."""
        return frozenset(WordRule.SEMANTIC.words(text)) - self.words
