"""Смесь алфавитов в описании merge: поиск подозрительных слов и починка латинских двойников кириллицы.

- `ScriptMixProbe` — до пяти слов со смесью алфавитов в названии, тезисе и пунктах (только uk, en, ru); ссылки,
  почта, хештеги и домены не проверяются — в них смесь законна; допустимые латинские слова — ресурс
  `merge_allowed_latin_tokens.txt`. Находка — жёсткий отказ semantic gate (`quality.py`).
- `HomoglyphMap`, `HomoglyphRepair` — слово кириллицей с латинскими двойниками букв исправляется (только uk и ru):
  модель иногда пишет «Кiев» латинской «i». Чинится только настоящая смесь, где кириллицы больше, чем латиницы,
  и у каждой латинской буквы есть двойник.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from app.core.alphabet import (
    CYRILLIC_LETTER_PATTERN,
    LANGUAGE_HOMOGLYPHS,
    LATIN_LETTER_PATTERN,
    LETTERS,
    SAFE_HOMOGLYPHS,
    CoreLanguage,
)
from app.core.text_format import SPACE
from app.core.web_link import URL_PATTERN
from app.llm.merges import rules
from app.llm.merges.description import MergedDescription
from app.observability.log_event import LogEvent
from app.resources.loader import TextResource
from app.texts.hashtags import HASHTAG_AFTER_SPACE_PATTERN

ALLOWED_LATIN_TOKENS_RESOURCE: Final[str] = "merge_allowed_latin_tokens.txt"
# Языки, которые пишутся кириллицей: в них латинское слово подозрительно, и в них чинятся двойники букв.
CYRILLIC_LANGUAGES: Final[frozenset[str]] = frozenset({CoreLanguage.UK.value, CoreLanguage.RU.value})

SCRIPT_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(f"[{LETTERS}][{LETTERS}0-9'_-]*")
NOT_LATIN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z]")
ABBREVIATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Z0-9]{2,6}")
CAPITALIZED_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Z][a-z]{1,14}")
EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\S+@\S+\.\S+\b", re.IGNORECASE)
BARE_DOMAIN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z]{2,}){1,3}\b", flags=re.IGNORECASE
)
# Слово для починки двойников — буквы латиницы и кириллицы с апострофами (\u02bc и '); цифры, знаки и пробелы — границы.
WORD_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(f"[{LETTERS}\u02bc']+")


@dataclass(frozen=True)
class ScriptMixProbe:
    """Поиск слов со смесью алфавитов; `allowed_latin_tokens` — латинские слова, допустимые в тексте кириллицей."""

    allowed_latin_tokens: frozenset[str]

    @classmethod
    def load(cls) -> ScriptMixProbe:
        return cls(allowed_latin_tokens=frozenset(TextResource(ALLOWED_LATIN_TOKENS_RESOURCE).lines))

    def suspects(self, texts: Iterable[str], language: str) -> tuple[str, ...]:
        """До пяти подозрительных слов по порядку текстов, без повторов; язык вне uk, en, ru — ничего."""
        if not CoreLanguage.covers(language):
            return ()
        found: list[str] = []
        for text in texts:
            for token in SCRIPT_TOKEN_PATTERN.findall(self._probe_text(text)):
                if token in found or not self._is_suspicious(token, language):
                    continue
                found.append(token)
                if len(found) >= rules.SCRIPT_MIX_MAX_SUSPECTS:
                    return tuple(found)
        return tuple(found)

    def _probe_text(self, text: str) -> str:
        """Текст без ссылок, почты, хештегов и доменов — в них смесь алфавитов законна."""
        probe: str = URL_PATTERN.sub(SPACE, text)
        probe = EMAIL_PATTERN.sub(SPACE, probe)
        probe = HASHTAG_AFTER_SPACE_PATTERN.sub(SPACE, probe)
        return BARE_DOMAIN_PATTERN.sub(SPACE, probe)

    def _is_suspicious(self, token: str, language: str) -> bool:
        """Буквы обоих алфавитов в одном слове; в английском тексте — кириллица; в тексте кириллицей — длинное
        латинское слово в нижнем регистре, если оно не допустимо."""
        has_cyrillic: bool = bool(CYRILLIC_LETTER_PATTERN.search(token))
        has_latin: bool = bool(LATIN_LETTER_PATTERN.search(token))
        if has_cyrillic and has_latin:
            return True
        if language == CoreLanguage.EN.value:
            return has_cyrillic and len(CYRILLIC_LETTER_PATTERN.findall(token)) >= rules.EN_MIN_CYRILLIC_CHARS
        if language not in CYRILLIC_LANGUAGES or not has_latin:
            return False
        if len(NOT_LATIN_PATTERN.sub("", token)) < rules.CYRILLIC_TEXT_MIN_LATIN_CHARS:
            return False
        if self._is_allowed_latin(token):
            return False
        return token == token.lower()

    def _is_allowed_latin(self, token: str) -> bool:
        """Допустимое слово, аббревиатура или слово с заглавной буквы."""
        if token.lower() in self.allowed_latin_tokens:
            return True
        return bool(ABBREVIATION_PATTERN.fullmatch(token) or CAPITALIZED_WORD_PATTERN.fullmatch(token))


@dataclass(frozen=True)
class HomoglyphMap:
    """Латинские двойники кириллических букв для языка с кириллицей (только uk и ru)."""

    language: str
    mapping: Mapping[str, str] = field(repr=False)

    @classmethod
    def of(cls, language: str) -> HomoglyphMap | None:
        if language not in CYRILLIC_LANGUAGES:
            return None
        return cls(language=language, mapping=MappingProxyType({**SAFE_HOMOGLYPHS, **LANGUAGE_HOMOGLYPHS[language]}))

    def repair_token(self, token: str) -> str | None:
        """Слово кириллицей с латинскими двойниками — исправленное слово; иначе None.

        Чинится только настоящая смесь, где кириллицы больше, чем латиницы, и у каждой латинской буквы есть
        двойник.
        """
        cyrillic_chars: list[str] = CYRILLIC_LETTER_PATTERN.findall(token)
        latin_chars: list[str] = LATIN_LETTER_PATTERN.findall(token)
        if not cyrillic_chars or not latin_chars:
            return None
        if len(cyrillic_chars) <= len(latin_chars):
            return None
        if any(char not in self.mapping for char in latin_chars):
            return None
        repaired: str = "".join(self.mapping.get(char, char) for char in token)
        return None if repaired == token else repaired


@dataclass(frozen=True)
class HomoglyphRepair:
    """Итог починки алфавита: описание после неё и исправленные слова (до и после) по порядку."""

    description: MergedDescription
    tokens_before: tuple[str, ...]
    tokens_after: tuple[str, ...]

    @classmethod
    def of(cls, description: MergedDescription, language: str) -> HomoglyphRepair:
        """Слова кириллицей с латинскими двойниками букв исправлены (только uk и ru; прочие языки — как есть)."""
        homoglyphs: HomoglyphMap | None = HomoglyphMap.of(language)
        if homoglyphs is None or not description.text:
            return cls(description=description, tokens_before=(), tokens_after=())
        before: list[str] = []
        after: list[str] = []

        def replace(match: re.Match[str]) -> str:
            token: str = match.group(0)
            repaired_token: str | None = homoglyphs.repair_token(token)
            if repaired_token is None:
                return token
            before.append(token)
            after.append(repaired_token)
            return repaired_token

        repaired_text: str = WORD_TOKEN_PATTERN.sub(replace, description.text)
        return cls(description=MergedDescription(repaired_text), tokens_before=tuple(before), tokens_after=tuple(after))

    @property
    def tokens_repaired(self) -> int:
        return len(self.tokens_before)

    def extend(self, event: LogEvent) -> LogEvent:
        """Событие с полями починки: сколько слов исправлено, какими они были и какими стали."""
        return event.extended(
            tokens_repaired=self.tokens_repaired, before_tokens=self.tokens_before, after_tokens=self.tokens_after
        )
