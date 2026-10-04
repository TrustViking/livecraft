"""Вкладка «Токены» на настоящем окне Tk за краем экрана (§8.2 п.10, §13 задача 7.1, §14 решение 45): срок, создание
токена одним файлом, загрузка — и окно после загрузки."""
from __future__ import annotations

import shutil
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk

import pytest

from app.config.files import SettingsFile
from app.config.settings import LivecraftSettings
from app.paths import DataDir, FileName, LivecraftPaths
from app.secretsafe.field import SecretField
from app.secretsafe.token import TOKEN_SUFFIX
from app.secretsafe.value import SecretValue
from app.setup.page import SetupPage
from app.setup.tabs.settings_section import SettingsSection
from app.setup.tabs.tokens_tab import TokensTab
from app.tests.conftest import CLIENT_SECRET_STUB, FORM_URL, REPO_CHANNELS_EXAMPLE
from app.tests.fixtures.settings import set_contacts, set_form_url
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.tests.fixtures.token import FakePicker, network_at
from app.tests.fixtures.vault import TOKEN_VALUES, VaultReads, save_own_values
from app.ui import messages_ru as msg

STAMP: str = "29-09-2026_150000"
CONTACTS: str = "@livecraft_help"


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на готовом корне: таблица и ключ OpenAI — из токена; ссылка на форму — своя."""
    set_form_url(ready_paths, FORM_URL)
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


@pytest.fixture
def creator(tmp_path: Path) -> LivecraftPaths:
    """Установка того, кто создал токен: свой ключ OpenAI и таблица, ссылка на форму."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path / "creator")
    paths.ensure_dirs()
    SettingsFile.of(paths).install_shipped()
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, paths.file(FileName.CHANNELS))
    paths.file(FileName.CLIENT_SECRET).write_text(CLIENT_SECRET_STUB, encoding="utf-8")
    return paths


def _create(driver: SetupWindowDriver, days: str) -> str:
    tab: TokensTab = driver.tokens
    tab.days.set(days)
    tab.create_line.button.invoke()
    driver.wait_for(tab.create_line)
    return tab.create_line.result_text


def test_the_tab_stands_before_advanced_with_one_file_for_three_days(driver: SetupWindowDriver) -> None:
    """Вида токена нет: токен — один файл; окно говорит, как его передавать (§14 решение 45)."""
    tab: TokensTab = driver.tokens
    assert [page for page in SetupPage][-3:] == [SetupPage.TOKENS, SetupPage.LOGS, SetupPage.ADVANCED]
    assert tab.days.get() == "3"
    texts: list[str] = driver.visible_texts()
    assert msg.SETUP_TOKENS_CREATE_TEXT in texts and msg.SETUP_TOKENS_LOAD_TEXT in texts
    assert not any(".lckey" in text for text in texts)
    assert tab.contents.cget("text") == msg.SETUP_TOKENS_CONTENTS.format(items=msg.TOKEN_SETTING_LABELS["form.url"])


def test_values_from_a_token_do_not_go_into_a_new_one(driver: SetupWindowDriver) -> None:
    """Значения ready_paths — из токена: в новый токен идёт только своя ссылка на форму (§14 решение 16)."""
    text: str = driver.tokens.contents.cget("text")
    for field in TOKEN_VALUES:
        assert field.human_label not in text


