"""Эхо тезиса в описании merge: первая строка тела повторяет тезис первого абзаца — и его починка.

`HookEcho.found` — тело (первая строка второго абзаца) повторяет тезис: длинное общее начало, последняя фраза тезиса
или весь тезис совпадают с ней по смысловым словам. `HookEcho.repaired` — описание без эха: сначала срезается повтор
тезиса до первого пункта второго абзаца; не помогло — пункт, вклеенный в тезис (`HookParagraph.split_trailing_bullet`),
выносится в тело. Эхо, которое не чинится, — отказ `hook_echo_in_body`; в разобранном ответе оно запрещает
восстанавливать число абзацев (`layout.py`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.core.text_format import NEWLINE, PARAGRAPH_BREAK, SPACE, WHITESPACE_RUN_PATTERN
from app.llm.merges import rules
from app.llm.merges.description import MergedDescription
from app.texts.description_marks import ROLE_MARKERS, BulletLine
from app.texts.similarity import TextPair

HOOK_SENTENCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[.!?]\s+|\n")
SENTENCE_ENDINGS: Final[tuple[str, ...]] = (". ", "! ", "? ")


@dataclass(frozen=True)
class HookSplit:
    """Тезис без вклеенного пункта и сам пункт; пункта нет — `bullet` None, тезис как был."""

    hook: str
    bullet: str | None


@dataclass(frozen=True)
class HookParagraph:
    """Первый абзац (тезис), в который модель могла вклеить первый пункт списка."""

    text: str

    def split_trailing_bullet(self) -> HookSplit:
        """Тезис и вклеенный в него пункт.

        Несколько строк: пункт — первая строка после первой, начинающаяся маркером. Одна строка: самый ранний
        маркер после начала строки, перед ним — только пробелы после последнего конца фразы дальше 40-го знака.
        """
        hook_lines: list[str] = self.text.split(NEWLINE)
        if len(hook_lines) > 1:
            return self._split_multiline(hook_lines)
        return self._split_single_line(self.text.strip())

    def _split_multiline(self, hook_lines: list[str]) -> HookSplit:
        for line_index in range(1, len(hook_lines)):
            if BulletLine.of(hook_lines[line_index]).has_marker_prefix:
                return HookSplit(NEWLINE.join(hook_lines[:line_index]).strip(), hook_lines[line_index].strip())
        return HookSplit(self.text, None)

    def _split_single_line(self, single_line: str) -> HookSplit:
        positions: list[int] = [
            position for position in (single_line.find(marker) for marker in ROLE_MARKERS) if position > 0
        ]
        if not positions:
            return HookSplit(self.text, None)
        bullet_position: int = min(positions)
        cut_position: int | None = self._sentence_cut(single_line, bullet_position)
        extracted_bullet: str = single_line[bullet_position:].strip()
        if cut_position is None or not BulletLine.of(extracted_bullet).has_marker_prefix:
            return HookSplit(self.text, None)
        return HookSplit(single_line[:cut_position].strip(), extracted_bullet)

    def _sentence_cut(self, single_line: str, bullet_position: int) -> int | None:
        """Позиция сразу за знаком конца фразы, после которого до маркера только пробелы."""
        prefix_text: str = single_line[:bullet_position]
        best_cut_position: int | None = None
        for ending in SENTENCE_ENDINGS:
            candidate_position: int = prefix_text.rfind(ending)
            if candidate_position < rules.FUSED_BULLET_MIN_POSITION:
                continue
            if single_line[candidate_position + len(ending) : bullet_position].strip():
                continue
            cut_after: int = candidate_position + 1
            if best_cut_position is None or cut_after > best_cut_position:
                best_cut_position = cut_after
        return best_cut_position


@dataclass(frozen=True)
class HookEcho:
    """Эхо тезиса в описании."""

    description: MergedDescription

    @property
    def found(self) -> bool:
        """Тело (первая строка второго абзаца) повторяет тезис первого абзаца."""
        paragraphs: list[str] = self.description.paragraphs
        if len(paragraphs) <= 1:
            return False
        hook_text: str = paragraphs[0].strip()
        body_opener_line: str = paragraphs[1].split(NEWLINE)[0].strip()
        if min(len(hook_text), len(body_opener_line)) < rules.ECHO_MIN_CHARS:
            return False
        pair: TextPair = TextPair(hook_text, body_opener_line)
        if pair.prefix_ratio > rules.ECHO_PREFIX_RATIO:
            return True
        similarity: float | None = pair.jaccard
        if similarity is None:
            return False
        if self._last_hook_sentence_echoes(hook_text, body_opener_line):
            return True
        return similarity >= rules.ECHO_JACCARD

    def _last_hook_sentence_echoes(self, hook_text: str, body_opener_line: str) -> bool:
        """Последняя фраза тезиса совпадает с первой строкой тела по смысловым словам."""
        sentences: list[str] = [part.strip() for part in HOOK_SENTENCE_PATTERN.split(hook_text) if part.strip()]
        if not sentences:
            return False
        last_sentence: str = sentences[-1]
        if min(len(last_sentence), len(body_opener_line)) < rules.ECHO_SENTENCE_MIN_CHARS:
            return False
        similarity: float | None = TextPair(last_sentence, body_opener_line).jaccard
        return similarity is not None and similarity >= rules.ECHO_SENTENCE_JACCARD

    def repaired(self) -> MergedDescription | None:
        """Описание без эха тезиса во втором абзаце; починить нельзя или эха нет — None.

        Первый проход срезает повтор тезиса до первого пункта второго абзаца (нет пункта — берёт третий абзац,
        если он начинается пунктом). Не помогло — второй проход выносит пункт, вклеенный в тезис, в тело.
        """
        if not self.found:
            return None
        first_pass: MergedDescription | None = self._without_echo_prefix()
        if first_pass is None:
            return None
        echo: HookEcho = HookEcho(first_pass)
        return first_pass if not echo.found else echo._with_fused_bullet_moved()

    def _without_echo_prefix(self) -> MergedDescription | None:
        hook, echo, *remaining = self.description.paragraphs
        echo_lines: list[str] = echo.split(NEWLINE)
        first_bullet_index: int | None = next(
            (index for index, line in enumerate(echo_lines) if BulletLine.of(line).has_marker_prefix), None
        )
        if first_bullet_index is not None:
            trimmed_echo: str = NEWLINE.join(echo_lines[first_bullet_index:])
            return MergedDescription(PARAGRAPH_BREAK.join([hook, trimmed_echo, *remaining]))
        if not remaining or not BulletLine.of(remaining[0]).has_marker_prefix:
            return None
        return MergedDescription(PARAGRAPH_BREAK.join([hook, *remaining]))

    def _with_fused_bullet_moved(self) -> MergedDescription | None:
        """Пункт, вклеенный в тезис, — первым пунктом тела (если тело не начинается тем же пунктом)."""
        hook, body_block, *remaining = self.description.paragraphs
        split: HookSplit = HookParagraph(hook).split_trailing_bullet()
        if split.bullet is None:
            return None
        body_bullets: list[str] = [
            line.strip() for line in body_block.split(NEWLINE) if BulletLine.of(line).has_marker_prefix
        ]
        is_same_bullet: bool = bool(body_bullets) and (
            WHITESPACE_RUN_PATTERN.sub(SPACE, body_bullets[0]) == WHITESPACE_RUN_PATTERN.sub(SPACE, split.bullet.strip())
        )
        new_body: str = body_block if is_same_bullet else split.bullet + NEWLINE + body_block
        repaired: MergedDescription = MergedDescription(PARAGRAPH_BREAK.join([split.hook, new_body, *remaining]))
        return None if HookEcho(repaired).found else repaired
