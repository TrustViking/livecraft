"""Описание из ответа модели и его правила, не зависящие от источников (CLAUDE.md §14 решение 23).

Перенесено из restreamer, поведение как есть:
- повтор абзацев — `core\\text_utils.py::has_duplicate_paragraphs`;
- эхо тезиса и его починка — `merge_validation_helpers.py::has_hook_echo_in_body`, `attempt_hook_echo_repair`
  (+ `_split_hook_trailing_bullet`, `_line_starts_with_bullet`, `_semantic_token_set`);
- призыв в первой строке — `merge_parser.py::_description_has_raw_opener_cta`;
- снятие служебных строк «title:», «description:», «source(s):» — `merge_parser.py::strip_meta_lines`;
- починка смешанного алфавита — `script_mix_repair.py` (`repair_script_mix_homoglyphs`, `_repair_token`);
- нормализация качества — `quality_normalizer.py::normalize_merge_description` (объекты шагов — `quality.py`);
- перегруженные пункты — `quality_diagnostics.py::count_overloaded_bullets`;
- заголовок повестки и выгрузка по источникам — `merge_text_utils.py` (`_contains_agenda_heading`,
  `_looks_like_per_source_dump`);
- счёт ссылок в ответе — `merge_links.py::_count_output_official_links`, `merge_youtube.py::_count_youtube_urls_in_text`;
- правила проверки покрытия — `merge_validation.py` (`_count_emoji`, `_has_adjacent_duplicate_lines`,
  `_has_cta_in_opening_lines_before_hook_or_bullet`, призыв и служебная строка в тезисе, общее начало абзацев из
  `_validate_coverage_preserving_merge_or_raise`); снятие неструктурных эмодзи —
  `merge_formatting.py::_strip_non_structural_emoji_from_line` и `_strip_non_structural_emoji_from_description`.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Final
from urllib.parse import SplitResult, urlsplit

from app.llm.merges.agenda import AgendaLexicon
from app.llm.merges.blocks import DescriptionBlocks
from app.llm.merges.quality import (
    BulletNormalization,
    CompactTrim,
    QualityDiagnostics,
    QualityFindings,
    QualityNormalization,
    QualityRequest,
    QualityRules,
    ServiceLineFix,
)
from app.core.sheet_text import normalize_youtube_link
from app.core.url_text import canonical_link_key, is_youtube_host, normalize_link_candidate, split_url
from app.llm.merges.rules import (
    ADJACENT_LINE_JACCARD,
    ADJACENT_LINE_MIN_CHARS,
    ADJACENT_LINE_MIN_TOKENS,
    ADJACENT_LINE_PREFIX_RATIO,
    BULLET_ABSOLUTE_MAX_CHAR_LIMIT,
    BULLET_OVERLOAD_CHAR_LIMIT,
    BULLET_OVERLOAD_NAME_LIMIT,
    OPENING_LINES,
    OPENING_PARAGRAPHS,
    PARAGRAPH_PREFIX_MIN_CHARS,
    PARAGRAPH_PREFIX_RATIO,
)
from app.observability.logging_setup import get_logger
from app.texts.analysis_text import is_service_tail_paragraph
from app.texts.description_marks import (
    ALLOWED_BULLET_MARKERS,
    BULLET_PREFIXES,
    SEMANTIC_TOKEN_PATTERN,
    URL_PATTERN,
    CtaLexicon,
    bullet_marker_for_line,
)
from app.texts.paragraphs import has_duplicate_paragraphs, normalize_newlines, split_paragraphs

if TYPE_CHECKING:
    from app.llm.merges.hook import BadHookLexicon

PARAGRAPH_JOINER: Final[str] = "\n\n"
LINE_JOINER: Final[str] = "\n"
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
META_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?i)^\s*(?:title|description|sources?)\s*:")

# Эхо тезиса (пороги донора): оба текста не короче 40 знаков; общее начало больше половины; последняя фраза
# тезиса (не короче 30 знаков) и первая строка тела совпадают по смысловым словам не меньше чем на 55 %;
# весь тезис и первая строка тела — не меньше чем на 60 %.
ECHO_MIN_CHARS: Final[int] = 40
ECHO_PREFIX_RATIO: Final[float] = 0.50
ECHO_SENTENCE_MIN_CHARS: Final[int] = 30
ECHO_SENTENCE_JACCARD: Final[float] = 0.55
ECHO_JACCARD: Final[float] = 0.60
HOOK_SENTENCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[.!?]\s+|\n")
# Пункт, сросшийся с тезисом в одной строке: конец фразы не ближе 40 знаков от начала строки.
FUSED_BULLET_MIN_POSITION: Final[int] = 40
SENTENCE_ENDINGS: Final[tuple[str, ...]] = (". ", "! ", "? ")

HOMOGLYPH_LANGUAGES: Final[tuple[str, ...]] = ("uk", "ru")
# Латинские буквы, у которых в обычных шрифтах есть неотличимый кириллический двойник. Остальные латинские буквы
# (b, d, f, g, …) двойника не имеют: слово с такой буквой — настоящая смесь алфавитов, её не трогаем.
SAFE_HOMOGLYPHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "a": "а", "c": "с", "e": "е", "k": "к", "o": "о", "p": "р", "x": "х", "y": "у",
        "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
        "X": "Х", "Y": "У",
    }
)
# Латинская «i»: в украинском — «і», в русском — «и».
LANGUAGE_HOMOGLYPHS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        "uk": MappingProxyType({"i": "і", "I": "І"}),
        "ru": MappingProxyType({"i": "и", "I": "И"}),
    }
)
CYRILLIC_CHAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")
LATIN_CHAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]")
# Слово — буквы латиницы и кириллицы с апострофами (ʼ и '); цифры, знаки и пробелы — границы слова.
WORD_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile("[A-Za-zА-Яа-яЁёІіЇїЄєҐґ\u02bc']+")
TOKENS_JOINER: Final[str] = ","
LOG_NONE: Final[str] = "none"

LOGGER: logging.Logger = get_logger("llm")
# Имя собственное для перегруженного пункта: от двух до четырёх слов подряд с заглавной буквы.
PROPER_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ'`-]{1,25}(?:\s+[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ'`-]{1,25}){1,3}\b", re.UNICODE
)
# Выгрузка по источникам: строки «Source 1:», «Video 2)» — хотя бы две; или в тексте есть «source 1» и «source 2».
SOURCE_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*(?:source|video)\s*\d+[:.)-]?", flags=re.IGNORECASE)
SOURCE_LINE_MIN_HITS: Final[int] = 2
SOURCE_DUMP_PAIRS: Final[tuple[tuple[str, str], ...]] = (("source 1", "source 2"), ("video 1", "video 2"))
# Эмодзи для счёта и снятия (`merge_validation.py::_count_emoji`, `merge_formatting.py::_EMOJI_PATTERN`).
EMOJI_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", flags=re.UNICODE)
SPACE_BEFORE_PUNCTUATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+([,.;:!?])")
REPEATED_SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s{2,}")


def _line_starts_with_bullet(line_text: str) -> bool:
    stripped_line: str = line_text.strip()
    return any(stripped_line.startswith(marker) for marker in ALLOWED_BULLET_MARKERS)


def _semantic_token_set(text: str) -> set[str]:
    return {token.lower() for token in SEMANTIC_TOKEN_PATTERN.findall(str(text or "")) if token.strip()}


def _without_emoji_in_line(line: str) -> tuple[str, bool]:
    """Строка без эмодзи вне маркера пункта в её начале и без пробелов перед знаками препинания; изменилась ли она."""
    indent: str = line[: len(line) - len(line.lstrip())]
    content: str = line[len(indent) :]
    protected_prefix: str = ""
    for marker in ALLOWED_BULLET_MARKERS:
        if content.startswith(f"{marker} "):
            protected_prefix = f"{indent}{marker} "
            content = content[len(marker) + 1 :]
            break
    tail: str = EMOJI_PATTERN.sub("", content)
    tail = SPACE_BEFORE_PUNCTUATION_PATTERN.sub(r"\1", tail)
    tail = REPEATED_SPACE_PATTERN.sub(" ", tail).strip()
    sanitized: str = f"{protected_prefix}{tail}".strip()
    return sanitized, sanitized != line.strip()


def _jaccard(first: set[str], second: set[str]) -> float | None:
    union_size: int = len(first | second)
    if union_size == 0:
        return None
    return len(first & second) / union_size


def _common_prefix_ratio(first_text: str, second_text: str) -> float:
    shorter_length: int = min(len(first_text), len(second_text))
    if shorter_length <= 0:
        return 0.0
    common_prefix_length: int = 0
    for first_char, second_char in zip(first_text, second_text):
        if first_char != second_char:
            break
        common_prefix_length += 1
    return common_prefix_length / shorter_length


@dataclass(frozen=True)
class HookParagraph:
    """Первый абзац (тезис), в который модель могла вклеить первый пункт списка."""

    text: str

    def split_trailing_bullet(self) -> tuple[str, str | None]:
        """Тезис без вклеенного пункта и сам пункт; пункта нет — тезис как есть и None.

        Несколько строк: пункт — первая строка после первой, начинающаяся маркером. Одна строка: самый ранний
        маркер после начала строки, перед ним — только пробелы после последнего конца фразы дальше 40-го знака.
        """
        hook_lines: list[str] = self.text.split(LINE_JOINER)
        if len(hook_lines) > 1:
            return self._split_multiline(hook_lines)
        return self._split_single_line(self.text.strip())

    def _split_multiline(self, hook_lines: list[str]) -> tuple[str, str | None]:
        for line_index in range(1, len(hook_lines)):
            if _line_starts_with_bullet(hook_lines[line_index]):
                return LINE_JOINER.join(hook_lines[:line_index]).strip(), hook_lines[line_index].strip()
        return self.text, None

    def _split_single_line(self, single_line: str) -> tuple[str, str | None]:
        positions: list[int] = [
            position for position in (single_line.find(marker) for marker in ALLOWED_BULLET_MARKERS) if position > 0
        ]
        if not positions:
            return self.text, None
        bullet_position: int = min(positions)
        cut_position: int | None = self._sentence_cut(single_line, bullet_position)
        if cut_position is None:
            return self.text, None
        extracted_bullet: str = single_line[bullet_position:].strip()
        if not _line_starts_with_bullet(extracted_bullet):
            return self.text, None
        return single_line[:cut_position].strip(), extracted_bullet

    @staticmethod
    def _sentence_cut(single_line: str, bullet_position: int) -> int | None:
        """Позиция сразу за знаком конца фразы, после которого до маркера только пробелы."""
        prefix_text: str = single_line[:bullet_position]
        best_cut_position: int | None = None
        for ending in SENTENCE_ENDINGS:
            candidate_position: int = prefix_text.rfind(ending)
            if candidate_position < FUSED_BULLET_MIN_POSITION:
                continue
            if single_line[candidate_position + len(ending) : bullet_position].strip() != "":
                continue
            cut_after: int = candidate_position + 1
            if best_cut_position is None or cut_after > best_cut_position:
                best_cut_position = cut_after
        return best_cut_position


@dataclass(frozen=True)
class HomoglyphMap:
    """Латинские двойники кириллических букв для языка с кириллицей (только uk и ru)."""

    language: str
    mapping: Mapping[str, str] = field(repr=False)

    @classmethod
    def of(cls, language: str) -> HomoglyphMap | None:
        if language not in HOMOGLYPH_LANGUAGES:
            return None
        return cls(language=language, mapping=MappingProxyType({**SAFE_HOMOGLYPHS, **LANGUAGE_HOMOGLYPHS[language]}))

    def repair_token(self, token: str) -> str | None:
        """Слово кириллицей с латинскими двойниками — исправленное слово; иначе None.

        Чинится только настоящая смесь, где кириллицы больше, чем латиницы, и у каждой латинской буквы есть
        двойник.
        """
        cyrillic_chars: list[str] = CYRILLIC_CHAR_PATTERN.findall(token)
        latin_chars: list[str] = LATIN_CHAR_PATTERN.findall(token)
        if not cyrillic_chars or not latin_chars:
            return None
        if len(cyrillic_chars) <= len(latin_chars):
            return None
        if any(char not in self.mapping for char in latin_chars):
            return None
        repaired: str = "".join(self.mapping.get(char, char) for char in token)
        return None if repaired == token else repaired


@dataclass(frozen=True)
class HomoglyphRepair:
    """Итог починки алфавита: описание после неё и исправленные слова (до и после) по порядку."""

    description: MergedDescription
    tokens_before: tuple[str, ...]
    tokens_after: tuple[str, ...]

    @property
    def tokens_repaired(self) -> int:
        return len(self.tokens_before)

    @property
    def log_line(self) -> str:
        return (
            f"tokens_repaired={self.tokens_repaired} "
            f"before_tokens={TOKENS_JOINER.join(self.tokens_before) or LOG_NONE} "
            f"after_tokens={TOKENS_JOINER.join(self.tokens_after) or LOG_NONE}"
        )


@dataclass(frozen=True)
class MergedDescription:
    """Текст описания из ответа модели. В `repr` текст не печатается."""

    text: str = field(repr=False)

    @property
    def paragraphs(self) -> list[str]:
        return split_paragraphs(self.text)

    @property
    def has_duplicate_paragraphs(self) -> bool:
        return has_duplicate_paragraphs(self.text)

    @property
    def has_hook_echo_in_body(self) -> bool:
        """Тело (первая строка второго абзаца) повторяет тезис первого абзаца."""
        paragraphs: list[str] = self.paragraphs
        if len(paragraphs) < 2:
            return False
        hook_text: str = paragraphs[0].strip()
        body_opener_line: str = paragraphs[1].split(LINE_JOINER)[0].strip()
        if len(hook_text) < ECHO_MIN_CHARS or len(body_opener_line) < ECHO_MIN_CHARS:
            return False
        if _common_prefix_ratio(hook_text, body_opener_line) > ECHO_PREFIX_RATIO:
            return True
        hook_tokens: set[str] = _semantic_token_set(hook_text)
        body_tokens: set[str] = _semantic_token_set(body_opener_line)
        similarity: float | None = _jaccard(hook_tokens, body_tokens)
        if similarity is None:
            return False
        if self._last_hook_sentence_echoes(hook_text, body_opener_line, body_tokens):
            return True
        return similarity >= ECHO_JACCARD

    @staticmethod
    def _last_hook_sentence_echoes(hook_text: str, body_opener_line: str, body_tokens: set[str]) -> bool:
        sentences: list[str] = [part.strip() for part in HOOK_SENTENCE_PATTERN.split(hook_text) if part.strip()]
        if not sentences:
            return False
        last_sentence: str = sentences[-1]
        if len(last_sentence) < ECHO_SENTENCE_MIN_CHARS or len(body_opener_line) < ECHO_SENTENCE_MIN_CHARS:
            return False
        similarity: float | None = _jaccard(_semantic_token_set(last_sentence), body_tokens)
        return similarity is not None and similarity >= ECHO_SENTENCE_JACCARD

    def hook_echo_repaired(self) -> MergedDescription | None:
        """Описание без эха тезиса во втором абзаце; починить нельзя или эха нет — None.

        Первый проход срезает повтор тезиса до первого пункта второго абзаца (нет пункта — берёт третий абзац,
        если он начинается пунктом). Не помогло — второй проход выносит пункт, вклеенный в тезис, в тело.
        """
        if not self.has_hook_echo_in_body:
            return None
        paragraphs: list[str] = self.paragraphs
        hook, echo, remaining = paragraphs[0], paragraphs[1], paragraphs[2:]
        first_pass: MergedDescription | None = self._without_echo_prefix(hook, echo, remaining)
        if first_pass is None:
            return None
        if not first_pass.has_hook_echo_in_body:
            return first_pass
        return first_pass._with_fused_bullet_moved()

    @staticmethod
    def _without_echo_prefix(hook: str, echo: str, remaining: list[str]) -> MergedDescription | None:
        echo_lines: list[str] = echo.split(LINE_JOINER)
        first_bullet_index: int | None = next(
            (index for index, line in enumerate(echo_lines) if _line_starts_with_bullet(line)), None
        )
        if first_bullet_index is not None:
            trimmed_echo: str = LINE_JOINER.join(echo_lines[first_bullet_index:])
            return MergedDescription(PARAGRAPH_JOINER.join([hook, trimmed_echo, *remaining]))
        if not remaining or not _line_starts_with_bullet(remaining[0]):
            return None
        return MergedDescription(PARAGRAPH_JOINER.join([hook, *remaining]))

    def _with_fused_bullet_moved(self) -> MergedDescription | None:
        paragraphs: list[str] = self.paragraphs
        if len(paragraphs) < 2:
            return None
        body_block: str = paragraphs[1]
        clean_hook, extracted_bullet = HookParagraph(paragraphs[0]).split_trailing_bullet()
        if extracted_bullet is None:
            return None
        body_bullets: list[str] = [line.strip() for line in body_block.split(LINE_JOINER) if _line_starts_with_bullet(line)]
        is_same_bullet: bool = bool(body_bullets) and (
            WHITESPACE_RUN_PATTERN.sub(" ", body_bullets[0])
            == WHITESPACE_RUN_PATTERN.sub(" ", extracted_bullet.strip())
        )
        new_body: str = body_block if is_same_bullet else extracted_bullet + LINE_JOINER + body_block
        repaired: MergedDescription = MergedDescription(PARAGRAPH_JOINER.join([clean_hook, new_body, *paragraphs[2:]]))
        return None if repaired.has_hook_echo_in_body else repaired

    def opens_with_cta(self, lexicon: CtaLexicon) -> bool:
        """Первая непустая строка первого абзаца начинается с призыва."""
        paragraphs: list[str] = self.paragraphs
        if not paragraphs:
            return False
        for raw_line in paragraphs[0].split(LINE_JOINER):
            line: str = str(raw_line or "").strip()
            if line:
                return lexicon.starts_with_prefix(line)
        return False

    def without_meta_lines(self) -> MergedDescription:
        """Без строк-заголовков «title:», «description:», «source(s):»; концы строк и края текста без пробелов."""
        kept_lines: list[str] = [
            line.rstrip() for line in normalize_newlines(self.text).split(LINE_JOINER) if not META_LINE_PATTERN.match(line.strip())
        ]
        return MergedDescription(LINE_JOINER.join(kept_lines).strip())

    def with_homoglyphs_repaired(self, language: str) -> HomoglyphRepair:
        """Слова кириллицей с латинскими двойниками букв исправлены (только uk и ru; прочие языки — как есть)."""
        homoglyphs: HomoglyphMap | None = HomoglyphMap.of(language)
        if homoglyphs is None or not self.text:
            return HomoglyphRepair(description=self, tokens_before=(), tokens_after=())
        before: list[str] = []
        after: list[str] = []

        def replace(match: re.Match[str]) -> str:
            token: str = match.group(0)
            repaired_token: str | None = homoglyphs.repair_token(token)
            if repaired_token is None:
                return token
            before.append(token)
            after.append(repaired_token)
            return repaired_token

        repaired_text: str = WORD_TOKEN_PATTERN.sub(replace, self.text)
        return HomoglyphRepair(
            description=MergedDescription(repaired_text), tokens_before=tuple(before), tokens_after=tuple(after)
        )

    @property
    def _trimmed_lines_text(self) -> str:
        """Переводы строки — `\\n`, концы строк и края текста без пробелов."""
        return LINE_JOINER.join(line.rstrip() for line in normalize_newlines(self.text).split(LINE_JOINER)).strip()

    def quality_normalized(self, request: QualityRequest, rules: QualityRules) -> QualityNormalization:
        """Описание в виде донора и диагностика итогового текста.

        Шаги донора по порядку: разбор на блоки → снятие повторов тезиса → служебные строки не того языка —
        канонические → маркеры пунктов → лишние пункты компактного контракта → сборка текста. Любая правка
        текста — `block_spacing_ok=False` (историческое имя донора).
        """
        source_text: str = self._trimmed_lines_text
        if not source_text:
            empty: QualityFindings = QualityFindings("", request, True, False, False, BulletNormalization(lines=()))
            return QualityNormalization(MergedDescription(""), QualityDiagnostics.of(empty, rules))
        fix: ServiceLineFix = ServiceLineFix.of(DescriptionBlocks.of(source_text, rules.cta), request.language, rules)
        bullets: BulletNormalization = BulletNormalization.of(fix.blocks.theses_lines)
        trim: CompactTrim = CompactTrim.of(bullets.lines, request.source_count)
        if trim.applied:
            LOGGER.info("merge_compact_bullet_trimmed %s", trim.log_line)
        rendered: str = replace(fix.blocks, theses_lines=trim.lines).render()
        spacing_ok: bool = rendered == source_text
        findings: QualityFindings = QualityFindings(
            rendered, request, spacing_ok, fix.wrong_language_heading_detected, fix.official_links_heading_mismatch, bullets
        )
        return QualityNormalization(MergedDescription(rendered), QualityDiagnostics.of(findings, rules))

    @property
    def overloaded_bullet_count(self) -> int:
        """Пункты с маркером-эмодзи длиннее 500 знаков или длиннее 280 знаков с тремя и больше именами."""
        count: int = 0
        for line in normalize_newlines(self.text).split(LINE_JOINER):
            stripped: str = line.strip()
            if not stripped.startswith(BULLET_PREFIXES):
                continue
            if len(stripped) > BULLET_ABSOLUTE_MAX_CHAR_LIMIT:
                count += 1
            elif len(stripped) > BULLET_OVERLOAD_CHAR_LIMIT:
                count += int(len(PROPER_NAME_PATTERN.findall(stripped)) >= BULLET_OVERLOAD_NAME_LIMIT)
        return count

    def contains_agenda_heading(self, lexicon: AgendaLexicon) -> bool:
        """В описании есть строка-заголовок повестки («Что в этом стриме:»)."""
        return lexicon.matches(self.text)

    @property
    def looks_like_per_source_dump(self) -> bool:
        """Описание пересказывает источники по очереди («Source 1: …», «Video 2: …»), а не сводит их."""
        lines: list[str] = [line.strip() for line in normalize_newlines(self.text).split(LINE_JOINER) if line.strip()]
        if sum(1 for line in lines if SOURCE_LINE_PATTERN.match(line)) >= SOURCE_LINE_MIN_HITS:
            return True
        lowered_text: str = str(self.text or "").lower()
        return any(first in lowered_text and second in lowered_text for first, second in SOURCE_DUMP_PAIRS)

    @property
    def official_link_count(self) -> int:
        """Разных ссылок (не YouTube) в тексте — по ключу повтора после снятия меток слежения."""
        keys: set[str] = set()
        for match in URL_PATTERN.finditer(str(self.text or "")):
            url: str | None = normalize_link_candidate(match.group(0))
            if url is None or is_youtube_host(urlsplit(url).netloc):
                continue
            keys.add(canonical_link_key(url))
        return len(keys)

    @property
    def youtube_link_count(self) -> int:
        """Разных видео YouTube в тексте — по короткой ссылке `https://youtu.be/<id>`."""
        links: set[str] = set()
        for match in URL_PATTERN.finditer(str(self.text or "")):
            raw_url: str = match.group(0).strip()
            parts: SplitResult | None = split_url(raw_url)
            if parts is None or not is_youtube_host(parts.netloc):
                continue
            link: str | None = normalize_youtube_link(raw_url)
            if link is not None:
                links.add(link)
        return len(links)

    @property
    def emoji_count(self) -> int:
        """Эмодзи вне маркеров пунктов: все эмодзи минус все вхождения маркеров (как у донора — где бы они ни стояли)."""
        text: str = str(self.text or "")
        structural: int = sum(text.count(marker) for marker in ALLOWED_BULLET_MARKERS)
        return max(0, len(EMOJI_PATTERN.findall(text)) - structural)

    def without_non_structural_emoji(self) -> tuple[MergedDescription, bool]:
        """Описание без эмодзи вне маркеров пунктов (пустые строки — пустыми) и изменилось ли оно."""
        lines: list[str] = []
        changed: bool = False
        for raw_line in normalize_newlines(self.text).split(LINE_JOINER):
            if not raw_line.strip():
                lines.append("")
                continue
            line, line_changed = _without_emoji_in_line(raw_line)
            lines.append(line)
            changed = changed or line_changed
        return MergedDescription(LINE_JOINER.join(lines).strip()), changed

    @property
    def has_adjacent_duplicate_lines(self) -> bool:
        """Две соседние строки почти одинаковы: длинное общее начало или почти те же смысловые слова."""
        lines: list[str] = [line.strip() for line in normalize_newlines(self.text).split(LINE_JOINER)]
        return any(_lines_repeat(current, following) for current, following in zip(lines, lines[1:]))

    @property
    def has_similar_paragraph_prefixes(self) -> bool:
        """Два абзаца (не короче 80 знаков) начинаются почти одинаково: общее начало больше 70 % короткого."""
        paragraphs: list[str] = self.paragraphs
        for first_index, first in enumerate(paragraphs):
            for second in paragraphs[first_index + 1 :]:
                if min(len(first), len(second)) < PARAGRAPH_PREFIX_MIN_CHARS:
                    continue
                if _common_prefix_ratio(first, second) > PARAGRAPH_PREFIX_RATIO:
                    return True
        return False

    def cta_in_opening_lines(self, cta: CtaLexicon, bad_hooks: BadHookLexicon, service_hints: tuple[str, ...]) -> bool:
        """В окне первых трёх строк первых двух абзацев призыв (или негодный тезис) стоит раньше тезиса и пунктов.

        Тезис или пункт — первая строка окна, которая не призыв, не негодный тезис и не служебная строка; строка
        с маркером пункта — пункт в любом случае. Ни тезиса, ни пункта в окне нет — призыв стоит первым.
        """
        window: list[str] = self._opening_lines()
        cta_indexes: list[int] = [
            index for index, line in enumerate(window) if cta.starts_with_prefix(line) or bad_hooks.matches(line)
        ]
        if not cta_indexes:
            return False
        content_index: int | None = next(
            (
                index
                for index, line in enumerate(window)
                if bullet_marker_for_line(line)
                or not (
                    cta.starts_with_prefix(line)
                    or bad_hooks.matches(line)
                    or is_service_tail_paragraph(line, service_hints)
                )
            ),
            None,
        )
        return content_index is None or min(cta_indexes) < content_index

    def _opening_lines(self) -> list[str]:
        lines: list[str] = [
            line.strip()
            for paragraph in self.paragraphs[:OPENING_PARAGRAPHS]
            for line in paragraph.split(LINE_JOINER)
            if line.strip()
        ]
        return lines[:OPENING_LINES]

    def cta_in_hook(self, bad_hooks: BadHookLexicon, service_hints: tuple[str, ...]) -> bool:
        """Первый абзац — служебная строка (призыв, заголовок ссылок) или негодный тезис."""
        paragraphs: list[str] = self.paragraphs
        if not paragraphs:
            return False
        first: str = paragraphs[0]
        return is_service_tail_paragraph(first, service_hints) or bad_hooks.matches(first)


def _lines_repeat(current: str, following: str) -> bool:
    """Соседние строки — повтор (пороги `rules.py`); пустая строка не повтор."""
    if not current or not following:
        return False
    if min(len(current), len(following)) < ADJACENT_LINE_MIN_CHARS:
        return False
    if _common_prefix_ratio(current, following) > ADJACENT_LINE_PREFIX_RATIO:
        return True
    current_tokens: list[str] = [token.lower() for token in SEMANTIC_TOKEN_PATTERN.findall(current)]
    following_tokens: list[str] = [token.lower() for token in SEMANTIC_TOKEN_PATTERN.findall(following)]
    if len(current_tokens) < ADJACENT_LINE_MIN_TOKENS or len(following_tokens) < ADJACENT_LINE_MIN_TOKENS:
        return False
    similarity: float | None = _jaccard(set(current_tokens), set(following_tokens))
    return similarity is not None and similarity >= ADJACENT_LINE_JACCARD
