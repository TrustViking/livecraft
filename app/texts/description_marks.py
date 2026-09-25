"""Разметка описания эфира: маркеры пунктов, ссылки, заголовок официальных ссылок, призывы.

Перенесено из restreamer как есть: константы `app\\core\\constants.py` (маркеры, шаблоны ссылок, смысловых слов),
`app\\core\\official_links.py::is_official_links_heading`, `app\\core\\cta_detection.py` (`starts_with_cta_prefix`,
`looks_like_cta_line`, `looks_like_cta_paragraph`), `app\\llm\\merges\\quality_service_lines.py::is_bullet_line`,
`app\\llm\\merges\\merge_text_utils.py` (`_bullet_marker_for_line`, `_extract_named_entities`).
Префиксы и подсказки призывов — ресурсы `lexicon_cta_prefixes.txt` и `lexicon_cta_hints.txt` (побайтно из
restreamer); `CtaLexicon` читает их сам, у донора они были глобальными константами.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from app.resources.loader import TextResource
from app.texts.paragraphs import starts_with_any_prefix

NEUTRAL_BULLET_MARKER: Final[str] = "🔹"
ACCENT_BULLET_MARKERS: Final[tuple[str, ...]] = ("📌", "🎤", "🎥", "⚖", "🌐", "✅")
ALLOWED_BULLET_MARKERS: Final[tuple[str, ...]] = (NEUTRAL_BULLET_MARKER, *ACCENT_BULLET_MARKERS)
BULLET_PREFIXES: Final[tuple[str, ...]] = tuple(f"{marker} " for marker in ALLOWED_BULLET_MARKERS)
# Пункт без маркера-эмодзи: «-», «*», «•», «▪», «◦», «‣», «–», «—» или «1.», «2)» — и текст после пробела.
PLAIN_BULLET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:[-*\u2022\u25aa\u25e6\u2023\u2013\u2014]|(?:\d+[.)]))\s+\S+", flags=re.UNICODE
)

URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://\S+", flags=re.IGNORECASE)
URL_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^https?://\S+$", re.IGNORECASE)
# Смысловое слово: не короче трёх букв или цифр латиницы и кириллицы.
SEMANTIC_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-zА-Яа-яЁёІіЇїЄєҐґ]{3,}", flags=re.UNICODE)
# Имя собственное: два и больше слов подряд с заглавной буквы, в каждом не меньше трёх букв.
NAMED_ENTITY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ'-]{2,})(?:\s+[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ'-]{2,})+\b", flags=re.UNICODE
)
# Заголовок официальных ссылок: обязательный 🌐, любой непустой текст на любом языке и двоеточие в конце.
# Без 🌐 шаблон ловил бы любую строку «Что-то:» в теле описания.
OFFICIAL_LINKS_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*\U0001F310\s*[^\s:][^:\n]*:\s*$")
HASHTAG_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<!\w)#[^\s#]+")
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
LINE_BREAK: Final[str] = "\n"

CTA_PREFIXES_RESOURCE: Final[str] = "lexicon_cta_prefixes.txt"
CTA_HINTS_RESOURCE: Final[str] = "lexicon_cta_hints.txt"
# Правило донора (`_PREFIX_HINTS`), а не лексикон: эти подсказки — начала слов («подпис» ловит «подписывайтесь»),
# поэтому граница слова справа у них не требуется; остальные подсказки — целое слово или фраза.
CTA_PREFIX_HINTS: Final[frozenset[str]] = frozenset({"долуч", "підпис", "подпис", "коментар", "комментар", "comment"})
# Абзац-призыв — не больше двух строк; абзац с хештегом не длиннее 220 знаков — призыв и без подсказок.
CTA_PARAGRAPH_MAX_LINES: Final[int] = 2
CTA_HASHTAG_PARAGRAPH_MAX_CHARS: Final[int] = 220


def is_official_links_heading(text: str) -> bool:
    """Строка — заголовок блока официальных ссылок («🌐 Официальные ссылки:»)."""
    normalized_text: str = str(text or "").strip()
    if not normalized_text:
        return False
    return bool(OFFICIAL_LINKS_HEADING_PATTERN.fullmatch(normalized_text))


def is_bullet_line(line: str) -> bool:
    """Строка — пункт списка: маркер-эмодзи с пробелом или простой маркер; заголовок ссылок пунктом не считается."""
    stripped: str = str(line or "").strip()
    if not stripped or is_official_links_heading(stripped):
        return False
    return stripped.startswith(BULLET_PREFIXES) or bool(PLAIN_BULLET_PATTERN.match(stripped))


def bullet_marker_for_line(line: str) -> str:
    """Маркер пункта в начале строки: эмодзи, первое слово простого пункта («-», «1)») или пустая строка."""
    stripped: str = str(line or "").strip()
    if not stripped:
        return ""
    for marker in ALLOWED_BULLET_MARKERS:
        if stripped.startswith(f"{marker} "):
            return marker
    if PLAIN_BULLET_PATTERN.match(stripped):
        return stripped.split(maxsplit=1)[0]
    return ""


def extract_named_entities(text: str) -> set[str]:
    """Имена собственные из двух и больше слов с заглавной буквы — в нижнем регистре."""
    return {match.group(0).strip().lower() for match in NAMED_ENTITY_PATTERN.finditer(str(text or ""))}


def starts_with_cta_prefix(text: str, prefixes: Sequence[str]) -> bool:
    """Строка начинается с призыва из списка префиксов (без учёта регистра)."""
    return starts_with_any_prefix(text, prefixes)


def _hint_pattern(hint: str) -> re.Pattern[str]:
    if hint in CTA_PREFIX_HINTS:
        return re.compile(rf"(?<!\w){re.escape(hint)}")
    return re.compile(rf"(?<!\w){re.escape(hint)}(?!\w)")


@dataclass(frozen=True)
class CtaLexicon:
    """Призывы: префиксы («Подпишитесь», «Subscribe», …), с которых описание не должно начинаться, и подсказки
    («смотрите», «comment», …), по которым строка или абзац узнаётся как призыв."""

    prefixes: tuple[str, ...]
    hints: tuple[str, ...] = ()
    hint_patterns: tuple[re.Pattern[str], ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "hint_patterns", tuple(_hint_pattern(hint) for hint in self.hints))

    @classmethod
    def load(cls) -> CtaLexicon:
        """Префиксы и подсказки из ресурсов `lexicon_cta_prefixes.txt` и `lexicon_cta_hints.txt`."""
        return cls(prefixes=TextResource(CTA_PREFIXES_RESOURCE).lines, hints=TextResource(CTA_HINTS_RESOURCE).lines)

    def starts_with_prefix(self, text: str) -> bool:
        return starts_with_cta_prefix(text, self.prefixes)

    def looks_like_cta_line(self, text: str) -> bool:
        """В строке (пробелы схлопнуты, нижний регистр) есть подсказка призыва."""
        normalized_text: str = WHITESPACE_RUN_PATTERN.sub(" ", str(text or "")).strip().lower()
        if not normalized_text:
            return False
        return self._contains_hint(normalized_text)

    def looks_like_cta_paragraph(self, text: str) -> bool:
        """Абзац — призыв: одна-две строки без заголовка ссылок, пунктов и строк-ссылок, и в нём хештег
        (абзац не длиннее 220 знаков) или подсказка призыва."""
        lines: list[str] = [line.strip() for line in str(text or "").split(LINE_BREAK) if line.strip()]
        if not lines or len(lines) > CTA_PARAGRAPH_MAX_LINES:
            return False
        if any(is_official_links_heading(line) for line in lines):
            return False
        if any(line.startswith(BULLET_PREFIXES) or PLAIN_BULLET_PATTERN.match(line) for line in lines):
            return False
        if any(URL_LINE_PATTERN.fullmatch(line) for line in lines):
            return False
        normalized_text: str = WHITESPACE_RUN_PATTERN.sub(" ", str(text or "")).strip().lower()
        if HASHTAG_TOKEN_PATTERN.search(normalized_text) and len(normalized_text) <= CTA_HASHTAG_PARAGRAPH_MAX_CHARS:
            return True
        return self._contains_hint(normalized_text)

    def _contains_hint(self, normalized_text: str) -> bool:
        return any(pattern.search(normalized_text) for pattern in self.hint_patterns)
