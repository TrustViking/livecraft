"""Правила названия эфира и первой фразы описания, которые пишет нейросеть (CLAUDE.md §14 решение 82).

Название — одна нейтральная фраза о предмете эфира: в нём нет цифр, чисел словами (`title_number_words.txt`), римских
чисел, кощунства (`title_blasphemy_words.txt`) и негатива (`title_negative_words.txt`), вопроса и восклицания, кавычек,
второй части через «|» и заглавных букв во всём названии. Первая фраза тела описания — без кощунства; негатив в
описании остаётся: оно говорит, о чём эфир.

Слова сравниваются целиком, без учёта регистра, «ё» как «е» и любой апостроф как «'»: «богослов», «богатство»,
«зв'язки» — не нарушение. Римское число — отдельное слово из заглавных I, V, X от двух знаков (II, IV, XII).
Аббревиатура в обычном названии (ОБСЄ, FBI) — не заглавные: нарушение — только когда заглавны все буквы названия, а
в нём есть слово хотя бы из двух букв (по однобуквенным словам регистра названия не видно).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final

from app.core.alphabet import LETTERS, YO_FOLD
from app.core.sequence import unique_in_order
from app.llm.merges.description import MergedDescription
from app.llm.merges.opening import DescriptionOpening
from app.observability.log_event import LogValue
from app.resources.loader import TextResource
from app.texts.paragraphs import SENTENCE_BREAK_PATTERN

NUMBER_WORDS_RESOURCE: Final[str] = "title_number_words.txt"
BLASPHEMY_WORDS_RESOURCE: Final[str] = "title_blasphemy_words.txt"
NEGATIVE_WORDS_RESOURCE: Final[str] = "title_negative_words.txt"

# Слово — буквы латиницы и кириллицы с апострофами (', ʼ, ’): «зв'язки» и «п’ять» — одно слово.
TITLE_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(f"[{LETTERS}\u02bc\u2019']+")
TITLE_DIGITS_PATTERN: Final[re.Pattern[str]] = re.compile("[0-9]+")
ROMAN_NUMERAL_PATTERN: Final[re.Pattern[str]] = re.compile("[IVX]{2,}")
APOSTROPHE_FOLD: Final[Mapping[int, str]] = MappingProxyType(str.maketrans({"\u02bc": "'", "\u2019": "'"}))
QUESTION_OR_EXCLAMATION_CHARS: Final[str] = "?!"
QUOTE_CHARS: Final[str] = "«»“”„\""
SEPARATOR_CHARS: Final[str] = "|"
CAPS_WORD_MIN_LETTERS: Final[int] = 2       # по однобуквенным словам не видно, заглавными ли написано название
FINDING_TEXT: Final[str] = "{code}({found})"
SENTENCE_SPLITS: Final[int] = 1             # первая фраза — до первого конца предложения


class TitleViolation(str, Enum):
    """Что нарушено в названии. Значение — код для лога и для подсказки повтора."""

    DIGIT = "digit"
    NUMBER_WORD = "number_word"
    ROMAN_NUMERAL = "roman_numeral"
    FORBIDDEN_WORD = "forbidden_word"
    QUESTION_OR_EXCLAMATION = "question_or_exclamation"
    QUOTE = "quote"
    SEPARATOR = "separator"
    ALL_CAPS = "all_caps"


@dataclass(frozen=True)
class TitleWord:
    """Слово глазами словарей: ключ сравнения — нижний регистр, «ё» как «е», любой апостроф как «'»."""

    text: str

    @property
    def key(self) -> str:
        return self.text.strip().lower().translate(YO_FOLD).translate(APOSTROPHE_FOLD)


@dataclass(frozen=True)
class TitleFinding:
    """Одно нарушение и что именно его дало: слова, числа, знаки (у заглавных — ничего: нарушение во всём названии)."""

    violation: TitleViolation
    found: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """`digit(2026)`, `forbidden_word(Бог)`, `all_caps` — код и найденное, без остального текста."""
        if not self.found:
            return self.violation.value
        return FINDING_TEXT.format(code=self.violation.value, found=LogValue.LIST_SEPARATOR.join(self.found))


