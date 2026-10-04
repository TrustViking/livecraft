"""Вкладка «Эфиры YouTube» в окне настройщика: вход в выбранный канал и проверка всех каналов (CLAUDE.md §8.2, §10).

Тот же код, что у --auth и --check, в фоновом потоке и только по кнопке; строка итога — те же строки, что печатает
консоль. После входа вкладка перечитывает каналы: ник и название могли выровняться по YouTube (§14 решение 25). Тест
ждёт итог, прокручивая события окна. К YouTube тесты не ходят: площадка — подделка стенда эфиров.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.broadcasts.service import ChannelService
from app.config.channel import ChannelConfig, ConfiguredChannels
from app.paths import LivecraftPaths
from app.setup.tabs.check_line import CheckLine
from app.tests.fixtures.broadcasts import BroadcastBench
from app.tests.fixtures.platform import channel_info
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.ui import messages_ru as msg


@pytest.fixture
def bench(ready_paths: LivecraftPaths) -> BroadcastBench:
    """Каналы yt_ua и yt_ru в channels.json и с токенами — до открытия окна: вкладка их показывает."""
    return BroadcastBench.with_tokens(ready_paths)


@pytest.fixture
def driver(bench: BroadcastBench, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    for driver in SetupWindowDriver.opened(bench.paths, pytestconfig):
        driver.check_channels_on(bench)
        yield driver


def _line(driver: SetupWindowDriver) -> CheckLine:
    return driver.channels.check_line


def test_the_tab_has_both_buttons(driver: SetupWindowDriver) -> None:
    texts: list[str] = driver.visible_texts()
    assert msg.SETUP_CHANNELS_BUTTON_CHECK in texts and msg.SETUP_CHANNELS_BUTTON_LOGIN in texts
    assert _line(driver).result_text == ""


def test_check_all_shows_the_lines_of_the_console_check(driver: SetupWindowDriver, bench: BroadcastBench) -> None:
    _line(driver).button.invoke()
    assert all(str(button.cget("state")) == "disabled" for button in _line(driver).buttons)
    driver.wait_for(_line(driver))
    ChannelService(bench.services(), ConfiguredChannels(bench.channels), bench.record.console).check()
    lines: list[str] = _line(driver).result_text.splitlines()
    assert lines[:-1] == bench.record.lines[:-1] and lines[-1] == msg.CHECK_OK_LINE.format(line=bench.record.lines[-1])
    assert all(str(button.cget("state")) == "normal" for button in _line(driver).buttons)


def test_log_in_without_a_selected_channel_says_so(driver: SetupWindowDriver, bench: BroadcastBench) -> None:
    _line(driver).buttons[1].invoke()
    assert driver.channels.edit_problem.text == msg.SETUP_CHANNELS_NOTHING_SELECTED
    assert not _line(driver).is_running and bench.platform.logins == []


def test_log_in_the_selected_channel_and_reread_the_aligned_channels(
    driver: SetupWindowDriver, bench: BroadcastBench
) -> None:
    """Вход в канал выбранной строки; YouTube назвал канал по-новому — вкладка показывает новое название."""
    ua: ChannelConfig = bench.channels[0]
    bench.platform.login_answers["yt_ua"] = [channel_info(ua, title="Новое название")]
    driver.channels.tree.selection_set("0")
    driver.channels.fill_from_selection()
    _line(driver).buttons[1].invoke()
    driver.wait_for(_line(driver))
    assert bench.platform.logins == ["yt_ua"]
    assert driver.channels.panel.channels[0].account_name == "Новое название"
    assert not driver.channels.is_dirty
