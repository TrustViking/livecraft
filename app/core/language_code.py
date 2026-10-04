"""Код языка ISO 639-1 — одно правило для настроек каналов и для заголовков описания (CLAUDE.md §11).

Код — ровно две строчные латинские буквы; «известный» код ещё и есть в справочнике pycountry. Строчность
проверяется отдельно: поиск pycountry регистр не различает и нашёл бы «UK».
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import pycountry

LANGUAGE_CODE_LENGTH: Final[int] = 2    # ISO 639-1


@dataclass(frozen=True)
class LanguageCode:
    """Строка, которую проверяют как код языка ISO 639-1."""

    text: str

    @property
    def is_shaped(self) -> bool:
        """Две строчные латинские буквы."""
        text: str = self.text
        return len(text) == LANGUAGE_CODE_LENGTH and text.isascii() and text.isalpha() and text.islower()

    @property
    def is_known(self) -> bool:
        """Код нужного вида, и справочник pycountry его знает."""
        return self.is_shaped and pycountry.languages.get(alpha_2=self.text) is not None
