"""Папка роли в окне без Tk (app\\setup\\fields\\folder_field.py; CLAUDE.md §14 решение 37): внутри корня — путь
относительно корня, вне корня — абсолютный, «По умолчанию» — имя роли; пишется только своё поле раздела folders."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config.files import SettingsFile
from app.config.setting_key import SettingKey
from app.config.settings import LivecraftSettings
from app.paths import DataDir, LivecraftPaths
from app.setup.fields.folder_field import FolderField
from app.tests.fixtures.settings import set_form_url
from app.ui import messages_ru as msg


def test_a_folder_inside_the_root_is_stored_relative(ready_paths: LivecraftPaths) -> None:
    folder: FolderField = FolderField.from_paths(ready_paths, SettingKey.FOLDERS_PACKAGES)
    assert folder.stored(ready_paths.root / "work" / "packages") == "work/packages"


def test_a_folder_outside_the_root_is_stored_absolute(ready_paths: LivecraftPaths, tmp_path: Path) -> None:
    folder: FolderField = FolderField.from_paths(ready_paths, SettingKey.FOLDERS_DOCS)
    outside: Path = tmp_path / "elsewhere" / "docs"
    assert folder.stored(outside) == str(outside)


@pytest.mark.parametrize(("key", "role"), [
    (SettingKey.FOLDERS_PACKAGES, DataDir.BCAST), (SettingKey.FOLDERS_DOCS, DataDir.DOCS),
    (SettingKey.FOLDERS_IMAGES, DataDir.IMAGE),
])
def test_the_default_is_the_role_name(ready_paths: LivecraftPaths, key: SettingKey, role: DataDir) -> None:
    folder: FolderField = FolderField.from_paths(ready_paths, key)
    assert folder.default == role.value
    chosen: FolderField = folder.choose(ready_paths.root / "other")
    assert chosen.value == "other"
    reset: FolderField = chosen.reset()
    assert reset.value == role.value and reset.place == ready_paths.root / role.value


def test_choosing_writes_only_its_own_field_over_the_file_on_disk(ready_paths: LivecraftPaths, tmp_path: Path) -> None:
    folder: FolderField = FolderField.from_paths(ready_paths, SettingKey.FOLDERS_IMAGES)
    set_form_url(ready_paths, "https://forms.gle/AbCdEf123456")          # записано после чтения модели
    outside: Path = tmp_path / "covers"
    saved: FolderField = folder.choose(outside)
    settings: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert settings.folders.images == str(outside) and settings.folders.packages == DataDir.BCAST.value
    assert settings.form.url == "https://forms.gle/AbCdEf123456"
    assert saved.value == str(outside) and saved.place == outside
    assert saved.status == msg.SETUP_FOLDER_STATUS.format(path=outside)       # вне корня — целиком


def test_the_row_shows_where_the_folder_is(ready_paths: LivecraftPaths) -> None:
    folder: FolderField = FolderField.from_paths(ready_paths, SettingKey.FOLDERS_PACKAGES)
    assert folder.status == msg.SETUP_FOLDER_STATUS.format(path=DataDir.BCAST.value)          # от корня программы
    assert (folder.label, folder.hint) == (
        msg.SETUP_FOLDER_LABELS["folders.packages"], msg.SETUP_FOLDER_HINTS["folders.packages"]
    )
