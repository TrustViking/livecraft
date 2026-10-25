"""Вкладка «Токены» без окна: создание токена одним файлом из своих значений и загрузка полученного (§13 задача 7.1,
§14 решения 16, 44, 45, 77; §7.4 — значения нигде не видны). `VALUES` — все значения, кроме проекта Google и каналов:
так выглядел токен до ползунка на каждое значение."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from app.config.files import SettingsFile
from app.config.setting_key import SettingKey
from app.config.settings import LivecraftSettings
from app.config.telegram import ChatTarget
from app.paths import DataDir, FileName, LivecraftPaths
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.token import TOKEN_SUFFIX, TokenProblem
from app.secretsafe.vault import Vault
from app.setup.page import SetupPage
from app.setup.panels.keys_panel import KeysPanel, RowAction
from app.setup.panels.token_file import ReceivedFiles, TokenFile
from app.setup.panels.token_panel import OPEN_KEYS, TokenDraft, TokenName, TokenPanel, TokenSettings, TokenVerdict
from app.setup.panels.token_scope import TokenItem, TokenScope
from app.setup.setup_vault import SetupVault
from app.tests.conftest import CLIENT_SECRET_STUB, FORM_URL, REPO_CHANNELS_EXAMPLE
from app.tests.fixtures.google_client import TEST_CLIENT_ID, TEST_PROJECT, choose_project, client_text, project_file
from app.tests.fixtures.logs import LogCapture
from app.observability.log_event import LogArea
from app.tests.fixtures.settings import set_contacts, set_form_url
from app.tests.fixtures.telegram import BOT_TOKEN, PRIVATE_CHAT_ID, connect_private_chat
from app.tests.fixtures.token import NETWORK_NOW, add_support, network_at, network_down
from app.tests.fixtures.vault import save_own_values, write_token_vault
from app.ui import messages_ru as msg

OWN_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-creator-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1creator-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
}
# То, что пришло создателю в чужом токене: дальше не передаётся (§14 решение 16).
FOREIGN_TOKEN_VALUES: dict[SecretField, str] = {
    SecretField.DRIVE_PREVIEWS_FOLDER: "1foreign-DrIvEfOlDeR_0123456789-abcd",
}
RECEIVER_OWN_SHEET: str = "1receiver-own-table-B3c4D5e6F7g8H9i0JkLmNoPqRs"
STAMP: str = "29-09-2026_150000"        # 12:00 UTC — 15:00 по Киеву, поясу поставки
PROJECT_LABEL: str = msg.GOOGLE_PROJECT.format(project=TEST_PROJECT)
CONTACTS: str = "@livecraft_help, help@example.com"
VERSION_OFFSET: int = 4                 # байт версии токена — сразу после магии
FILE_ITEMS: frozenset[TokenItem] = frozenset({TokenItem.GOOGLE_PROJECT, TokenItem.YOUTUBE_CHANNELS})
VALUES: TokenScope = TokenScope(frozenset(TokenItem) - FILE_ITEMS)
PROJECT: TokenScope = TokenScope(VALUES.items | {TokenItem.GOOGLE_PROJECT})
CHANNELS: TokenScope = TokenScope(VALUES.items | {TokenItem.YOUTUBE_CHANNELS})
BOTH: TokenScope = TokenScope(frozenset(TokenItem))


def _root(tmp_path: Path, name: str) -> LivecraftPaths:
    """Корень установки: настройки поставки, каналы из примера, client_secret.json — как у человека."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path / name)
    paths.ensure_dirs()
    SettingsFile.of(paths).install_shipped()
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, paths.file(FileName.CHANNELS))
    project_file(paths).write_text(CLIENT_SECRET_STUB, encoding="utf-8")
    return choose_project(paths, project_file(paths))