def test_creating_a_token_shows_its_file_and_the_period(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    text: str = _create(driver, "3")
    assert text.split("\n")[:2] == [
        msg.SETUP_TOKENS_CREATED.format(token=f"tokens\\livecraft_{STAMP}{TOKEN_SUFFIX}"),
        msg.SETUP_TOKENS_VALID_UNTIL.format(until="02.10.2026 15:00"),
    ]
    assert [path.suffix for path in ready_paths.dir(DataDir.TOKENS).iterdir()] == [TOKEN_SUFFIX]


def test_the_period_typed_in_the_window_is_the_period_of_the_token(driver: SetupWindowDriver) -> None:
    text: str = _create(driver, "7")
    assert text.split("\n")[1] == msg.SETUP_TOKENS_VALID_UNTIL.format(until="06.10.2026 15:00")


def test_a_bad_period_is_said_and_nothing_is_created(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    text: str = _create(driver, "0")
    assert text == msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOKENS_DAYS_PROBLEM.format(maximum=3650))
    assert list(ready_paths.dir(DataDir.TOKENS).iterdir()) == []


def test_a_loaded_token_refreshes_the_other_tabs(
    driver: SetupWindowDriver, creator: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    """Загруженный токен: вкладки с полями сейфа и ссылкой на форму перечитаны — окно без перезапуска."""
    own_key: str = "sk-proj-creator-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789"
    save_own_values(creator, {SecretField.OPENAI_API_KEY: own_key})
    set_form_url(creator, "https://forms.gle/CreatorForm1234")
    for maker in SetupWindowDriver.opened(creator, pytestconfig):
        _create(maker, "3")
    token: Path = next(creator.dir(DataDir.TOKENS).glob("*" + TOKEN_SUFFIX))
    driver.tokens_on(network_at(), FakePicker(token))
    driver.tokens.load_line.button.invoke()
    driver.wait_for(driver.tokens.load_line)
    assert driver.tokens.load_line.result_text.split("\n")[0] == msg.SETUP_TOKENS_LOADED.format(
        items=msg.LIST_JOINER.join((SecretField.OPENAI_API_KEY.human_label, msg.TOKEN_SETTING_LABELS["form.url"]))
    )
    status: str = str(driver.key_view(SecretField.OPENAI_API_KEY).status.cget("text"))
    assert status == msg.SETUP_KEY_STATUS_TOKEN.format(
        mask=SecretValue(field=SecretField.OPENAI_API_KEY, value=own_key).short_mask
    )
    assert own_key not in status
    assert driver.tabs.form.form_link.link.url == "https://forms.gle/CreatorForm1234"


def test_a_loaded_token_shows_its_contacts_and_another_tab_does_not_erase_them(
    driver: SetupWindowDriver, creator: LivecraftPaths, ready_paths: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    """Контакты документа из токена (§13 задача 9.6): поле на «Google-документе» показывает загруженное, а запись
    раздела настроек другой вкладки не возвращает в файл прежнее значение."""
    set_contacts(creator, CONTACTS)
    for maker in SetupWindowDriver.opened(creator, pytestconfig):
        _create(maker, "3")
    token: Path = next(creator.dir(DataDir.TOKENS).glob("*" + TOKEN_SUFFIX))
    contacts: tk.Widget = driver.settings_input("docs_contacts")
    assert isinstance(contacts, ttk.Entry) and contacts.get() == ""
    driver.type(driver.settings_input("keep_days"), "45")                  # набрано на «Дополнительно», не сохранено
    driver.tokens_on(network_at(), FakePicker(token))
    driver.tokens.load_line.button.invoke()
    driver.wait_for(driver.tokens.load_line)
    assert contacts.get() == CONTACTS and not driver.tabs.is_dirty
    advanced: SettingsSection = driver.section_of("keep_days")
    driver.type(driver.settings_input("keep_days"), "45")
    advanced.save_button.invoke()
    saved: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert (saved.keep_days, saved.docs.contacts) == (45, CONTACTS)


def test_a_loaded_token_makes_the_window_read_the_vault_again(
    driver: SetupWindowDriver, creator: LivecraftPaths, pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Слой токена пишет фоновый поток: по итогу загрузки сейф окна читается заново — один раз."""
    save_own_values(creator, {SecretField.OPENAI_API_KEY: "sk-proj-creator-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789"})
    for maker in SetupWindowDriver.opened(creator, pytestconfig):
        _create(maker, "3")
    token: Path = next(creator.dir(DataDir.TOKENS).glob("*" + TOKEN_SUFFIX))
    reads: VaultReads = VaultReads.counted(monkeypatch)
    driver.tokens_on(network_at(), FakePicker(token))
    driver.tokens.load_line.button.invoke()
    driver.wait_for(driver.tokens.load_line)
    driver.window.refresh()
    assert reads.both == (1, 0)


def test_closing_the_file_choice_loads_nothing(driver: SetupWindowDriver) -> None:
    driver.tokens_on(network_at(), FakePicker(None))
    driver.tokens.load_line.button.invoke()
    assert not driver.tokens.load_line.is_running and driver.tokens.load_line.result_text == ""


def test_the_window_is_not_narrower_than_its_tabs(driver: SetupWindowDriver) -> None:
    """Названия вкладок не обрезаются: окно не уже полосы вкладок, даже если его сжать (§13 задача 7.1)."""
    driver.show(driver.tokens.frame, "900x700")
    notebook: tk.Misc = driver.window.notebook
    last: int = int(notebook.index(tk.END)) - 1
    width: int = driver.window.root.winfo_width()
    assert width >= notebook.winfo_reqwidth()
    assert any(_tab_at(notebook, x) == last for x in range(width - 60, width))


def _tab_at(notebook: tk.Misc, x: int) -> int | None:
    """Вкладка под точкой полосы вкладок; там её нет — None."""
    try:
        return int(notebook.index(f"@{x},10"))
    except tk.TclError:
        return None
