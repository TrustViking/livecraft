"""Блоки «🌐 …:» с официальными ссылками в ответе модели: снимаются из текста, ссылки идут в общий блок описания.

Перенесено из restreamer, поведение как есть: `app\\publish\\sanitizers\\description_composer.py`
(`DescriptionComposer.extract_official_links`, `_extract_official_links_url_lines`,
`_extract_official_links_from_heading_paragraph`). Абзац с заголовком и строками-ссылками снимается целиком; заголовок
без ссылок забирает следующий абзац, если тот — одни ссылки; иначе пустой заголовок подавляется и считается.
Ссылки YouTube и неполные в блок не идут. Абзац, где после заголовка есть не-ссылка, ссылок не даёт.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.sequence import unique_in_order
from app.core.text_format import PARAGRAPH_BREAK
from app.texts.description_marks import is_official_links_heading
from app.texts.paragraphs import nonempty_lines, split_paragraphs
from app.texts.source_link import SourceLink
from app.texts.tail import is_source_url_line


def official_link_urls(lines: Sequence[str]) -> tuple[str, ...]:
    """Ссылки строк блока: все непустые строки — ссылки, иначе ни одной; YouTube и неполные пропускаются."""
    urls: list[str] = []
    for line in lines:
        normalized: str = str(line or "").strip()
        if not normalized:
            continue
        if not is_source_url_line(normalized):
            return ()
        cleaned: SourceLink = SourceLink.of(normalized)
        if cleaned.url is None or cleaned.is_youtube:
            continue
        urls.append(cleaned.url)
    return unique_in_order(urls)


@dataclass(frozen=True)
class OfficialLinksBlocks:
    """Текст без блоков официальных ссылок, был ли заголовок, ссылки блоков, сколько пустых заголовков подавлено."""

    cleaned_text: str
    heading_found: bool = False
    source_urls: tuple[str, ...] = ()
    empty_blocks_suppressed: int = 0

    @classmethod
    def of(cls, text: str) -> OfficialLinksBlocks:
        paragraphs: list[str] = split_paragraphs(text)
        kept: list[str] = []
        urls: list[str] = []
        suppressed: int = 0
        heading_found: bool = False
        index: int = 0
        while index < len(paragraphs):
            paragraph: str = str(paragraphs[index] or "").strip()
            index += 1
            if not cls._starts_with_heading(paragraph):
                kept.append(paragraph)
                continue
            heading_found = True
            own: tuple[str, ...] = official_link_urls(nonempty_lines(paragraph)[1:])
            if own:
                urls.extend(own)
                continue
            following: str = str(paragraphs[index] or "").strip() if index < len(paragraphs) else ""
            following_urls: tuple[str, ...] = official_link_urls(following.splitlines())
            if following_urls:
                urls.extend(following_urls)
                index += 1
                continue
            suppressed += 1
        return cls(
            cleaned_text=PARAGRAPH_BREAK.join(item for item in kept if item).strip(),
            heading_found=heading_found,
            source_urls=unique_in_order(urls),
            empty_blocks_suppressed=suppressed,
        )

    @classmethod
    def _starts_with_heading(cls, paragraph: str) -> bool:
        lines: list[str] = nonempty_lines(paragraph)
        return bool(lines) and is_official_links_heading(lines[0])
