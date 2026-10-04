from __future__ import annotations

import dataclasses

import pytest

from app.slots.preview import Preview
from app.tests.fixtures.packages import jpeg


def test_the_preview_is_a_jpeg_with_its_size() -> None:
    preview: Preview = Preview(data=b"\xff\xd8jpeg", width=1280, height=720)
    assert preview.mime_type == "image/jpeg"
    assert preview.size_bytes == 6


def test_the_youtube_ceiling_is_two_megabytes() -> None:
    """Потолок `thumbnails.set` — 2 МБ: нормализация источника ужимает обложку до него."""
    assert Preview.MAX_BYTES == 2 * 1024 * 1024


def test_the_preview_is_a_value() -> None:
    preview: Preview = Preview(data=b"\xff\xd8a", width=1, height=1)
    assert preview == Preview(data=b"\xff\xd8a", width=1, height=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        preview.width = 2          # type: ignore[misc]


def test_a_preview_from_image_bytes_keeps_the_bytes_and_reads_the_size() -> None:
    """Обложка из пакета: байты как есть, размеры — из самой картинки."""
    data: bytes = jpeg(32, 18)
    assert Preview.of_image(data) == Preview(data=data, width=32, height=18)


@pytest.mark.parametrize("data", [b"", b"not an image", b"\xff\xd8broken"])
def test_bytes_that_are_not_an_image_give_no_preview(data: bytes) -> None:
    assert Preview.of_image(data) is None
