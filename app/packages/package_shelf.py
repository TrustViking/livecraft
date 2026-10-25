"""Полка bcast\\ — все пакеты режима Б одной картой слотов (CLAUDE.md §14 решение 18; правила planers
`app\\package\\bcast.py`).

Читаются все *.bcast папки (подпапок там нет); пакеты — от старого к новому по моменту сборки, затем по имени файла;
тот же slot_id из более нового пакета побеждает — у слота форма и обложки его пакета. Прошедшее — по «сейчас»
программы: старт не позже «сейчас». Непрочитанный пакет — отказ со своей причиной, остальные читаются.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, tzinfo
from enum import Enum
from pathlib import Path
from typing import Final

from app.observability.log_event import LogArea, LogEvent, get_logger
from app.packages.package_file import PackageFailure, PackageFile, ReadPackage
from app.packages.package_line import PackageLines
from app.packages.package_slot import PackageSlot
from app.slots.slot import SlotEntry

LOGGER = get_logger(LogArea.PACKAGES)

PACKAGE_SUFFIX: Final[str] = ".bcast"
PACKAGE_GLOB: Final[str] = "*" + PACKAGE_SUFFIX


class ShelfEvent(str, Enum):
    """События полки в логе."""

    SCANNED = "bcast_scanned"
    SUPERSEDED = "slot_superseded"


@dataclass(frozen=True)
class PackageShelf:
    """Пакеты bcast\\ (от старого к новому), отказы, будущие слоты (новее побеждает; по порядку слотов) и прошедшие
    записи слотов (так же)."""

    packages: tuple[ReadPackage, ...] = ()
    failures: tuple[PackageFailure, ...] = ()
    slots: tuple[PackageSlot, ...] = ()
    past: tuple[SlotEntry, ...] = ()

    @classmethod
    def read(cls, folder: Path, zone: tzinfo, now: datetime) -> PackageShelf:
        """Все пакеты папки: прочитанные сливаются в одну карту слотов, отказы — отдельно."""
        packages: list[ReadPackage] = []
        failures: list[PackageFailure] = []
        for path in sorted(path for path in folder.glob(PACKAGE_GLOB) if path.is_file()):
            read: ReadPackage | PackageFailure = PackageFile(path, zone, now).read()
            if isinstance(read, PackageFailure):
                failures.append(read)
            else:
                packages.append(read)
        packages.sort(key=lambda package: (package.generated_at, package.path.name))
        shelf: PackageShelf = cls(tuple(packages), tuple(failures))._merged()
        shelf.event.emit(LOGGER)
        return shelf

    def _merged(self) -> PackageShelf:
        """Одна карта слотов: пакеты от старого к новому, тот же slot_id из более нового пакета заменяет прежний."""
        future: dict[str, PackageSlot] = {}
        past: dict[str, SlotEntry] = {}
        owners: dict[str, Path] = {}
        for package in self.packages:
            for slot_id in package.slot_ids:
                previous: Path | None = owners.get(slot_id)
                if previous is not None:
                    superseded: LogEvent = LogEvent.of(ShelfEvent.SUPERSEDED, slot=slot_id, old_package=previous.name)
                    superseded.extended(new_package=package.path.name).emit(LOGGER)
                owners[slot_id] = package.path
            future.update((item.slot.slot_id, item) for item in package.future)
            past.update((entry.slot_id, entry) for entry in package.past)
        return PackageShelf(
            packages=self.packages,
            failures=self.failures,
            slots=tuple(sorted(future.values(), key=lambda item: item.slot.key.sort_key)),
            past=tuple(sorted(past.values(), key=lambda entry: entry.key.sort_key)),
        )

    @property
    def is_empty(self) -> bool:
        """В папке нет ни одного файла пакета."""
        return not self.packages and not self.failures

    @property
    def known(self) -> dict[str, datetime]:
        """slot_id → старт всех слотов полки, будущих и прошедших: эфир прошедшего слота на своей минуте — не сирота,
        эфир известного слота на другой минуте — «перенесён»."""
        known: dict[str, datetime] = {entry.slot_id: entry.start for entry in self.past}
        known.update((item.slot.slot_id, item.slot.start) for item in self.slots)
        return known

    def lines(self, languages: Collection[str]) -> PackageLines:
        """Строки пакетов: прочитанные (от старого к новому), затем непрочитанные; «мои» слоты — языков каналов."""
        return PackageLines(
            (*(package.line(languages) for package in self.packages), *(failure.line for failure in self.failures))
        )

    @property
    def event(self) -> LogEvent:
        scanned: LogEvent = LogEvent.of(ShelfEvent.SCANNED, packages=len(self.packages), problems=len(self.failures))
        all_past: int = sum(1 for package in self.packages if not package.future)
        return scanned.extended(active_slots=len(self.slots), past_slots=len(self.past), all_past_packages=all_past)
