"""Ползунок на каждое значение токена (§8.2 п.10, §14 решение 77): в токен входит только выбранное, ползунки стоят
группами по линиям работы, значения, которого на установке нет, выбрать нельзя."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.config.files import SettingsFile
from app.config.setting_key import SettingKey
from app.config.settings import LivecraftSettings
from app.config.telegram import ChatTarget, TelegramSettings
from app.paths import DataDir, FileName, LivecraftPaths
from app.platforms.passport import ChannelPassport, PassportEntry
from app.run.mode import LINE_ORDER
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.token import TOKEN_SUFFIX, TokenContent
from app.secretsafe.vault import Vault
from app.setup.panels.token_files import TokenFileName
from app.setup.panels.token_panel import TokenDraft, TokenPanel, TokenSettings, TokenVerdict
from app.setup.panels.token_scope import TokenGroup, TokenItem, TokenScope
from app.setup.setup_vault import SetupVault
from app.tests.conftest import CLIENT_SECRET_STUB, FORM_URL, REPO_CHANNELS_EXAMPLE
from app.tests.fixtures.google_client import TEST_CLIENT_ID, TEST_PROJECT, choose_project, project_file
from app.tests.fixtures.settings import set_contacts, set_form_url, with_telegram
from app.tests.fixtures.telegram import BOT_TOKEN, PRIVATE_CHAT_ID
from app.tests.fixtures.token import network_at
from app.tests.fixtures.vault import save_own_values, write_token_vault
from app.ui import messages_ru as msg

OWN_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-creator-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1creator-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.DRIVE_PREVIEWS_FOLDER: "1previews-DrIvEfOlDeR_0123456789-abcd",
    SecretField.DRIVE_DOCS_FOLDER: "1docs-DrIvEfOlDeR_0123456789-abcdefgh",
    SecretField.TELEGRAM_BOT_TOKEN: BOT_TOKEN,
}
GROUP_CHAT_ID: str = "-1001000000001"
CONTACTS: str = "@livecraft_help"
PROJECT_LABEL: str = msg.GOOGLE_PROJECT.format(project=TEST_PROJECT)
NONE: TokenScope = TokenScope()
CHANNEL_LOGIN: str = "@kanal_ua.token.json"
# Что несёт токен из одного ползунка: поля сейфа, открытые настройки и файлы. Куда слать объявления указывает на чат с
# ботом — едет только с ним.
CARRIED: dict[TokenItem, tuple[frozenset[SecretField], frozenset[str], frozenset[str]]] = {
    TokenItem.GOOGLE_PROJECT: (
        frozenset(), frozenset(), frozenset({TokenFileName.CLIENT.value, FileName.SHEETS_TOKEN.value})
    ),
    TokenItem.PLAN_SHEET: (frozenset({SecretField.SHEETS_ID}), frozenset(), frozenset()),
    TokenItem.OPENAI_KEY: (frozenset({SecretField.OPENAI_API_KEY}), frozenset(), frozenset()),
    TokenItem.PREVIEWS_FOLDER: (frozenset({SecretField.DRIVE_PREVIEWS_FOLDER}), frozenset(), frozenset()),
    TokenItem.DOCS_FOLDER: (frozenset({SecretField.DRIVE_DOCS_FOLDER}), frozenset(), frozenset()),
    TokenItem.DOC_CONTACTS: (frozenset(), frozenset({SettingKey.DOCS_CONTACTS.value}), frozenset()),
    TokenItem.BOT_TOKEN: (frozenset({SecretField.TELEGRAM_BOT_TOKEN}), frozenset(), frozenset()),
    TokenItem.PRIVATE_CHAT: (
        frozenset(),
        frozenset({SettingKey.TELEGRAM_PRIVATE_CHAT_ID.value, SettingKey.TELEGRAM_TARGET.value}),
        frozenset(),
    ),
    TokenItem.GROUP_CHAT: (frozenset(), frozenset({SettingKey.TELEGRAM_GROUP_CHAT_ID.value}), frozenset()),
    TokenItem.YOUTUBE_CHANNELS: (
        frozenset(), frozenset(), frozenset({FileName.CHANNELS.value, FileName.PASSPORT.value, CHANNEL_LOGIN})
    ),
    TokenItem.FORM_LINK: (frozenset(), frozenset({SettingKey.FORM_URL.value}), frozenset()),
}


def _google_login(refresh: str) -> str:
    """Файл входа Google через выбранный проект создателя (§14 решение 67)."""
    return json.dumps({"token": "ya29.access", "refresh_token": refresh, "client_id": TEST_CLIENT_ID, "client_secret": "s"})


def _root(tmp_path: Path, name: str) -> LivecraftPaths:
    """Корень установки: настройки поставки, каналы из примера, свой проект Google."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path / name)
    paths.ensure_dirs()
    SettingsFile.of(paths).install_shipped()
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, paths.file(FileName.CHANNELS))
    project_file(paths).write_text(CLIENT_SECRET_STUB, encoding="utf-8")
    return choose_project(paths, project_file(paths))


