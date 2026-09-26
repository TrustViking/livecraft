"""Разметка описания эфира: пункты списка, заголовок официальных ссылок, имена собственные, призывы.

`BulletLine` — строка глазами списка: маркер пункта, текст после него и два варианта «пункт ли это». Санация
считает пунктом и заголовок «🌐 …:» (у него маркер 🌐), проверка ответа модели — нет: заголовок ссылок не тезис.
Заголовок официальных ссылок — одно определение (`is_official_links_heading`). Призывы — лексикон `CtaLexicon`:
префиксы, с которых описание не должно начинаться, и подсказки, по которым строка или абзац узнаётся как призыв
(ресурсы `lexicon_cta_prefixes.txt`, `lexicon_cta_hints.txt`, `lexicon_cta_prefix_hints.txt`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from app.core.alphabet import LOWER_LETTERS, UPPER_LETTERS
from app.core.text_format import SPACE
from app.core.web_link import URL_LINE_PATTERN
from app.resources.loader import TextResource
from app.texts.hashtags import HASHTAG_PATTERN
from app.texts.paragraphs import collapse_spaces, nonempty_lines

NEUTRAL_BULLET_MARKER: Final[str] = "🔹"
ACCENT_BULLET_MARKERS: Final[tuple[str, ...]] = ("📌", "🎤", "🎥", "⚖", "🌐", "✅")
ALLOWED_BULLET_MARKERS: Final[tuple[str, ...]] = (NEUTRAL_BULLET_MARKER, *ACCENT_BULLET_MARKERS)
BULLET_PREFIXES: Final[tuple[str, ...]] = tuple(f"{marker} " for marker in ALLOWED_BULLET_MARKERS)
# Простой маркер пункта: «-», «*», «•», «▪», «◦», «‣», «–», «—» или «1.», «2)» — и пробелы после него.
PLAIN_BULLET_MARKER: Final[str] = r"^\s*(?:[-*•▪◦‣–—]|(?:\d+[.)]))\s+"
PLAIN_BULLET_MARKER_PATTERN: Final[re.Pattern[str]] = re.compile(PLAIN_BULLET_MARKER)
PLAIN_BULLET_PATTERN: Final[re.Pattern[str]] = re.compile(PLAIN_BULLET_MARKER + r"\S+")     # маркер и текст после него

# Имя собственное: два и больше слов подряд с заглавной буквы, в каждом не меньше трёх букв.
NAMED_ENTITY_WORD: Final[str] = f"[{UPPER_LETTERS}][{LOWER_LETTERS}'-]{{2,}}"
NAMED_ENTITY_PATTERN: Final[re.Pattern[str]] = re.compile(rf"\b(?:{NAMED_ENTITY_WORD})(?:\s+{NAMED_ENTITY_WORD})+\b")
# Заголовок официальных ссылок: обязательный 🌐, любой непустой текст на любом языке и двоеточие в конце.
# Без 🌐 шаблон ловил бы любую строку «Что-то:» в теле описания.
OFFICIAL_LINKS_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*\U0001F310\s*[^\s:][^:\n]*:\s*$")

CTA_PREFIXES_RESOURCE: Final[str] = "lexicon_cta_prefixes.txt"
CTA_HINTS_RESOURCE: Final[str] = "lexicon_cta_hints.txt"
# Подсказки-начала слов («подпис» ловит «подписывайтесь»): граница слова справа у них не требуется.
CTA_PREFIX_HINTS_RESOURCE: Final[str] = "lexicon_cta_prefix_hints.txt"
HINT_START_TEMPLATE: Final[str] = r"(?<!\w){hint}"
HINT_WORD_TEMPLATE: Final[str] = r"(?<!\w){hint}(?!\w)"
# Абзац-призыв — не больше двух строк; абзац с хештегом не длиннее 220 знаков — призыв и без подсказок.
CTA_PARAGRAPH_MAX_LINES: Final[int] = 2
CTA_HASHTAG_PARAGRAPH_MAX_CHARS: Final[int] = 220


def is_official_links_heading(text: str) -> bool:
    """Строка — заголовок блока официальных ссылок («🌐 Официальные ссылки:»)."""
    return OFFICIAL_LINKS_HEADING_PATTERN.fullmatch((text or "").strip()) is not None


def extract_named_entities(text: str) -> set[str]:
    """Имена собственные из двух и больше слов с заглавной буквы — в нижнем регистре."""
    return {match.group(0).strip().lower() for match in NAMED_ENTITY_PATTERN.finditer(text or "")}


@dataclass(frozen=True)
class BulletLine:
    """Строка описания без краевых пробелов глазами списка: маркер пункта и текст после него."""

    text: str

    @classmethod
    def of(cls, line: str) -> BulletLine:
        return cls((line or "").strip())

    @property
    def emoji_marker(self) -> str:
        """Маркер-эмодзи с пробелом после него в начале строки; нет — пусто."""
        return next((marker for marker in ALLOWED_BULLET_MARKERS if self.text.startswith(marker + SPACE)), "")

    @property
    def marker(self) -> str:
        """Маркер пункта: эмодзи, первое слово простого пункта («-», «1)») или пусто."""
        if self.emoji_marker:
            return self.emoji_marker
        return self.text.split(maxsplit=1)[0] if PLAIN_BULLET_PATTERN.match(self.text) else ""

    @property
    def content(self) -> str:
        """Текст после маркера-эмодзи или простого маркера; строка без маркера — целиком."""
        if self.emoji_marker:
            return self.text[len(self.emoji_marker) :].strip()
        return PLAIN_BULLET_MARKER_PATTERN.sub("", self.text, count=1).strip()

    @property
    def is_bullet(self) -> bool:
        """Пункт для санации: маркер-эмодзи с пробелом или простой маркер с текстом; заголовок «🌐 …:» — тоже."""
        return bool(self.emoji_marker) or PLAIN_BULLET_PATTERN.match(self.text) is not None

    @property
    def is_list_item(self) -> bool:
        """Пункт для проверки ответа модели: как `is_bullet`, но заголовок официальных ссылок — не пункт."""
        return self.is_bullet and not is_official_links_heading(self.text)

    @property
    def has_marker_prefix(self) -> bool:
        """Строка начинается маркером-эмодзи, даже без пробела после него."""
        return self.text.startswith(ALLOWED_BULLET_MARKERS)


@dataclass(frozen=True)
class CtaLexicon:
    """Призывы: префиксы («Подпишитесь», «Subscribe», …), с которых описание не должно начинаться, и подсказки
    («смотрите», «comment», …), по которым строка или абзац узнаётся как призыв. Подсказка из `prefix_hints` —
    начало слова, остальные — целое слово или фраза."""

    prefixes: tuple[str, ...]
    hints: tuple[str, ...] = ()
    prefix_hints: frozenset[str] = frozenset()

    @classmethod
    def load(cls) -> CtaLexicon:
        """Префиксы и подсказки из ресурсов программы."""
        return cls(
            prefixes=TextResource(CTA_PREFIXES_RESOURCE).lines,
            hints=TextResource(CTA_HINTS_RESOURCE).lines,
            prefix_hints=frozenset(TextResource(CTA_PREFIX_HINTS_RESOURCE).lines),
        )

    @cached_property
    def hint_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Шаблон каждой подсказки: слева — не буква; справа — не буква, если подсказка не начало слова."""
        return tuple(re.compile(self._hint_template(hint).format(hint=re.escape(hint))) for hint in self.hints)

    def _hint_template(self, hint: str) -> str:
        return HINT_START_TEMPLATE if hint in self.prefix_hints else HINT_WORD_TEMPLATE

    def starts_with_prefix(self, text: str) -> bool:
        """Текст (без краёв, без учёта регистра) начинается с одного из непустых префиксов."""
        normalized: str = (text or "").strip().lower()
        if not normalized:
            return False
        return any(prefix.strip() and normalized.startswith(prefix.strip().lower()) for prefix in self.prefixes)

    def looks_like_cta_line(self, text: str) -> bool:
        """В строке (пробелы схлопнуты, нижний регистр) есть подсказка призыва."""
        normalized: str = collapse_spaces(text).lower()
        return bool(normalized) and self._contains_hint(normalized)

    def looks_like_cta_paragraph(self, text: str) -> bool:
        """Абзац — призыв: одна-две строки без заголовка ссылок, пунктов и строк-ссылок, и в нём хештег
        (абзац не длиннее 220 знаков) или подсказка призыва."""
        lines: list[str] = nonempty_lines(text)
        if not lines or len(lines) > CTA_PARAGRAPH_MAX_LINES:
            return False
        if any(is_official_links_heading(line) or BulletLine(line).is_bullet for line in lines):
            return False
        if any(URL_LINE_PATTERN.fullmatch(line) for line in lines):
            return False
        normalized: str = collapse_spaces(text).lower()
        if HASHTAG_PATTERN.search(normalized) and len(normalized) <= CTA_HASHTAG_PARAGRAPH_MAX_CHARS:
            return True
        return self._contains_hint(normalized)

    def _contains_hint(self, normalized_text: str) -> bool:
        return any(pattern.search(normalized_text) for pattern in self.hint_patterns)
