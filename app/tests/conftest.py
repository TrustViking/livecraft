"""Общие фикстуры: папки livecraft в tmp_path, фиксированное «сейчас», корень репо."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.paths import LivecraftPaths, build_paths, ensure_dirs

KYIV_WINTER: timezone = timezone(timedelta(hours=2))   # даты и время — по Киеву (CLAUDE.md §6, инвариант 4)
FIXED_NOW: datetime = datetime(2026, 9, 20, 12, 0, tzinfo=KYIV_WINTER)
REPO_ROOT: Path = Path(__file__).resolve().parents[2]


@pytest.fixture
def livecraft_paths(tmp_path: Path) -> LivecraftPaths:
    """Корень запуска во временной папке: папки созданы, файлов в них нет — как после установки."""
    paths: LivecraftPaths = build_paths(tmp_path / "root")
    ensure_dirs(paths)
    return paths


@pytest.fixture
def now() -> datetime:
    """Фиксированный момент со смещением: часы в тестах не плывут (CLAUDE.md §11)."""
    return FIXED_NOW


@pytest.fixture
def repo_root() -> Path:
    """Корень репо: нужен тестам, которые читают файлы проекта (.gitattributes, livecraft.bat)."""
    return REPO_ROOT
