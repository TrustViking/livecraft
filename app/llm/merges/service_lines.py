"""Служебные строки описания (вводная строка, заголовок ссылок, призыв) и их язык.

Перенесено из restreamer `app\\llm\\merges\\quality_service_lines.py`, поведение как есть (CLAUDE.md §14 решение 23):
- канонические строки на языке блока — `canonical_service_line`, ресурс `canonical_service_lines.json` побайтно;
- призыв на языке блока с сохранением хештегов — `replace_cta_preserving_hashtags`;
- язык служебной строки и абзаца — `detect_service_language`, `detect_paragraph_language`, `_detect_text_language`
  (подсказки донора — ресурс `merge_service_language_hints.json` без правки значений), `is_wrong_service_language`,
  `is_short_service_line`. Последний шаг — langdetect `core\\language.py::detect_language_from_text` донора, здесь —
  `app\\sources\\language.py::TextLanguageDetector` (та же чистка и тот же сид); «не решил» — `unknown`, как у донора.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from app.resources.loader import TextResource
from app.sources.language import TextLanguageDetector

SERVICE_LINES_RESOURCE: Final[str] = "canonical_service_lines.json"
LANGUAGE_HINTS_RESOURCE: Final[str] = "merge_service_language_hints.json"
FALLBACK_LANGUAGE: Final[str] = "other"
CORE_LANGUAGES: Final[frozenset[str]] = frozenset({"uk", "en", "ru"})

# Метки языка, которые не код языка: пустой текст, «прочий язык», langdetect не решил.
LANGUAGE_NONE: Final[str] = "none"
LANGUAGE_OTHER: Final[str] = "other"
LANGUAGE_UNKNOWN: Final[str] = "unknown"
UNDECIDED_LANGUAGES: Final[frozenset[str]] = frozenset({LANGUAGE_NONE, LANGUAGE_OTHER, LANGUAGE_UNKNOWN})

# Служебная строка — не длиннее 140 знаков; абзац короче 12 знаков язык не получает.
SERVICE_LINE_MAX_CHARS: Final[int] = 140
PARAGRAPH_MIN_CHARS: Final[int] = 12

WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
HASHTAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:^|\s)(#[^\s#]+)")
# Буквы, которые есть только в одном из двух алфавитов: украинские і ї є ґ, русские ы э ъ.
UKRAINIAN_LETTER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[іїєґ]")
RUSSIAN_LETTER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[ыэъ]")

HINT_KEYS: Final[tuple[str, ...]] = ("uk_phrases", "ru_phrases", "en_phrases", "uk_words", "ru_words")
BAD_SERVICE_LINES: Final[str] = "resource {name}: language {language} lacks keys {keys}"
BAD_HINTS: Final[str] = "resource {name}: key {key} must be a list of strings"


class ServiceLineKey(str, Enum):
    """Служебная строка описания."""

    LEAD_IN = "lead_in"                 # «В этом стриме вы увидите:»
    LINKS_HEADING = "links_heading"     # «🌐 Официальные ссылки:»
    CTA = "cta"                         # «Смотрите эфир и делитесь мнением.»


@dataclass(frozen=True)
class ServiceLineCatalog:
    """Канонические служебные строки по языкам; для языка вне каталога — строки `other`."""

    lines: Mapping[str, Mapping[ServiceLineKey, str]]

    @classmethod
    def load(cls) -> ServiceLineCatalog:
        return cls.from_data(TextResource(SERVICE_LINES_RESOURCE).data)

    @classmethod
    def from_data(cls, raw: Mapping[str, Any]) -> ServiceLineCatalog:
        """Каталог из объекта JSON: не объекты пропускаются, как у донора; языку без нужного ключа — `ValueError`."""
        lines: dict[str, Mapping[ServiceLineKey, str]] = {}
        for language, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            texts: dict[str, str] = {str(key): str(value) for key, value in payload.items()}
            missing: list[str] = [key.value for key in ServiceLineKey if key.value not in texts]
            if missing:
                raise ValueError(BAD_SERVICE_LINES.format(name=SERVICE_LINES_RESOURCE, language=language, keys=missing))
            lines[str(language)] = MappingProxyType({key: texts[key.value] for key in ServiceLineKey})
        if FALLBACK_LANGUAGE not in lines:
            raise ValueError(
                BAD_SERVICE_LINES.format(name=SERVICE_LINES_RESOURCE, language=FALLBACK_LANGUAGE, keys="all")
            )
        return cls(lines=MappingProxyType(lines))

    def line(self, language: str, key: ServiceLineKey) -> str:
        return self.lines.get(language, self.lines[FALLBACK_LANGUAGE])[key]

    def cta_preserving_hashtags(self, text: str, language: str) -> str:
        """Канонический призыв языка, за ним — хештеги прежнего призыва через пробел."""
        hashtags: list[str] = [match.group(1) for match in HASHTAG_PATTERN.finditer(str(text or ""))]
        base_text: str = self.line(language, ServiceLineKey.CTA)
        if hashtags:
            return f"{base_text} {' '.join(hashtags)}".strip()
        return base_text


@dataclass(frozen=True)
class ServiceLanguage:
    """Язык служебной строки и абзаца: фразы-подсказки, буквы алфавита, слова-подсказки, затем langdetect."""

    uk_phrases: tuple[str, ...]
    ru_phrases: tuple[str, ...]
    en_phrases: tuple[str, ...]
    uk_words: tuple[str, ...]           # слова с пробелами по краям: « це », « про »
    ru_words: tuple[str, ...]
    detector: TextLanguageDetector = field(repr=False)

    @classmethod
    def load(cls, detector: TextLanguageDetector | None = None) -> ServiceLanguage:
        raw: Mapping[str, Any] = TextResource(LANGUAGE_HINTS_RESOURCE).data
        hints: dict[str, tuple[str, ...]] = {key: cls._hint_list(raw, key) for key in HINT_KEYS}
        return cls(**hints, detector=detector or TextLanguageDetector.from_resources())

    @staticmethod
    def _hint_list(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
        value: Any = raw.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(BAD_HINTS.format(name=LANGUAGE_HINTS_RESOURCE, key=key))
        return tuple(value)

    def detect_service(self, text: str) -> str:
        """Язык служебной строки: пусто — `none`; фразы-подсказки uk, ru, en; дальше — правило текста."""
        normalized: str = WHITESPACE_RUN_PATTERN.sub(" ", str(text or "")).strip().lower()
        if not normalized:
            return LANGUAGE_NONE
        for language, phrases in (("uk", self.uk_phrases), ("ru", self.ru_phrases), ("en", self.en_phrases)):
            if any(phrase in normalized for phrase in phrases):
                return language
        return self._detect_text(normalized)

    def detect_paragraph(self, text: str) -> str:
        """Язык абзаца: короче 12 знаков — `none`; иначе правило текста."""
        normalized: str = WHITESPACE_RUN_PATTERN.sub(" ", str(text or "")).strip()
        if len(normalized) < PARAGRAPH_MIN_CHARS:
            return LANGUAGE_NONE
        return self._detect_text(normalized.lower())

    def _detect_text(self, normalized_text: str) -> str:
        if UKRAINIAN_LETTER_PATTERN.search(normalized_text):
            return "uk"
        if RUSSIAN_LETTER_PATTERN.search(normalized_text):
            return "ru"
        padded: str = f" {normalized_text} "
        if any(word in padded for word in self.uk_words):
            return "uk"
        if any(word in padded for word in self.ru_words):
            return "ru"
        return self.detector.detect(normalized_text) or LANGUAGE_UNKNOWN

    @staticmethod
    def is_wrong(detected: str, expected: str) -> bool:
        """Язык служебной строки явно не тот: определён, язык блока — uk, en или ru, и они различаются."""
        if detected in UNDECIDED_LANGUAGES or expected not in CORE_LANGUAGES:
            return False
        return detected != expected

    @staticmethod
    def is_short_service_line(text: str) -> bool:
        return len(WHITESPACE_RUN_PATTERN.sub(" ", str(text or "")).strip()) <= SERVICE_LINE_MAX_CHARS
