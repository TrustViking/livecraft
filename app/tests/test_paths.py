from __future__ import annotations

import dataclasses
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import paths as paths_module
from app.observability.logging_setup import RunLog
from app.paths import (
    REPLACE_RETRY_POLICY,
    ROOT_ENV_VAR,
    TEMP_FILE_SUFFIX,
    AtomicFile,
    DataDir,
    FileName,
    LivecraftPaths,
    write_text_atomically,
)

ENCODING: str = "utf-8"
# Каждый путь, который читает программа, — относительно корня (CLAUDE.md §5). Правка §5 должна ронять этот тест.
EXPECTED_FILES: dict[FileName, str] = {
    FileName.CONFIG: "secrets/livecraft.json",
    FileName.CHANNELS: "secrets/channels.json",
    FileName.CHANNELS_PREVIOUS: "secrets/channels.previous.json",
    FileName.CLIENT_SECRET: "secrets/client_secret.json",
    FileName.SHEETS_TOKEN: "secrets/sheets.token.json",
    FileName.COOKIES: "secrets/cookies.txt",
    FileName.VAULT_LOCAL: "secrets/vault.local.dat",
    FileName.VAULT_TOKEN: "secrets/vault.token.dat",
    FileName.TOKEN_RECEIVED: "secrets/token_received.json",
    FileName.YTDLP: "tools/yt-dlp.exe",
    FileName.DENO: "tools/deno.exe",
    FileName.LOCK: "state/livecraft.lock",
    FileName.YTDLP_CHECK: "state/ytdlp_last_check.json",
    FileName.DENO_CHECK: "state/deno_last_check.json",
    FileName.STARTUP_LOG: "logs/startup.log",
    FileName.RECORDS: "secrets/livecraft.sqlite3",
    FileName.PASSPORT: "secrets/channels_passport.json",
    FileName.KEYS: "keystreams/keys.txt",
    FileName.YTDLP_CACHE: "state/yt-dlp-cache",
    FileName.DENO_CACHE: "state/deno-cache",
}
EXPECTED_DIRS: dict[str, str] = {"logs_dir": "logs", "bcast_dir": "bcast"}
EXPECTED_DIRECTORIES: tuple[str, ...] = (
    "secrets", "tools", "image", "bcast", "docs", "tokens", "keystreams", "state", "logs"
)


def test_root_comes_from_the_environment_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Подмена корня — только для тестов и отладки, но именно так корень задают все тесты запуска."""
    monkeypatch.setenv(ROOT_ENV_VAR, str(tmp_path))
    assert LivecraftPaths.locate() == LivecraftPaths(tmp_path.resolve())


def test_blank_environment_variable_falls_back_to_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, "   ")
    assert LivecraftPaths.locate().root == Path(paths_module.__file__).resolve().parents[1]


def test_without_the_variable_the_root_is_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev-режим: корень — родитель app\\, то есть корень репо; в нём и лежит livecraft.bat."""
    monkeypatch.delenv(ROOT_ENV_VAR, raising=False)
    root: Path = LivecraftPaths.locate().root
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
    assert LivecraftPaths.locate().root == tmp_path.resolve()


def test_every_file_sits_where_section_five_says(tmp_path: Path) -> None:
    """Одно правило «файл в папке данных»: у каждого имени своя папка, у каждой папки — своя роль (§6, инвариант 10)."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    actual: dict[FileName, str] = {name: paths.file(name).relative_to(tmp_path).as_posix() for name in FileName}
    assert actual == EXPECTED_FILES


def test_the_google_project_file_lies_where_the_settings_say(tmp_path: Path) -> None:
    """§14 решение 66: файл проекта — путь из настроек тем же правилом, что папки ролей: относительный — от корня,
    абсолютный — как есть; не выбран — None."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    assert paths.project_file is None
    inside: LivecraftPaths = paths.with_google_project(Path("secrets") / "client.json")
    assert inside.project_file == tmp_path / "secrets" / "client.json"
    outside: Path = tmp_path.parent / "elsewhere" / "any name.json"
    assert paths.with_google_project(outside).project_file == outside
    assert inside.with_folders(paths.folders).project_file == inside.project_file