@pytest.fixture
def creator(tmp_path: Path) -> LivecraftPaths:
    """Установка того, кто создаёт токен: свои ключ OpenAI, таблица и бот, форма и личный чат, чужой токен."""
    paths: LivecraftPaths = _root(tmp_path, "creator")
    write_token_vault(paths, FOREIGN_TOKEN_VALUES)
    save_own_values(paths, OWN_VALUES)
    connect_private_chat(paths)
    set_form_url(paths, FORM_URL)
    return paths


@pytest.fixture
def receiver(tmp_path: Path) -> LivecraftPaths:
    return _root(tmp_path, "receiver")


def _panel(paths: LivecraftPaths, network: object = None) -> TokenPanel:
    return TokenPanel(paths=paths, network=network_at() if network is None else network)  # type: ignore[arg-type]


def _own(paths: LivecraftPaths) -> Vault:
    """Свои значения — так, как их даёт окну его сейф."""
    return SetupVault.open(paths).lenient.own


def _create(paths: LivecraftPaths, days: str = "3", scope: TokenScope = VALUES) -> TokenVerdict:
    return _panel(paths).create(TokenDraft(days_text=days, scope=scope), _own(paths))


def _token_files(paths: LivecraftPaths) -> list[str]:
    return sorted(path.name for path in paths.dir(DataDir.TOKENS).iterdir())


def _file(paths: LivecraftPaths) -> Path:
    """Созданный токен установки `paths` — как его выберет получатель."""
    return next(path for path in paths.dir(DataDir.TOKENS).iterdir() if path.suffix == TOKEN_SUFFIX)


def _values(vault_load: VaultLoad, origin: VaultOrigin) -> dict[SecretField, str]:
    layer = vault_load.token if origin is VaultOrigin.TOKEN else vault_load.own
    return {field: entry.secret.reveal() for field, entry in layer.entries.items()}


# --- создание


def test_a_token_is_one_file_in_the_tokens_folder_under_its_moment(creator: LivecraftPaths) -> None:
    verdict: TokenVerdict = _create(creator)
    assert verdict.is_ok
    assert _token_files(creator) == [f"lvc_{STAMP}{TOKEN_SUFFIX}"]
    assert verdict.text.split("\n")[:2] == [
        msg.SETUP_TOKENS_CREATED.format(token=f"tokens\\lvc_{STAMP}{TOKEN_SUFFIX}"),
        msg.SETUP_TOKENS_VALID_UNTIL.format(until="02.10.2026 15:00"),
    ]


def test_the_period_sets_the_last_moment_of_loading(creator: LivecraftPaths) -> None:
    verdict: TokenVerdict = _create(creator, days="1")
    assert verdict.text.split("\n")[1] == msg.SETUP_TOKENS_VALID_UNTIL.format(until="30.09.2026 15:00")


def test_the_token_names_what_is_inside_and_no_value(creator: LivecraftPaths) -> None:
    """Внутри — свои значения и открытые настройки, названиями; ни одного значения в строках (§7.4)."""
    panel: TokenPanel = _panel(creator)
    items: str = msg.LIST_JOINER.join((
        SecretField.OPENAI_API_KEY.human_label, SecretField.SHEETS_ID.human_label,
        SecretField.TELEGRAM_BOT_TOKEN.human_label, msg.TOKEN_SETTING_LABELS["form.url"],
        msg.TOKEN_SETTING_LABELS["telegram.target"], msg.TOKEN_SETTING_LABELS["telegram.private_chat_id"],
    ))
    assert panel.contents_line(_own(creator), VALUES) == msg.SETUP_TOKENS_CONTENTS.format(items=items)
    verdict: TokenVerdict = panel.create(TokenDraft(days_text="3", scope=VALUES), _own(creator))
    assert verdict.text.split("\n")[2] == msg.SETUP_TOKENS_INSIDE.format(items=items)
    for value in (*OWN_VALUES.values(), BOT_TOKEN, FORM_URL, PRIVATE_CHAT_ID, *FOREIGN_TOKEN_VALUES.values()):
        assert value not in verdict.text and value not in panel.contents_line(_own(creator), VALUES)


