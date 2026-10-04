"""Слоты и пакет для объявлений в Telegram (app\\publish\\announce_*.py): слот задаётся стартом, языком, текстами и
обложками; пакет — настоящий файл во временной папке теста."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.packages.package import PackagePeriod, PackageResult
from app.slots.preview import Preview
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
COVER: Preview = Preview(data=b"\xff\xd8cover-1\xff\xd9", width=1280, height=720)
OTHER_COVER: Preview = Preview(data=b"\xff\xd8cover-2\xff\xd9", width=1280, height=720)
SOURCE_LINK: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
PACKAGE_NAME: str = "plan_16-10-2026_17-10-2026_gen28-09-2026-1005.bcast"
PACKAGE_BYTES: bytes = b"PK\x03\x04package"


def stream_slot(
    start: datetime,
    language: str = "uk",
    texts: SlotTexts = SlotTexts(title="Эфир", description="Опис", origin=SlotTextOrigin.SOURCE_SINGLE),
    previews: tuple[Preview, ...] = (COVER,),
) -> StreamSlot:
    """Годный слот: старт в поясе программы, язык, тексты и обложки."""
    return StreamSlot(key=SlotKey(start, language), texts=texts, previews=previews, sources=(SOURCE_LINK,))


def written_package(bcast_dir: Path, slots: int, previews: int, period: PackagePeriod) -> PackageResult:
    """Записанный пакет: файл с байтами `PACKAGE_BYTES`, счётчики и период."""
    path: Path = bcast_dir / PACKAGE_NAME
    path.write_bytes(PACKAGE_BYTES)
    return PackageResult(
        path=path, problem=None, slots=slots, previews=previews, size_bytes=len(PACKAGE_BYTES), period=period
    )
