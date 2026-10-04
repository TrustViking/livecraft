"""Обложка слота — готовый JPEG, пригодный для YouTube (CLAUDE.md §4).

Значение, которое пересекает шов: откуда оно взялось (скачивание и нормализация Pillow — app\\sources\\preview.py,
файл пакета plan_*.bcast — `of_image`), контур B не знает. Обложку эфира ставит `thumbnails.set` с типом
`image/jpeg` и потолком YouTube 2 МБ.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import ClassVar, Final

from PIL import Image, UnidentifiedImageError

MIME_TYPE: Final[str] = "image/jpeg"
# Pillow не открыл байты: не картинка, битый файл, «бомба распаковки».
UNREADABLE_IMAGE_ERRORS: Final[tuple[type[Exception], ...]] = (
    UnidentifiedImageError, OSError, Image.DecompressionBombError
)
# Расширение файла обложки — по MIME_TYPE: обложка всегда JPEG (имена обложек слота и превью видео).
PREVIEW_FILE_EXTENSION: Final[str] = ".jpg"
# Имя файла обложки слота — номер с 1 в порядке обложек (StreamSlot.preview_file_names).
PREVIEW_FILE_TEMPLATE: Final[str] = "{slot_id}_{index}" + PREVIEW_FILE_EXTENSION


@dataclass(frozen=True)
class Preview:
    """Готовая обложка: JPEG не больше MAX_BYTES и её размеры в пикселях."""

    MAX_BYTES: ClassVar[int] = 2 * 1024 * 1024      # потолок YouTube для thumbnails.set

    data: bytes
    width: int
    height: int

    @classmethod
    def of_image(cls, data: bytes) -> Preview | None:
        """Готовая обложка из файла, который уже был обложкой (пакет plan_*.bcast): размеры — из заголовка картинки,
        байты — как есть. Не картинка — None."""
        try:
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
        except UNREADABLE_IMAGE_ERRORS:
            return None
        return cls(data=data, width=width, height=height)

    @property
    def mime_type(self) -> str:
        return MIME_TYPE

    @property
    def size_bytes(self) -> int:
        return len(self.data)
