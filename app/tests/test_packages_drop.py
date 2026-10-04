"""Пакет, открытый из проводника (`livecraft.exe <файл>.bcast`): копия в bcast\\ целиком (§14 решение 18)."""
from __future__ import annotations

from pathlib import Path

from app.packages.package_drop import DropProblem, PackageDrop, PackageDropResult
from app.paths import LivecraftPaths
from app.tests.fixtures.packages import write_package
from app.ui import messages_ru as msg


def test_a_package_from_elsewhere_is_copied_into_bcast(livecraft_paths: LivecraftPaths, tmp_path: Path) -> None:
    source: Path = write_package(tmp_path / "downloads", name="plan_17-03-2027.bcast")
    result: PackageDropResult = PackageDrop(source).place(livecraft_paths)
    target: Path = livecraft_paths.bcast_dir / source.name
    assert result.is_placed and result.is_copied and target.read_bytes() == source.read_bytes()
    assert result.console_line == msg.PACKAGE_DROP_COPIED.format(path=livecraft_paths.shown(target))
    assert [path.name for path in livecraft_paths.bcast_dir.iterdir()] == [source.name]     # временного файла нет


def test_a_package_already_in_bcast_is_not_copied(livecraft_paths: LivecraftPaths) -> None:
    source: Path = write_package(livecraft_paths.bcast_dir)
    before: int = source.stat().st_mtime_ns
    result: PackageDropResult = PackageDrop(source).place(livecraft_paths)
    assert result.is_placed and not result.is_copied and source.stat().st_mtime_ns == before
    assert result.console_line == msg.PACKAGE_DROP_IN_PLACE.format(path=livecraft_paths.shown(source))


def test_a_file_that_is_not_a_package_is_not_opened(livecraft_paths: LivecraftPaths, tmp_path: Path) -> None:
    source: Path = tmp_path / "plan.zip"
    source.write_bytes(b"PK")
    result: PackageDropResult = PackageDrop(source).place(livecraft_paths)
    assert result.problem is DropProblem.NOT_PACKAGE and not result.is_placed
    assert result.console_line == msg.PACKAGE_DROP_PROBLEMS["not_package"].format(path=source)
    assert not any(livecraft_paths.bcast_dir.glob("*"))


def test_a_missing_file_is_not_opened(livecraft_paths: LivecraftPaths, tmp_path: Path) -> None:
    source: Path = tmp_path / "gone.bcast"
    result: PackageDropResult = PackageDrop(source).place(livecraft_paths)
    assert result.problem is DropProblem.MISSING
    assert result.console_line == msg.PACKAGE_DROP_PROBLEMS["missing"].format(path=source)


def test_the_suffix_is_matched_without_case(livecraft_paths: LivecraftPaths, tmp_path: Path) -> None:
    source: Path = write_package(tmp_path, name="PLAN.BCAST")
    assert PackageDrop(source).place(livecraft_paths).is_copied