def test_the_google_project_from_a_token_is_named_by_project_id(tmp_path: Path) -> None:
    """Проект из токена ложится в secrets\\google_project_<ID>.json; подключить при запуске можно только такие файлы без
    «.previous» (прежний проект сборок 9.21)."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    paths.ensure_dirs()
    assert paths.found_project_files == ()
    received: Path = paths.received_project_file("proj-100200")
    assert received.relative_to(tmp_path).as_posix() == "secrets/google_project_proj-100200.json"
    previous: Path = paths.dir(DataDir.SECRETS) / "google_project_guests.previous.json"
    for path in (received, previous, paths.file(FileName.CLIENT_SECRET)):
        path.write_text("{}", encoding=ENCODING)
    assert paths.found_project_files == (received,)
    other: Path = paths.received_project_file("other")
    other.write_text("{}", encoding=ENCODING)
    assert paths.found_project_files == (other, received)


def test_every_directory_property_sits_where_section_five_says(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    actual: dict[str, str] = {name: Path(getattr(paths, name)).relative_to(tmp_path).as_posix() for name in EXPECTED_DIRS}
    assert actual == EXPECTED_DIRS


def test_channel_token_lies_in_secrets_under_its_stem(tmp_path: Path) -> None:
    """Токен владельца канала — secrets\\<имя>.token.json; имя из ника строит ChannelHandle.token_file_stem."""
    token: Path = LivecraftPaths(tmp_path).token_file("@Kanal.X")
    assert token.relative_to(tmp_path).as_posix() == "secrets/@Kanal.X.token.json"


def test_paths_object_is_frozen(tmp_path: Path) -> None:
    """Пути — не настройка на ходу: подменить их можно только новым объектом."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.root = tmp_path / "other"          # type: ignore[misc]


