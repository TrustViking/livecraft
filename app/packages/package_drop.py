"""Пакет, открытый из проводника: `livecraft.exe <файл>.bcast` (CLAUDE.md §10, §14 решения 18, 37).

Файл копируется в папку пакетов из настроек целиком (временный файл рядом и одна замена — читатель полки не увидит
недописанного), затем — обычный запуск по включённым линиям. Файл, который уже лежит в папке пакетов, не копируется.
Не .bcast или файла нет — пакет не открыт: строка с причиной, код 2.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.observability.log_event import LogArea, LogEvent, get_logger
from app.packages.package import TEMP_PREFIX_TEMPLATE
from app.packages.package_shelf import PACKAGE_SUFFIX
from app.paths import AtomicFile, LivecraftPaths
from app.ui.messages import msg

LOGGER = get_logger(LogArea.PACKAGES)


class DropProblem(str, Enum):
    """Почему пакет не открыт; значения — ключи PACKAGE_DROP_PROBLEMS."""

    NOT_PACKAGE = "not_package"     # не .bcast
    MISSING = "missing"             # файла нет


class DropEvent(str, Enum):
    """События открытого пакета в логе."""

    PLACED = "package_placed"
    REFUSED = "package_refused"


@dataclass(frozen=True)
class PackageDropResult:
    """Итог: где пакет лежит в bcast\\ (для людей), скопирован ли он; или почему не открыт."""

    source: Path
    shown: str | None = None
    is_copied: bool = False
    problem: DropProblem | None = None

    @property
    def is_placed(self) -> bool:
        return self.problem is None

    @property
    def console_line(self) -> str:
        if self.problem is not None:
            return msg.PACKAGE_DROP_PROBLEMS[self.problem.value].format(path=self.source)
        template: str = msg.PACKAGE_DROP_COPIED if self.is_copied else msg.PACKAGE_DROP_IN_PLACE
        return template.format(file=self.source.name, path=self.shown)

    @property
    def event(self) -> LogEvent:
        if self.problem is not None:
            return LogEvent.of(DropEvent.REFUSED, source=self.source, problem=self.problem)
        return LogEvent.of(DropEvent.PLACED, source=self.source, target=self.shown, copied=self.is_copied)


@dataclass(frozen=True)
class PackageDrop:
    """Файл пакета из командной строки."""

    source: Path

    def place(self, paths: LivecraftPaths) -> PackageDropResult:
        """Копия в bcast\\; файл уже там — как есть. Строка лога — всегда."""
        result: PackageDropResult = self._placed(paths)
        result.event.emit(LOGGER, logging.INFO if result.is_placed else logging.WARNING)
        return result

    def _placed(self, paths: LivecraftPaths) -> PackageDropResult:
        if self.source.suffix.lower() != PACKAGE_SUFFIX:
            return PackageDropResult(self.source, problem=DropProblem.NOT_PACKAGE)
        if not self.source.is_file():
            return PackageDropResult(self.source, problem=DropProblem.MISSING)
        folder: Path = paths.bcast_dir
        target: Path = folder / self.source.name
        is_in_place: bool = self.source.resolve().parent == folder.resolve()
        if not is_in_place:
            folder.mkdir(parents=True, exist_ok=True)
            atomic: AtomicFile = AtomicFile(target=target, prefix=TEMP_PREFIX_TEMPLATE.format(stem=target.stem))
            atomic.write(lambda temp: shutil.copyfile(self.source, temp))
        return PackageDropResult(self.source, paths.shown(target), is_copied=not is_in_place)
