"""Раскладка описания из ответа модели: тело и служебный хвост, восстановление числа абзацев тела.

Перенесено из restreamer как есть (`merge_parser.py::separate_merge_body_and_tail`, `MergeTailSeparationResult`,
`_split_body_and_allowed_tail`, `_looks_like_*_paragraph`, `_split_single_paragraph_safely`,
`_collapse_paragraphs_to_limit`). Хвост снимается с конца: хештеги, официальные ссылки под заголовком «🌐 …:»,
ссылки YouTube. Тело из одного абзаца делится пополам по фразам, лишние абзацы тела сливаются группами —
кроме случая, когда в теле повтор абзацев или эхо тезиса: такое восстанавливать нельзя, это отказ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.llm.merges.description import MergedDescription
from app.llm.merges.reject import MergeRejectCode
from app.texts.description_marks import URL_LINE_PATTERN, is_official_links_heading
from app.texts.paragraphs import normalize_multiline_text, split_paragraphs

PARAGRAPH_JOINER: Final[str] = "\n\n"
LINE_JOINER: Final[str] = "\n"
SENTENCE_JOINER: Final[str] = " "
HASHTAG_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^#[^\s#]+$")
SENTENCE_BREAK_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?…])\s+")
YOUTUBE_MARK: Final[str] = "youtu"
# Один абзац тела делится, только если в нём не меньше четырёх фраз; левая часть — не меньше двух фраз.
SPLIT_MIN_SENTENCES: Final[int] = 4
SPLIT_MIN_LEFT_SENTENCES: Final[int] = 2
# Лишние абзацы тела сливаются, только если их не больше чем на четыре сверх предела.
COLLAPSE_MAX_EXCESS: Final[int] = 4
LOG_NONE: Final[str] = "none"
BLOCKS_JOINER: Final[str] = ","


class TailBlock(str, Enum):
    """Вид служебного абзаца в конце описания."""

    HASHTAGS = "hashtags"
    OFFICIAL_LINKS = "official_links"
    YOUTUBE_LINKS = "youtube_links"

    @classmethod
    def of(cls, paragraph: str) -> TailBlock | None:
        """Вид хвостового абзаца; абзац тела — None. Порядок проверки донорский."""
        if cls._is_hashtags(paragraph):
            return cls.HASHTAGS
        if cls._is_official_links(paragraph):
            return cls.OFFICIAL_LINKS
        if cls._is_youtube_links(paragraph):
            return cls.YOUTUBE_LINKS
        return None

    @staticmethod
    def _lines(paragraph: str) -> list[str]:
        return [line.strip() for line in str(paragraph or "").split(LINE_JOINER) if line.strip()]

    @staticmethod
    def _is_hashtags(paragraph: str) -> bool:
        tokens: list[str] = [token.strip() for token in str(paragraph or "").split() if token.strip()]
        return bool(tokens) and all(HASHTAG_TOKEN_PATTERN.fullmatch(token) for token in tokens)

    @classmethod
    def _is_official_links(cls, paragraph: str) -> bool:
        lines: list[str] = cls._lines(paragraph)
        if not lines or not is_official_links_heading(lines[0]):
            return False
        return all(URL_LINE_PATTERN.fullmatch(line) for line in lines[1:])

    @classmethod
    def _is_youtube_links(cls, paragraph: str) -> bool:
        lines: list[str] = cls._lines(paragraph)
        if not lines:
            return False
        return all(URL_LINE_PATTERN.fullmatch(line) and YOUTUBE_MARK in line.lower() for line in lines)


class LayoutRecovery(str, Enum):
    """Что сделано с числом абзацев тела (`recovery_note` донора)."""

    NOT_NEEDED = "not_needed"
    SPLIT_SINGLE = "split_single_body_paragraph"
    COLLAPSED = "collapsed_excess_body_paragraphs"
    NOT_POSSIBLE = "body_recovery_not_possible"
    BLOCKED = "recovery_blocked_duplicate_paragraph"

    @property
    def is_applied(self) -> bool:
        return self in (LayoutRecovery.SPLIT_SINGLE, LayoutRecovery.COLLAPSED)


@dataclass(frozen=True)
class DescriptionLayout:
    """Описание, разложенное на тело и хвост. Тексты абзацев в `repr` не печатаются.

    `body_paragraph_count` — абзацев тела до восстановления, `body_paragraph_count_after_recovery` — после;
    `blocked_reason` — отказ, из-за которого восстановление запрещено (повтор абзацев или эхо тезиса).
    """

    body_paragraphs: tuple[str, ...] = field(repr=False)
    tail_paragraphs: tuple[str, ...] = field(repr=False)
    tail_blocks: tuple[TailBlock, ...]
    raw_paragraph_count: int
    body_paragraph_count: int
    recovery: LayoutRecovery
    blocked_reason: MergeRejectCode | None = None

    @classmethod
    def of(cls, text: str, max_body_paragraphs: int) -> DescriptionLayout:
        normalized_text: str = normalize_multiline_text(text)
        paragraphs: list[str] = split_paragraphs(normalized_text)
        body, tail, blocks = cls._split_tail(paragraphs)
        recovered, recovery = cls._recover(body, max_body_paragraphs)
        return cls(
            body_paragraphs=tuple(recovered),
            tail_paragraphs=tuple(tail),
            tail_blocks=tuple(blocks),
            raw_paragraph_count=len(paragraphs),
            body_paragraph_count=len(body),
            recovery=recovery,
            blocked_reason=MergeRejectCode.DUPLICATE_PARAGRAPH if recovery is LayoutRecovery.BLOCKED else None,
        )

    @staticmethod
    def _split_tail(paragraphs: list[str]) -> tuple[list[str], list[str], list[TailBlock]]:
        body: list[str] = list(paragraphs)
        tail: list[str] = []
        blocks: list[TailBlock] = []
        while body:
            block: TailBlock | None = TailBlock.of(body[-1])
            if block is None:
                break
            tail.insert(0, body.pop())
            blocks.insert(0, block)
        return body, tail, blocks

    @classmethod
    def _recover(cls, body: list[str], max_body_paragraphs: int) -> tuple[list[str], LayoutRecovery]:
        is_candidate: bool = len(body) == 1 or len(body) > max_body_paragraphs
        raw_body: MergedDescription = MergedDescription(PARAGRAPH_JOINER.join(body).strip())
        if is_candidate and raw_body.text and (raw_body.has_duplicate_paragraphs or raw_body.has_hook_echo_in_body):
            return body, LayoutRecovery.BLOCKED
        if len(body) == 1:
            split: list[str] | None = cls._split_single(body[0])
            return (split, LayoutRecovery.SPLIT_SINGLE) if split is not None else (body, LayoutRecovery.NOT_NEEDED)
        if len(body) > max_body_paragraphs:
            collapsed: list[str] | None = cls._collapse(body, max_body_paragraphs)
            if collapsed is not None and len(collapsed) <= max_body_paragraphs:
                return collapsed, LayoutRecovery.COLLAPSED
            return body, LayoutRecovery.NOT_POSSIBLE
        return body, LayoutRecovery.NOT_NEEDED

    @staticmethod
    def _split_single(paragraph: str) -> list[str] | None:
        """Один абзац — два по фразам: левая половина не меньше двух фраз."""
        sentences: list[str] = [
            part.strip() for part in SENTENCE_BREAK_PATTERN.split(str(paragraph or "").strip()) if part.strip()
        ]
        if len(sentences) < SPLIT_MIN_SENTENCES:
            return None
        split_index: int = max(SPLIT_MIN_LEFT_SENTENCES, len(sentences) // 2)
        left: str = SENTENCE_JOINER.join(sentences[:split_index]).strip()
        right: str = SENTENCE_JOINER.join(sentences[split_index:]).strip()
        if not left or not right:
            return None
        return [left, right]

    @staticmethod
    def _collapse(paragraphs: list[str], max_paragraphs: int) -> list[str] | None:
        """Лишние абзацы тела сливаются в соседние группами (старшие группы на один абзац больше)."""
        cleaned: list[str] = [item.strip() for item in paragraphs if item.strip()]
        if not cleaned:
            return None
        if len(cleaned) <= max_paragraphs:
            return cleaned
        if len(cleaned) > max_paragraphs + COLLAPSE_MAX_EXCESS:
            return None
        base_group_size, remainder = divmod(len(cleaned), max_paragraphs)
        collapsed: list[str] = []
        start_index: int = 0
        for group_index in range(max_paragraphs):
            group_size: int = base_group_size + (1 if group_index < remainder else 0)
            group: list[str] = cleaned[start_index : start_index + max(1, group_size)]
            if not group:
                break
            collapsed.append(LINE_JOINER.join(group).strip())
            start_index += max(1, group_size)
        return collapsed if len(collapsed) <= max_paragraphs else None

    @property
    def body_paragraph_count_after_recovery(self) -> int:
        return len(self.body_paragraphs)

    @property
    def body_text(self) -> str:
        return PARAGRAPH_JOINER.join(self.body_paragraphs).strip()

    @property
    def full_text(self) -> str:
        return PARAGRAPH_JOINER.join(p for p in (self.body_text, *self.tail_paragraphs) if p.strip()).strip()

    @property
    def tail_detected(self) -> bool:
        return bool(self.tail_blocks)

    @property
    def recovery_applied(self) -> bool:
        return self.recovery.is_applied

    @property
    def log_fields(self) -> str:
        """Поля строки `merge_description_tail_analysis` донора — только числа и виды блоков, без текста."""
        return (
            f"raw_paragraph_count={self.raw_paragraph_count} "
            f"tail_separated={'yes' if self.tail_detected else 'no'} "
            f"tail_blocks={BLOCKS_JOINER.join(block.value for block in self.tail_blocks) or LOG_NONE} "
            f"body_paragraph_count={self.body_paragraph_count} "
            f"recovery_applied={'yes' if self.recovery_applied else 'no'} "
            f"body_paragraph_count_after_recovery={self.body_paragraph_count_after_recovery}"
        )
