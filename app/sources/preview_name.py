"""Имя файла превью видео: «{номер}_{ЯЗЫК}_{название латиницей}.jpg» (CLAUDE.md §14 решение 27).

Номер — место видео среди готовых видео той же даты и того же языка в порядке таблицы (с 1), язык — код заглавными,
название — название видео латиницей: кириллица по таблице транслитерации (ресурс `preview_name_latin.json`),
остальные знаки — подчёркиванием. В имени только латинские буквы, цифры, «.», «_» и «-», подчёркивания не идут
подряд, края без знаков, основа имени не длиннее `MAX_STEM_CHARS`. Пустое название — «video». Одно и то же видео
даёт одно и то же имя в каждом запуске: копия на Диске с тем же именем и размером не загружается второй раз.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.alphabet import LATIN_LETTERS, LATIN_LOWER
from app.resources.loader import TextResource
from app.slots.preview import PREVIEW_FILE_EXTENSION

PREVIEW_NAME_TEMPLATE: Final[str] = "{index}_{language}_{title}"
MAX_STEM_CHARS: Final[int] = 120
FALLBACK_TITLE: Final[str] = "video"
LATIN_RESOURCE: Final[str] = "preview_name_latin.json"
LATIN_LETTERS_KEY: Final[str] = "letters"
# Название латиницей: всё, что не строчная латинская буква и не цифра, — одним подчёркиванием.
TITLE_JUNK_PATTERN: Final[re.Pattern[str]] = re.compile(f"[^{LATIN_LOWER}0-9]+")
# Основа имени: всё, что не латинская буква, не цифра, не «.», «_» и «-», — подчёркиванием; подряд — одно.
STEM_JUNK_PATTERN: Final[re.Pattern[str]] = re.compile(f"[^{LATIN_LETTERS}0-9._-]+")
REPEATED_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile("_+")


class NameMark(str, Enum):
    """Знаки имени файла превью."""

    SEPARATOR = "_"         # вместо пробелов и прочих знаков
    EDGES = "._-"           # чем не может начинаться и кончаться основа имени


@dataclass(frozen=True)
class PreviewName:
    """Имя превью одного видео: номер среди видео своей даты и языка, код языка и название видео."""

    index: int
    language: str
    title: str

    @property
    def latin_title(self) -> str:
        """Название латиницей в нижнем регистре; знаков, кроме подчёркиваний между словами, нет; пусто — «video»."""
        letters: Mapping[str, str] = TextResource(LATIN_RESOURCE).data[LATIN_LETTERS_KEY]
        latin: str = self.title.lower().translate(str.maketrans(dict(letters)))
        cleaned: str = TITLE_JUNK_PATTERN.sub(NameMark.SEPARATOR.value, latin).strip(NameMark.SEPARATOR.value)
        return (cleaned or FALLBACK_TITLE)[:MAX_STEM_CHARS]

    @property
    def stem(self) -> str:
        """Основа имени: «{номер}_{ЯЗЫК}_{название}», только разрешённые знаки, не длиннее MAX_STEM_CHARS."""
        raw: str = PREVIEW_NAME_TEMPLATE.format(index=self.index, language=self.language.upper(), title=self.latin_title)
        safe: str = REPEATED_SEPARATOR_PATTERN.sub(
            NameMark.SEPARATOR.value, STEM_JUNK_PATTERN.sub(NameMark.SEPARATOR.value, raw)
        )
        edges: str = NameMark.EDGES.value
        return safe.strip(edges)[:MAX_STEM_CHARS].rstrip(edges) or FALLBACK_TITLE

    @property
    def file_name(self) -> str:
        return self.stem + PREVIEW_FILE_EXTENSION
