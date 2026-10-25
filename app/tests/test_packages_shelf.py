"""Полка bcast\\ — правила planers `bcast.py` на объектах livecraft: одна карта слотов, новее побеждает, прошедшие
отдельно (режим Б, §14 решение 18)."""
from __future__ import annotations

from pathlib import Path

from app.packages.package_file import PackageFault
from app.packages.package_line import PackageLine, PackageLines, PackageLineStatus
from app.packages.package_shelf import PackageShelf
from app.tests.fixtures.packages import KYIV, PACKAGE_FORM_URL, PACKAGE_NOW, manifest, slot_record, write_package
from app.ui import messages_ru as msg

OTHER_FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-other-form/viewform"


def shelf_of(folder: Path) -> PackageShelf:
    return PackageShelf.read(folder, KYIV, PACKAGE_NOW)


def test_the_newer_package_wins_for_the_same_slot(tmp_path: Path) -> None:
    """Имена файлов нарочно в обратном порядке: решает момент сборки, а не имя."""
    write_package(tmp_path, manifest(slot_record(title="Старое"), generated_at="13-03-2027 10:15"), "b_old.bcast")
    write_package(tmp_path, manifest(slot_record(title="Новое"), generated_at="14-03-2027 09:00"), "a_new.bcast")
    shelf: PackageShelf = shelf_of(tmp_path)
    assert [package.path.name for package in shelf.packages] == ["b_old.bcast", "a_new.bcast"]
    [item] = shelf.slots
    assert (item.slot.slot_id, item.slot.title) == ("17-03-2027_1900_uk", "Новое")


def test_the_winning_slot_keeps_the_form_of_its_own_package(tmp_path: Path) -> None:
    """У каждого слота — форма его пакета: слот, который новый пакет не заменил, остаётся с формой старого."""
    old: Path = write_package(
        tmp_path,
        manifest(slot_record(), slot_record("18-03-2027"), generated_at="13-03-2027 10:15", form_url=OTHER_FORM_URL),
        "old.bcast",
    )
    write_package(tmp_path, manifest(slot_record(), generated_at="14-03-2027 09:00"), "new.bcast")
    forms: dict[str, str] = {item.slot.slot_id: item.form.url for item in shelf_of(tmp_path).slots}
    assert forms == {"17-03-2027_1900_uk": PACKAGE_FORM_URL, "18-03-2027_1900_uk": OTHER_FORM_URL}
    assert old.exists()


def test_past_slots_leave_the_map(tmp_path: Path) -> None:
    write_package(tmp_path, manifest(slot_record("15-03-2027"), slot_record("17-03-2027")))
    shelf: PackageShelf = shelf_of(tmp_path)
    assert [item.slot.slot_id for item in shelf.slots] == ["17-03-2027_1900_uk"]
    assert [entry.slot_id for entry in shelf.past] == ["15-03-2027_1900_uk"]
    assert set(shelf.known) == {"15-03-2027_1900_uk", "17-03-2027_1900_uk"}
    assert shelf.known["15-03-2027_1900_uk"] == shelf.past[0].start


def test_the_slots_follow_the_slot_order(tmp_path: Path) -> None:
    write_package(tmp_path, manifest(slot_record("18-03-2027"), slot_record(language="en"), slot_record()))
    assert [item.slot.slot_id for item in shelf_of(tmp_path).slots] == [
        "17-03-2027_1900_uk", "17-03-2027_1900_en", "18-03-2027_1900_uk"
    ]


def test_a_package_with_only_past_slots_is_all_past(tmp_path: Path) -> None:
    path: Path = write_package(tmp_path, manifest(slot_record("14-03-2027"), slot_record("15-03-2027")))
    shelf: PackageShelf = shelf_of(tmp_path)
    assert shelf.slots == () and not shelf.is_empty
    assert shelf.lines(("uk",)).lines == (PackageLine(path.name, PackageLineStatus.ALL_PAST),)


def test_a_damaged_file_is_a_failure_and_stays_in_place(tmp_path: Path) -> None:
    broken: Path = tmp_path / "broken.bcast"
    broken.write_bytes(b"not a zip")
    good: Path = write_package(tmp_path)
    shelf: PackageShelf = shelf_of(tmp_path)
    [failure] = shelf.failures
    assert (failure.file, failure.fault) == (broken, PackageFault.NOT_ZIP) and broken.exists()
    assert [package.path for package in shelf.packages] == [good] and len(shelf.slots) == 1
    lines: PackageLines = shelf.lines(("uk",))
    assert [line.status for line in lines.lines] == [PackageLineStatus.ACCEPTED, PackageLineStatus.DAMAGED]
    assert [line.file_name for line in lines.unreadable] == ["broken.bcast"]


def test_subfolders_and_other_files_are_not_read(tmp_path: Path) -> None:
    """Пакеты читаются одним списком из корня bcast\\; вложенные папки и чужие файлы — не пакеты."""
    write_package(tmp_path / "old")
    (tmp_path / "notes.txt").write_text("не пакет", encoding="utf-8")
    shelf: PackageShelf = shelf_of(tmp_path)
    assert shelf.is_empty and shelf.slots == () and shelf.known == {}


def test_the_progress_line_counts_the_accepted_packages(tmp_path: Path) -> None:
    write_package(tmp_path, manifest(slot_record(), slot_record(language="ru")), "a.bcast")
    (tmp_path / "b.bcast").write_bytes(b"not a zip")
    lines: PackageLines = shelf_of(tmp_path).lines(("uk",))
    assert lines.progress_line == msg.PROGRESS_PACKAGES_READ.format(packages=2, slots_total=2, slots_mine=1)
