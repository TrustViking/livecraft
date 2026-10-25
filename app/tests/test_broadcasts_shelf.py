"""Строки полки bcast\\ при входе «Пакеты»: консоль — итог одной строкой, отчёт — пакет за пакетом (§14 решения 18, 51).
"""
from __future__ import annotations

from pathlib import Path

from app.broadcasts.shelf import ShelfRead
from app.packages.package_shelf import PackageShelf
from app.tests.fixtures.packages import KYIV, PACKAGE_NOW, manifest, slot_record, write_package
from app.ui import messages_ru as msg

FOLDER: str = "bcast"


def _shelf(folder: Path) -> PackageShelf:
    """Три файла: старый и новый пакет с общим слотом и повреждённый."""
    write_package(folder, manifest(slot_record(), slot_record("18-03-2027"), generated_at="13-03-2027 10:15"), "a.bcast")
    write_package(folder, manifest(slot_record(), generated_at="14-03-2027 09:00"), "b.bcast")
    (folder / "c.bcast").write_bytes(b"not a zip")
    return PackageShelf.read(folder, KYIV, PACKAGE_NOW)


def test_without_broadcasts_the_console_gets_one_summary_line_and_the_unread_packages(tmp_path: Path) -> None:
    """В bcast\\ копятся десятки пакетов: строка на каждый в консоли — шум; итог — файлы и слоты после вытеснения."""
    shelf: PackageShelf = _shelf(tmp_path)
    [failure] = shelf.failures
    assert ShelfRead(shelf, FOLDER).console_lines == (
        msg.SHELF_SUMMARY.format(path=FOLDER, packages=3, slots=2),
        msg.CONSOLE_ATTENTION_PACKAGE.format(text=failure.line.text),
    )


def test_without_broadcasts_the_report_names_every_package(tmp_path: Path) -> None:
    shelf: PackageShelf = _shelf(tmp_path)
    [failure] = shelf.failures
    assert ShelfRead(shelf, FOLDER).part_report.body == (
        msg.SHELF_PACKAGE_ACCEPTED.format(file="a.bcast", slots=2),
        msg.SHELF_PACKAGE_ACCEPTED.format(file="b.bcast", slots=1),
        failure.line.text,
    )


def test_with_broadcasts_the_shelf_says_nothing_itself(tmp_path: Path) -> None:
    """Эфиры идут — пакеты называют строка прогресса и часть эфиров."""
    read: ShelfRead = ShelfRead(_shelf(tmp_path), FOLDER, ("uk",))
    assert read.console_lines == ()
    assert read.part_report.body == ()
