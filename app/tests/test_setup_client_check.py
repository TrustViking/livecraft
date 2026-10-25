"""Проект Google на вкладке «Главная» без окна: входы и проект, выбор по пути и проверка
(app\\setup\\panels\\client_check.py; CLAUDE.md §8.2 п.1, §14 решение 66)."""
from __future__ import annotations

import logging
from collections.abc import Iterator
import shutil
from pathlib import Path

import pytest

from app.config.files import SettingsFile
from app.google.oauth_client import OAuthClient
from app.observability.log_event import LogArea
from app.paths import DataDir, FileName, LivecraftPaths
from app.setup.panels.client_check import ClientCheck, ClientFiles, ClientLogins, ClientVerdict
from app.setup.panels.token_file import ReceivedFiles, TokenFile
from app.tests.conftest import REPO_CHANNELS_EXAMPLE
from app.tests.fixtures.google_client import (
    NOT_KNOWN,
    TEST_CLIENT_ID,
    TEST_SECRET,
    FakeTokenEndpoint,
    choose_project,
    client_text,
    login_text,
    project_file,
)
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

OTHER_PROJECT: str = "livecraft-guests"
OTHER_CLIENT_ID: str = "2000-guests.apps.googleusercontent.com"
OTHER_CLIENT: str = client_text(project=OTHER_PROJECT, client_id=OTHER_CLIENT_ID, secret="GOCSPX-guests")
OWN_CLIENT: str = client_text()
THIS: str = "проект Google kanal-test"


@pytest.fixture
def setup_log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.SETUP, logging.DEBUG) as capture:
        yield capture


@pytest.fixture
def paths(livecraft_paths: LivecraftPaths) -> LivecraftPaths:
    """Установка: каналы @kanal_ua и @kanal_ru из примера, выбран проект kanal-test — файл в secrets, путь к нему
    в настройках."""
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_paths.file(FileName.CHANNELS))
    project_file(livecraft_paths).write_text(OWN_CLIENT, encoding="utf-8")
    return choose_project(livecraft_paths, project_file(livecraft_paths))


def _client(text: str = OWN_CLIENT) -> OAuthClient:
    client: OAuthClient | None = OAuthClient.of_text(text)
    assert client is not None
    return client


AGAIN: str = "через другой проект: при запуске программа войдёт заново через этот проект"


def _logins(paths: LivecraftPaths, operator: str | None, **channels: str) -> None:
    """Входы установки: оператор и каналы (ник без «@» → client_id входа)."""
    if operator is not None:
        paths.file(FileName.SHEETS_TOKEN).write_text(login_text(operator), encoding="utf-8")
    for handle, client_id in channels.items():
        paths.token_file("@" + handle).write_text(login_text(client_id), encoding="utf-8")


def _check(paths: LivecraftPaths, google: FakeTokenEndpoint | None = None) -> ClientCheck:
    return ClientCheck(files=ClientFiles(paths), probe=(google or FakeTokenEndpoint()).probe)


def _chosen_setting(paths: LivecraftPaths) -> str:
    """Путь к файлу проекта, как он записан в livecraft.json."""
    return SettingsFile.of(paths).load().google.project_file


def _write(folder: Path, name: str, text: str) -> Path:
    path: Path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


# --- входы и проект


def test_the_operator_and_channels_signed_in_through_this_project(paths: LivecraftPaths) -> None:
    _logins(paths, TEST_CLIENT_ID, kanal_ua=TEST_CLIENT_ID, kanal_ru=TEST_CLIENT_ID)
    assert ClientLogins.of(paths).lines(_client()) == ("вход оператора и каналы @kanal_ua, @kanal_ru — через этот проект",)


def test_logins_through_another_project_are_made_again(paths: LivecraftPaths) -> None:
    """Вход другого проекта программа делает заново через выбранный (§14 решение 67) — строка говорит это, у каналов —
    ещё и как войти сразу."""
    _logins(paths, OTHER_CLIENT_ID, kanal_ua=TEST_CLIENT_ID, kanal_ru=OTHER_CLIENT_ID)
    assert ClientLogins.of(paths).lines(_client()) == (
        "каналы @kanal_ua — через этот проект",
        "вход оператора и каналы @kanal_ru — " + AGAIN + msg.SETUP_CLIENT_LOGINS_RELOGIN,
    )


