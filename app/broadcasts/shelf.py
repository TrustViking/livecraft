"""Вход «Пакеты»: полка bcast\\ и её строки (CLAUDE.md §10, §14 решения 18, 51; поведение — runner planers
`_run_bcast`).

Полка читается по «сейчас» программы — и без каналов: слоты пакетов нужны и выводу. Строка прогресса о пакетах — сразу,
если в папке есть хоть один файл; слоты языков каналов в строках пакетов считаются, только когда идут эфиры (каналы
прочитаны). Нет файлов или нет будущих слотов — строка и код 3, дальше не идём; непрочитанные пакеты тогда — строками
внимания здесь же. Иначе слоты полки идут в вывод и в часть «эфиры»; пакеты называет отчёт и консоль эфиров, а когда
эфиры не идут — строки полки. Часть отчёта запуска «Пакеты» — строки полки (`part_report`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.broadcasts.run import BroadcastSlots
from app.config.channel import ConfiguredChannels
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.packages.package_line import PackageLines
from app.packages.package_shelf import PackageShelf
from app.paths import LivecraftPaths
from app.pipeline.progress import RunProgress
from app.run.exit_code import RunOutcome
from app.run.report_section import PartReport
from app.ui.messages import msg


@dataclass(frozen=True)
class ShelfRead:
    """Полка, папка bcast\\ для людей и языки каналов (эфиры не идут — None)."""

    shelf: PackageShelf
    folder: str
    languages: tuple[str, ...] | None = None

    @classmethod
    def read(
        cls,
        paths: LivecraftPaths,
        settings: LivecraftSettings,
        channels: ConfiguredChannels | None,
        progress: RunProgress,
    ) -> ShelfRead:
        """Все пакеты bcast\\ по «сейчас» в поясе программы; в папке есть файлы — строка прогресса. Эфиры не идут
        (`channels` — None) — слоты языков каналов не считаются."""
        now: datetime = Clock(settings.zone).now()
        shelf: PackageShelf = PackageShelf.read(paths.bcast_dir, settings.zone, now)
        languages: tuple[str, ...] | None = None if channels is None else channels.served_languages
        read: ShelfRead = cls(shelf, paths.shown(paths.bcast_dir), languages)
        if not shelf.is_empty and read.languages is not None:
            progress.packages_read(read.lines)
        return read

    @property
    def lines(self) -> PackageLines:
        """Строки пакетов: слоты — всего и языков каналов (эфиры не идут — языков нет)."""
        return self.shelf.lines(self.languages or ())

    @property
    def has_slots(self) -> bool:
        """Есть будущие слоты — есть работа для части «эфиры»."""
        return bool(self.shelf.slots)

    @property
    def outcome(self) -> RunOutcome:
        return RunOutcome.DONE if self.has_slots else RunOutcome.NOTHING_PLANNED

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Нет файлов — одна строка; нет будущих слотов — непрочитанные пакеты и строка о слотах; эфиры идут — ничего:
        пакеты назовут отчёт и консоль части «эфиры»; не идут — итог полки одной строкой и непрочитанные пакеты (в
        bcast\\ их копятся десятки: строка на пакет — шум; полный список — в отчёте)."""
        if self.shelf.is_empty:
            return (msg.BCAST_EMPTY.format(path=self.folder),)
        if self.has_slots:
            return () if self.languages is not None else (self._summary_line, *self._problem_lines)
        return (*self._problem_lines, msg.BCAST_NO_FUTURE_SLOTS.format(path=self.folder))

    @property
    def _summary_line(self) -> str:
        """Сколько файлов пакетов в папке и сколько будущих слотов после вытеснения (новее побеждает)."""
        packages: int = len(self.shelf.packages) + len(self.shelf.failures)
        return msg.SHELF_SUMMARY.format(path=self.folder, packages=packages, slots=len(self.shelf.slots))

    @property
    def _problem_lines(self) -> tuple[str, ...]:
        """Непрочитанные пакеты — строками внимания."""
        return tuple(msg.CONSOLE_ATTENTION_PACKAGE.format(text=line.text) for line in self.lines.unreadable)

    @property
    def _package_lines(self) -> tuple[str, ...]:
        """Эфиры не идут — пакеты называет полка: принятый — число будущих слотов, прочие — строкой пакета."""
        read: tuple[str, ...] = tuple(
            msg.SHELF_PACKAGE_ACCEPTED.format(file=package.path.name, slots=len(package.future))
            if package.future else package.line(()).text
            for package in self.shelf.packages
        )
        return (*read, *(failure.line.text for failure in self.shelf.failures))

    @property
    def part_report(self) -> PartReport:
        """Часть «Пакеты» отчёта запуска: эфиры не идут — строка на каждый пакет; иначе строки консоли полки (есть
        будущие слоты и эфиры идут — строк нет, и пакеты называет часть эфиров)."""
        if self.has_slots and self.languages is None:
            return PartReport(msg.REPORT_PART_SHELF, self._package_lines)
        return PartReport(msg.REPORT_PART_SHELF, self.console_lines)

    @property
    def slots(self) -> BroadcastSlots:
        return BroadcastSlots.of_shelf(self.shelf, self.lines)