def test_the_data_folders_are_the_roles_plus_tools(tmp_path: Path) -> None:
    """Одна папка данных на роль (§6, инвариант 10) и tools\\ для внешних бинарников."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    assert tuple(folder.value for folder in DataDir) == EXPECTED_DIRECTORIES
    assert all(paths.dir(folder) == tmp_path / folder.value for folder in DataDir)


def test_a_document_copy_lies_in_the_folder_of_its_date(tmp_path: Path) -> None:
    """Копия документа объявлений — docs\\<DD-MM-YYYY>\\<имя файла> (§14 решение 33)."""
    path: Path = LivecraftPaths(tmp_path).doc_copy_file("17-03-2027", "copy.docx")
    assert path == tmp_path / "docs" / "17-03-2027" / "copy.docx"


def test_the_report_is_named_by_the_start_of_the_run_like_the_log(tmp_path: Path) -> None:
    """logs\\<DD-MM-YYYY>_<HHMMSS>_report.md: тот же штамп, что у лога запуска."""
    started: datetime = datetime(2027, 3, 16, 12, 0, 5, tzinfo=ZoneInfo("Europe/Kyiv"))
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    paths.logs_dir.mkdir()
    log: RunLog = RunLog.open(paths.logs_dir, False, started)
    log.close()
    report: Path = paths.report_file(started)
    assert report == tmp_path / "logs" / "16-03-2027_120005_report.md"
    assert log.path.name.removesuffix("_livecraft.log") == report.name.removesuffix("_report.md")


def test_a_path_for_people_starts_at_the_root(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    assert paths.shown(paths.file(FileName.KEYS)) == str(Path("keystreams") / "keys.txt")


def test_ensure_dirs_creates_exactly_the_data_folders(tmp_path: Path) -> None:
    """Папки создаются, файлы в них — нет: конфиги и сейф пишет настройщик (CLAUDE.md §8)."""
    root: Path = tmp_path / "root"
    paths: LivecraftPaths = LivecraftPaths(root)
    paths.ensure_dirs()
    assert sorted(item.name for item in root.iterdir()) == sorted(EXPECTED_DIRECTORIES)
    assert all(list(paths.dir(folder).iterdir()) == [] for folder in DataDir)


def test_ensure_dirs_repeats_without_complaint(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path / "root")
    paths.ensure_dirs()
    keys: Path = paths.dir(DataDir.KEYSTREAMS) / "keys.txt"
    keys.write_text("", encoding=ENCODING)
    paths.ensure_dirs()
    assert keys.is_file()


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


def test_atomic_write_removes_the_temporary_when_replace_fails(tmp_path: Path) -> None:
    """Сбой замены (имя цели занято непустой папкой) — OSError наружу, временного файла не остаётся."""
    target: Path = tmp_path / "keys.txt"
    target.mkdir()
    (target / "inside.txt").write_text("прежнее", encoding=ENCODING)
    with pytest.raises(OSError):
        write_text_atomically(target, "новое", ENCODING)
    assert (target / "inside.txt").read_text(encoding=ENCODING) == "прежнее"
    assert not any(item.name.endswith(TEMP_FILE_SUFFIX) for item in tmp_path.iterdir())


def test_atomic_file_writes_what_the_filler_wrote(tmp_path: Path) -> None:
    """Содержимое пишет вызывающий — во временный файл рядом; на место цели он встаёт целиком."""
    target: Path = tmp_path / "plan.bcast"
    AtomicFile(target=target, prefix=".plan_").write(lambda path: path.write_bytes(b"PK"))
    assert target.read_bytes() == b"PK"
    assert [item.name for item in tmp_path.iterdir()] == [target.name]


def test_atomic_file_removes_the_temporary_when_the_filler_fails(tmp_path: Path) -> None:
    """Сбой записи — ошибка наружу, прежний файл цел, временного файла нет."""
    target: Path = tmp_path / "plan.bcast"
    target.write_bytes(b"old")

    def fail(path: Path) -> None:
        path.write_bytes(b"half")
        raise OSError("disk full")

    with pytest.raises(OSError):
        AtomicFile(target=target, prefix=".plan_").write(fail)
    assert target.read_bytes() == b"old"
    assert [item.name for item in tmp_path.iterdir()] == [target.name]


def test_atomic_file_names_the_temporary_by_its_prefix(tmp_path: Path) -> None:
    """Временный файл лежит рядом с целью и начинается с приставки: недописанное видно по имени."""
    target: Path = tmp_path / "keys.txt"
    seen: list[str] = []
    AtomicFile.at(target).write(lambda path: seen.append(path.name) or path.write_text("", encoding=ENCODING))
    assert seen[0].startswith(target.name) and seen[0].endswith(TEMP_FILE_SUFFIX)


def test_a_busy_target_is_replaced_once_the_reader_lets_it_go(tmp_path: Path) -> None:
    """Windows не меняет файл, открытый другим: замена повторяется после короткой паузы; читатель отпустил файл после
    второй паузы — на месте новый файл, временного нет."""
    target: Path = tmp_path / "vault.local.dat"
    target.write_text("прежнее", encoding=ENCODING)
    reader = target.open(encoding=ENCODING)
    pauses: list[float] = []

    def sleep(seconds: float) -> None:
        pauses.append(seconds)
        if len(pauses) == 2:
            reader.close()

    AtomicFile(target=target, prefix=target.name, sleep=sleep).write_text("новое", ENCODING)
    assert len(pauses) == 2 and max(pauses) <= REPLACE_RETRY_POLICY.max_delay_sec
    assert target.read_text(encoding=ENCODING) == "новое"
    assert [item.name for item in tmp_path.iterdir()] == [target.name]


def test_a_target_busy_for_too_long_is_an_error_and_leaves_no_temporary(tmp_path: Path) -> None:
    """Файл занят дольше всех повторов политики — PermissionError наружу, прежний файл цел, временного нет."""
    target: Path = tmp_path / "vault.local.dat"
    target.write_text("прежнее", encoding=ENCODING)
    pauses: list[float] = []
    with target.open(encoding=ENCODING), pytest.raises(PermissionError):
        AtomicFile(target=target, prefix=target.name, sleep=pauses.append).write_text("новое", ENCODING)
    assert len(pauses) == REPLACE_RETRY_POLICY.max_retries
    assert sum(pauses) <= REPLACE_RETRY_POLICY.max_retries * REPLACE_RETRY_POLICY.max_delay_sec
    assert target.read_text(encoding=ENCODING) == "прежнее"
    assert [item.name for item in tmp_path.iterdir()] == [target.name]


def test_another_replace_failure_is_not_repeated(tmp_path: Path) -> None:
    """Не занятость (временного файла уже нет) — ошибка сразу, без пауз."""
    target: Path = tmp_path / "keys.txt"
    pauses: list[float] = []
    with pytest.raises(FileNotFoundError):
        AtomicFile(target=target, prefix=target.name, sleep=pauses.append).write(lambda path: path.unlink())
    assert pauses == []


def test_a_target_read_by_another_thread_is_written_after_it(tmp_path: Path) -> None:
    """Фоновая проверка окна читает сейф, а окно в этот миг его пишет: запись дожидается читателя и проходит."""
    target: Path = tmp_path / "vault.local.dat"
    target.write_text("прежнее", encoding=ENCODING)
    opened: threading.Event = threading.Event()

    def read() -> None:
        with target.open(encoding=ENCODING):
            opened.set()
            time.sleep(0.3)

    reader: threading.Thread = threading.Thread(target=read)
    reader.start()
    opened.wait()
    write_text_atomically(target, "новое", ENCODING)
    reader.join()
    assert target.read_text(encoding=ENCODING) == "новое"


def test_atomic_write_needs_an_existing_parent_directory(tmp_path: Path) -> None:
    """Папку создаёт ensure_dirs; запись в несуществующую папку — OSError, а не тихое создание."""
    with pytest.raises(OSError):
        write_text_atomically(tmp_path / "missing" / "keys.txt", "текст", ENCODING)


def test_paths_fixture_gives_a_ready_root(livecraft_paths: LivecraftPaths) -> None:
    assert all(livecraft_paths.dir(folder).is_dir() for folder in DataDir)
    assert not livecraft_paths.file(FileName.CONFIG).exists() and not livecraft_paths.file(FileName.VAULT_TOKEN).exists()
