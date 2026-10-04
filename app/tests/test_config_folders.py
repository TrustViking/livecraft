"""Раздел folders livecraft.json (app\\config\\folders.py, §14 решение 37) и папки ролей в путях программы
(app\\paths.py::DataFolders): поставочный вид, относительная и абсолютная папка, пустое значение, дописывание
раздела."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config.files import SettingsFile, ShippedSettings
from app.config.folders import FolderSettings
from app.config.json_node import ConfigError, ConfigProblem
from app.config.settings import LivecraftSettings
from app.core.text_format import TEXT_ENCODING
from app.paths import DataDir, DataFolders, FileName, LivecraftPaths
from app.tests.fixtures.config import settings_data, settings_error, write_json

SHIPPED: LivecraftSettings = ShippedSettings().settings


def test_the_shipped_folders_are_the_role_names_in_the_root() -> None:
    assert SHIPPED.folders == FolderSettings(packages="bcast", docs="docs", images="image")
    assert SHIPPED.folders.data_folders == DataFolders()


def test_without_chosen_folders_the_paths_are_the_role_names_in_the_root(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    assert paths.bcast_dir == tmp_path / "bcast"
    assert paths.dir(DataDir.DOCS) == tmp_path / "docs" and paths.dir(DataDir.IMAGE) == tmp_path / "image"
    assert paths.with_folders(SHIPPED.folders.data_folders) == paths


def test_a_relative_folder_is_from_the_root_and_an_absolute_one_as_it_is(tmp_path: Path) -> None:
    elsewhere: Path = tmp_path / "elsewhere" / "copies"
    folders: FolderSettings = FolderSettings(packages="shared/packages", docs=str(elsewhere), images="image")
    paths: LivecraftPaths = LivecraftPaths(tmp_path / "root").with_folders(folders.data_folders)
    assert paths.bcast_dir == tmp_path / "root" / "shared" / "packages"
    assert paths.doc_copy_file("28-09-2026", "doc.docx") == elsewhere / "28-09-2026" / "doc.docx"
    assert paths.dir(DataDir.IMAGE) == tmp_path / "root" / "image"
    assert paths.file(FileName.KEYS) == tmp_path / "root" / "keystreams" / "keys.txt"     # прочие роли не выбираются
    assert paths.shown(elsewhere / "28-09-2026" / "doc.docx") == str(elsewhere / "28-09-2026" / "doc.docx")
    assert paths.shown(paths.bcast_dir / "plan.bcast") == str(Path("shared", "packages", "plan.bcast"))


def test_ensure_dirs_makes_the_chosen_folders(tmp_path: Path) -> None:
    elsewhere: Path = tmp_path / "elsewhere" / "packages"
    folders: FolderSettings = FolderSettings(packages=str(elsewhere), docs="copies", images="image")
    LivecraftPaths(tmp_path / "root").with_folders(folders.data_folders).ensure_dirs()
    assert elsewhere.is_dir() and (tmp_path / "root" / "copies").is_dir()
    assert not (tmp_path / "root" / "bcast").exists() and not (tmp_path / "root" / "docs").exists()


def test_the_section_round_trips_through_the_file(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["folders"] = {"packages": "D:/Shared/Packages", "docs": "copies", "images": "previews"}
    file: SettingsFile = SettingsFile(write_json(tmp_path / "livecraft.json", data))
    settings: LivecraftSettings = file.load()
    assert settings.folders == FolderSettings(packages="D:/Shared/Packages", docs="copies", images="previews")
    assert settings.to_data()["folders"] == data["folders"]


def test_an_empty_folder_is_an_error_with_its_path(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["folders"]["docs"] = "  "
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.reason) == ("folders.docs", ConfigProblem.INVALID)


def test_a_missing_folder_of_the_section_is_named(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    del data["folders"]["images"]
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.reason) == ("folders.images", ConfigProblem.FIELD_MISSING)


def test_a_file_without_the_section_gets_it_from_the_template(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    del data["folders"]
    file: SettingsFile = SettingsFile(write_json(tmp_path / "livecraft.json", data))
    assert file.complete_sections() == ("folders",)
    assert file.load().folders == SHIPPED.folders
    assert list(json.loads(file.path.read_text(encoding=TEXT_ENCODING))) == list(settings_data())
