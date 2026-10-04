"""Вкладка «Форма» в окне настройщика: живая проверка формы ключей (CLAUDE.md §8.2, §6 инвариант 2).

Проверка идёт в фоновом потоке — сама после сохранения ссылки, иначе по кнопке; при открытии окна проверок нет. Тест
ждёт итог, прокручивая события окна. К Google тесты не ходят: форма и таблица — подделки.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.paths import LivecraftPaths
from app.setup.tabs.check_line import CheckLine
from app.setup.tabs.link_row import LinkRowView
from app.tests.fixtures.broadcasts import form_page
from app.tests.fixtures.form import SHORT_URL, TRAINING_FORM_TITLE, FakeForms
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.tests.fixtures.sheets import FakeSheetsReader
from app.ui import messages_ru as msg


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def _line(driver: SetupWindowDriver) -> CheckLine:
    return driver.tabs.form.line


def _save_link(driver: SetupWindowDriver, url: str) -> LinkRowView:
    link: LinkRowView = driver.tabs.form.form_link
    driver.type(link.entry, url)
    link.save_button.invoke()
    return link


def test_the_form_row_has_a_check_button_and_nothing_is_read_on_open(driver: SetupWindowDriver) -> None:
    forms: FakeForms = FakeForms.answering(form_page("17.03.2027"))
    driver.check_form_on(forms, FakeSheetsReader())
    assert msg.SETUP_FORM_BUTTON_CHECK in driver.visible_texts()
    assert _line(driver).result_text == "" and forms.gets == []


def test_saving_the_link_reads_the_form(driver: SetupWindowDriver) -> None:
    forms: FakeForms = FakeForms.answering(form_page("17.03.2027"))
    driver.check_form_on(forms, FakeSheetsReader())
    _save_link(driver, SHORT_URL)
    assert _line(driver).is_running
    driver.wait_for(_line(driver))
    assert _line(driver).result_text.startswith(msg.SETUP_FORM_OK.split("{")[0] + TRAINING_FORM_TITLE)
    assert [call.url for call in forms.gets] == [SHORT_URL]


def test_the_button_reads_the_form_again_and_deleting_the_link_reads_nothing(driver: SetupWindowDriver) -> None:
    forms: FakeForms = FakeForms.answering(form_page("17.03.2027"))
    driver.check_form_on(forms, FakeSheetsReader())
    link: LinkRowView = _save_link(driver, SHORT_URL)
    driver.wait_for(_line(driver))
    _line(driver).button.invoke()
    driver.wait_for(_line(driver))
    assert len(forms.gets) == 2
    link.clear_button.invoke()
    assert not _line(driver).is_running and len(forms.gets) == 2


def test_without_a_link_the_button_says_what_to_do(driver: SetupWindowDriver) -> None:
    _line(driver).button.invoke()
    driver.wait_for(_line(driver))
    assert _line(driver).result_text == msg.SETUP_FORM_FAILED.format(problem=msg.SETUP_FORM_NOT_SET)
