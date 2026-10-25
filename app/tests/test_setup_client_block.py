"""Проект Google — первым на «Главной», на настоящем окне Tk за краем экрана (CLAUDE.md §8.2 п.1, §14 решение 66):
статус с путём к файлу, выбор файла, проверка, «Перейти» к нему; диалог выбора файла и Google — подделки."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk

import pytest

from app.config.files import SettingsFile
from app.config.google import GoogleSettings
from app.paths import LivecraftPaths
from app.run.mode import RunPart
from app.setup.page import SetupPage
from app.setup.panels.client_check import ClientCheck, ClientFiles
from app.setup.panels.token_scope import TokenItem
from app.setup.tabs.check_line import RowState
from app.setup.tabs.client_block import ClientBlock
from app.setup.tabs.tab_theme import STATUS_UNSET_FOREGROUND
from app.tests.fixtures.google_client import FakeTokenEndpoint, NOT_KNOWN, client_text, project_file
from app.tests.fixtures.settings import set_drive_folder
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.ui import messages_ru as msg

THIS: str = "проект Google kanal-test"
GUESTS: str = "проект Google livecraft-guests"
SHOWN: str = str(Path("secrets") / "google_project_kanal-test.json")


class FakeClientPicker:
    """Выбор файла клиента без диалога: None — человек закрыл диалог."""

    def __init__(self, chosen: Path | None) -> None:
        self.chosen: Path | None = chosen

    def client(self) -> Path | None:
        return self.chosen


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def _block(driver: SetupWindowDriver, google: FakeTokenEndpoint, chosen: Path | None = None) -> ClientBlock:
    """Раздел проекта Google спрашивает подделку Google, а файл выбирает без диалога."""
    block: ClientBlock = driver.tabs.home.client
    block.check = ClientCheck(files=ClientFiles(driver.window.paths), probe=google.probe)
    block.picker = FakeClientPicker(chosen)  # type: ignore[assignment]
    return block


def _press(driver: SetupWindowDriver, block: ClientBlock, button: str) -> str:
    {"pick": block.line.button, "check": block.check_button}[button].invoke()
    driver.wait_for(block.line)
    return block.line.result_text


def test_the_project_stands_first_on_home_with_its_status(driver: SetupWindowDriver) -> None:
    """Работа начинается с проекта Google: он сразу под тем, что делает Livecraft, до строк линий; на «Дополнительно»
    его нет."""
    block: ClientBlock = driver.tabs.home.client
    assert str(block.frame).startswith(str(driver.tabs.home.frame) + ".")
    texts: list[str] = driver.visible_texts()
    assert texts.index(msg.SETUP_HOME_INTRO) < texts.index(msg.SETUP_CLIENT_TITLE) < texts.index(msg.SETUP_HOME_HOWTO)
    assert texts.index(msg.SETUP_CLIENT_TEXT) < texts.index(msg.SETUP_HOME_HOWTO)
    assert texts.count(msg.SETUP_CLIENT_TEXT) == 1       # заголовок «Проект Google» — ещё и ползунок «Токенов»
    assert "программа запоминает путь к нему" in msg.SETUP_CLIENT_TEXT
    assert block.status.cget("text") == f"✓ {THIS} — {SHOWN} — введено в окне настройки"


def test_choosing_a_file_remembers_its_path_and_checks_it(driver: SetupWindowDriver, tmp_path: Path) -> None:
    """Выбранный файл остаётся где лежит: в настройках — путь к нему; прежний файл проекта не тронут."""
    guests: Path = tmp_path / "client_secret_2000-guests.apps.googleusercontent.com.json"
    guests.write_text(client_text(project="livecraft-guests", client_id="2000-guests"), encoding="utf-8")
    block: ClientBlock = _block(driver, FakeTokenEndpoint(), guests)
    driver.tokens.switches[TokenItem.GOOGLE_PROJECT].flip()       # проект в токене — по ползунку (§14 решение 77)
    result: str = _press(driver, block, "pick")
    assert result.split("\n") == [f"✓ Выбран {GUESTS}.", f"✓ {GUESTS}: Google этот клиент знает"]
    assert block.status.cget("text") == f"✓ {GUESTS} — {guests} — введено в окне настройки"
    assert SettingsFile.of(driver.window.paths).load().google.project_file == str(guests)
    assert GUESTS in driver.tokens.contents.cget("text")          # окно — по свежей проверке: «В токен войдут»
    assert project_file(driver.window.paths).read_text(encoding="utf-8") == client_text()
    assert [str(button.cget("text")) for button in (block.line.button, block.check_button)] == [
        msg.SETUP_CLIENT_BUTTON_PICK, msg.SETUP_CLIENT_BUTTON_CHECK
    ]


def test_the_check_button_asks_google_and_shows_a_problem_in_red(driver: SetupWindowDriver) -> None:
    block: ClientBlock = _block(driver, FakeTokenEndpoint(answers=[NOT_KNOWN]))
    result: str = _press(driver, block, "check")
    assert result.startswith(f"✗ {THIS}: Google этот клиент не знает")
    assert block.line.shown[0].state is RowState.PROBLEM
    assert str(block.line.labels[0].cget("foreground")) == STATUS_UNSET_FOREGROUND


def test_closing_the_file_choice_changes_nothing(driver: SetupWindowDriver) -> None:
    google: FakeTokenEndpoint = FakeTokenEndpoint()
    block: ClientBlock = _block(driver, google, None)
    block.line.button.invoke()
    assert not block.line.is_running and google.urls == [] and block.line.result_text == ""


def test_without_a_project_the_window_says_where_to_choose_it(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> None:
    SettingsFile.of(ready_paths).save_google(GoogleSettings(project_file=""))
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        assert driver.tabs.home.client.status.cget("text") == "✗ " + msg.READINESS_GAP_CLIENT_SECRET
        assert msg.READINESS_GAP_CLIENT_SECRET in driver.window.readiness_line.cget("text")


def test_a_project_file_that_is_gone_is_named_with_its_path(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> None:
    project_file(ready_paths).unlink()
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        missing: str = msg.READINESS_GAP_PROJECT_MISSING.format(path=SHOWN)
        assert driver.tabs.home.client.status.cget("text") == "✗ " + missing
        assert missing in driver.window.readiness_line.cget("text")


def test_go_to_the_missing_project_opens_home_from_its_top(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> None:
    """Входу не хватает проекта Google — «Перейти» открывает «Главную» с начала, где проект стоит первым."""
    project_file(ready_paths).unlink()
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        driver.show(driver.tabs.home.frame, "900x400")
        driver.tabs.home.scroll.canvas.yview_moveto(1.0)
        driver.show(driver.tabs.advanced.frame, "900x400")
        assert driver.tabs.home.scroll.canvas.yview()[0] > 0
        driver.tabs.home.input.go_button.invoke()
        driver.window.root.update()
        assert driver.selected_page is SetupPage.HOME
        assert driver.tabs.home.scroll.canvas.yview()[0] == 0


def test_go_to_of_a_line_that_lacks_only_the_project_opens_home(
    ready_paths: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    """Линии не хватает только проекта Google — «Перейти» ведёт на «Главную» к её началу; не хватает и другого — на
    вкладку линии."""
    project_file(ready_paths).unlink()
    set_drive_folder(ready_paths)
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        driver.show(driver.tabs.home.frame, "900x400")
        driver.tabs.home.scroll.canvas.yview_moveto(1.0)
        go: ttk.Button | None = driver.tabs.home.lines[RunPart.DRIVE_PREVIEWS].go_button
        assert go is not None
        go.invoke()
        driver.window.root.update()
        assert driver.selected_page is SetupPage.HOME
        assert driver.tabs.home.scroll.canvas.yview()[0] == 0
        package: ttk.Button | None = driver.tabs.home.lines[RunPart.PACKAGE].go_button
        assert package is not None
        package.invoke()
        driver.window.root.update()
        assert driver.selected_page is SetupPage.PACKAGE
