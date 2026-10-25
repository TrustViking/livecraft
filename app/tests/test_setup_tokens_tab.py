"""Вкладка «Токены» на настоящем окне Tk за краем экрана (§8.2 п.10, §13 задача 7.1, §14 решения 45, 70, 77): срок,
ползунок на каждое значение группами по линиям, создание токена одним файлом, загрузка — и окно после загрузки."""
from __future__ import annotations

import shutil
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk

import pytest

from app.config.channel import ChannelConfig, ConfiguredChannels, Platform, Privacy
from app.config.files import ChannelsFile, SettingsFile
from app.config.settings import LivecraftSettings
from app.paths import DataDir, FileName, LivecraftPaths
from app.secretsafe.field import SecretField
from app.secretsafe.token import TOKEN_SUFFIX
from app.secretsafe.value import SecretValue
from app.setup.page import SetupPage
from app.setup.panels.token_scope import TokenGroup, TokenItem
from app.setup.tabs.tab_layout import PAD
from app.setup.tabs.tokens_tab import TokensTab
from app.tests.conftest import CLIENT_SECRET_STUB, FORM_URL, REPO_CHANNELS_EXAMPLE
from app.tests.fixtures.google_client import TEST_PROJECT, choose_project, project_file
from app.tests.fixtures.settings import set_contacts, set_form_url
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.tests.fixtures.token import FakePicker, network_at
from app.tests.fixtures.vault import TOKEN_VALUES, VaultReads, save_own_values
from app.ui import messages_ru as msg

STAMP: str = "29-09-2026_150000"
PROJECT_LABEL: str = msg.GOOGLE_PROJECT.format(project=TEST_PROJECT)
CONTACTS: str = "@livecraft_help"
FILE_ITEMS: frozenset[TokenItem] = frozenset({TokenItem.GOOGLE_PROJECT, TokenItem.YOUTUBE_CHANNELS})


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
    project_file(paths).write_text(CLIENT_SECRET_STUB, encoding="utf-8")
    return choose_project(paths, project_file(paths))


def _create(driver: SetupWindowDriver, days: str, items: tuple[TokenItem, ...] | None = None) -> str:
    """Токен на срок `days` с ползунками `items`; не названы — все доступные значения, кроме проекта и каналов."""
    tab: TokensTab = driver.tokens
    for item, switch in tab.switches.items():
        if switch.is_enabled and (item not in FILE_ITEMS if items is None else item in items):
            switch.flip()
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
    assert tab.contents.cget("text") == msg.SETUP_TOKENS_NOTHING
    tab.switches[TokenItem.FORM_LINK].flip()
    assert tab.contents.cget("text") == msg.SETUP_TOKENS_CONTENTS.format(items=msg.TOKEN_SETTING_LABELS["form.url"])


def test_values_from_a_token_do_not_go_into_a_new_one(driver: SetupWindowDriver) -> None:
    """Значения ready_paths — из токена: их ползунки бледные, в новый токен идёт только своя ссылка на форму (§14
    решения 16, 77)."""
    tab: TokensTab = driver.tokens
    for item, switch in tab.switches.items():
        if switch.is_enabled:
            switch.flip()
    text: str = tab.contents.cget("text")
    for field in TOKEN_VALUES:
        assert field.human_label not in text
        assert not tab.switches[next(item for item in TokenItem if item.field is field)].is_enabled


