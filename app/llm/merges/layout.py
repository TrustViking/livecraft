"""Раскладка описания из ответа модели: тело и служебный хвост, восстановление числа абзацев тела.

Хвост снимается с конца (`TailSplit`): хештеги, официальные ссылки под заголовком «🌐 …:», ссылки YouTube.
Число абзацев тела восстанавливается (`BodyRecovery`): тело из одного абзаца делится пополам по фразам, лишние
абзацы тела сливаются группами — кроме случая, когда в теле повтор абзацев или эхо тезиса: такое восстанавливать
нельзя, это отказ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.core.text_format import NEWLINE, PARAGRAPH_BREAK, SPACE
from app.core.web_link import URL_LINE_PATTERN, WebLink
from app.llm.merges import rules
from app.llm.merges.description import MergedDescription
from app.llm.merges.hook_echo import HookEcho
from app.llm.merges.reject import MergeRejectCode
from app.observability.log_event import LogEvent
from app.texts.description_marks import is_official_links_heading
from app.texts.hashtags import is_hashtags_line
from app.texts.paragraphs import SENTENCE_BREAK_PATTERN, nonempty_lines, normalize_multiline_text, split_paragraphs

SPLIT_PARTS: Final[int] = 2          # один абзац тела делится на две части


class TailBlock(str, Enum):
    """Вид служебного абзаца в конце описания."""

    HASHTAGS = "hashtags"
    OFFICIAL_LINKS = "official_links"
    YOUTUBE_LINKS = "youtube_links"

    @classmethod
    def of(cls, paragraph: str) -> TailBlock | None:
        """Вид хвостового абзаца; абзац тела — None."""
        if is_hashtags_line(paragraph):
            return cls.HASHTAGS
        if cls._is_official_links(paragraph):
            return cls.OFFICIAL_LINKS
        if cls._is_youtube_links(paragraph):
            return cls.YOUTUBE_LINKS
        return None

    @classmethod
    def _is_official_links(cls, paragraph: str) -> bool:
        lines: list[str] = nonempty_lines(paragraph)
        if not lines or not is_official_links_heading(lines[0]):
            return False
        return all(URL_LINE_PATTERN.fullmatch(line) for line in lines[1:])

    @classmethod
    def _is_youtube_links(cls, paragraph: str) -> bool:
        """Все строки абзаца — ссылки на YouTube: хост из списка, а не похожее имя сайта."""
        lines: list[str] = nonempty_lines(paragraph)
        if not lines:
            return False
        return all(URL_LINE_PATTERN.fullmatch(line) and WebLink.of(line).unwrapped.is_youtube for line in lines)


class LayoutRecovery(str, Enum):
    """Что сделано с числом абзацев тела."""

    NOT_NEEDED = "not_needed"
    SPLIT_SINGLE = "split_single_body_paragraph"
    COLLAPSED = "collapsed_excess_body_paragraphs"
    NOT_POSSIBLE = "body_recovery_not_possible"
    BLOCKED = "recovery_blocked_duplicate_paragraph"

    @property
    def is_applied(self) -> bool:
        return self in (LayoutRecovery.SPLIT_SINGLE, LayoutRecovery.COLLAPSED)


@dataclass(frozen=True)
class TailSplit:
    """Абзацы описания, разделённые на тело и служебный хвост; `blocks` — вид каждого абзаца хвоста."""

    body: tuple[str, ...]
    tail: tuple[str, ...]
    blocks: tuple[TailBlock, ...]

    @classmethod
    def of(cls, paragraphs: list[str]) -> TailSplit:
        """Хвост снимается с конца, пока последний абзац — служебный."""
        body: list[str] = list(paragraphs)
        tail: list[str] = []
        blocks: list[TailBlock] = []
        while body:
            block: TailBlock | None = TailBlock.of(body[-1])
            if block is None:
                break
            tail.insert(0, body.pop())
            blocks.insert(0, block)
        return cls(body=tuple(body), tail=tuple(tail), blocks=tuple(blocks))


@dataclass(frozen=True)
class BodyRecovery:
    """Абзацы тела после восстановления их числа и что с ними сделано."""

    paragraphs: tuple[str, ...]
    recovery: LayoutRecovery

    @classmethod
    def of(cls, body: tuple[str, ...], max_body_paragraphs: int) -> BodyRecovery:
        """Один абзац — делится; больше предела — сливается; повтор абзацев или эхо тезиса запрещают и то, и другое."""
        is_candidate: bool = len(body) == 1 or len(body) > max_body_paragraphs
        raw_body: MergedDescription = MergedDescription(PARAGRAPH_BREAK.join(body).strip())
        if is_candidate and raw_body.text and (raw_body.has_duplicate_paragraphs or HookEcho(raw_body).found):
            return cls(body, LayoutRecovery.BLOCKED)
        if len(body) == 1:
            return cls._split(body)
        if len(body) > max_body_paragraphs:
            return cls._collapsed(body, max_body_paragraphs)
        return cls(body, LayoutRecovery.NOT_NEEDED)

    @classmethod
    def _split(cls, body: tuple[str, ...]) -> BodyRecovery:
        """Один абзац — два по фразам, если фраз не меньше четырёх: левая половина не меньше двух фраз."""
        sentences: list[str] = [part.strip() for part in SENTENCE_BREAK_PATTERN.split(body[0].strip()) if part.strip()]
        if len(sentences) < rules.SPLIT_MIN_SENTENCES:
            return cls(body, LayoutRecovery.NOT_NEEDED)
        split_index: int = max(rules.SPLIT_MIN_LEFT_SENTENCES, len(sentences) // SPLIT_PARTS)
        left: str = SPACE.join(sentences[:split_index]).strip()
        right: str = SPACE.join(sentences[split_index:]).strip()
        if not left or not right:
            return cls(body, LayoutRecovery.NOT_NEEDED)
        return cls((left, right), LayoutRecovery.SPLIT_SINGLE)

    @classmethod
    def _collapsed(cls, body: tuple[str, ...], max_paragraphs: int) -> BodyRecovery:
        """Лишние абзацы тела сливаются в соседние группами (старшие группы на один абзац больше); лишних больше
        чем на четыре сверх предела — восстановить нельзя."""
        cleaned: list[str] = [item.strip() for item in body if item.strip()]
        if not cleaned or len(cleaned) > max_paragraphs + rules.COLLAPSE_MAX_EXCESS:
            return cls(body, LayoutRecovery.NOT_POSSIBLE)
        if len(cleaned) <= max_paragraphs:
            return cls(tuple(cleaned), LayoutRecovery.COLLAPSED)
        base_group_size, remainder = divmod(len(cleaned), max_paragraphs)
        collapsed: list[str] = []
        start_index: int = 0
        for group_index in range(max_paragraphs):
            group_size: int = base_group_size + (1 if group_index < remainder else 0)
            collapsed.append(NEWLINE.join(cleaned[start_index : start_index + group_size]).strip())
            start_index += group_size
        return cls(tuple(collapsed), LayoutRecovery.COLLAPSED)


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
        paragraphs: list[str] = split_paragraphs(normalize_multiline_text(text))
        split: TailSplit = TailSplit.of(paragraphs)
        recovered: BodyRecovery = BodyRecovery.of(split.body, max_body_paragraphs)
        return cls(
            body_paragraphs=recovered.paragraphs,
            tail_paragraphs=split.tail,
            tail_blocks=split.blocks,
            raw_paragraph_count=len(paragraphs),
            body_paragraph_count=len(split.body),
            recovery=recovered.recovery,
            blocked_reason=MergeRejectCode.DUPLICATE_PARAGRAPH if recovered.recovery is LayoutRecovery.BLOCKED else None,
        )

    @property
    def body_paragraph_count_after_recovery(self) -> int:
        return len(self.body_paragraphs)

    @property
    def body_text(self) -> str:
        return PARAGRAPH_BREAK.join(self.body_paragraphs).strip()

    @property
    def full_text(self) -> str:
        return PARAGRAPH_BREAK.join(p for p in (self.body_text, *self.tail_paragraphs) if p.strip()).strip()

    @property
    def tail_detected(self) -> bool:
        return bool(self.tail_blocks)

    @property
    def recovery_applied(self) -> bool:
        return self.recovery.is_applied

    def extend(self, event: LogEvent) -> LogEvent:
        """Событие с полями раскладки — только числа и виды блоков, без текста."""
        return event.extended(
            raw_paragraph_count=self.raw_paragraph_count,
            tail_separated=self.tail_detected,
            tail_blocks=self.tail_blocks,
            body_paragraph_count=self.body_paragraph_count,
            recovery_applied=self.recovery_applied,
            body_paragraph_count_after_recovery=self.body_paragraph_count_after_recovery,
        )
