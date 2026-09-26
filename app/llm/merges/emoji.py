"""Эмодзи в описании merge: счёт вне маркеров пунктов и их снятие.

Маркеры пунктов (🔹, 📌, …) — структура списка, а не украшение: счёт (`EmojiUsage.count`) вычитает все их вхождения,
снятие (`EmojiUsage.cleaned`) оставляет маркер в начале строки. Больше десяти эмодзи вне маркеров — отказ проверки
покрытия; при трёх и больше источниках отказ снимается снятием эмодзи (`check.py::FormattingRecovery`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.core.text_format import NEWLINE, REPEATED_SPACE_PATTERN, SPACE
from app.llm.merges.description import MergedDescription
from app.texts.description_marks import ALLOWED_BULLET_MARKERS

EMOJI_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", flags=re.UNICODE)
SPACE_BEFORE_PUNCTUATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+([,.;:!?])")
PUNCTUATION_GROUP: Final[str] = r"\1"


@dataclass(frozen=True)
class EmojiCleanup:
    """Описание без эмодзи вне маркеров пунктов и изменилось ли оно."""

    description: MergedDescription
    changed: bool


@dataclass(frozen=True)
class EmojiUsage:
    """Эмодзи описания."""

    description: MergedDescription

    @property
    def count(self) -> int:
        """Эмодзи вне маркеров пунктов: все эмодзи минус все вхождения маркеров, где бы они ни стояли."""
        text: str = self.description.text
        structural: int = sum(text.count(marker) for marker in ALLOWED_BULLET_MARKERS)
        return max(0, len(EMOJI_PATTERN.findall(text)) - structural)

    def cleaned(self) -> EmojiCleanup:
        """Описание без эмодзи вне маркеров пунктов; пустые строки остаются пустыми."""
        lines: list[str] = []
        changed: bool = False
        for raw_line in self.description.lines:
            line: str = self._line_cleaned(raw_line) if raw_line.strip() else ""
            lines.append(line)
            changed = changed or line != raw_line.strip()
        return EmojiCleanup(MergedDescription(NEWLINE.join(lines).strip()), changed)

    def _line_cleaned(self, line: str) -> str:
        """Строка без эмодзи вне маркера пункта в её начале и без пробелов перед знаками препинания."""
        indent: str = line[: len(line) - len(line.lstrip())]
        content: str = line[len(indent) :]
        protected_prefix: str = ""
        for marker in ALLOWED_BULLET_MARKERS:
            if content.startswith(f"{marker}{SPACE}"):
                protected_prefix = f"{indent}{marker}{SPACE}"
                content = content[len(marker) + 1 :]
                break
        tail: str = EMOJI_PATTERN.sub("", content)
        tail = SPACE_BEFORE_PUNCTUATION_PATTERN.sub(PUNCTUATION_GROUP, tail)
        tail = REPEATED_SPACE_PATTERN.sub(SPACE, tail).strip()
        return f"{protected_prefix}{tail}".strip()
