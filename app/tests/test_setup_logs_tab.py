"""Вкладка «Логи» на настоящем окне Tk за краем экрана (§8.2 п.11, §14 решения 46, 62): место в окне, одна кнопка
«Сохранить архив логов», архив в папке logs и папка, которая открывается с выделенным архивом; бота и чата поддержки
нет."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.system import FolderOpener
from app.paths import DataDir, LivecraftPaths
from app.runtime.log_archive import LOG_ARCHIVE_LIMIT_MEGABYTES
from app.setup.page import SetupPage
from app.setup.tabs.logs_tab import LogsTab
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.ui import messages_ru as msg

ARCHIVE: str = "livecraft_logs_29-09-2026_150000.zip"


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def test_the_tab_stands_before_advanced_and_has_one_button(driver: SetupWindowDriver) -> None:
    tab: LogsTab = driver.logs
    assert list(SetupPage)[-2:] == [SetupPage.LOGS, SetupPage.ADVANCED]
    assert [item.page for item in driver.tabs.all][-2:] == [SetupPage.LOGS, SetupPage.ADVANCED]
    texts: list[str] = driver.visible_texts()
    assert msg.SETUP_TAB_TITLES["logs"] in texts
    assert msg.SETUP_LOGS_INTRO.format(limit=LOG_ARCHIVE_LIMIT_MEGABYTES) in texts
    assert tab.save_line.buttons == [tab.save_line.button]
    assert tab.save_line.button.cget("text") == msg.SETUP_LOGS_BUTTON_SAVE
    assert not any("поддержк" in text for text in texts)


def test_the_archive_goes_to_the_logs_folder_and_its_folder_opens_with_it(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    driver.logs.save_line.button.invoke()
    driver.wait_for(driver.logs.save_line)
    saved: Path = ready_paths.dir(DataDir.LOGS) / ARCHIVE
    assert saved.is_file()
    first: str = driver.logs.save_line.result_text.split("\n")[0]
    assert first.startswith(msg.CHECK_OK_LINE.format(line=msg.SETUP_LOGS_SAVED.format(
        path=ready_paths.shown(saved), files=0, megabytes=0
    ).split(" (")[0]))
    assert driver.revealed == [saved]


def test_an_archive_that_does_not_write_opens_no_folder(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    (ready_paths.dir(DataDir.LOGS) / ARCHIVE).mkdir()
    driver.logs.save_line.button.invoke()
    driver.wait_for(driver.logs.save_line)
    assert driver.logs.save_line.result_text.startswith(msg.CHECK_MARK_PROBLEM)
    assert driver.revealed == []


def test_the_folder_opener_selects_the_file_in_explorer(tmp_path: Path) -> None:
    """Проводник открывает папку файла и выделяет его; путь — в кавычках (в нём бывают пробелы)."""
    launched: list[str] = []
    archive: Path = tmp_path / "logs folder" / ARCHIVE
    FolderOpener(launch=launched.append).show_file(archive)
    assert launched == [f'explorer /select,"{archive}"']