@pytest.mark.parametrize("days", ["0", "-1", "три", "", "3651", "1.5"])
def test_the_period_is_a_whole_number_of_days_in_bounds(creator: LivecraftPaths, days: str) -> None:
    verdict: TokenVerdict = _create(creator, days=days)
    assert not verdict.is_ok
    assert verdict.text == msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOKENS_DAYS_PROBLEM.format(maximum=3650))
    assert _token_files(creator) == []


def test_without_own_values_there_is_nothing_to_pass(receiver: LivecraftPaths) -> None:
    """Только значения и OAuth-клиент из чужого токена — передавать нечего и с ползунком «Проект Google»: дальше они
    не идут (§14 решения 16, 65)."""
    write_token_vault(receiver, FOREIGN_TOKEN_VALUES)
    ReceivedFiles.load(receiver).with_written([TokenFile.read(project_file(receiver))]).save()
    panel: TokenPanel = _panel(receiver)
    assert panel.contents_line(_own(receiver), VALUES) == panel.contents_line(_own(receiver), PROJECT)
    assert panel.contents_line(_own(receiver), PROJECT) == msg.SETUP_TOKENS_NOTHING
    verdict: TokenVerdict = panel.create(TokenDraft(days_text="3", scope=PROJECT), _own(receiver))
    assert verdict.text == msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOKENS_NOTHING)
    assert _token_files(receiver) == []


def test_without_network_no_token_is_created(creator: LivecraftPaths) -> None:
    draft: TokenDraft = TokenDraft(days_text="3", scope=VALUES)
    verdict: TokenVerdict = _panel(creator, network_down()).create(draft, _own(creator))
    assert verdict.text == msg.CHECK_PROBLEM_LINE.format(line=msg.TOKEN_PROBLEM_TEXT["no_network"])
    assert _token_files(creator) == []


# --- загрузка


