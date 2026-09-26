from __future__ import annotations

import dataclasses

import pytest

from app.slots.preview import Preview


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
