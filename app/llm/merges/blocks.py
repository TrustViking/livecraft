"""Описание merge по блокам: тезис, вводная строка и пункты, заголовок ссылок и ссылки, призыв.

Перенесено из restreamer, поведение как есть (CLAUDE.md §14 решение 23):
- разбор на блоки — `quality_service_lines.py::extract_merge_blocks` (`MergeBlocks`);
- сборка блоков обратно в текст — `quality_normalizer.py::_render_blocks`;
- смесь алфавитов в названии, тезисе и пунктах — `quality_diagnostics.py::_detect_script_mix_suspects`
  (+ `_normalize_script_mix_probe_text`, `_is_allowed_latin_token_in_cyrillic_text`, `_is_suspicious_script_token`);
  допустимые латинские слова — ресурс `merge_allowed_latin_tokens.txt` без правки значений (читает `QualityRules`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.texts.description_marks import (
    URL_LINE_PATTERN,
    URL_PATTERN,
    CtaLexicon,
    is_bullet_line,
    is_official_links_heading,
)

PARAGRAPH_BREAK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
PARAGRAPH_JOINER: Final[str] = "\n\n"
LINE_JOINER: Final[str] = "\n"
URL_PATH_SLASHES: Final[int] = 3                  # «https://site.org/» — у ссылки на корень сайта слэш снимается

SCRIPT_MIX_LANGUAGES: Final[frozenset[str]] = frozenset({"uk", "en", "ru"})
CYRILLIC_TEXT_LANGUAGES: Final[frozenset[str]] = frozenset({"uk", "ru"})
SCRIPT_MIX_MAX_SUSPECTS: Final[int] = 5
# В английском тексте подозрительно слово хотя бы с двумя кириллическими буквами; в тексте кириллицей —
# латинское слово в нижнем регистре не короче четырёх латинских букв, если это не аббревиатура, не слово
# с заглавной буквы и не допустимое слово.
EN_MIN_CYRILLIC_CHARS: Final[int] = 2
CYRILLIC_TEXT_MIN_LATIN_CHARS: Final[int] = 4
SCRIPT_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ][A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9'_-]*", flags=re.UNICODE
)
CYRILLIC_PATTERN: Final[re.Pattern[str]] = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]", re.UNICODE)
LATIN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]", re.UNICODE)
NOT_LATIN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z]")
ABBREVIATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Z0-9]{2,6}")
CAPITALIZED_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Z][a-z]{1,14}")
HASHTAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:^|\s)(#[^\s#]+)")
EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\S+@\S+\.\S+\b", re.IGNORECASE)
BARE_DOMAIN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z]{2,}){1,3}\b", flags=re.IGNORECASE
)


def _collapse(text: str) -> str:
    return WHITESPACE_RUN_PATTERN.sub(" ", text).strip()


def _lines(paragraph: str) -> list[str]:
    return [line.strip() for line in paragraph.split(LINE_JOINER) if line.strip()]


def _script_mix_probe_text(text: str) -> str:
    """Текст без ссылок, почты, хештегов и доменов — в них смесь алфавитов законна."""
    probe: str = URL_PATTERN.sub(" ", str(text or ""))
    probe = EMAIL_PATTERN.sub(" ", probe)
    probe = HASHTAG_PATTERN.sub(" ", probe)
    return BARE_DOMAIN_PATTERN.sub(" ", probe)


def _is_allowed_latin_token(token: str, allowed_latin_tokens: frozenset[str]) -> bool:
    normalized_token: str = str(token or "").strip()
    if not normalized_token:
        return True
    if normalized_token.lower() in allowed_latin_tokens:
        return True
    return bool(ABBREVIATION_PATTERN.fullmatch(normalized_token) or CAPITALIZED_WORD_PATTERN.fullmatch(normalized_token))


def _is_suspicious_token(token: str, language: str, allowed_latin_tokens: frozenset[str]) -> bool:
    normalized_token: str = str(token or "").strip()
    if not normalized_token:
        return False
    has_cyrillic: bool = bool(CYRILLIC_PATTERN.search(normalized_token))
    has_latin: bool = bool(LATIN_PATTERN.search(normalized_token))
    if has_cyrillic and has_latin:
        return True
    if language == "en":
        return has_cyrillic and len(CYRILLIC_PATTERN.findall(normalized_token)) >= EN_MIN_CYRILLIC_CHARS
    if language not in CYRILLIC_TEXT_LANGUAGES or not has_latin:
        return False
    if len(NOT_LATIN_PATTERN.sub("", normalized_token)) < CYRILLIC_TEXT_MIN_LATIN_CHARS:
        return False
    if _is_allowed_latin_token(normalized_token, allowed_latin_tokens):
        return False
    return normalized_token == normalized_token.lower()


@dataclass(frozen=True)
class DescriptionBlocks:
    """Блоки описания. `theses_lines` — вводная строка (если есть) и пункты; `lead_in` — вводная строка."""

    hook: str
    lead_in: str
    theses_lines: tuple[str, ...]
    links_heading: str
    links_urls: tuple[str, ...]
    cta: str

    @classmethod
    def of(cls, text: str, cta: CtaLexicon) -> DescriptionBlocks:
        """Разбор текста на блоки по абзацам — правило донора без изменений."""
        builder: _BlocksBuilder = _BlocksBuilder()
        paragraphs: list[str] = [part.strip() for part in PARAGRAPH_BREAK_PATTERN.split(text) if part.strip()]
        for paragraph in paragraphs:
            builder.take(paragraph, cta)
        return builder.finish(paragraphs)

    def render(self) -> str:
        """Текст из блоков: тезис, пункты, заголовок и ссылки, призыв — абзацами через пустую строку."""
        paragraphs: list[str] = []
        if self.hook:
            paragraphs.append(_collapse(self.hook))
        if self.theses_lines:
            paragraphs.append(LINE_JOINER.join(line.strip() for line in self.theses_lines if line.strip()).strip())
        if self.links_heading:
            paragraphs.append(LINE_JOINER.join([self.links_heading.strip(), *self._rendered_urls()]).strip())
        if self.cta:
            paragraphs.append(_collapse(self.cta))
        return PARAGRAPH_JOINER.join(paragraph for paragraph in paragraphs if paragraph).strip()

    def _rendered_urls(self) -> list[str]:
        urls: list[str] = []
        for item in self.links_urls:
            url: str = item.strip()
            if not url:
                continue
            if url.endswith("/") and url.count("/") == URL_PATH_SLASHES:
                url = url.rstrip("/")
            urls.append(url)
        return urls

    @property
    def is_single_echo_cta(self) -> bool:
        """Призыв повторяет тезис, а пунктов и заголовка ссылок нет."""
        return bool(self.hook) and self.hook == self.cta and not self.theses_lines and not self.links_heading

    @property
    def is_single_echo_thesis(self) -> bool:
        """Единственная строка пунктов повторяет тезис, а заголовка ссылок нет."""
        return (
            bool(self.hook)
            and len(self.theses_lines) == 1
            and self.theses_lines[0] == self.hook
            and not self.links_heading
        )

    def script_mix_suspects(self, title: str, language: str, allowed_latin_tokens: frozenset[str]) -> tuple[str, ...]:
        """До пяти слов со смесью алфавитов в названии, тезисе и пунктах (только для uk, en, ru)."""
        if language not in SCRIPT_MIX_LANGUAGES:
            return ()
        suspects: list[str] = []
        for raw_text in (title, self.hook, *self.theses_lines):
            for token in SCRIPT_TOKEN_PATTERN.findall(_script_mix_probe_text(raw_text)):
                cleaned_token: str = str(token or "").strip()
                if not cleaned_token or not _is_suspicious_token(cleaned_token, language, allowed_latin_tokens):
                    continue
                if cleaned_token not in suspects:
                    suspects.append(cleaned_token)
                if len(suspects) >= SCRIPT_MIX_MAX_SUSPECTS:
                    return tuple(suspects)
        return tuple(suspects)


class _BlocksBuilder:
    """Изменяемое состояние разбора по абзацам (порядок и правила донора); наружу — только `DescriptionBlocks`."""

    def __init__(self) -> None:
        self.hook: str = ""
        self.lead_in: str = ""
        self.theses_lines: list[str] = []
        self.links_heading: str = ""
        self.links_urls: list[str] = []
        self.cta: str = ""

    def take(self, paragraph: str, cta: CtaLexicon) -> None:
        lines: list[str] = _lines(paragraph)
        if not lines:
            return
        if is_official_links_heading(lines[0]):
            self._take_links(lines)
            return
        if any(is_bullet_line(line) for line in lines):
            self._take_bullets(lines)
            return
        if cta.looks_like_cta_paragraph(paragraph):
            self.cta = _collapse(paragraph)
            return
        if not self.hook:
            self.hook = " ".join(lines).strip()
        elif not self.cta:
            self.cta = _collapse(paragraph)

    def _take_links(self, lines: list[str]) -> None:
        """Заголовок ссылок, за ним строки-ссылки; прочие строки после ссылок — призыв, если его ещё нет."""
        self.links_heading = lines[0]
        trailing_after_urls: list[str] = []
        for line in lines[1:]:
            if URL_LINE_PATTERN.match(line):
                self.links_urls.append(line)
            else:
                trailing_after_urls.append(line)
        if trailing_after_urls and not self.cta:
            self.cta = _collapse(" ".join(trailing_after_urls))

    def _take_bullets(self, lines: list[str]) -> None:
        first_bullet: int = next(index for index, line in enumerate(lines) if is_bullet_line(line))
        bullet_end: int = first_bullet
        while bullet_end < len(lines) and is_bullet_line(lines[bullet_end]):
            bullet_end += 1
        bullets: list[str] = lines[first_bullet:bullet_end]
        if first_bullet > 0:
            self._take_lead_in_and_bullets(lines, first_bullet, bullets)
        else:
            self.theses_lines.extend(bullets)
        trailing_lines: list[str] = lines[bullet_end:]
        if not trailing_lines:
            return
        if is_official_links_heading(trailing_lines[0]):
            self._take_links(trailing_lines)
        elif not self.cta:
            self.cta = _collapse(" ".join(trailing_lines))

    def _take_lead_in_and_bullets(self, lines: list[str], first_bullet: int, bullets: list[str]) -> None:
        """Строка перед первым пунктом — вводная (если пунктов ещё не было); строки до неё — тезис."""
        if not self.theses_lines:
            self.lead_in = lines[first_bullet - 1]
            self.theses_lines = [self.lead_in, *bullets]
        else:
            self.theses_lines.extend(bullets)
        if not self.hook:
            self.hook = " ".join(lines[: first_bullet - 1]).strip()

    def finish(self, paragraphs: list[str]) -> DescriptionBlocks:
        """Пунктов не нашлось — строки второго абзаца считаются пунктами, первая из них — вводной; тезиса нет —
        им становится первый абзац."""
        if not self.theses_lines:
            for paragraph in paragraphs[1:2]:
                lines: list[str] = _lines(paragraph)
                if lines:
                    self.theses_lines = lines
                    self.lead_in = lines[0]
                    break
        if not self.hook and paragraphs:
            self.hook = _collapse(paragraphs[0])
        return DescriptionBlocks(
            hook=self.hook,
            lead_in=self.lead_in,
            theses_lines=tuple(self.theses_lines),
            links_heading=self.links_heading,
            links_urls=tuple(self.links_urls),
            cta=self.cta,
        )
