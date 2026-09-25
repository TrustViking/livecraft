"""Разметка описания эфира: маркеры пунктов, ссылки, заголовок официальных ссылок, призывы в начале текста.

Перенесено из restreamer как есть: константы `app\\core\\constants.py` (маркеры, шаблоны ссылок, смысловых слов),
`app\\core\\official_links.py::is_official_links_heading`, `app\\core\\cta_detection.py::starts_with_cta_prefix`.
Префиксы призывов — ресурс `lexicon_cta_prefixes.txt` (побайтно из restreamer); `CtaLexicon` читает его сам,
у донора префиксы передавались глобальной константой.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.resources.loader import TextResource
from app.texts.paragraphs import starts_with_any_prefix

NEUTRAL_BULLET_MARKER: Final[str] = "🔹"
ACCENT_BULLET_MARKERS: Final[tuple[str, ...]] = ("📌", "🎤", "🎥", "⚖", "🌐", "✅")
ALLOWED_BULLET_MARKERS: Final[tuple[str, ...]] = (NEUTRAL_BULLET_MARKER, *ACCENT_BULLET_MARKERS)

URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://\S+", flags=re.IGNORECASE)
URL_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^https?://\S+$", re.IGNORECASE)
# Смысловое слово: не короче трёх букв или цифр латиницы и кириллицы.
SEMANTIC_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-zА-Яа-яЁёІіЇїЄєҐґ]{3,}", flags=re.UNICODE)
# Заголовок официальных ссылок: обязательный 🌐, любой непустой текст на любом языке и двоеточие в конце.
# Без 🌐 шаблон ловил бы любую строку «Что-то:» в теле описания.
OFFICIAL_LINKS_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*🌐\s*[^\s:][^:\n]*:\s*$")
CTA_PREFIXES_RESOURCE: Final[str] = "lexicon_cta_prefixes.txt"


def is_official_links_heading(text: str) -> bool:
    """Строка — заголовок блока официальных ссылок («🌐 Официальные ссылки:»)."""
    normalized_text: str = str(text or "").strip()
    if not normalized_text:
        return False
    return bool(OFFICIAL_LINKS_HEADING_PATTERN.fullmatch(normalized_text))


def starts_with_cta_prefix(text: str, prefixes: Sequence[str]) -> bool:
    """Строка начинается с призыва из списка префиксов (без учёта регистра)."""
    return starts_with_any_prefix(text, prefixes)


@dataclass(frozen=True)
class CtaLexicon:
    """Префиксы призывов («Подпишитесь», «Subscribe», …), с которых описание не должно начинаться."""

    prefixes: tuple[str, ...]

    @classmethod
    def load(cls) -> CtaLexicon:
        """Префиксы из ресурса `lexicon_cta_prefixes.txt`."""
        return cls(prefixes=TextResource(CTA_PREFIXES_RESOURCE).lines)

    def starts_with_prefix(self, text: str) -> bool:
        return starts_with_cta_prefix(text, self.prefixes)
