"""Архив папки логов для поддержки (§13 задача 7.2, §14 решения 20, 46): новые файлы первыми до предела, diagnostics.txt
внутри, в архиве — только файлы данной папки и без прежних архивов логов; имя — по моменту."""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from app.paths import DataDir, LivecraftPaths
from app.runtime.log_archive import LOG_ARCHIVE_LIMIT_BYTES, LogArchive, PackedLogs

DIAGNOSTICS: str = "diagnostics_program version=7.2\n"
STAMP: str = "29-09-2026_150000"
ARCHIVE: str = "livecraft_logs_29-09-2026_150000.zip"
EPOCH: int = 1_790_000_000


def _log(folder: Path, name: str, size: int, age: int) -> Path:
    """Файл логов размером `size` байт, изменённый `age` секунд назад относительно EPOCH."""
    path: Path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (EPOCH - age, EPOCH - age))
    return path


def _names(packed: PackedLogs) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(packed.data)) as archive:
        return archive.namelist()


def test_the_newest_files_go_first_up_to_the_limit(tmp_path: Path) -> None:
    """Новые файлы кладутся, пока сумма с diagnostics.txt не больше предела; первый не вместившийся и все старше —
    нет, даже если старый файл поместился бы."""
    _log(tmp_path, "new.log", 40, age=0)
    _log(tmp_path, "middle.log", 40, age=10)
    _log(tmp_path, "big.log", 60, age=20)
    _log(tmp_path, "old.log", 1, age=30)
    limit: int = 40 + 40 + len(DIAGNOSTICS.encode())
    packed: PackedLogs = LogArchive(tmp_path, limit).pack(DIAGNOSTICS, STAMP)
    assert _names(packed) == ["diagnostics.txt", "new.log", "middle.log"]
    assert (packed.name, packed.files, packed.skipped, packed.size) == (ARCHIVE, 2, 2, len(packed.data))


def test_diagnostics_are_inside_and_subfolders_keep_their_path(tmp_path: Path) -> None:
    _log(tmp_path, "run.log", 5, age=0)
    _log(tmp_path / "forms", "page.html", 5, age=5)
    packed: PackedLogs = LogArchive(tmp_path, LOG_ARCHIVE_LIMIT_BYTES).pack(DIAGNOSTICS, STAMP)
    with zipfile.ZipFile(io.BytesIO(packed.data)) as archive:
        assert archive.read("diagnostics.txt").decode("utf-8") == DIAGNOSTICS
        assert archive.namelist() == ["diagnostics.txt", "run.log", "forms/page.html"]
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())
    assert (packed.files, packed.skipped) == (2, 0)


def test_only_the_logs_folder_goes_into_the_archive(livecraft_paths: LivecraftPaths) -> None:
    """Файлы соседних папок корня — сейф, ключи потоков, токены доступа — в архив не попадают по построению."""
    livecraft_paths.ensure_dirs()
    _log(livecraft_paths.dir(DataDir.LOGS), "run.log", 5, age=0)
    for folder in (DataDir.SECRETS, DataDir.TOKENS, DataDir.KEYSTREAMS):
        _log(livecraft_paths.dir(folder), "private.dat", 5, age=0)
    packed: PackedLogs = LogArchive(livecraft_paths.dir(DataDir.LOGS), LOG_ARCHIVE_LIMIT_BYTES).pack(DIAGNOSTICS, STAMP)
    assert _names(packed) == ["diagnostics.txt", "run.log"]


def test_an_empty_folder_gives_the_diagnostics_alone(tmp_path: Path) -> None:
    packed: PackedLogs = LogArchive(tmp_path, LOG_ARCHIVE_LIMIT_BYTES).pack(DIAGNOSTICS, STAMP)
    assert _names(packed) == ["diagnostics.txt"] and (packed.files, packed.skipped) == (0, 0)


def test_previous_log_archives_do_not_go_into_the_new_one(tmp_path: Path) -> None:
    """Архив ложится в саму папку логов (§14 решение 46): прежние архивы в новый не входят, остальные файлы — да."""
    _log(tmp_path, "livecraft_logs_28-09-2026_120000.zip", 5, age=0)
    _log(tmp_path, "run.log", 5, age=5)
    _log(tmp_path, "notes.zip", 5, age=10)
    packed: PackedLogs = LogArchive(tmp_path, LOG_ARCHIVE_LIMIT_BYTES).pack(DIAGNOSTICS, STAMP)
    assert _names(packed) == ["diagnostics.txt", "run.log", "notes.zip"]
    assert (packed.name, packed.files, packed.skipped) == (ARCHIVE, 2, 0)