def test_a_loaded_token_becomes_the_token_layer_and_the_open_settings(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    _create(creator)
    verdict: TokenVerdict = _panel(receiver).load(_file(creator))
    assert verdict.is_ok
    loaded: VaultLoad = VaultStore.open(receiver).load()
    assert _values(loaded, VaultOrigin.TOKEN) == {**OWN_VALUES, SecretField.TELEGRAM_BOT_TOKEN: BOT_TOKEN}
    assert _values(loaded, VaultOrigin.OWN) == {}
    settings: LivecraftSettings = SettingsFile.of(receiver).load()
    assert settings.form.url == FORM_URL
    assert (settings.telegram.target, settings.telegram.private_chat_id) == (ChatTarget.PRIVATE, PRIVATE_CHAT_ID)
    assert verdict.text.split("\n")[1] == msg.SETUP_TOKENS_LOADED_UNTIL.format(until="02.10.2026 15:00")


def test_a_token_carries_the_document_contacts_and_loading_writes_them(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    """Контакты для стримеров в документе объявлений — открытая настройка токена (§13 задача 9.6)."""
    set_contacts(creator, CONTACTS)
    panel: TokenPanel = _panel(creator)
    assert msg.TOKEN_SETTING_LABELS["docs.contacts"] in panel.contents_line(_own(creator), VALUES)
    assert _create(creator).is_ok
    set_contacts(receiver, "@old_contacts")
    verdict: TokenVerdict = _panel(receiver).load(_file(creator))
    assert verdict.is_ok and msg.TOKEN_SETTING_LABELS["docs.contacts"] in verdict.text
    assert CONTACTS not in verdict.text                                       # значение — не в строках
    settings: LivecraftSettings = SettingsFile.of(receiver).load()
    assert settings.docs.contacts == CONTACTS
    assert settings.docs.access is SettingsFile.of(creator).load().docs.access     # прочее в разделе — на месте


def test_empty_contacts_are_not_in_the_token_and_do_not_erase_the_receivers(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    assert msg.TOKEN_SETTING_LABELS["docs.contacts"] not in _panel(creator).contents_line(_own(creator), VALUES)
    _create(creator)
    set_contacts(receiver, "@receiver_contacts")
    assert _panel(receiver).load(_file(creator)).is_ok
    assert SettingsFile.of(receiver).load().docs.contacts == "@receiver_contacts"


def test_the_contacts_label_is_one_for_the_token_and_the_window() -> None:
    assert msg.TOKEN_SETTING_LABELS["docs.contacts"] is msg.SETUP_SETTINGS_FIELD_LABELS["docs.contacts"]
    assert OPEN_KEYS[-1] is SettingKey.DOCS_CONTACTS and set(msg.TOKEN_SETTING_LABELS) == {key.value for key in OPEN_KEYS}


def test_without_file_switches_the_token_carries_no_foreign_values_project_channels_or_google_logins(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    """Без ползунков проекта и каналов в токен идут свои значения и открытые настройки: ни значения из чужого токена,
    ни проект Google, ни каналы, ни входы в Google; проект получателя остаётся (§7.3, §14 решения 16, 65, 77)."""
    creator.token_file("kanal.x").write_text("{}", encoding="utf-8")
    creator.file(FileName.SHEETS_TOKEN).write_text("{}", encoding="utf-8")
    _create(creator)
    _panel(receiver).load(_file(creator))
    loaded: VaultLoad = VaultStore.open(receiver).load()
    assert SecretField.DRIVE_PREVIEWS_FOLDER not in loaded.vault.entries
    assert not receiver.token_file("kanal.x").exists() and not receiver.file(FileName.SHEETS_TOKEN).exists()
    assert receiver.file(FileName.CHANNELS).read_bytes() == REPO_CHANNELS_EXAMPLE.read_bytes()
    assert project_file(receiver).read_text(encoding="utf-8") == CLIENT_SECRET_STUB
    assert ReceivedFiles.load(receiver).prints == {}


def test_a_token_of_the_previous_version_with_a_support_bot_and_chat_loads_without_them(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    """Токен версии с ботом и чатом поддержки загружается: бота и чата поддержки после загрузки нет ни в сейфе, ни в
    livecraft.json (§14 решение 62), остальное — на месте."""
    _create(creator)
    add_support(_file(creator), "-1002000000002")
    verdict: TokenVerdict = _panel(receiver).load(_file(creator))
    assert verdict.is_ok
    loaded: VaultLoad = VaultStore.open(receiver).load()
    assert set(_values(loaded, VaultOrigin.TOKEN)) == {*OWN_VALUES, SecretField.TELEGRAM_BOT_TOKEN}
    vault_text: str = receiver.file(FileName.VAULT_TOKEN).read_text(encoding="utf-8")
    assert "support_bot_token" not in vault_text
    config: str = receiver.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert "support_chat_id" not in config and "-1002000000002" not in config
    assert SettingsFile.of(receiver).load().telegram.private_chat_id == PRIVATE_CHAT_ID


def test_own_values_stay_first_and_deleting_one_returns_the_token_value(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    save_own_values(receiver, {SecretField.SHEETS_ID: RECEIVER_OWN_SHEET})
    _create(creator)
    _panel(receiver).load(_file(creator))
    panel: KeysPanel = KeysPanel.of(SetupVault(VaultStore.open(receiver)), SetupPage.PLAN)
    assert panel.vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    assert panel.row(SecretField.SHEETS_ID).reset_label == msg.SETUP_KEYS_BUTTON_RESET_TO_TOKEN
    after: KeysPanel = panel.reset(SecretField.SHEETS_ID).save().panel
    secret = after.vault.get(SecretField.SHEETS_ID)
    assert secret is not None and secret.reveal() == OWN_VALUES[SecretField.SHEETS_ID]
    assert after.vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.TOKEN


def test_a_token_value_is_never_shown_by_the_window(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    """Значение из токена — маской и «заменить своим»; «показать» ему не доступно никогда (§14 решение 11)."""
    _create(creator)
    _panel(receiver).load(_file(creator))
    panel: KeysPanel = KeysPanel.of(SetupVault(VaultStore.open(receiver)), SetupPage.MERGE)
    row = panel.row(SecretField.OPENAI_API_KEY)
    assert row.actions == frozenset({RowAction.REPLACE})
    assert panel.own_value(SecretField.OPENAI_API_KEY) is None
    assert OWN_VALUES[SecretField.OPENAI_API_KEY] not in row.status
    assert msg.SETUP_KEYS_NOTICE_PROTECTION in panel.notices


def test_loading_and_creating_log_no_value(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    with LogCapture.on(LogArea.SETUP, logging.DEBUG) as setup_log, LogCapture.on(LogArea.VAULT, logging.DEBUG) as vault_log:
        _create(creator, scope=PROJECT)
        _panel(receiver).load(_file(creator))
    text: str = "\n".join((*setup_log.messages(), *vault_log.messages()))
    assert "token_created until=" in text and f"project={TEST_PROJECT}" in text and "token_loaded" in text
    for value in (*OWN_VALUES.values(), BOT_TOKEN, FORM_URL, PRIVATE_CHAT_ID):
        assert value not in text


def test_a_new_token_replaces_the_previous_token_values(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    write_token_vault(receiver, FOREIGN_TOKEN_VALUES)
    _create(creator)
    _panel(receiver).load(_file(creator))
    assert SecretField.DRIVE_PREVIEWS_FOLDER not in VaultStore.open(receiver).load().token.entries


# --- полученные с токеном открытые настройки дальше не идут (§13 задача 9.39, §14 решения 44, 77)

RECEIVER_FORM_URL: str = "https://docs.google.com/forms/d/e/receiver-own-form/viewform"
SETTING_ITEMS: frozenset[TokenItem] = frozenset({TokenItem.FORM_LINK, TokenItem.PRIVATE_CHAT, TokenItem.DOC_CONTACTS})


def test_received_open_settings_give_no_switch_and_do_not_go_into_a_new_token(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    set_contacts(creator, CONTACTS)
    _create(creator)
    assert _panel(receiver).load(_file(creator)).is_ok
    panel: TokenPanel = _panel(receiver)
    assert not panel.available(_own(receiver)) & SETTING_ITEMS
    assert panel.contents(_own(receiver), VALUES).settings == {}
    assert panel.contents_line(_own(receiver), VALUES) == msg.SETUP_TOKENS_NOTHING


def test_a_received_setting_changed_in_the_window_is_own_again(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    """Ссылку на форму человек поменял в окне (запись livecraft.json): она снова своя; чат с ботом остаётся полученным,
    и куда слать объявления без своего чата не едет."""
    _create(creator)
    _panel(receiver).load(_file(creator))
    set_form_url(receiver, RECEIVER_FORM_URL)
    panel: TokenPanel = _panel(receiver)
    assert panel.available(_own(receiver)) & SETTING_ITEMS == {TokenItem.FORM_LINK}
    assert panel.contents(_own(receiver), VALUES).settings == {SettingKey.FORM_URL.value: RECEIVER_FORM_URL}


def test_a_new_token_marks_its_settings_received_and_keeps_the_earlier_marks(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    """Полученное заменяет полученное: второй токен несёт только контакты — форма и чат первого остаются полученными."""
    _create(creator)
    _panel(receiver).load(_file(creator))
    for path in list(creator.dir(DataDir.TOKENS).iterdir()):
        path.unlink()
    set_contacts(creator, CONTACTS)
    _create(creator, scope=TokenScope.of(TokenItem.DOC_CONTACTS))
    assert _panel(receiver).load(_file(creator)).is_ok
    assert set(ReceivedFiles.load(receiver).settings) >= {
        SettingKey.FORM_URL.value, SettingKey.TELEGRAM_PRIVATE_CHAT_ID.value, SettingKey.DOCS_CONTACTS.value
    }
    assert not _panel(receiver).available(_own(receiver)) & SETTING_ITEMS


def test_the_target_goes_only_with_its_own_chat(tmp_path: Path) -> None:
    private: str = SettingKey.TELEGRAM_PRIVATE_CHAT_ID.value
    group: str = SettingKey.TELEGRAM_GROUP_CHAT_ID.value
    target: str = SettingKey.TELEGRAM_TARGET.value
    settings: TokenSettings = TokenSettings({target: ChatTarget.PRIVATE.value, private: "111", group: "-222"})
    empty: ReceivedFiles = ReceivedFiles(path=tmp_path / "received.json", prints={}, settings={})
    assert settings.own(empty.with_settings({private: "111"})).values == {group: "-222"}
    assert settings.own(empty.with_settings({group: "-222", target: ChatTarget.PRIVATE.value})).values == {
        private: "111", target: ChatTarget.PRIVATE.value
    }
    assert settings.own(empty.with_settings({private: "999"})).values == settings.values


# --- что не загружается — причина словами, и ничего не записано


def _refused(receiver: LivecraftPaths, verdict: TokenVerdict, problem: TokenProblem) -> None:
    assert not verdict.is_ok
    assert verdict.text == msg.CHECK_PROBLEM_LINE.format(line=problem.human)
    assert not receiver.file(FileName.VAULT_TOKEN).exists()
    assert SettingsFile.of(receiver).load().form.url == ""


def test_a_changed_byte_is_not_loaded(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    _create(creator)
    token: Path = _file(creator)
    data: bytearray = bytearray(token.read_bytes())
    data[-1] ^= 0x01
    token.write_bytes(bytes(data))
    _refused(receiver, _panel(receiver).load(token), TokenProblem.DAMAGED)


def test_an_expired_token_is_not_loaded(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    _create(creator, days="3")
    late: TokenPanel = _panel(receiver, network_at(NETWORK_NOW + timedelta(days=4)))
    _refused(receiver, late.load(_file(creator)), TokenProblem.EXPIRED)


def test_without_network_no_token_is_loaded(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    _create(creator)
    _refused(receiver, _panel(receiver, network_down()).load(_file(creator)), TokenProblem.NO_NETWORK)


def test_a_token_of_the_previous_version_asks_for_a_new_one(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    """Токен версии 1 (пара или один файл с байтом вида) не загружается: причина — создать новый токен."""
    _create(creator)
    token: Path = _file(creator)
    data: bytearray = bytearray(token.read_bytes())
    data[VERSION_OFFSET] = 1
    token.write_bytes(bytes(data))
    _refused(receiver, _panel(receiver).load(token), TokenProblem.VERSION)


def test_a_file_that_is_not_a_token_is_not_loaded(receiver: LivecraftPaths, tmp_path: Path) -> None:
    other: Path = tmp_path / "notes.lctoken"
    other.write_text("не токен", encoding="utf-8")
    _refused(receiver, _panel(receiver).load(other), TokenProblem.NOT_TOKEN)

# --- ползунки «Проект Google» и «Каналы YouTube» (§14 решения 65, 70, 77)


def _google_login(refresh: str, client_id: str = TEST_CLIENT_ID) -> str:
    """Файл входа Google; по умолчанию вход через выбранный проект создателя (§14 решение 67)."""
    return json.dumps({"token": "ya29.access", "refresh_token": refresh, "client_id": client_id, "client_secret": "s"})


@pytest.fixture
def signed_in(creator: LivecraftPaths) -> LivecraftPaths:
    """Создатель вошёл в канал @kanal_ua и оператором; в @kanal_ru не входил."""
    creator.token_file("@kanal_ua").write_text(_google_login("1//creator-ua"), encoding="utf-8")
    creator.file(FileName.SHEETS_TOKEN).write_text(_google_login("1//creator-operator"), encoding="utf-8")
    return creator


def _added(without: str, *labels: str) -> str:
    """Строка «В токен войдут: …» без ползунков проекта и каналов и названия файлов после неё."""
    return without.removesuffix(".") + msg.LIST_JOINER + msg.LIST_JOINER.join(labels) + "."


def test_each_switch_adds_only_its_own_names_to_the_line(signed_in: LivecraftPaths) -> None:
    """«Проект Google» — проект и вход оператора, «Каналы YouTube» — каналы и входы в них (§14 решения 70, 77)."""
    panel: TokenPanel = _panel(signed_in)
    without: str = panel.contents_line(_own(signed_in), VALUES)
    channels: str = msg.TOKEN_FILE_LABELS["channels"].format(handles="@kanal_ua, @kanal_ru")
    logins: str = msg.TOKEN_FILE_LABELS["logins"].format(handles="@kanal_ua")
    operator: str = msg.TOKEN_FILE_LABELS["operator"]
    assert PROJECT_LABEL not in without and operator not in without and "@kanal_ua" not in without
    assert panel.contents_line(_own(signed_in), PROJECT) == _added(without, PROJECT_LABEL, operator)
    assert panel.contents_line(_own(signed_in), CHANNELS) == _added(without, channels, logins)
    both: str = panel.contents_line(_own(signed_in), BOTH)
    assert both == _added(without, PROJECT_LABEL, channels, logins, operator)
    assert "1//creator" not in both


def test_the_line_names_no_logins_made_through_another_project(signed_in: LivecraftPaths) -> None:
    """Входы через другой проект в токен не идут (§14 решение 67): в строке — только каналы."""
    other: str = "other.apps.googleusercontent.com"
    signed_in.token_file("@kanal_ua").write_text(_google_login("1//other-ua", other), encoding="utf-8")
    signed_in.file(FileName.SHEETS_TOKEN).write_text(_google_login("1//other-operator", other), encoding="utf-8")
    panel: TokenPanel = _panel(signed_in)
    without: str = panel.contents_line(_own(signed_in), VALUES)
    channels: str = msg.TOKEN_FILE_LABELS["channels"].format(handles="@kanal_ua, @kanal_ru")
    assert panel.contents_line(_own(signed_in), BOTH) == _added(without, PROJECT_LABEL, channels)
    assert panel.contents_line(_own(signed_in), PROJECT) == _added(without, PROJECT_LABEL)
    assert panel.contents_line(_own(signed_in), CHANNELS) == _added(without, channels)


def test_a_token_with_both_switches_gives_the_receiver_the_same_files(
    signed_in: LivecraftPaths, tmp_path: Path
) -> None:
    """Пустая установка получает клиент, каналы, вход канала, паспорт и вход оператора — те же, что у создателя."""
    receiver: LivecraftPaths = LivecraftPaths(tmp_path / "clean")
    receiver.ensure_dirs()
    SettingsFile.of(receiver).install_shipped()
    verdict: TokenVerdict = _panel(signed_in).create(TokenDraft(days_text="3", scope=BOTH), _own(signed_in))
    assert verdict.is_ok
    with LogCapture.on(LogArea.SETUP) as capture:
        loaded: TokenVerdict = _panel(receiver).load(_file(signed_in))
    assert loaded.is_ok and msg.TOKEN_FILE_LABELS["operator"] in loaded.text
    assert project_file(receiver).read_bytes() == project_file(signed_in).read_bytes()
    for name in (FileName.SHEETS_TOKEN, FileName.CHANNELS):
        assert receiver.file(name).read_bytes() == signed_in.file(name).read_bytes()
    assert receiver.token_file("@kanal_ua").read_bytes() == signed_in.token_file("@kanal_ua").read_bytes()
    assert not receiver.token_file("@kanal_ru").exists()
    assert "1//creator" not in "\n".join(capture.messages())


def test_a_file_that_does_not_write_says_save(signed_in: LivecraftPaths, receiver: LivecraftPaths) -> None:
    receiver.file(FileName.SHEETS_TOKEN).mkdir()               # на месте файла входа — папка: запись откажет
    _panel(signed_in).create(TokenDraft(days_text="3", scope=BOTH), _own(signed_in))
    verdict: TokenVerdict = _panel(receiver).load(_file(signed_in))
    assert not verdict.is_ok
    assert verdict.text.startswith(msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOKENS_SAVE_FAILED.format(reason="")))


# --- имя токена по содержимому (§14 решение 66)


def test_a_token_with_the_client_and_channels_names_the_project_and_the_channels(signed_in: LivecraftPaths) -> None:
    verdict: TokenVerdict = _panel(signed_in).create(TokenDraft(days_text="3", scope=BOTH), _own(signed_in))
    assert verdict.is_ok
    assert _token_files(signed_in) == [f"lvc_{TEST_PROJECT}_channels_{STAMP}{TOKEN_SUFFIX}"]


def test_a_token_with_the_project_only_names_only_the_project(signed_in: LivecraftPaths) -> None:
    assert _create(signed_in, scope=PROJECT).is_ok
    assert _token_files(signed_in) == [f"lvc_{TEST_PROJECT}_{STAMP}{TOKEN_SUFFIX}"]


def test_a_token_with_the_channels_only_names_only_the_channels(signed_in: LivecraftPaths) -> None:
    assert _create(signed_in, scope=CHANNELS).is_ok
    assert _token_files(signed_in) == [f"lvc_channels_{STAMP}{TOKEN_SUFFIX}"]


def test_a_token_without_the_client_has_no_project_in_its_name(creator: LivecraftPaths) -> None:
    project_file(creator).unlink()
    assert _create(creator, scope=PROJECT).is_ok
    assert _token_files(creator) == [f"lvc_{STAMP}{TOKEN_SUFFIX}"]


def test_the_switch_without_channels_in_the_content_gives_no_channels_mark(signed_in: LivecraftPaths) -> None:
    """Ползунок включён, а каналов в содержимом нет (channels.json не прочитан): имя — по содержимому, без channels."""
    signed_in.file(FileName.CHANNELS).unlink()
    verdict: TokenVerdict = _panel(signed_in).create(TokenDraft(days_text="3", scope=BOTH), _own(signed_in))
    assert verdict.is_ok and msg.TOKEN_FILE_LABELS["operator"] in verdict.text
    assert _token_files(signed_in) == [f"lvc_{TEST_PROJECT}_{STAMP}{TOKEN_SUFFIX}"]


def test_the_name_joins_only_the_parts_the_token_has() -> None:
    assert TokenName(project="proj-100200", has_channels=True, stamp="10-10-2026_185735").stem == (
        "lvc_proj-100200_channels_10-10-2026_185735"
    )
    assert TokenName(project=None, has_channels=True, stamp=STAMP).stem == f"lvc_channels_{STAMP}"


def test_a_renamed_token_loads_and_names_its_project(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    """Имя токена программа не читает: переименованный (расширение то же) загружается как прежде."""
    _create(creator, scope=PROJECT)
    renamed: Path = _file(creator).rename(_file(creator).with_name("токен для получателя" + TOKEN_SUFFIX))
    verdict: TokenVerdict = _panel(receiver).load(renamed)
    assert verdict.is_ok and PROJECT_LABEL in verdict.text.split("\n")[0]


def test_loading_beside_an_own_project_says_which_project_works(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    """У получателя свой рабочий проект: проект из токена сохранён в secrets, рабочим остался свой — строка итога
    загрузки говорит это и где сменить (§14 решения 65, 66)."""
    project_file(receiver).unlink()
    own: Path = receiver.root / "own client.json"
    own.write_text(client_text(project="receiver-project"), encoding="utf-8")
    choose_project(receiver, own)
    _create(creator, scope=PROJECT)
    verdict: TokenVerdict = _panel(receiver).load(_file(creator))
    assert verdict.is_ok
    kept: str = msg.SETUP_TOKENS_PROJECT_KEPT.format(
        project=TEST_PROJECT, file=str(Path("secrets") / f"google_project_{TEST_PROJECT}.json"), own="receiver-project"
    )
    assert verdict.text.split("\n")[-1] == kept
    assert SettingsFile.placed(receiver).project_file == own