def test_creating_a_token_shows_its_file_and_the_period(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    text: str = _create(driver, "3")
    assert text.split("\n")[:2] == [
        msg.SETUP_TOKENS_CREATED.format(token=f"tokens\\lvc_{STAMP}{TOKEN_SUFFIX}"),
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
    поля настроек другой вкладки не возвращает в файл прежнее значение."""
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
    driver.save_setting("keep_days", "45")
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


def test_a_switch_per_value_grouped_by_lines_all_off(driver: SetupWindowDriver) -> None:
    """Ползунков столько, сколько значений; группы — заголовками, ползунки — подписями и подсказками; все выключены
    (§14 решение 77)."""
    tab: TokensTab = driver.tokens
    assert list(tab.switches) == [item for group in TokenGroup.all() for item in group.items]
    assert len(tab.switches) == len(TokenItem)
    assert not any(switch.variable.get() for switch in tab.switches.values())
    texts: list[str] = driver.visible_texts()
    for group in TokenGroup.all():
        assert group.heading in texts
    for item in TokenItem:
        assert item.label in texts and (not item.hint or item.hint in texts)


def test_switches_and_the_period_stand_on_one_vertical(driver: SetupWindowDriver) -> None:
    """Подписи разной длины — а ползунки и поле срока у одного левого края, сразу за самой длинной подписью: широкие
    подсказки столбец подписей не растягивают (проверка окна 24-10-2026)."""
    tab: TokensTab = driver.tokens
    driver.show(tab.frame, "900x700")
    driver.window.root.update_idletasks()
    fields: list[tk.Misc] = [tab.days, *tab.switches.values()]
    assert len({field.winfo_x() for field in fields}) == 1
    labels: list[int] = [
        widget.winfo_x() + widget.winfo_width()
        for widget in tab.days.master.winfo_children()
        if isinstance(widget, ttk.Label) and int(widget.grid_info()["column"]) == 0 and widget.grid_info().get("columnspan", 1) == 1
    ]
    assert len(labels) == len(fields) and max(labels) <= tab.days.winfo_x() <= max(labels) + PAD


def test_a_pale_switch_does_not_turn_on_and_the_line_stays(driver: SetupWindowDriver) -> None:
    """Ключа OpenAI своего нет (он из токена): ползунок бледный, щелчок его не включает, строка не меняется."""
    tab: TokensTab = driver.tokens
    switch = tab.switches[TokenItem.OPENAI_KEY]
    assert not switch.is_enabled
    switch.flip()
    assert switch.variable.get() is False and tab.contents.cget("text") == msg.SETUP_TOKENS_NOTHING


def test_a_value_removed_elsewhere_turns_its_switch_off_and_pale(driver: SetupWindowDriver) -> None:
    """Ссылку на форму стёрли на другой вкладке: окно по свежей проверке гасит её ползунок и строку."""
    tab: TokensTab = driver.tokens
    tab.switches[TokenItem.FORM_LINK].flip()
    set_form_url(driver.window.paths, "")
    driver.window.refresh()
    switch = tab.switches[TokenItem.FORM_LINK]
    assert not switch.is_enabled and switch.variable.get() is False
    assert tab.contents.cget("text") == msg.SETUP_TOKENS_NOTHING


def test_the_project_and_channels_switches_each_change_only_their_own_names(driver: SetupWindowDriver) -> None:
    """«Проект Google» и «Каналы YouTube» добавляют в строку и убирают из неё только своё (§14 решения 70, 77)."""
    tab: TokensTab = driver.tokens
    project = tab.switches[TokenItem.GOOGLE_PROJECT]
    channels_switch = tab.switches[TokenItem.YOUTUBE_CHANNELS]
    channels: str = msg.TOKEN_FILE_LABELS["channels"].format(handles="@kanal_ua, @kanal_ru")
    assert PROJECT_LABEL not in tab.contents.cget("text") and channels not in tab.contents.cget("text")
    project.flip()
    assert PROJECT_LABEL in tab.contents.cget("text") and channels not in tab.contents.cget("text")
    channels_switch.flip()
    assert PROJECT_LABEL in tab.contents.cget("text") and channels in tab.contents.cget("text")
    project.flip()
    assert PROJECT_LABEL not in tab.contents.cget("text") and channels in tab.contents.cget("text")
    channels_switch.flip()
    assert channels not in tab.contents.cget("text")


def test_a_loaded_token_with_channels_shows_them_on_the_channels_tab(
    driver: SetupWindowDriver, creator: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    """Токен с каналами: вкладка «Эфиры YouTube» показывает их сразу, без перезапуска окна."""
    ChannelsFile.of(creator).save(ConfiguredChannels((
        ChannelConfig(
            platform=Platform.YOUTUBE, account_name="Kanal Test", handle="@kanal_test",
            google_account="kanal@example.com", languages=("en",), privacy=Privacy.UNLISTED,
        ),
    )))
    for maker in SetupWindowDriver.opened(creator, pytestconfig):
        _create(maker, "3", (TokenItem.YOUTUBE_CHANNELS,))
    token: Path = next(creator.dir(DataDir.TOKENS).glob("*" + TOKEN_SUFFIX))
    driver.tokens_on(network_at(), FakePicker(token))
    driver.tokens.load_line.button.invoke()
    driver.wait_for(driver.tokens.load_line)
    tree = driver.tabs.broadcasts.tree
    handles: list[str] = [str(tree.item(item, "values")[0]) for item in tree.get_children()]
    assert handles == ["@kanal_ua", "@kanal_ru", "@kanal_test"]
