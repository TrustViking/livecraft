"""Архив папки логов для поддержки (CLAUDE.md §13 задача 7.2, §14 решения 20, 43, 46).

Окно настройщика кладёт его в саму папку логов под именем `livecraft_logs_<DD-MM-YYYY_HHMMSS>.zip` (`ArchiveName`) и,
если есть бот и чат поддержки, отправляет туда. В архиве — `diagnostics.txt` и файлы одной папки (с подпапками, если
они есть), кроме прежних архивов логов, новые первыми по времени изменения: файлы кладутся, пока сумма их исходных
размеров вместе с diagnostics.txt не больше предела; первый не вместившийся и все старше него не входят (`skipped`).
Предел поставки — 45 МБ: запас под предел sendDocument Bot API (50 МБ). Архивируется только данная папка — секреты,
ключи потоков и токены доступа лежат в других папках и в архив не попадают по построению.
"""
from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.core.text_format import TEXT_ENCODING

BYTES_PER_MEGABYTE: Final[int] = 1024 * 1024
LOG_ARCHIVE_LIMIT_MEGABYTES: Final[int] = 45
LOG_ARCHIVE_LIMIT_BYTES: Final[int] = LOG_ARCHIVE_LIMIT_MEGABYTES * BYTES_PER_MEGABYTE
DIAGNOSTICS_FILE_NAME: Final[str] = "diagnostics.txt"


class ArchiveName(str, Enum):
    """Режим записи ZIP, шаблоны поиска файлов папки и имя архива."""

    WRITE_MODE = "w"
    EVERY_NAME = "*"                            # шаблон rglob: все имена вглубь
    TEMPLATE = "livecraft_logs_{stamp}.zip"     # имя архива: {stamp} — момент DD-MM-YYYY_HHMMSS по поясу программы
    OWN_PATTERN = "livecraft_logs_*.zip"        # прежние архивы логов: в новый они не входят


@dataclass(frozen=True)
class LogFile:
    """Файл папки логов: путь, размер и время изменения — одним обращением к диску."""

    path: Path
    size: int
    modified: float

    @classmethod
    def of(cls, path: Path) -> LogFile:
        stat: os.stat_result = path.stat()
        return cls(path=path, size=stat.st_size, modified=stat.st_mtime)


@dataclass(frozen=True)
class PackedLogs:
    """Готовый архив: имя файла, байты ZIP, сколько файлов папки вошло, сколько не вошло за пределом и размер архива."""

    name: str
    data: bytes
    files: int
    skipped: int

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def megabytes(self) -> float:
        return self.size / BYTES_PER_MEGABYTE


@dataclass(frozen=True)
class LogArchive:
    """Архив папки `folder` не больше `limit_bytes` по исходным размерам файлов."""

    folder: Path
    limit_bytes: int

    def pack(self, diagnostics: str, stamp: str) -> PackedLogs:
        """ZIP с `diagnostics.txt` и файлами папки, новыми первыми, до предела; имя — по моменту `stamp`. OSError
        чтения — наружу."""
        name: str = ArchiveName.TEMPLATE.value.format(stamp=stamp)
        text: bytes = diagnostics.encode(TEXT_ENCODING)
        files: tuple[LogFile, ...] = self._files
        chosen: tuple[LogFile, ...] = self._fitting(files, self.limit_bytes - len(text))
        buffer: io.BytesIO = io.BytesIO()
        with zipfile.ZipFile(buffer, ArchiveName.WRITE_MODE.value, compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(DIAGNOSTICS_FILE_NAME, text)
            for file in chosen:
                archive.write(file.path, arcname=file.path.relative_to(self.folder).as_posix())
        return PackedLogs(name=name, data=buffer.getvalue(), files=len(chosen), skipped=len(files) - len(chosen))

    @property
    def _files(self) -> tuple[LogFile, ...]:
        """Файлы папки вглубь, кроме прежних архивов логов, новые первыми."""
        paths: list[Path] = [
            path for path in self.folder.rglob(ArchiveName.EVERY_NAME.value)
            if path.is_file() and not path.match(ArchiveName.OWN_PATTERN.value)
        ]
        found: list[LogFile] = [LogFile.of(path) for path in paths]
        return tuple(sorted(found, key=lambda file: file.modified, reverse=True))

    def _fitting(self, files: tuple[LogFile, ...], budget: int) -> tuple[LogFile, ...]:
        """Файлы `files` (новые первыми), пока их сумма не больше `budget`; первый не вместившийся и все старше —
        нет."""
        chosen: list[LogFile] = []
        for file in files:
            if file.size > budget:
                break
            chosen.append(file)
            budget -= file.size
        return tuple(chosen)