@pytest.fixture
def creator(tmp_path: Path) -> LivecraftPaths:
    """Установка, где задано всё, что может нести токен: свои значения сейфа, форма, контакты, чат с ботом и группа
    (объявления — в чат с ботом), проект, вход оператора, каналы с входом в @kanal_ua и записью паспорта."""
    paths: LivecraftPaths = _root(tmp_path, "creator")
    save_own_values(paths, OWN_VALUES)
    set_form_url(paths, FORM_URL)
    set_contacts(paths, CONTACTS)
    file: SettingsFile = SettingsFile.of(paths)
    file.save(with_telegram(file.load(), TelegramSettings(ChatTarget.PRIVATE, GROUP_CHAT_ID, PRIVATE_CHAT_ID)))
    paths.token_file("@kanal_ua").write_text(_google_login("1//creator-ua"), encoding="utf-8")
    paths.file(FileName.SHEETS_TOKEN).write_text(_google_login("1//creator-operator"), encoding="utf-8")
    passport: ChannelPassport = ChannelPassport(paths.file(FileName.PASSPORT))
    passport.record(PassportEntry(
        handle="@kanal_ua", account_name="kanal_ua", youtube_channel_id="UCkanal_ua", youtube_title="kanal_ua",
        youtube_handle_raw="@kanal_ua", google_account="kanal@example.com", token_file=CHANNEL_LOGIN,
        channel_url="https://www.youtube.com/channel/UCkanal_ua", handle_url="https://www.youtube.com/@kanal_ua",
        first_verified_at="01-10-2026 12:00", last_verified_at="01-10-2026 12:00",
    ))
    assert passport.save() is None
    return paths


@pytest.fixture
def receiver(tmp_path: Path) -> LivecraftPaths:
    return _root(tmp_path, "receiver")


def _panel(paths: LivecraftPaths) -> TokenPanel:
    return TokenPanel(paths=paths, network=network_at())


def _own(paths: LivecraftPaths) -> Vault:
    return SetupVault.open(paths).lenient.own


def _carried(content: TokenContent) -> tuple[frozenset[SecretField], frozenset[str], frozenset[str]]:
    return frozenset(content.vault.entries), frozenset(content.settings), frozenset(content.files)


def test_an_empty_choice_carries_nothing_and_creates_no_token(creator: LivecraftPaths) -> None:
    panel: TokenPanel = _panel(creator)
    assert _carried(panel.contents(_own(creator), NONE)) == (frozenset(), frozenset(), frozenset())
    assert panel.contents_line(_own(creator), NONE) == msg.SETUP_TOKENS_NOTHING
    verdict: TokenVerdict = panel.create(TokenDraft(days_text="3", scope=NONE), _own(creator))
    assert verdict.text == msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOKENS_NOTHING)
    assert list(creator.dir(DataDir.TOKENS).iterdir()) == []


@pytest.mark.parametrize("item", list(TokenItem))
def test_each_switch_alone_carries_only_its_value(creator: LivecraftPaths, item: TokenItem) -> None:
    assert _carried(_panel(creator).contents(_own(creator), TokenScope.of(item))) == CARRIED[item]


def test_where_announcements_go_rides_only_with_the_chat_it_points_to() -> None:
    """Назначение — чат с ботом: едет с чатом с ботом, с группой — нет; назначения без чата нет и с чатом."""
    values: dict[str, str] = {
        SettingKey.TELEGRAM_TARGET.value: ChatTarget.PRIVATE.value,
        SettingKey.TELEGRAM_PRIVATE_CHAT_ID.value: PRIVATE_CHAT_ID,
        SettingKey.TELEGRAM_GROUP_CHAT_ID.value: GROUP_CHAT_ID,
    }
    settings: TokenSettings = TokenSettings(values)
    assert settings.only(TokenScope.of(TokenItem.PRIVATE_CHAT)).values == {
        SettingKey.TELEGRAM_PRIVATE_CHAT_ID.value: PRIVATE_CHAT_ID,
        SettingKey.TELEGRAM_TARGET.value: ChatTarget.PRIVATE.value,
    }
    assert settings.only(TokenScope.of(TokenItem.GROUP_CHAT)).values == {
        SettingKey.TELEGRAM_GROUP_CHAT_ID.value: GROUP_CHAT_ID
    }
    without_target: TokenSettings = TokenSettings({SettingKey.TELEGRAM_PRIVATE_CHAT_ID.value: PRIVATE_CHAT_ID})
    assert without_target.only(TokenScope.of(TokenItem.PRIVATE_CHAT)).values == {
        SettingKey.TELEGRAM_PRIVATE_CHAT_ID.value: PRIVATE_CHAT_ID
    }


