"""Общие фикстуры: папки livecraft в tmp_path, фиксированное «сейчас», корень репо, сейф на диске,
живой и мёртвый посторонние процессы.
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.paths import LivecraftPaths, build_paths, ensure_dirs
from app.secretsafe.dpapi import Dpapi
from app.secretsafe.store import ProgramKey, VaultStore

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


@pytest.fixture
def vault_store(livecraft_paths: LivecraftPaths) -> VaultStore:
    """Сейф на временном корне, собранный боевым путём: оба файла из paths, свой ключ и DPAPI этой машины."""
    return VaultStore(
        supplied_path=livecraft_paths.vault_file,
        local_path=livecraft_paths.vault_local_file,
        program_key=ProgramKey.load(livecraft_paths.program_key_file),
        dpapi=Dpapi.load(),
    )


@pytest.fixture
def dead_pid() -> int:
    """Честный номер мёртвого процесса: запускаем python с пустой командой и дожидаемся его конца."""
    child: subprocess.Popen[bytes] = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


@pytest.fixture
def live_foreign_process() -> Iterator[subprocess.Popen[bytes]]:
    """Живой посторонний процесс: его номером занимают замок в проверках «чужой владелец жив»."""
    child: subprocess.Popen[bytes] = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield child
    finally:
        child.kill()
        child.wait()
