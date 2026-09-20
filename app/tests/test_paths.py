from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from app import paths as paths_module
from app.paths import (
    ROOT_ENV_VAR,
    TEMP_FILE_SUFFIX,
    LivecraftPaths,
    build_paths,
    ensure_dirs,
    resolve_root,
    write_text_atomically,
)

ENCODING: str = "utf-8"
# Каждое поле объекта путей — относительно корня (CLAUDE.md §5). Правка §5 должна ронять этот тест.
EXPECTED_LAYOUT: dict[str, str] = {
    "root": ".",
    "secrets_dir": "secrets",
    "config_file": "secrets/livecraft.json",
    "channels_file": "secrets/channels.json",
    "channels_previous_file": "secrets/channels.previous.json",
    "channels_passport_file": "secrets/channels_passport.json",
    "client_secret_file": "secrets/client_secret.json",
    "sheets_token_file": "secrets/sheets.token.json",
    "cookies_file": "secrets/cookies.txt",
    "records_file": "secrets/livecraft.sqlite3",
    "vault_file": "secrets/vault.dat",
    "vault_local_file": "secrets/vault.local.dat",
    "program_key_file": "secrets/program.key",
    "tools_dir": "tools",
    "ytdlp_exe": "tools/yt-dlp.exe",
    "deno_exe": "tools/deno.exe",
    "image_dir": "image",
    "keystreams_dir": "keystreams",
    "keys_file": "keystreams/keys.txt",
    "state_dir": "state",
    "lock_file": "state/livecraft.lock",
    "logs_dir": "logs",
    "startup_log_file": "logs/startup.log",
}
EXPECTED_DIRECTORIES: tuple[str, ...] = ("secrets", "tools", "image", "keystreams", "state", "logs")


def test_root_comes_from_the_environment_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Подмена корня — только для тестов и отладки, но именно так корень задают все тесты запуска."""
    monkeypatch.setenv(ROOT_ENV_VAR, str(tmp_path))
    assert resolve_root() == tmp_path.resolve()


def test_blank_environment_variable_falls_back_to_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, "   ")
    assert resolve_root() == Path(paths_module.__file__).resolve().parents[1]


def test_without_the_variable_the_root_is_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev-режим: корень — родитель app\\, то есть корень репо; в нём и лежит livecraft.bat."""
    monkeypatch.delenv(ROOT_ENV_VAR, raising=False)
    root: Path = resolve_root()
    assert root == Path(paths_module.__file__).resolve().parents[1]
    assert (root / "app" / "main.py").is_file()


def test_frozen_build_keeps_data_next_to_the_exe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В собранной программе корень — папка exe: данные оператора лежат рядом с ней (CLAUDE.md §5)."""
    monkeypatch.delenv(ROOT_ENV_VAR, raising=False)
    monkeypatch.setattr(paths_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths_module.sys, "executable", str(tmp_path / "livecraft.exe"))
    assert resolve_root() == tmp_path.resolve()


def test_every_path_sits_where_section_five_says(tmp_path: Path) -> None:
    paths: LivecraftPaths = build_paths(tmp_path)
    actual: dict[str, str] = {
        field.name: Path(getattr(paths, field.name)).relative_to(tmp_path).as_posix()
        for field in dataclasses.fields(paths)
    }
    assert actual == EXPECTED_LAYOUT


def test_paths_object_is_frozen(tmp_path: Path) -> None:
    """Пути — не настройка на ходу: подменить их можно только новым объектом."""
    paths: LivecraftPaths = build_paths(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.root = tmp_path / "other"          # type: ignore[misc]


def test_directories_are_the_five_data_folders_plus_tools(tmp_path: Path) -> None:
    paths: LivecraftPaths = build_paths(tmp_path)
    assert tuple(item.name for item in paths.directories) == EXPECTED_DIRECTORIES


def test_ensure_dirs_creates_exactly_the_directories(tmp_path: Path) -> None:
    """Папки создаются, файлы в них — нет: конфиги и сейф пишет настройщик (CLAUDE.md §8)."""
    root: Path = tmp_path / "root"
    paths: LivecraftPaths = build_paths(root)
    ensure_dirs(paths)
    assert sorted(item.name for item in root.iterdir()) == sorted(EXPECTED_DIRECTORIES)
    assert all(directory.is_dir() for directory in paths.directories)
    assert all(list(directory.iterdir()) == [] for directory in paths.directories)


def test_ensure_dirs_repeats_without_complaint(tmp_path: Path) -> None:
    paths: LivecraftPaths = build_paths(tmp_path / "root")
    ensure_dirs(paths)
    (paths.keystreams_dir / "keys.txt").write_text("", encoding=ENCODING)
    ensure_dirs(paths)
    assert paths.keys_file.is_file()


def test_atomic_write_replaces_the_file_and_leaves_no_temporary(tmp_path: Path) -> None:
    target: Path = tmp_path / "keys.txt"
    target.write_text("прежнее", encoding=ENCODING)
    write_text_atomically(target, "новое\nсодержимое\n", ENCODING)
    assert target.read_text(encoding=ENCODING) == "новое\nсодержимое\n"
    assert [item.name for item in tmp_path.iterdir()] == [target.name]


def test_atomic_write_keeps_line_endings_as_given(tmp_path: Path) -> None:
    """newline="" в записи: перевод строки выбирает тот, кто строит текст, а не Windows."""
    target: Path = tmp_path / "report.md"
    write_text_atomically(target, "первая\nвторая\n", ENCODING)
    assert target.read_bytes() == "первая\nвторая\n".encode(ENCODING)


def test_atomic_write_removes_the_temporary_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сбой замены — OSError наружу, временного файла не остаётся, прежний файл цел."""
    target: Path = tmp_path / "keys.txt"
    target.write_text("прежнее", encoding=ENCODING)

    def _refuse(source: object, destination: object) -> None:
        raise OSError("replace refused")

    monkeypatch.setattr(os, "replace", _refuse)
    with pytest.raises(OSError):
        write_text_atomically(target, "новое", ENCODING)
    assert target.read_text(encoding=ENCODING) == "прежнее"
    assert not any(item.name.endswith(TEMP_FILE_SUFFIX) for item in tmp_path.iterdir())


def test_atomic_write_needs_an_existing_parent_directory(tmp_path: Path) -> None:
    """Папку создаёт ensure_dirs; запись в несуществующую папку — OSError, а не тихое создание."""
    with pytest.raises(OSError):
        write_text_atomically(tmp_path / "missing" / "keys.txt", "текст", ENCODING)


def test_paths_fixture_gives_a_ready_root(livecraft_paths: LivecraftPaths) -> None:
    assert all(directory.is_dir() for directory in livecraft_paths.directories)
    assert not livecraft_paths.config_file.exists() and not livecraft_paths.vault_file.exists()