@dataclass(frozen=True)
class TitleFindings:
    """Нарушения названия или первой фразы описания; пусто — правила соблюдены."""

    findings: tuple[TitleFinding, ...] = ()

    @property
    def is_found(self) -> bool:
        return bool(self.findings)

    @property
    def violations(self) -> tuple[TitleViolation, ...]:
        return tuple(finding.violation for finding in self.findings)

    @property
    def label(self) -> str:
        """Коды и найденное через запятую — подробность отказа в логе и подсказка повтора модели."""
        return LogValue.LIST_SEPARATOR.join(finding.label for finding in self.findings)


@dataclass(frozen=True)
class TitleText:
    """Название глазами правил: слова, слова из словаря, римские числа, знаки, заглавные."""

    text: str

    @property
    def words(self) -> tuple[str, ...]:
        return tuple(TITLE_WORD_PATTERN.findall(self.text))

    def words_in(self, lexicon: frozenset[str]) -> tuple[str, ...]:
        """Слова текста, чей ключ есть в словаре, — по порядку, без повторов."""
        return unique_in_order(word for word in self.words if TitleWord(word).key in lexicon)

    @property
    def roman_numerals(self) -> tuple[str, ...]:
        return unique_in_order(word for word in self.words if ROMAN_NUMERAL_PATTERN.fullmatch(word))

    @property
    def digits(self) -> tuple[str, ...]:
        return unique_in_order(TITLE_DIGITS_PATTERN.findall(self.text))

    def chars_of(self, chars: str) -> tuple[str, ...]:
        """Знаки из набора, которые есть в тексте, — по порядку, без повторов."""
        return unique_in_order(char for char in self.text if char in chars)

    @property
    def is_all_caps(self) -> bool:
        """Все буквы заглавные, и есть слово хотя бы из двух букв."""
        has_word: bool = any(len(word) >= CAPS_WORD_MIN_LETTERS for word in self.words)
        return has_word and self.text == self.text.upper()


@dataclass(frozen=True)
class TitleRules:
    """Правила названия и первой фразы описания со словарями: числа словами, кощунство, негатив (ключи `TitleWord`)."""

    number_words: frozenset[str]
    blasphemy_words: frozenset[str]
    negative_words: frozenset[str]

    @classmethod
    def load(cls) -> TitleRules:
        return cls(
            number_words=cls._lexicon(NUMBER_WORDS_RESOURCE),
            blasphemy_words=cls._lexicon(BLASPHEMY_WORDS_RESOURCE),
            negative_words=cls._lexicon(NEGATIVE_WORDS_RESOURCE),
        )

    @classmethod
    def _lexicon(cls, name: str) -> frozenset[str]:
        return frozenset(TitleWord(line).key for line in TextResource(name).lines)

    def title_violations(self, title: str) -> TitleFindings:
        """Нарушения названия в порядке перечисления `TitleViolation`, с найденными словами и знаками."""
        text: TitleText = TitleText(title)
        candidates: tuple[TitleFinding, ...] = (
            TitleFinding(TitleViolation.DIGIT, text.digits),
            TitleFinding(TitleViolation.NUMBER_WORD, text.words_in(self.number_words)),
            TitleFinding(TitleViolation.ROMAN_NUMERAL, text.roman_numerals),
            TitleFinding(TitleViolation.FORBIDDEN_WORD, text.words_in(self.blasphemy_words | self.negative_words)),
            TitleFinding(TitleViolation.QUESTION_OR_EXCLAMATION, text.chars_of(QUESTION_OR_EXCLAMATION_CHARS)),
            TitleFinding(TitleViolation.QUOTE, text.chars_of(QUOTE_CHARS)),
            TitleFinding(TitleViolation.SEPARATOR, text.chars_of(SEPARATOR_CHARS)),
        )
        findings: list[TitleFinding] = [finding for finding in candidates if finding.found]
        if text.is_all_caps:
            findings.append(TitleFinding(TitleViolation.ALL_CAPS))
        return TitleFindings(tuple(findings))

    def opening_violations(self, description: MergedDescription) -> TitleFindings:
        """Слова кощунства в первой фразе первого абзаца описания; негатив там не нарушение."""
        paragraph: str = DescriptionOpening(description).first_paragraph.strip()
        sentence: str = SENTENCE_BREAK_PATTERN.split(paragraph, maxsplit=SENTENCE_SPLITS)[0]
        words: tuple[str, ...] = TitleText(sentence).words_in(self.blasphemy_words)
        return TitleFindings((TitleFinding(TitleViolation.FORBIDDEN_WORD, words),) if words else ())