def test_the_line_names_only_what_is_chosen(creator: LivecraftPaths) -> None:
    panel: TokenPanel = _panel(creator)
    line: str = panel.contents_line(_own(creator), TokenScope.of(TokenItem.OPENAI_KEY, TokenItem.GOOGLE_PROJECT))
    assert line == msg.SETUP_TOKENS_CONTENTS.format(items=msg.LIST_JOINER.join((
        SecretField.OPENAI_API_KEY.human_label, PROJECT_LABEL, msg.TOKEN_FILE_LABELS["operator"]
    )))
    for value in (*OWN_VALUES.values(), FORM_URL, PRIVATE_CHAT_ID, GROUP_CHAT_ID, CONTACTS):
        assert value not in panel.contents_line(_own(creator), TokenScope(frozenset(TokenItem)))


def test_a_token_with_the_project_and_the_form_gives_the_receiver_only_them(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    """Токен тестерам по пакетам: проект Google и ссылка на форму — у получателя слой сейфа пуст, форма и проект на
    месте, Telegram и каналов нет (§14 решение 77)."""
    scope: TokenScope = TokenScope.of(TokenItem.GOOGLE_PROJECT, TokenItem.FORM_LINK)
    assert _panel(creator).create(TokenDraft(days_text="3", scope=scope), _own(creator)).is_ok
    token: Path = next(creator.dir(DataDir.TOKENS).glob("*" + TOKEN_SUFFIX))
    project_file(receiver).unlink()
    verdict: TokenVerdict = _panel(receiver).load(token)
    assert verdict.is_ok
    loaded: VaultLoad = VaultStore.open(receiver).load()
    assert loaded.token.entries == {} and loaded.own.entries == {}
    settings: LivecraftSettings = SettingsFile.of(receiver).load()
    assert settings.form.url == FORM_URL
    assert (settings.telegram.private_chat_id, settings.telegram.group_chat_id, settings.docs.contacts) == ("", "", "")
    assert SettingsFile.placed(receiver).project_file == receiver.received_project_file(TEST_PROJECT)
    assert receiver.file(FileName.SHEETS_TOKEN).is_file()
    assert receiver.file(FileName.CHANNELS).read_bytes() == REPO_CHANNELS_EXAMPLE.read_bytes()
    assert not receiver.token_file("@kanal_ua").exists()


def test_available_names_only_what_this_installation_has(creator: LivecraftPaths) -> None:
    """Чужое значение и пустая настройка — не «есть»: ползунок такого значения бледный."""
    write_token_vault(creator, {SecretField.DRIVE_DOCS_FOLDER: "1foreign-docs-folder-0123456789"})
    store: VaultStore = VaultStore.open(creator)
    store.save_local(_own(creator).without_field(SecretField.DRIVE_DOCS_FOLDER))
    set_contacts(creator, "")
    available: frozenset[TokenItem] = _panel(creator).available(_own(creator))
    assert available == frozenset(TokenItem) - {TokenItem.DOCS_FOLDER, TokenItem.DOC_CONTACTS}
    assert _own(creator).origin_of(SecretField.DRIVE_DOCS_FOLDER) is None
    assert VaultStore.open(creator).load().vault.origin_of(SecretField.DRIVE_DOCS_FOLDER) is VaultOrigin.TOKEN


def test_the_scope_keeps_only_the_chosen_vault_fields(creator: LivecraftPaths) -> None:
    kept: Vault = TokenScope.of(TokenItem.BOT_TOKEN, TokenItem.FORM_LINK).vault(_own(creator))
    assert set(kept.entries) == {SecretField.TELEGRAM_BOT_TOKEN}


def test_the_groups_go_project_first_then_lines_in_home_order_with_every_value_once() -> None:
    groups: tuple[TokenGroup, ...] = TokenGroup.all()
    assert groups[0] == TokenGroup(msg.SETUP_CLIENT_TITLE, (TokenItem.GOOGLE_PROJECT,))
    lines = [item.line for group in groups[1:] for item in group.items]
    assert [LINE_ORDER.index(line) for line in lines if line] == sorted(LINE_ORDER.index(line) for line in lines if line)
    assert sorted(item for group in groups for item in group.items) == sorted(TokenItem)
    assert [group.heading for group in groups[1:]] == [
        msg.RUN_PART_LABELS[part] for part in ("plan", "merge", "drive_previews", "doc", "announce", "broadcast", "keys")
    ]
    assert TokenGroup.all()[5].items == (TokenItem.BOT_TOKEN, TokenItem.PRIVATE_CHAT, TokenItem.GROUP_CHAT)


def test_every_value_has_a_label_and_the_project_and_channels_have_hints() -> None:
    assert set(msg.SETUP_TOKENS_ITEM_LABELS) == {item.value for item in TokenItem}
    assert all(item.label for item in TokenItem)
    assert {item for item in TokenItem if item.hint} == {
        TokenItem.GOOGLE_PROJECT, TokenItem.GROUP_CHAT, TokenItem.YOUTUBE_CHANNELS
    }