def test_only_the_operator_through_another_project_has_no_channel_advice(paths: LivecraftPaths) -> None:
    _logins(paths, OTHER_CLIENT_ID)
    assert ClientLogins.of(paths).lines(_client()) == ("вход оператора — " + AGAIN,)


def test_logins_that_are_not_there_are_not_named(paths: LivecraftPaths) -> None:
    """Входа нет — его нет и в строках; channels.json нет — каналов нет."""
    assert ClientLogins.of(paths).lines(_client()) == ()
    paths.file(FileName.CHANNELS).unlink()
    _logins(paths, TEST_CLIENT_ID)
    assert ClientLogins.of(paths).lines(_client()) == ("вход оператора — через этот проект",)


# --- выбор: путь к файлу в настройках, файл не копируется


def test_a_choice_remembers_the_full_path_of_a_file_outside_the_program(
    livecraft_paths: LivecraftPaths, tmp_path: Path, setup_log: LogCapture
) -> None:
    """Файл с любым именем в любой папке: в настройках — полный путь, файл не скопирован и не переименован."""
    files: ClientFiles = ClientFiles(livecraft_paths)
    assert files.status_line == "✗ " + msg.READINESS_GAP_CLIENT_SECRET
    source: Path = _write(tmp_path, "any name 1000-test.json", OWN_CLIENT)
    chosen: ClientVerdict = files.choose(source)
    assert chosen.is_ok and chosen.text == f"✓ Выбран {THIS}."
    assert _chosen_setting(livecraft_paths) == str(source)
    assert source.read_text(encoding="utf-8") == OWN_CLIENT
    assert list(livecraft_paths.dir(DataDir.SECRETS).glob("google_project_*")) == []
    assert files.status_line == f"✓ {THIS} — {source} — введено в окне настройки"
    assert any(line.startswith("google_client_chosen project=kanal-test file=") for line in setup_log.messages())


def test_a_file_inside_the_program_folder_is_remembered_from_the_root(livecraft_paths: LivecraftPaths) -> None:
    """Путь внутри папки программы — от корня: программу можно перенести вместе с файлом."""
    folder: Path = livecraft_paths.root / "clients"
    folder.mkdir()
    assert ClientFiles(livecraft_paths).choose(_write(folder, "desktop.json", OWN_CLIENT)).is_ok
    assert _chosen_setting(livecraft_paths) == str(Path("clients") / "desktop.json")
    assert SettingsFile.placed(livecraft_paths).project_file == folder / "desktop.json"


def test_a_new_choice_replaces_the_path_and_leaves_the_old_file(paths: LivecraftPaths, tmp_path: Path) -> None:
    """Сменить проект — выбрать другой файл: прежний остаётся где лежал, рабочим становится новый."""
    guests: Path = _write(tmp_path, "guests.json", OTHER_CLIENT)
    chosen: ClientVerdict = ClientFiles(paths).choose(guests)
    assert chosen.text == f"✓ Выбран проект Google {OTHER_PROJECT}."
    assert _chosen_setting(paths) == str(guests)
    assert project_file(paths).read_text(encoding="utf-8") == OWN_CLIENT
    assert ClientFiles(paths).status_line == f"✓ проект Google {OTHER_PROJECT} — {guests} — введено в окне настройки"


def test_a_chosen_file_that_is_gone_or_unfit_is_named_with_its_path(paths: LivecraftPaths, tmp_path: Path) -> None:
    """Файла по пути нет или он не клиент Desktop — строка с путём; к Google проверка не ходит."""
    google: FakeTokenEndpoint = FakeTokenEndpoint()
    gone: Path = tmp_path / "gone.json"
    choose_project(paths, gone)
    missing: str = "✗ " + msg.READINESS_GAP_PROJECT_MISSING.format(path=gone)
    assert ClientFiles(paths).status_line == missing
    assert _check(paths, google).run(lambda: None).text == missing
    gone.write_text(client_text(kind="web"), encoding="utf-8")
    unfit: str = "✗ " + msg.READINESS_GAP_PROJECT_UNFIT.format(path=gone)
    assert ClientFiles(paths).status_line == unfit
    assert _check(paths, google).run(lambda: None).text == unfit
    assert google.urls == []


