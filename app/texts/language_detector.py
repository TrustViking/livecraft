"""Код языка из сырого значения и язык текста (CLAUDE.md §3 шаг 2.3, §14 решение 12).

- `normalize_language` — код языка ISO 639-1 из того, как его пишут yt-dlp и langdetect (`ua` → `uk`, `en-US` → `en`):
  сначала известное написание, затем вид «xx» или «xx-yy», затем известное начало; не похоже на язык — None.
  Написания и начала — данные (`language_aliases.txt`, `language_prefixes.txt`), а не код.
- `TextLanguageDetector` — langdetect по тексту, очищенному от ссылок, хештегов и служебного хвоста: ими язык
  источника и служебных строк описания решается одинаково.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from functools import cache
from typing import Final

from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

from app.resources.loader import TextResource
from app.texts.analysis_text import AnalysisTextReport
from app.texts.phrase_lexicon import ServiceHints

DETECTOR_SEED: Final[int] = 0              # langdetect без сида отвечает по-разному на один текст
MIN_DETECT_LENGTH: Final[int] = 20         # короче — langdetect гадает
LANGUAGE_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"([a-z]{2,3})(?:-[a-z]{2,3})?")
ALIASES_RESOURCE: Final[str] = "language_aliases.txt"
PREFIXES_RESOURCE: Final[str] = "language_prefixes.txt"


class CodeSeparator(str, Enum):
    """Разделитель частей кода языка: `en_US` пишется как `en-US`."""

    UNDERSCORE = "_"
    HYPHEN = "-"


@dataclass(frozen=True)
class LanguageSpellings:
    """Известные написания кода языка и известные начала кода — в порядке проверки."""

    aliases: Mapping[str, str]
    prefixes: tuple[tuple[str, str], ...]

    @classmethod
    @cache
    def load(cls) -> LanguageSpellings:
        """Написания и начала из ресурсов программы; один объект на процесс."""
        return cls(aliases=dict(cls._pairs(ALIASES_RESOURCE)), prefixes=cls._pairs(PREFIXES_RESOURCE))

    @classmethod
    def _pairs(cls, resource: str) -> tuple[tuple[str, str], ...]:
        """Строки ресурса «написание код» парами."""
        return tuple((spelling, code) for spelling, code in (line.split() for line in TextResource(resource).lines))

    def prefixed(self, text: str) -> str | None:
        """Код по первому известному началу текста; ни одно не подошло — None."""
        return next((code for prefix, code in self.prefixes if text.startswith(prefix)), None)


def normalize_language(raw: str | None) -> str | None:
    """Код языка из сырого значения yt-dlp или langdetect; не похоже на язык — None."""
    text: str = (raw or "").strip().lower().replace(CodeSeparator.UNDERSCORE.value, CodeSeparator.HYPHEN.value)
    if not text:
        return None
    spellings: LanguageSpellings = LanguageSpellings.load()
    alias: str | None = spellings.aliases.get(text)
    if alias is not None:
        return alias
    code: re.Match[str] | None = LANGUAGE_CODE_PATTERN.fullmatch(text)
    if code is not None:
        return code.group(1)
    return spellings.prefixed(text)


@dataclass(frozen=True)
class TextLanguageDetector:
    """langdetect по тексту: сначала чистка, короткий текст — без ответа."""

    service_hints: ServiceHints
    min_length: int = MIN_DETECT_LENGTH

    def __post_init__(self) -> None:
        DetectorFactory.seed = DETECTOR_SEED

    @classmethod
    def from_resources(cls) -> TextLanguageDetector:
        return cls(service_hints=ServiceHints.load())

    def detect(self, text: str) -> str | None:
        """Код языка текста; текст после чистки короче `min_length` или langdetect не решил — None."""
        cleaned: str = AnalysisTextReport.of(text, self.service_hints).text
        if len(cleaned) < self.min_length:
            return None
        try:
            detected: str = detect(cleaned)
        except LangDetectException:
            return None
        return normalize_language(detected)
