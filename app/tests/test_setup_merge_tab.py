"""Вкладка «Нейросеть» в окне настройщика: живая проверка ключа OpenAI (CLAUDE.md §8.2, §7.4).

Проверка идёт в фоновом потоке — сама после сохранения ключа, иначе по кнопке; при открытии окна проверок нет. Тест
ждёт итог, прокручивая события окна. К OpenAI тесты не ходят: нейросеть за разъёмом — подделка.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.llm.errors import LlmErrorKind, LlmFailure
from app.llm.selection import ChoiceReason
from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField
from app.setup.tabs.check_line import CheckLine
from app.tests.fixtures.merges import FAKE_BACKEND, QueueBackend
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.ui import messages_ru as msg

OWN_OPENAI_KEY: str = "sk-proj-own-Zy9xWvUtSrQpOnMlKjIhGfEdCbA9876543210"
ACCEPTED: str = msg.SETUP_LLM_KEY_OK.format(
    choice=msg.LLM_CHOICE_LINE.format(model="gpt-5.6-sol", reason=ChoiceReason.PRIMARY_CONFIRMED.human)
)


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def _line(driver: SetupWindowDriver) -> CheckLine:
    return driver.tabs.merge.key_line


def test_the_key_row_has_a_check_button_and_nothing_is_checked_on_open(driver: SetupWindowDriver) -> None:
    backend: QueueBackend = QueueBackend(probe_kind=None)
    driver.check_key_on(backend)
    assert msg.SETUP_LLM_KEY_BUTTON_CHECK in driver.visible_texts()
    assert _line(driver).result_text == "" and not _line(driver).is_running
    assert backend.probes == []


def test_saving_a_key_checks_it_with_the_model_choice_of_the_run(driver: SetupWindowDriver) -> None:
    backend: QueueBackend = QueueBackend(probe_kind=None)
    driver.check_key_on(backend)
    driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert _line(driver).is_running
    driver.wait_for(_line(driver))
    assert _line(driver).result_text == ACCEPTED
    assert backend.probes == ["gpt-5.6-sol"]
    assert not any(OWN_OPENAI_KEY in text for text in driver.visible_texts())


def test_the_button_checks_the_key_again(driver: SetupWindowDriver) -> None:
    backend: QueueBackend = QueueBackend(probe_kind=None)
    driver.check_key_on(backend)
    _line(driver).button.invoke()
    driver.wait_for(_line(driver))
    _line(driver).button.invoke()
    driver.wait_for(_line(driver))
    assert backend.probes == ["gpt-5.6-sol", "gpt-5.6-sol"]


def test_a_refused_key_shows_the_refusal(driver: SetupWindowDriver) -> None:
    driver.check_key_on(QueueBackend(probe_kind=LlmErrorKind.AUTH))
    _line(driver).button.invoke()
    driver.wait_for(_line(driver))
    refusal: str = LlmFailure(LlmErrorKind.AUTH, FAKE_BACKEND).human
    assert _line(driver).result_text == msg.SETUP_LLM_KEY_FAILED.format(
        problem=msg.LLM_CHOICE_REFUSED.format(reason=refusal)
    )


def test_saving_the_same_key_again_checks_nothing(driver: SetupWindowDriver) -> None:
    """Тот же ключ сохранён ещё раз: ключ, с которым пойдёт запуск, не сменился — проверять нечего."""
    backend: QueueBackend = QueueBackend(probe_kind=None)
    driver.check_key_on(backend)
    driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    driver.wait_for(_line(driver))
    driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert not _line(driver).is_running and backend.probes == ["gpt-5.6-sol"]
