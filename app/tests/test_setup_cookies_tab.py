"""Вкладка «Cookies YouTube» на настоящем окне Tk за краем экрана (CLAUDE.md §8.2, §14 решение 73): статус файла,
загрузка через подделку диалога выбора файла, проверка тем же кодом, что у запуска, синяя строка входа в YouTube
(§14 решение 80; yt-dlp подменён), срок напоминания, бледность при входе «Пакеты»."""
from __future__ import annotations

import os
import subprocess
import tkinter as tk
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config.files import SettingsFile
from app.core.dates import format_human_date
from app.paths import FileName, LivecraftPaths
from app.run.mode import RunPart
from app.runtime.cookies_file import NETSCAPE_HEADER
from app.setup.page import SetupPage
from app.setup.panels.cookies_check import CookiesFileCheck
from app.setup.tabs.check_line import RowState
from app.setup.tabs.cookies_tab import CookiesTab
from app.setup.tabs.tab_layout import INFO_FOREGROUND
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.ui import messages_ru as msg

SHOWN: str = "secrets\\cookies.txt"
KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")      # пояс поставки
FAR: int = int(datetime(2099, 1, 1, 12, tzinfo=KYIV).timestamp())
LOGIN_TEXT: str = (
    NETSCAPE_HEADER + f"\n.youtube.com\tTRUE\t/\tTRUE\t{FAR}\tSAPISID\tv\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tv\n"
)


class FakeCookiesPicker:
    """Выбор файла cookies без диалога: None — человек закрыл диалог."""

    def __init__(self, chosen: Path | None) -> None:
        self.chosen: Path | None = chosen

    def cookies(self) -> Path | None:
        return self.chosen


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def _tab(driver: SetupWindowDriver, chosen: Path | None = None) -> CookiesTab:
    """Вкладка, которая выбирает файл без диалога."""
    tab: CookiesTab = driver.tabs.cookies
    tab.picker = FakeCookiesPicker(chosen)  # type: ignore[assignment]
    return tab


