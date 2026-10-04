"""Хвост ответа модели: призывы, хештеги и ссылки в конце описания и в конце абзацев (CLAUDE.md §14 решение 23).

- `TrailingTail.of(lines, cta)`: с конца текста по строкам снимаются строки-ссылки, затем строки хештегов, затем
  строки-призывы (хештеги в конце строки-призыва уходят к хештегам); `body_end_index` — где кончается тело.
- `EmbeddedTail.of(text, cta)`: в каждом абзаце тела с конца снимаются ссылки, хештеги и последнее предложение-призыв.
Снятое копит один накопитель — `TailCollector`; итог — значение `TailFragments`. Призыв узнаёт лексикон `CtaLexicon`
(строка-призыв, последнее предложение-призыв), ссылки и хештеги в конце абзаца — `TailParagraph`.
Свободные функции модуля — чистые преобразования строк без знания о предметных объектах.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from app.core.sequence import unique_in_order
from app.core.text_format import PARAGRAPH_BREAK, SPACE
from app.core.web_link import URL_LINE_PATTERN, WebLink
from app.texts.description_marks import ROLE_MARKERS, CtaLexicon, TextTail
from app.texts.hashtags import HASHTAG_TAIL_PATTERN, HASHTAG_WORD_PATTERN, is_hashtags_line
from app.texts.paragraphs import collapse_spaces, split_paragraphs
from app.texts.source_link import SourceLink

_MARKER_ALTERNATIVES: Final[str] = "|".join(re.escape(marker) for marker in ROLE_MARKERS)
# Два и больше маркера пункта подряд в начале строки («🔹 🔹 текст», «🔹 📌 текст») — остаётся первый.
DOUBLE_BULLET_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^(\s*)({_MARKER_ALTERNATIVES})((?:\s+(?:{_MARKER_ALTERNATIVES}))+)\s*", re.MULTILINE
)
DOUBLE_BULLET_REPLACEMENT: Final[str] = r"\1\2 "          # отступ и первый маркер, затем пробел
# Ссылки в конце абзаца: после начала, пробела или открывающей скобки — одна или несколько через пробел.
URL_TAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?is)(?:^|[\s\(\[])(https?://\S+(?:\s+https?://\S+)*)\s*$")
TAIL_GROUP: Final[int] = 1
HASHTAG_PREFIX_TRIM: Final[str] = " ,;"


def is_source_url_line(line: str) -> bool:
    """Строка — одна ссылка http(s) (обрамление скобками и знаки препинания в конце не мешают)."""
    return URL_LINE_PATTERN.fullmatch(WebLink.of(line).unwrapped.text) is not None


def clean_double_bullet_markers(text: str) -> str:
    """Сдвоенные маркеры пункта в начале строки — один, первый."""
    return DOUBLE_BULLET_PATTERN.sub(DOUBLE_BULLET_REPLACEMENT, text)


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
        """Фрагменты этого хвоста, затем `later` (у санации — сначала внутренние, потом хвост в конце): призывы
        (пробелы схлопнуты, без пустых) и ссылки — без повторов без учёта регистра, в порядке первого появления;
        флаг — «или»; счётчики — сумма."""
        cta_lines: tuple[str, ...] = tuple(collapse_spaces(line) for line in (*self.cta_lines, *later.cta_lines))
        by_case: dict[str, str] = {}
        for line in cta_lines:
            by_case.setdefault(line.lower(), line)
        return TailFragments(
            cta_lines=tuple(line for line in by_case.values() if line),
            hashtag_lines=(*self.hashtag_lines, *later.hashtag_lines),
            hashtags_split_from_cta=self.hashtags_split_from_cta or later.hashtags_split_from_cta,
            source_urls=unique_in_order((*self.source_urls, *later.source_urls)),
            url_change_count=self.url_change_count + later.url_change_count,
            malformed_urls_dropped=self.malformed_urls_dropped + later.malformed_urls_dropped,
        )

    @property
    def hashtags_line(self) -> str:
        """Хештеги всех строк одной строкой: без повторов без учёта регистра, в порядке первого появления."""
        words: tuple[str, ...] = tuple(word for line in self.hashtag_lines for word in line.split())
        by_case: dict[str, str] = {}
        for word in words:
            if HASHTAG_WORD_PATTERN.fullmatch(word):
                by_case.setdefault(word.lower(), word)
        return SPACE.join(by_case.values())


@dataclass(frozen=True)
class UrlTail:
    """Абзац без ссылок в конце: текст до них, чистые ссылки, сколько изменила чистка, сколько отброшено."""

    text: str
    urls: tuple[str, ...] = ()
    change_count: int = 0
    malformed: int = 0


@dataclass(frozen=True)
class TailParagraph:
    """Абзац без краевых пробелов и хвосты в его конце: ссылки и хештеги."""

    text: str

    @classmethod
    def of(cls, paragraph: str) -> TailParagraph:
        return cls(paragraph.strip())

    @property
    def url_tail(self) -> UrlTail:
        """Ссылки в конце абзаца: неполные отброшены, остальные почищены и без повторов."""
        match: re.Match[str] | None = URL_TAIL_PATTERN.search(self.text)
        if match is None:
            return UrlTail(text=self.text)
        taken: TailCollector = TailCollector()
        for raw in match.group(TAIL_GROUP).split():
            taken.add_url_line(raw)
        before: str = self.text[: match.start(TAIL_GROUP)].rstrip()
        return UrlTail(before, unique_in_order(taken.urls), taken.url_changes, taken.malformed)

    @property
    def hashtag_tail(self) -> TextTail:
        """Хештеги в конце абзаца; текст до них — без пробелов, запятых и `;` в конце."""
        match: re.Match[str] | None = HASHTAG_TAIL_PATTERN.search(self.text)
        candidate: str = match.group(TAIL_GROUP).strip() if match is not None else ""
        if match is None or not is_hashtags_line(candidate):
            return TextTail(self.text)
        return TextTail(text=self.text[: match.start(TAIL_GROUP)].rstrip(HASHTAG_PREFIX_TRIM), tail=candidate)


@dataclass(frozen=True)
class CtaTailLine:
    """Строка хвоста глазами призыва: строка-призыв целиком или строка-призыв с хештегами в конце."""

    line: str
    cta: CtaLexicon

    @property
    def hashtags(self) -> TextTail:
        return TailParagraph.of(self.line).hashtag_tail

    @property
    def has_split_hashtags(self) -> bool:
        """Хештеги в конце строки-призыва: они уходят к хештегам, призыв — без них."""
        return bool(self.hashtags.tail) and self.cta.is_standalone_line(self.hashtags.text)

    @property
    def is_cta(self) -> bool:
        return self.has_split_hashtags or self.cta.is_standalone_line(self.line)


@dataclass
class TailCollector:
    """Снятое с хвоста по мере прохода: призывы, хештеги, отделялись ли хештеги от призыва, ссылки, сколько ссылок
    изменила чистка и сколько неполных отброшено."""

    cta_lines: list[str] = field(default_factory=list)
    hashtag_lines: list[str] = field(default_factory=list)
    hashtags_split_from_cta: bool = False
    urls: list[str] = field(default_factory=list)
    url_changes: int = 0
    malformed: int = 0

    def add_url_line(self, line: str) -> None:
        """Строка-ссылка: неполная отбрасывается и считается, прочая чистится; изменённая чисткой — считается."""
        link: SourceLink = SourceLink.of(line)
        if link.url is None:
            self.malformed += 1
            return
        self.url_changes += int(link.url != line)
        self.urls.append(link.url)

    def add_urls(self, tail: UrlTail) -> None:
        self.urls.extend(tail.urls)
        self.url_changes += tail.change_count
        self.malformed += tail.malformed

    def add_hashtags(self, line: str) -> None:
        if line:
            self.hashtag_lines.append(line)

    def add_cta(self, line: str) -> None:
        if line:
            self.cta_lines.append(line)

    def add_cta_line(self, line: CtaTailLine) -> None:
        """Строка-призыв хвоста; хештеги в её конце — к хештегам."""
        if line.has_split_hashtags:
            self.add_hashtags(line.hashtags.tail)
            self.hashtags_split_from_cta = True
        self.add_cta(line.hashtags.text if line.has_split_hashtags else line.line)

    def fragments(self, backward: bool) -> TailFragments:
        """Итог; `backward` — снималось с конца текста: порядок строк возвращается к порядку текста."""
        step: int = -1 if backward else 1
        urls: tuple[str, ...] = tuple(self.urls[::step])
        return TailFragments(
            cta_lines=tuple(self.cta_lines[::step]),
            hashtag_lines=tuple(self.hashtag_lines[::step]),
            hashtags_split_from_cta=self.hashtags_split_from_cta,
            source_urls=urls if backward else unique_in_order(urls),
            url_change_count=self.url_changes,
            malformed_urls_dropped=self.malformed,
        )


@dataclass
class BackwardLines:
    """Строки текста с конца: `end` — где сейчас кончается тело."""

    lines: Sequence[str]
    end: int

    def take_while(self, accepts: Callable[[str], bool]) -> Iterable[str]:
        """Строки с конца, пока подходят (пустые между ними — тоже снимаются); отдаёт непустые без краёв."""
        while self.end > 0:
            candidate: str = self.lines[self.end - 1].strip()
            if candidate and not accepts(candidate):
                return
            self.end -= 1
            if candidate:
                yield candidate


@dataclass(frozen=True)
class TrailingTail:
    """Хвост в конце текста: строки с `body_end_index` и дальше — ссылки, хештеги, призывы."""

    body_end_index: int
    fragments: TailFragments

    @classmethod
    def of(cls, lines: Sequence[str], cta: CtaLexicon) -> TrailingTail:
        rest: BackwardLines = BackwardLines(lines=lines, end=len(lines))
        collector: TailCollector = TailCollector()
        for line in rest.take_while(is_source_url_line):
            collector.add_url_line(line)
        for line in rest.take_while(is_hashtags_line):
            collector.add_hashtags(line)
        for line in rest.take_while(lambda candidate: CtaTailLine(candidate, cta).is_cta):
            collector.add_cta_line(CtaTailLine(line, cta))
        return cls(body_end_index=rest.end, fragments=collector.fragments(backward=True))


@dataclass(frozen=True)
class EmbeddedTail:
    """Тело без хвостов внутри абзацев: текст тела и снятые фрагменты."""

    body_text: str
    fragments: TailFragments

    @classmethod
    def of(cls, text: str, cta: CtaLexicon) -> EmbeddedTail:
        collector: TailCollector = TailCollector()
        kept: list[str] = []
        for paragraph in split_paragraphs(text):
            url_tail: UrlTail = TailParagraph.of(paragraph).url_tail
            hashtags: TextTail = TailParagraph.of(url_tail.text).hashtag_tail
            cta_tail: TextTail = cta.split_final_sentence(hashtags.text)
            collector.hashtags_split_from_cta |= bool(hashtags.tail and cta_tail.tail)
            if cta_tail.text:
                kept.append(cta_tail.text)
            collector.add_urls(url_tail)
            collector.add_hashtags(hashtags.tail)
            collector.add_cta(cta_tail.tail)
        return cls(body_text=PARAGRAPH_BREAK.join(kept).strip(), fragments=collector.fragments(backward=False))
