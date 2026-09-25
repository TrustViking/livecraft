"""Описание из ответа модели и его правила, не зависящие от источников (CLAUDE.md §14 решение 23).

Перенесено из restreamer, поведение как есть:
- повтор абзацев — `core\\text_utils.py::has_duplicate_paragraphs`;
- эхо тезиса и его починка — `merge_validation_helpers.py::has_hook_echo_in_body`, `attempt_hook_echo_repair`
  (+ `_split_hook_trailing_bullet`, `_line_starts_with_bullet`, `_semantic_token_set`);
- призыв в первой строке — `merge_parser.py::_description_has_raw_opener_cta`;
- снятие служебных строк «title:», «description:», «source(s):» — `merge_parser.py::strip_meta_lines`;
- починка смешанного алфавита — `script_mix_repair.py` (`repair_script_mix_homoglyphs`, `_repair_token`).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from app.texts.description_marks import ALLOWED_BULLET_MARKERS, SEMANTIC_TOKEN_PATTERN, CtaLexicon
from app.texts.paragraphs import has_duplicate_paragraphs, normalize_newlines, split_paragraphs

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
# Третий абзац-заглушка: проверка эха у донора смотрит только на первые два абзаца.
ECHO_CHECK_PLACEHOLDER: Final[str] = "Placeholder paragraph for length."
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
WORD_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile("[A-Za-zА-Яа-яЁёІіЇїЄєҐґʼ']+")
TOKENS_JOINER: Final[str] = ","
LOG_NONE: Final[str] = "none"


def _line_starts_with_bullet(line_text: str) -> bool:
    stripped_line: str = line_text.strip()
    return any(stripped_line.startswith(marker) for marker in ALLOWED_BULLET_MARKERS)


def _semantic_token_set(text: str) -> set[str]:
    return {token.lower() for token in SEMANTIC_TOKEN_PATTERN.findall(str(text or "")) if token.strip()}


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
        paragraphs: list[str] = self.paragraphs
        if len(paragraphs) < 2:
            return None
        hook, echo, remaining = paragraphs[0], paragraphs[1], paragraphs[2:]
        if not MergedDescription(PARAGRAPH_JOINER.join((hook, echo, ECHO_CHECK_PLACEHOLDER))).has_hook_echo_in_body:
            return None
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