def _exported_file(path: Path, text: str = LOGIN_TEXT, days_ago: int = 2) -> datetime:
    """Файл cookies, выгруженный `days_ago` суток назад; дата выгрузки — его время изменения."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    moment: datetime = datetime.now(KYIV) - timedelta(days=days_ago)
    os.utime(path, (moment.timestamp(), moment.timestamp()))
    return moment


def _press(driver: SetupWindowDriver, tab: CookiesTab, button: str) -> list[str]:
    {"load": tab.line.button, "check": tab.line.buttons[1]}[button].invoke()
    driver.wait_for(tab.line)
    return tab.line.result_text.split("\n")


def test_the_tab_follows_the_plan_and_says_there_is_no_file(driver: SetupWindowDriver) -> None:
    """Вкладка — сразу за «Таблицей плана»: зачем cookies, как их выгрузить, статус «файла нет», кнопки, срок."""
    pages: list[SetupPage] = [tab.page for tab in driver.tabs.all]
    assert pages.index(SetupPage.COOKIES) == pages.index(SetupPage.PLAN) + 1
    assert SetupPage.COOKIES.title == "Cookies YouTube"
    texts: list[str] = driver.visible_texts()
    for text in (msg.SETUP_COOKIES_INTRO, msg.SETUP_COOKIES_HOWTO, msg.SETUP_COOKIES_BUTTON_LOAD, msg.SETUP_COOKIES_BUTTON_CHECK):
        assert text in texts
    assert "в токен они не входят" in msg.SETUP_COOKIES_INTRO
    status: str = driver.tabs.cookies.status.cget("text")
    assert status == f"✗ Файла cookies нет ({SHOWN}) — загрузите его кнопкой «Загрузить файл…»."
    assert driver.settings_input("cookies_remind_days").get() == "7"


def test_loading_a_file_copies_it_with_its_date_and_checks_it(driver: SetupWindowDriver, tmp_path: Path) -> None:
    source: Path = tmp_path / "Downloads" / "www.youtube.com_cookies.txt"
    exported: datetime = _exported_file(source)
    tab: CookiesTab = _tab(driver, source)
    date: str = format_human_date(exported)
    assert _press(driver, tab, "load") == [
        f"✓ Файл загружен: {SHOWN}",
        f"✓ Файл cookies: {SHOWN}",
        "✓ Вид: Netscape",
        f"✓ Выгружены {date}, 2 сут. назад; срок напоминания — 7 сут.",
        "✓ Cookies входа в аккаунт YouTube: есть, действуют до 01.01.2099",
    ]
    copy: Path = driver.window.paths.file(FileName.COOKIES)
    assert copy.read_text(encoding="utf-8") == LOGIN_TEXT
    assert abs(copy.stat().st_mtime - exported.timestamp()) < 1           # дата выгрузки сохранена
    assert tab.status.cget("text") == f"✓ Файл cookies {SHOWN}: выгружены {date}"
    assert [row.state for row in tab.line.shown] == [RowState.OK] * 5


def test_a_closed_dialog_does_nothing(driver: SetupWindowDriver) -> None:
    tab: CookiesTab = _tab(driver, None)
    tab.line.button.invoke()
    assert not tab.line.is_running and tab.line.result_text == ""


def test_a_file_of_another_form_is_not_loaded_and_the_old_one_stays(driver: SetupWindowDriver, tmp_path: Path) -> None:
    old: Path = driver.window.paths.file(FileName.COOKIES)
    _exported_file(old)
    source: Path = tmp_path / "cookies.json"
    source.write_text('[{"name": "SAPISID"}]', encoding="utf-8")
    tab: CookiesTab = _tab(driver, source)
    assert _press(driver, tab, "load") == ["✗ Файл не загружен: не формат Netscape, прежний файл остался."]
    assert old.read_text(encoding="utf-8") == LOGIN_TEXT


def test_the_check_names_a_finished_reminder_right_away(driver: SetupWindowDriver) -> None:
    """Строки файла — со знаками; вход в YouTube — не среди них, а синей строкой под ними (решение 80); срок
    напоминания закончился — «✗» в строке даты и в статусе."""
    exported: datetime = _exported_file(driver.window.paths.file(FileName.COOKIES), days_ago=9)
    date: str = format_human_date(exported)
    lines: list[str] = _press(driver, _tab(driver), "check")
    assert lines == [
        f"✓ Файл cookies: {SHOWN}",
        "✓ Вид: Netscape",
        f"✗ Выгружены {date} (9 сут.): срок напоминания 7 сут. закончился — выгрузите новые",
        "✓ Cookies входа в аккаунт YouTube: есть, действуют до 01.01.2099",
    ]
    assert not any(line.startswith(("✓ Вход в YouTube", "✗ Вход в YouTube")) for line in lines)
    assert driver.tabs.cookies.status.cget("text") == (
        f"✗ Файл cookies {SHOWN}: выгружены {date} — срок напоминания закончился"
    )


def test_the_check_of_a_fresh_file_is_all_ok(driver: SetupWindowDriver) -> None:
    exported: datetime = _exported_file(driver.window.paths.file(FileName.COOKIES), days_ago=0)
    tab: CookiesTab = _tab(driver)
    lines: list[str] = _press(driver, tab, "check")
    assert lines[2] == f"✓ Выгружены {format_human_date(exported)}, 0 сут. назад; срок напоминания — 7 сут."
    assert [row.state for row in tab.line.shown] == [RowState.OK] * 4


class _YtDlp:
    """Подделка subprocess.run для проверки входа: ответ yt-dlp на ленту вошедшего; вызовы считаются."""

    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode: int = returncode
        self.stderr: str = stderr
        self.calls: int = 0

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls += 1
        return subprocess.CompletedProcess(command, self.returncode, stdout="", stderr=self.stderr)


@pytest.mark.parametrize(
    ("answer", "login"),
    [
        (_YtDlp(0), msg.COOKIES_WINDOW_LOGIN_YES),
        (_YtDlp(0, "WARNING: The provided YouTube account cookies are no longer valid."), msg.COOKIES_WINDOW_LOGIN_NO),
    ],
)
def test_the_check_asks_youtube_about_the_login_and_says_it_in_blue(
    driver: SetupWindowDriver, answer: _YtDlp, login: str
) -> None:
    """«Проверить» спрашивает YouTube, есть ли вход (yt-dlp подменён), и пишет итог синим — не зелёным и не красным:
    на работу программы вход не влияет; строки файла — прежние, со знаками."""
    paths: LivecraftPaths = driver.window.paths
    paths.file(FileName.YTDLP).parent.mkdir(parents=True, exist_ok=True)
    paths.file(FileName.YTDLP).write_bytes(b"")
    _exported_file(paths.file(FileName.COOKIES), days_ago=0)
    tab: CookiesTab = _tab(driver)
    tab.check = CookiesFileCheck(paths, answer)
    assert tab.login.cget("text") == ""
    lines: list[str] = _press(driver, tab, "check")
    assert answer.calls == 1 and len(lines) == 4 and login not in lines
    assert str(tab.login.cget("text")) == login
    assert str(tab.login.cget("foreground")) == INFO_FOREGROUND
    assert "работе программы это не мешает" in msg.COOKIES_WINDOW_LOGIN_NO


def test_without_a_cookies_file_there_is_no_login_without_asking_youtube(driver: SetupWindowDriver) -> None:
    tab: CookiesTab = _tab(driver)
    answer: _YtDlp = _YtDlp(0)
    tab.check = CookiesFileCheck(driver.window.paths, answer)
    _press(driver, tab, "check")
    assert (answer.calls, str(tab.login.cget("text"))) == (0, msg.COOKIES_WINDOW_LOGIN_NO)


def test_the_reminder_is_saved_by_itself(driver: SetupWindowDriver) -> None:
    driver.save_setting("cookies_remind_days", "3")
    assert driver.setting_line("cookies_remind_days") == msg.SETUP_FIELD_SAVED
    assert SettingsFile.of(driver.window.paths).load().cookies.remind_days == 3
    driver.save_setting("cookies_remind_days", "0")                   # меньше суток — не годится, файл не тронут
    assert driver.setting_line("cookies_remind_days") not in ("", msg.SETUP_FIELD_SAVED)
    assert SettingsFile.of(driver.window.paths).load().cookies.remind_days == 3


def test_the_tab_is_pale_with_the_packages_input(driver: SetupWindowDriver) -> None:
    """Cookies нужны только yt-dlp, который читает видео таблицы: при входе «Пакеты» вкладка бледная."""
    tab: CookiesTab = driver.tabs.cookies
    entry: tk.Widget = driver.settings_input("cookies_remind_days")
    assert tab.line.button.instate(["!disabled"]) and entry.instate(["!disabled"])  # type: ignore[attr-defined]
    driver.tabs.home.input.row.choice.buttons[RunPart.PACKAGES_IN.value].invoke()
    assert tab.line.button.instate([tk.DISABLED]) and entry.instate([tk.DISABLED])  # type: ignore[attr-defined]
    assert msg.SETUP_FIELD_NEEDED_BY.format(lines=RunPart.PLAN.human_label) in driver.visible_texts()
