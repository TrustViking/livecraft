"""Начало описания merge: призыв, негодный тезис или служебная строка там, где должен стоять тезис.

Три правила разного охвата. `starts_with_cta` — первая непустая строка первого абзаца начинается с призыва:
так ответ отвергается ещё при разборе. `cta_before_content` — в окне первых трёх строк первых двух абзацев призыв
(или негодный тезис) стоит раньше тезиса и пунктов. `hook_is_service_line` — весь первый абзац — служебная строка
(призыв, заголовок ссылок) или негодный тезис. Два последних — проверка покрытия (`check.py`).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.text_format import NEWLINE
from app.llm.merges import rules
from app.llm.merges.description import MergedDescription
from app.llm.merges.hook import BadHookLexicon
from app.texts.description_marks import BulletLine, CtaLexicon
from app.texts.phrase_lexicon import ServiceHints


@dataclass(frozen=True)
class DescriptionOpening:
    """Начало описания глазами призывов и служебных строк."""

    description: MergedDescription

    @property
    def first_paragraph(self) -> str:
        """Первый абзац; описания нет — пусто."""
        paragraphs: list[str] = self.description.paragraphs
        return paragraphs[0] if paragraphs else ""

    @property
    def first_line(self) -> str:
        """Первая непустая строка первого абзаца без краёв; описания нет — пусто."""
        return next((line.strip() for line in self.first_paragraph.split(NEWLINE) if line.strip()), "")

    def starts_with_cta(self, cta: CtaLexicon) -> bool:
        """Первая непустая строка первого абзаца начинается с призыва."""
        first_line: str = self.first_line
        return bool(first_line) and cta.starts_with_prefix(first_line)

    def cta_before_content(self, cta: CtaLexicon, bad_hooks: BadHookLexicon, service_hints: ServiceHints) -> bool:
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
                if BulletLine.of(line).marker
                or not (cta.starts_with_prefix(line) or bad_hooks.matches(line) or service_hints.is_tail_paragraph(line))
            ),
            None,
        )
        return content_index is None or min(cta_indexes) < content_index

    def _opening_lines(self) -> list[str]:
        lines: list[str] = [
            line.strip()
            for paragraph in self.description.paragraphs[: rules.OPENING_PARAGRAPHS]
            for line in paragraph.split(NEWLINE)
            if line.strip()
        ]
        return lines[: rules.OPENING_LINES]

    def hook_is_service_line(self, bad_hooks: BadHookLexicon, service_hints: ServiceHints) -> bool:
        """Первый абзац — служебная строка (призыв, заголовок ссылок) или негодный тезис."""
        first: str = self.first_paragraph
        return bool(first) and (service_hints.is_tail_paragraph(first) or bad_hooks.matches(first))
