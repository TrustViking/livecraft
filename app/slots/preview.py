"""Обложка слота — готовый JPEG, пригодный для YouTube (CLAUDE.md §4).

Значение, которое пересекает шов: откуда оно взялось (скачивание и нормализация Pillow — app\\sources\\preview.py),
контур B не знает. Обложку эфира ставит `thumbnails.set` с типом `image/jpeg` и потолком YouTube 2 МБ.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

MIME_TYPE: Final[str] = "image/jpeg"


@dataclass(frozen=True)
class Preview:
    """Готовая обложка: JPEG не больше MAX_BYTES и её размеры в пикселях."""

    MAX_BYTES: ClassVar[int] = 2 * 1024 * 1024      # потолок YouTube для thumbnails.set

    data: bytes
    width: int
    height: int

    @property
    def mime_type(self) -> str:
        return MIME_TYPE

    @property
    def size_bytes(self) -> int:
        return len(self.data)