def test_a_file_that_cannot_be_read_is_named_and_changes_nothing(paths: LivecraftPaths, tmp_path: Path) -> None:
    chosen: ClientVerdict = ClientFiles(paths).choose(tmp_path / "gone.json")
    assert not chosen.is_ok and chosen.text.startswith("✗ " + msg.SETUP_CLIENT_UNREADABLE.format(reason=""))
    assert _chosen_setting(paths) == str(Path("secrets") / "google_project_kanal-test.json")


@pytest.mark.parametrize("text", [client_text(kind="web"), "{}", "not json"])
def test_a_file_that_does_not_fit_changes_nothing(paths: LivecraftPaths, tmp_path: Path, text: str) -> None:
    before: bytes = paths.file(FileName.CONFIG).read_bytes()
    chosen: ClientVerdict = ClientFiles(paths).choose(_write(tmp_path, "web.json", text))
    assert not chosen.is_ok and chosen.text == "✗ " + msg.SETUP_CLIENT_NOT_DESKTOP
    assert paths.file(FileName.CONFIG).read_bytes() == before


def test_a_client_received_with_a_token_is_named_so(paths: LivecraftPaths) -> None:
    ReceivedFiles.load(paths).with_written([TokenFile.read(project_file(paths))]).save()
    shown: str = str(Path("secrets") / "google_project_kanal-test.json")
    assert ClientFiles(paths).status_line == f"✓ {THIS} — {shown} — получено с токеном"


# --- проверка


def test_the_check_says_google_knows_the_client_and_where_the_logins_are(paths: LivecraftPaths) -> None:
    _logins(paths, TEST_CLIENT_ID, kanal_ua=OTHER_CLIENT_ID)
    with LogCapture.on(LogArea.SETUP, logging.DEBUG) as capture:
        verdict: ClientVerdict = _check(paths).run(lambda: None)
    assert verdict.is_ok
    assert verdict.text.split("\n") == [
        f"✓ {THIS}: Google этот клиент знает",
        "вход оператора — через этот проект",
        "каналы @kanal_ua — " + AGAIN + msg.SETUP_CLIENT_LOGINS_RELOGIN,
    ]
    lines: list[str] = capture.messages()
    assert "google_client_checked project=kanal-test known=yes this=operator other=@kanal_ua" in lines
    assert not any(TEST_SECRET in line or TEST_CLIENT_ID in line for line in lines)


def test_a_client_google_does_not_know_is_a_problem_but_stays_chosen(paths: LivecraftPaths, tmp_path: Path) -> None:
    """Проверка у Google запись не останавливает: клиент выбран, строка — «Google не знает»."""
    broken: Path = _write(tmp_path, "broken.json", client_text(secret="GOCSPX-wrong"))
    verdict: ClientVerdict = _check(paths, FakeTokenEndpoint(answers=[NOT_KNOWN])).choose(broken)
    assert not verdict.is_ok
    assert verdict.text.split("\n")[1].startswith(f"✗ {THIS}: Google этот клиент не знает")
    assert _chosen_setting(paths) == str(broken)


def test_without_a_project_the_check_says_so(livecraft_paths: LivecraftPaths) -> None:
    google: FakeTokenEndpoint = FakeTokenEndpoint()
    assert _check(livecraft_paths, google).run(lambda: None).text == "✗ " + msg.READINESS_GAP_CLIENT_SECRET
    project_file(livecraft_paths).write_text(OWN_CLIENT, encoding="utf-8")
    assert _check(livecraft_paths, google).run(lambda: None).text == "✗ " + msg.READINESS_GAP_CLIENT_SECRET
    assert google.urls == []


def test_without_network_the_check_says_no_internet(paths: LivecraftPaths) -> None:
    verdict: ClientVerdict = _check(paths, FakeTokenEndpoint.offline()).run(lambda: None)
    assert not verdict.is_ok and "нет интернета" in verdict.text
