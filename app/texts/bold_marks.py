"""Разметка жирного `*…*` в названии и описании слота (CLAUDE.md §14 решения 61, 63).

Звёздочки — часть текста слота: в пакете и на YouTube они остаются (YouTube сам показывает их жирным). Объявления
в Telegram и документ объявлений показывают размеченное жирным начертанием, без звёздочек: `BoldText` — тот же текст,
разобранный на части, жирные и нет; каждый вывод сам решает, как показать жирную часть.

Разметка — пара звёздочек внутри одной строки: открывающая — в начале строки или после пробела, закрывающая — в
конце строки, перед пробелом или знаком препинания (за ней не буква и не цифра); между ними хотя бы один знак, без
«*» и перевода строки, без пробела сразу после открывающей и перед закрывающей. Так «5*3*2», «a * b * c», «**» и
звёздочки через перевод строки разметкой не считаются и остаются как есть.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

BOLD_MARK_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<!\S)\*([^\s*](?:[^*\n]*[^\s*])?)\*(?!\w)")


@dataclass(frozen=True)
class BoldPart:
    """Часть текста: сам текст без звёздочек и жирная ли она."""

    text: str
    is_bold: bool


@dataclass(frozen=True)
class BoldText:
    """Текст, разобранный на части по разметке `*…*`; пустых частей нет."""

    parts: tuple[BoldPart, ...]

    @classmethod
    def of(cls, text: str) -> BoldText:
        """Разобрать разметку текста слота: размеченное — жирные части, остальное — обычные."""
        parts: list[BoldPart] = []
        end: int = 0
        for match in BOLD_MARK_PATTERN.finditer(text):
            parts.append(BoldPart(text[end:match.start()], is_bold=False))
            parts.append(BoldPart(match.group(1), is_bold=True))
            end = match.end()
        parts.append(BoldPart(text[end:], is_bold=False))
        return cls(tuple(part for part in parts if part.text))

    @classmethod
    def unmarked(cls, text: str) -> BoldText:
        """Текст программы, а не слота (метки, ссылки): разметки в нём нет, весь он — одна обычная часть."""
        return cls((BoldPart(text, is_bold=False),) if text else ())

    @property
    def plain(self) -> str:
        """Текст без звёздочек разметки."""
        return "".join(part.text for part in self.parts)
