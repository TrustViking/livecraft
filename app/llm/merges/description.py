"""Описание из ответа модели и его правила, не зависящие от источников и словарей (CLAUDE.md §14 решение 23).

`MergedDescription` — текст описания: абзацы и строки, повтор абзацев и соседних строк, похожие начала абзацев,
перегруженные пункты, пересказ по источникам, счёт ссылок, снятие строк «title:», «description:», «source(s):».
Правила над описанием, которым нужны словари или починка текста, живут в своих объектах: эхо тезиса —
`hook_echo.py::HookEcho`, призыв и служебная строка в начале — `opening.py::DescriptionOpening`, эмодзи —
`emoji.py::EmojiUsage`, смесь алфавитов — `script_mix.py`, нормализация качества — `quality.py::QualityNormalization`.

Имена собственные в пункте (`BULLET_NAME_PATTERN`) — своё правило, не правило имён описания
(`app\\texts\\description_marks.py::extract_named_entities`): оно считает имена внутри одного пункта, и цепочка
ограничена четырьмя словами, чтобы перечень имён через пробел не склеился в одно имя и пункт считался перегруженным.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from app.core.alphabet import LOWER_LETTERS, UPPER_LETTERS
from app.core.text_format import NEWLINE
from app.core.web_link import URL_PATTERN, WebLink
from app.core.youtube_video import YouTubeVideoId
from app.llm.merges import rules
from app.texts.description_marks import BULLET_PREFIXES
from app.texts.paragraphs import has_duplicate_paragraphs, normalize_newlines, split_paragraphs
from app.texts.similarity import TextPair, WordRule

META_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?i)^\s*(?:title|description|sources?)\s*:")
# Имя собственное в пункте: от двух до четырёх слов подряд с заглавной буквы.
BULLET_NAME_WORD: Final[str] = f"[{UPPER_LETTERS}][{LOWER_LETTERS}'`-]{{1,25}}"
BULLET_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(rf"\b{BULLET_NAME_WORD}(?:\s+{BULLET_NAME_WORD}){{1,3}}\b")
# Выгрузка по источникам: строки «Source 1:», «Video 2)» — хотя бы две; или в тексте есть «source 1» и «source 2».
SOURCE_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*(?:source|video)\s*\d+[:.)-]?", flags=re.IGNORECASE)
SOURCE_DUMP_PAIRS: Final[tuple[tuple[str, str], ...]] = (("source 1", "source 2"), ("video 1", "video 2"))


@dataclass(frozen=True)
class LinePair:
    """Две соседние строки описания."""

    current: str
    following: str

    @property
    def repeats(self) -> bool:
        """Повтор: обе строки длинные и у них длинное общее начало или почти те же смысловые слова; пустая строка
        повтором не бывает."""
        if not self.current or not self.following:
            return False
        if min(len(self.current), len(self.following)) < rules.ADJACENT_LINE_MIN_CHARS:
            return False
        pair: TextPair = TextPair(self.current, self.following)
        if pair.prefix_ratio > rules.ADJACENT_LINE_PREFIX_RATIO:
            return True
        current_words: list[str] = WordRule.SEMANTIC.words(self.current)
        following_words: list[str] = WordRule.SEMANTIC.words(self.following)
        if min(len(current_words), len(following_words)) < rules.ADJACENT_LINE_MIN_TOKENS:
            return False
        similarity: float | None = pair.jaccard
        return similarity is not None and similarity >= rules.ADJACENT_LINE_JACCARD


@dataclass(frozen=True)
class MergedDescription:
    """Текст описания из ответа модели. В `repr` текст не печатается."""

    text: str = field(repr=False)

    @property
    def paragraphs(self) -> list[str]:
        return split_paragraphs(self.text)

    @property
    def lines(self) -> list[str]:
        """Строки текста как есть; переводы строки приведены к `\\n`."""
        return normalize_newlines(self.text).split(NEWLINE)

    @property
    def has_duplicate_paragraphs(self) -> bool:
        return has_duplicate_paragraphs(self.text)

    def without_meta_lines(self) -> MergedDescription:
        """Без строк-заголовков «title:», «description:», «source(s):»; концы строк и края текста без пробелов."""
        kept_lines: list[str] = [line.rstrip() for line in self.lines if not META_LINE_PATTERN.match(line.strip())]
        return MergedDescription(NEWLINE.join(kept_lines).strip())

    @property
    def trimmed_lines_text(self) -> str:
        """Переводы строки — `\\n`, концы строк и края текста без пробелов."""
        return NEWLINE.join(line.rstrip() for line in self.lines).strip()

    @property
    def overloaded_bullet_count(self) -> int:
        """Пункты с маркером-эмодзи длиннее 500 знаков или длиннее 280 знаков с тремя и больше именами."""
        count: int = 0
        for line in self.lines:
            stripped: str = line.strip()
            if not stripped.startswith(BULLET_PREFIXES):
                continue
            if len(stripped) > rules.BULLET_ABSOLUTE_MAX_CHAR_LIMIT:
                count += 1
            elif len(stripped) > rules.BULLET_OVERLOAD_CHAR_LIMIT:
                count += int(len(BULLET_NAME_PATTERN.findall(stripped)) >= rules.BULLET_OVERLOAD_NAME_LIMIT)
        return count

    @property
    def looks_like_per_source_dump(self) -> bool:
        """Описание пересказывает источники по очереди («Source 1: …», «Video 2: …»), а не сводит их."""
        hits: int = sum(1 for line in self.lines if SOURCE_LINE_PATTERN.match(line.strip()))
        if hits >= rules.SOURCE_LINE_MIN_HITS:
            return True
        lowered_text: str = self.text.lower()
        return any(first in lowered_text and second in lowered_text for first, second in SOURCE_DUMP_PAIRS)

    @property
    def official_link_count(self) -> int:
        """Разных ссылок (не YouTube) в тексте — по ключу повтора после снятия меток слежения."""
        keys: set[str] = set()
        for match in URL_PATTERN.finditer(self.text):
            url: str | None = WebLink.of(match.group(0)).candidate
            if url is None or WebLink.of(url).is_youtube:
                continue
            keys.add(WebLink.of(url).key)
        return len(keys)

    @property
    def youtube_link_count(self) -> int:
        """Разных видео YouTube в тексте — по короткой ссылке `https://youtu.be/<id>`."""
        links: set[str] = set()
        for match in URL_PATTERN.finditer(self.text):
            raw_url: str = match.group(0).strip()
            if not WebLink.of(raw_url).is_youtube:
                continue
            video: YouTubeVideoId | None = YouTubeVideoId.of(raw_url)
            if video is not None:
                links.add(video.short_url)
        return len(links)

    @property
    def has_adjacent_duplicate_lines(self) -> bool:
        """Две соседние строки почти одинаковы: длинное общее начало или почти те же смысловые слова."""
        lines: list[str] = [line.strip() for line in self.lines]
        return any(LinePair(current, following).repeats for current, following in zip(lines, lines[1:]))

    @property
    def has_similar_paragraph_prefixes(self) -> bool:
        """Два абзаца (не короче 80 знаков) начинаются почти одинаково: общее начало больше 70 % короткого."""
        paragraphs: list[str] = self.paragraphs
        for first_index, first in enumerate(paragraphs):
            for second in paragraphs[first_index + 1 :]:
                if min(len(first), len(second)) < rules.PARAGRAPH_PREFIX_MIN_CHARS:
                    continue
                if TextPair(first, second).prefix_ratio > rules.PARAGRAPH_PREFIX_RATIO:
                    return True
        return False
