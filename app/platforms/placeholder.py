"""Отпечаток картинки эфира и метка заглушки обложки в описании потока.

У нового эфира своей обложки ещё нет: его картинка — заглушка канала. Отпечаток этой картинки программа пишет в
описание ключа потока (`token`, «thumb0=<sha>»); по нему следующий запуск узнаёт эфир без обложки. Вид метки не
меняется: эфиры на живых каналах создал planers, и livecraft узнаёт их по тому же отпечатку.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final

PICTURE_SHA_CHARS: Final[int] = 12
PLACEHOLDER_TOKEN_TEMPLATE: Final[str] = "thumb0={sha}"
PLACEHOLDER_PATTERN: Final[re.Pattern[str]] = re.compile(r"thumb0=([0-9a-f]{12})")


@dataclass(frozen=True)
class PlaceholderMark:
    """Отпечаток картинки: sha256 её байтов, первые `PICTURE_SHA_CHARS` hex."""

    sha: str

    @classmethod
    def of(cls, picture: bytes) -> PlaceholderMark:
        return cls(hashlib.sha256(picture).hexdigest()[:PICTURE_SHA_CHARS])

    @classmethod
    def found_in(cls, description: str) -> PlaceholderMark | None:
        """Отпечаток заглушки из описания потока; метки нет — None."""
        found: re.Match[str] | None = PLACEHOLDER_PATTERN.search(description)
        return cls(found.group(1)) if found else None

    @property
    def token(self) -> str:
        """Метка заглушки в описании потока."""
        return PLACEHOLDER_TOKEN_TEMPLATE.format(sha=self.sha)
