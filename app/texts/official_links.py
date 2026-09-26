"""Блоки «🌐 …:» с официальными ссылками в ответе модели: снимаются из текста, ссылки идут в общий блок описания.

Абзац с заголовком и строками-ссылками снимается целиком; заголовок без ссылок забирает следующий абзац, если тот —
одни ссылки; иначе пустой заголовок подавляется и считается. Ссылки блока — правило `LinkLines`: все непустые строки
— ссылки, иначе ни одной; YouTube и неполные в блок не идут. Проход по абзацам — `HeadingScan`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.sequence import unique_in_order
from app.core.text_format import PARAGRAPH_BREAK
from app.texts.description_marks import is_official_links_heading
from app.texts.paragraphs import nonempty_lines, split_paragraphs
from app.texts.source_link import SourceLink
from app.texts.tail import is_source_url_line


@dataclass(frozen=True)
class LinkLines:
    """Строки под заголовком «🌐 …:» или абзац после него."""

    lines: tuple[str, ...]

    @property
    def urls(self) -> tuple[str, ...]:
        """Ссылки строк: все непустые строки — ссылки, иначе ни одной; YouTube и неполные пропускаются."""
        filled: tuple[str, ...] = tuple(line.strip() for line in self.lines if line.strip())
        if not all(is_source_url_line(line) for line in filled):
            return ()
        cleaned: tuple[SourceLink, ...] = tuple(SourceLink.of(line) for line in filled)
        return unique_in_order(link.url for link in cleaned if link.url is not None and not link.is_youtube)


@dataclass(frozen=True)
class OfficialLinksBlocks:
    """Текст без блоков официальных ссылок, был ли заголовок, ссылки блоков, сколько пустых заголовков подавлено."""

    cleaned_text: str
    heading_found: bool = False
    source_urls: tuple[str, ...] = ()
    empty_blocks_suppressed: int = 0

    @classmethod
    def of(cls, text: str) -> OfficialLinksBlocks:
        return HeadingScan(tuple(split_paragraphs(text))).run()


@dataclass
class HeadingScan:
    """Проход по абзацам текста: абзацы, которые остаются, ссылки блоков, подавленные заголовки."""

    paragraphs: tuple[str, ...]
    index: int = 0
    kept: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    suppressed: int = 0
    heading_found: bool = False

    def run(self) -> OfficialLinksBlocks:
        while self.index < len(self.paragraphs):
            self._take(self._next())
        return OfficialLinksBlocks(
            cleaned_text=PARAGRAPH_BREAK.join(item for item in self.kept if item).strip(),
            heading_found=self.heading_found,
            source_urls=unique_in_order(self.urls),
            empty_blocks_suppressed=self.suppressed,
        )

    def _next(self) -> str:
        paragraph: str = self.paragraphs[self.index].strip()
        self.index += 1
        return paragraph

    def _take(self, paragraph: str) -> None:
        """Абзац без заголовка остаётся; с заголовком — отдаёт свои ссылки или забирает следующий абзац ссылок."""
        lines: list[str] = nonempty_lines(paragraph)
        if not lines or not is_official_links_heading(lines[0]):
            self.kept.append(paragraph)
            return
        self.heading_found = True
        own: tuple[str, ...] = LinkLines(tuple(lines[1:])).urls
        following: tuple[str, ...] = () if own or self.index >= len(self.paragraphs) else self._following_urls
        self.urls.extend(own or following)
        if following:
            self.index += 1
        elif not own:
            self.suppressed += 1

    @property
    def _following_urls(self) -> tuple[str, ...]:
        return LinkLines(tuple(self.paragraphs[self.index].strip().splitlines())).urls
