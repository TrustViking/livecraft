"""Хвост ответа модели: призывы, хештеги и ссылки в конце описания и в конце абзацев (CLAUDE.md §14 решение 23).

Перенесено из restreamer, поведение как есть: `app\\publish\\sanitizers\\tail_parser.py::TailParser`.
- `TrailingTail.of(lines, cta)` — `split_tail`: с конца текста по строкам снимаются строки-ссылки, затем строки
  хештегов, затем строки-призывы (хештеги в конце строки-призыва уходят к хештегам); `body_end_index` — где кончается тело.
- `EmbeddedTail.of(text, cta)` — `extract_embedded`: в каждом абзаце тела с конца снимаются ссылки, хештеги и последнее
  предложение-призыв.
Правила строк и абзацев — методы `TailReader`: призыв узнаётся по лексикону `CtaLexicon` (подсказки донора
`CTA_HINTS` — `CtaLexicon.hints`). Итоги — объекты-значения, без кортежей между функциями.
Свободные функции модуля — чистые преобразования строк без знания о предметных объектах.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from app.core.url_text import SourceUrl, dedupe_nonempty
from app.observability.logging_setup import get_logger
from app.texts.description_marks import ALLOWED_BULLET_MARKERS, URL_LINE_PATTERN, CtaLexicon
from app.texts.paragraphs import split_paragraphs

LOGGER = get_logger("texts")

HASHTAG_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^#[^\s#]+$")
_MARKER_ALTERNATIVES: Final[str] = "|".join(re.escape(marker) for marker in ALLOWED_BULLET_MARKERS)
# Два и больше маркера пункта подряд в начале строки («🔹 🔹 текст», «🔹 📌 текст») — остаётся первый.
DOUBLE_BULLET_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^(\s*)({_MARKER_ALTERNATIVES})((?:\s+(?:{_MARKER_ALTERNATIVES}))+)\s*", re.MULTILINE
)
# Ссылки в конце абзаца: после начала, пробела или открывающей скобки — одна или несколько через пробел.
URL_TAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?is)(?:^|[\s\(\[])(https?://\S+(?:\s+https?://\S+)*)\s*$")
HASHTAG_TAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?is)(#[^\s#]+(?:\s+#[^\s#]+)*)\s*$")
SENTENCE_BREAK_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?…])\s+")
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
URL_EDGE_CHARS: Final[str] = "<>()[]{}"
URL_TRAILING_PUNCTUATION: Final[str] = ".,;"
HASHTAG_PREFIX_TRIM: Final[str] = " ,;"
CTA_LINE_LEAD_CHARS: Final[str] = "-*•> "
# Строка-призыв без подсказки в начале — не длиннее 200 знаков (длинный абзац со словом «комментарий» — не призыв).
STANDALONE_CTA_MAX_CHARS: Final[int] = 200
PARAGRAPH_JOINER: Final[str] = "\n\n"
TOKEN_JOINER: Final[str] = " "


def is_source_url_line(line: str) -> bool:
    """Строка — одна ссылка http(s) (обрамление скобками и знаки препинания в конце не мешают)."""
    candidate: str = str(line or "").strip().strip(URL_EDGE_CHARS).rstrip(URL_TRAILING_PUNCTUATION)
    return bool(candidate and URL_LINE_PATTERN.fullmatch(candidate))


def is_hashtags_line(line: str) -> bool:
    """Строка — только хештеги через пробел."""
    tokens: list[str] = [item for item in str(line or "").split() if item]
    return bool(tokens) and all(HASHTAG_TOKEN_PATTERN.fullmatch(item) for item in tokens)


def merge_hashtag_lines(lines: Iterable[str]) -> str:
    """Хештеги всех строк одной строкой: без повторов без учёта регистра, в порядке первого появления."""
    tokens: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for token in str(line or "").split():
            cleaned: str = token.strip()
            if not cleaned or not HASHTAG_TOKEN_PATTERN.fullmatch(cleaned) or cleaned.lower() in seen:
                continue
            seen.add(cleaned.lower())
            tokens.append(cleaned)
    return TOKEN_JOINER.join(tokens)


def dedupe_cta_lines(lines: Iterable[str]) -> tuple[str, ...]:
    """Строки-призывы с схлопнутыми пробелами, без пустых и повторов без учёта регистра."""
    kept: list[str] = []
    seen: set[str] = set()
    for line in lines:
        cleaned: str = WHITESPACE_RUN_PATTERN.sub(" ", str(line or "")).strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        kept.append(cleaned)
    return tuple(kept)


def clean_double_bullet_markers(text: str) -> str:
    """Сдвоенные маркеры пункта в начале строки — один, первый."""
    return DOUBLE_BULLET_PATTERN.sub(r"\1\2 ", text)


@dataclass(frozen=True)
class TailFragments:
    """Что снято с хвоста: строки-призывы, строки хештегов, отделялись ли хештеги от призыва, ссылки источников,
    сколько ссылок изменила чистка и сколько неполных ссылок отброшено."""

    cta_lines: tuple[str, ...] = ()
    hashtag_lines: tuple[str, ...] = ()
    hashtags_split_from_cta: bool = False
    source_urls: tuple[str, ...] = ()
    url_change_count: int = 0
    malformed_urls_dropped: int = 0

    def followed_by(self, later: TailFragments) -> TailFragments:
        """Фрагменты этого хвоста, затем `later` (у санации донора — сначала внутренние, потом хвост в конце):
        призывы и ссылки — без повторов, в порядке первого появления; флаг — «или»; счётчики — сумма."""
        return TailFragments(
            cta_lines=dedupe_cta_lines((*self.cta_lines, *later.cta_lines)),
            hashtag_lines=(*self.hashtag_lines, *later.hashtag_lines),
            hashtags_split_from_cta=self.hashtags_split_from_cta or later.hashtags_split_from_cta,
            source_urls=dedupe_nonempty((*self.source_urls, *later.source_urls)),
            url_change_count=self.url_change_count + later.url_change_count,
            malformed_urls_dropped=self.malformed_urls_dropped + later.malformed_urls_dropped,
        )

    @property
    def hashtags_line(self) -> str:
        """Хештеги всех строк одной строкой (`merge_hashtag_lines`)."""
        return merge_hashtag_lines(self.hashtag_lines)


@dataclass(frozen=True)
class UrlTail:
    """Абзац без ссылок в конце: текст до них, чистые ссылки, сколько изменила чистка, сколько отброшено."""

    text: str
    urls: tuple[str, ...] = ()
    change_count: int = 0
    malformed: int = 0


@dataclass(frozen=True)
class TextTail:
    """Абзац без хвоста одного вида (хештеги или призыв): текст до хвоста и сам хвост; хвоста нет — пусто."""

    text: str
    tail: str = ""


@dataclass(frozen=True)
class TailReader:
    """Правила хвоста над строками и абзацами; призыв узнаётся по лексикону."""

    cta: CtaLexicon

    def is_standalone_cta_line(self, line: str) -> bool:
        """Строка-призыв: начинается с подсказки (после «-», «*», «•», «>») или короткая строка с подсказкой."""
        normalized_line: str = WHITESPACE_RUN_PATTERN.sub(" ", str(line or "")).strip().lower()
        if not normalized_line:
            return False
        cleaned_line: str = normalized_line.lstrip(CTA_LINE_LEAD_CHARS)
        if any(cleaned_line.startswith(hint) for hint in self.cta.hints):
            return True
        return len(normalized_line) <= STANDALONE_CTA_MAX_CHARS and self.cta.looks_like_cta_line(line)

    def url_tail(self, paragraph: str) -> UrlTail:
        """Ссылки в конце абзаца: неполные отброшены, остальные почищены и без повторов."""
        normalized: str = str(paragraph or "").strip()
        if not normalized:
            return UrlTail(text="")
        match: re.Match[str] | None = URL_TAIL_PATTERN.search(normalized)
        if match is None:
            return UrlTail(text=normalized)
        urls: list[str] = []
        changes: int = 0
        malformed: int = 0
        for raw_url in (item for item in match.group(1).split() if item):
            cleaned: SourceUrl = self.source_url(raw_url)
            if cleaned.url is None:
                malformed += 1
                continue
            changes += int(cleaned.url != raw_url)
            urls.append(cleaned.url)
        return UrlTail(normalized[: match.start(1)].rstrip(), dedupe_nonempty(urls), changes, malformed)

    @staticmethod
    def source_url(raw: str) -> SourceUrl:
        """Чистка ссылки хвоста; ссылка YouTube без id — строка лога донора."""
        cleaned: SourceUrl = SourceUrl.of(raw)
        if cleaned.youtube_dropped:
            LOGGER.info("%s", cleaned.log_line)
        return cleaned

    def hashtag_tail(self, paragraph: str) -> TextTail:
        """Хештеги в конце абзаца; текст до них — без пробелов, запятых и `;` в конце."""
        normalized: str = str(paragraph or "").strip()
        if not normalized:
            return TextTail(text="")
        match: re.Match[str] | None = HASHTAG_TAIL_PATTERN.search(normalized)
        if match is None:
            return TextTail(text=normalized)
        candidate: str = match.group(1).strip()
        if not is_hashtags_line(candidate):
            return TextTail(text=normalized)
        return TextTail(text=normalized[: match.start(1)].rstrip(HASHTAG_PREFIX_TRIM), tail=candidate)

    def cta_tail(self, paragraph: str) -> TextTail:
        """Последнее предложение абзаца — призыв; абзац из одного предложения-призыва уходит в хвост целиком."""
        normalized: str = str(paragraph or "").strip()
        if not normalized:
            return TextTail(text="")
        sentences: list[str] = SENTENCE_BREAK_PATTERN.split(normalized)
        if len(sentences) < 2:
            if self.cta.looks_like_cta_line(normalized):
                return TextTail(text="", tail=normalized)
            return TextTail(text=normalized)
        candidate: str = sentences[-1].strip()
        if not self.cta.looks_like_cta_line(candidate):
            return TextTail(text=normalized)
        body: str = " ".join(sentences[:-1]).strip()
        if not body:
            return TextTail(text=normalized)
        return TextTail(text=body, tail=candidate)


@dataclass
class TailScan:
    """Проход по строкам с конца: где сейчас кончается тело и что уже снято."""

    lines: Sequence[str]
    reader: TailReader
    end: int
    cta_lines: list[str] = field(default_factory=list)
    hashtag_lines: list[str] = field(default_factory=list)
    hashtags_split_from_cta: bool = False
    urls: list[str] = field(default_factory=list)
    url_changes: int = 0
    malformed: int = 0

    def take_urls(self) -> None:
        """Строки-ссылки с конца; неполная ссылка отбрасывается и считается."""
        while self.end > 0:
            candidate: str = self.lines[self.end - 1].strip()
            if candidate and not is_source_url_line(candidate):
                return
            self.end -= 1
            if not candidate:
                continue
            cleaned: SourceUrl = self.reader.source_url(candidate)
            if cleaned.url is None:
                self.malformed += 1
                continue
            self.url_changes += int(cleaned.url != candidate)
            self.urls.insert(0, cleaned.url)

    def take_hashtags(self) -> None:
        """Строки хештегов перед ссылками."""
        while self.end > 0:
            candidate: str = self.lines[self.end - 1].strip()
            if candidate and not is_hashtags_line(candidate):
                return
            self.end -= 1
            if candidate:
                self.hashtag_lines.insert(0, candidate)

    def take_cta(self) -> None:
        """Строки-призывы перед хештегами; хештеги в конце строки-призыва уходят к хештегам."""
        while self.end > 0:
            candidate: str = self.lines[self.end - 1].strip()
            if candidate:
                split: TextTail = self.reader.hashtag_tail(candidate)
                if split.tail and self.reader.is_standalone_cta_line(split.text):
                    self.hashtag_lines.insert(0, split.tail)
                    self.hashtags_split_from_cta = True
                    candidate = split.text
            if candidate and not self.reader.is_standalone_cta_line(candidate):
                return
            self.end -= 1
            if candidate:
                self.cta_lines.insert(0, candidate)

    @property
    def fragments(self) -> TailFragments:
        return TailFragments(
            cta_lines=tuple(self.cta_lines),
            hashtag_lines=tuple(self.hashtag_lines),
            hashtags_split_from_cta=self.hashtags_split_from_cta,
            source_urls=tuple(self.urls),
            url_change_count=self.url_changes,
            malformed_urls_dropped=self.malformed,
        )


@dataclass(frozen=True)
class TrailingTail:
    """Хвост в конце текста: строки с `body_end_index` и дальше — ссылки, хештеги, призывы (`split_tail` донора)."""

    body_end_index: int
    fragments: TailFragments

    @classmethod
    def of(cls, lines: Sequence[str], cta: CtaLexicon) -> TrailingTail:
        scan: TailScan = TailScan(lines=lines, reader=TailReader(cta), end=len(lines))
        scan.take_urls()
        scan.take_hashtags()
        scan.take_cta()
        return cls(body_end_index=scan.end, fragments=scan.fragments)


@dataclass(frozen=True)
class EmbeddedTail:
    """Тело без хвостов внутри абзацев (`extract_embedded` донора): текст тела и снятые фрагменты."""

    body_text: str
    fragments: TailFragments

    @classmethod
    def of(cls, text: str, cta: CtaLexicon) -> EmbeddedTail:
        reader: TailReader = TailReader(cta)
        kept: list[str] = []
        cta_lines: list[str] = []
        hashtag_lines: list[str] = []
        split_hashtags: bool = False
        urls: list[str] = []
        changes: int = 0
        malformed: int = 0
        for paragraph in split_paragraphs(text):
            url_tail: UrlTail = reader.url_tail(paragraph.strip())
            hashtags: TextTail = reader.hashtag_tail(url_tail.text)
            cta_tail: TextTail = reader.cta_tail(hashtags.text)
            split_hashtags = split_hashtags or bool(hashtags.tail and cta_tail.tail)
            if cta_tail.text:
                kept.append(cta_tail.text)
            urls.extend(url_tail.urls)
            changes += url_tail.change_count
            malformed += url_tail.malformed
            if hashtags.tail:
                hashtag_lines.append(hashtags.tail)
            if cta_tail.tail:
                cta_lines.append(cta_tail.tail)
        fragments: TailFragments = TailFragments(
            cta_lines=tuple(cta_lines),
            hashtag_lines=tuple(hashtag_lines),
            hashtags_split_from_cta=split_hashtags,
            source_urls=dedupe_nonempty(urls),
            url_change_count=changes,
            malformed_urls_dropped=malformed,
        )
        return cls(body_text=PARAGRAPH_JOINER.join(kept).strip(), fragments=fragments)
