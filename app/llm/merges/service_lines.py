"""Служебные строки описания (вводная строка, заголовок ссылок, призыв) и их язык.

- канонические строки на языке блока — `ServiceLineCatalog`, ресурс `canonical_service_lines.json`;
- призыв на языке блока с сохранением хештегов — `ServiceLineCatalog.cta_preserving_hashtags`;
- язык служебной строки и абзаца — `ServiceLanguage`: фразы-подсказки (ресурс `merge_service_language_hints.json`),
  буквы алфавита, слова-подсказки, затем `app\\texts\\language_detector.py::TextLanguageDetector`; «не решил» — `unknown`;
- язык явно не тот — одно правило `LanguageMatch` для тезиса и для служебных строк: язык, который не определился
  (`none`, `other`, `unknown`), несовпадением не считается.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final

from app.core.alphabet import RUSSIAN_LETTER_PATTERN, UKRAINIAN_LETTER_PATTERN, CoreLanguage
from app.core.text_format import SPACE
from app.llm.merges import rules
from app.resources.loader import TextResource
from app.texts.hashtags import HASHTAG_AFTER_SPACE_PATTERN
from app.texts.language_detector import TextLanguageDetector
from app.texts.paragraphs import collapse_spaces

SERVICE_LINES_RESOURCE: Final[str] = "canonical_service_lines.json"
LANGUAGE_HINTS_RESOURCE: Final[str] = "merge_service_language_hints.json"

# Метки языка, которые не код языка: пустой текст, «прочий язык», язык не определился.
LANGUAGE_NONE: Final[str] = "none"
LANGUAGE_OTHER: Final[str] = "other"
LANGUAGE_UNKNOWN: Final[str] = "unknown"
UNDECIDED_LANGUAGES: Final[frozenset[str]] = frozenset({LANGUAGE_NONE, LANGUAGE_OTHER, LANGUAGE_UNKNOWN})
# Строки каталога для языка вне каталога.
FALLBACK_LANGUAGE: Final[str] = LANGUAGE_OTHER

HINT_KEYS: Final[tuple[str, ...]] = ("uk_phrases", "ru_phrases", "en_phrases", "uk_words", "ru_words")
ALL_KEYS: Final[str] = "all"
BAD_SERVICE_LINES: Final[str] = "resource {name}: language {language} lacks keys {keys}"
BAD_HINTS: Final[str] = "resource {name}: key {key} must be a list of strings"


class ServiceLineKey(str, Enum):
    """Служебная строка описания."""

    LEAD_IN = "lead_in"                 # «В этом стриме вы увидите:»
    LINKS_HEADING = "links_heading"     # «🌐 Официальные ссылки:»
    CTA = "cta"                         # «Смотрите эфир и делитесь мнением.»


@dataclass(frozen=True)
class LanguageMatch:
    """Язык текста против языка блока."""

    detected: str
    expected: str

    @property
    def is_wrong(self) -> bool:
        """Язык явно не тот: он определился, язык блока — uk, en или ru, и они различаются."""
        if self.detected in UNDECIDED_LANGUAGES or not CoreLanguage.covers(self.expected):
            return False
        return self.detected != self.expected


@dataclass(frozen=True)
class ServiceLineCatalog:
    """Канонические служебные строки по языкам; для языка вне каталога — строки `other`."""

    lines: Mapping[str, Mapping[ServiceLineKey, str]]

    @classmethod
    def load(cls) -> ServiceLineCatalog:
        return cls.from_data(TextResource(SERVICE_LINES_RESOURCE).data)

    @classmethod
    def from_data(cls, raw: Mapping[str, object]) -> ServiceLineCatalog:
        """Каталог из объекта JSON: не объекты пропускаются; языку без нужного ключа — `ValueError`."""
        lines: dict[str, Mapping[ServiceLineKey, str]] = {}
        for language, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            texts: dict[str, str] = {str(key): str(value) for key, value in payload.items()}
            missing: list[str] = [key.value for key in ServiceLineKey if key.value not in texts]
            if missing:
                raise ValueError(BAD_SERVICE_LINES.format(name=SERVICE_LINES_RESOURCE, language=language, keys=missing))
            lines[language] = MappingProxyType({key: texts[key.value] for key in ServiceLineKey})
        if FALLBACK_LANGUAGE not in lines:
            raise ValueError(
                BAD_SERVICE_LINES.format(name=SERVICE_LINES_RESOURCE, language=FALLBACK_LANGUAGE, keys=ALL_KEYS)
            )
        return cls(lines=MappingProxyType(lines))

    def line(self, language: str, key: ServiceLineKey) -> str:
        return self.lines.get(language, self.lines[FALLBACK_LANGUAGE])[key]

    def cta_preserving_hashtags(self, text: str, language: str) -> str:
        """Канонический призыв языка, за ним — хештеги прежнего призыва через пробел."""
        hashtags: list[str] = [match.group(1) for match in HASHTAG_AFTER_SPACE_PATTERN.finditer(text)]
        base_text: str = self.line(language, ServiceLineKey.CTA)
        if hashtags:
            return SPACE.join((base_text, *hashtags)).strip()
        return base_text


@dataclass(frozen=True)
class ServiceLanguage:
    """Язык служебной строки и абзаца: фразы-подсказки, буквы алфавита, слова-подсказки, затем определитель языка."""

    uk_phrases: tuple[str, ...]
    ru_phrases: tuple[str, ...]
    en_phrases: tuple[str, ...]
    uk_words: tuple[str, ...]           # слова с пробелами по краям: « це », « про »
    ru_words: tuple[str, ...]
    detector: TextLanguageDetector = field(repr=False)

    @classmethod
    def load(cls, detector: TextLanguageDetector | None = None) -> ServiceLanguage:
        raw: Mapping[str, object] = TextResource(LANGUAGE_HINTS_RESOURCE).data
        hints: dict[str, tuple[str, ...]] = {key: cls._hints(raw, key) for key in HINT_KEYS}
        return cls(**hints, detector=detector or TextLanguageDetector.from_resources())

    @classmethod
    def _hints(cls, raw: Mapping[str, object], key: str) -> tuple[str, ...]:
        """Подсказки одного вида: список строк; иначе ресурс испорчен — `ValueError`."""
        value: object = raw.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(BAD_HINTS.format(name=LANGUAGE_HINTS_RESOURCE, key=key))
        return tuple(value)

    @property
    def _phrases(self) -> tuple[tuple[CoreLanguage, tuple[str, ...]], ...]:
        return (
            (CoreLanguage.UK, self.uk_phrases),
            (CoreLanguage.RU, self.ru_phrases),
            (CoreLanguage.EN, self.en_phrases),
        )

    def detect_service(self, text: str) -> str:
        """Язык служебной строки: пусто — `none`; фразы-подсказки uk, ru, en; дальше — правило текста."""
        normalized: str = collapse_spaces(text).lower()
        if not normalized:
            return LANGUAGE_NONE
        for language, phrases in self._phrases:
            if any(phrase in normalized for phrase in phrases):
                return language.value
        return self._detect_text(normalized)

    def detect_paragraph(self, text: str) -> str:
        """Язык абзаца: короче 12 знаков — `none`; иначе правило текста."""
        normalized: str = collapse_spaces(text)
        if len(normalized) < rules.SERVICE_PARAGRAPH_MIN_CHARS:
            return LANGUAGE_NONE
        return self._detect_text(normalized.lower())

    def _detect_text(self, normalized_text: str) -> str:
        if UKRAINIAN_LETTER_PATTERN.search(normalized_text):
            return CoreLanguage.UK.value
        if RUSSIAN_LETTER_PATTERN.search(normalized_text):
            return CoreLanguage.RU.value
        padded: str = f"{SPACE}{normalized_text}{SPACE}"
        if any(word in padded for word in self.uk_words):
            return CoreLanguage.UK.value
        if any(word in padded for word in self.ru_words):
            return CoreLanguage.RU.value
        return self.detector.detect(normalized_text) or LANGUAGE_UNKNOWN
