"""Вкладка «Токены» без окна: создание токена одним файлом из своих значений и загрузка полученного (§13 задача 7.1,
§14 решения 16, 44, 45; §7.4 — значения нигде не видны)."""
from __future__ import annotations

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
from app.setup.panels.token_panel import OPEN_KEYS, TokenDraft, TokenPanel, TokenVerdict
from app.setup.setup_vault import SetupVault
from app.tests.conftest import CLIENT_SECRET_STUB, FORM_URL, REPO_CHANNELS_EXAMPLE
from app.tests.fixtures.logs import LogCapture
from app.observability.log_event import LogArea
from app.tests.fixtures.settings import set_contacts, set_form_url
from app.tests.fixtures.telegram import BOT_TOKEN, PRIVATE_CHAT_ID, connect_private_chat
from app.tests.fixtures.token import NETWORK_NOW, network_at, network_down
from app.tests.fixtures.vault import save_own_values, write_token_vault
from app.ui import messages_ru as msg

OWN_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-creator-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1creator-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
}
# То, что пришло создателю в чужом токене: дальше не передаётся (§14 решение 16).
FOREIGN_TOKEN_VALUES: dict[SecretField, str] = {
    SecretField.DRIVE_FOLDER: "1foreign-DrIvEfOlDeR_0123456789-abcd",
}
SUPPORT_BOT_TOKEN: str = "987654321:AAFsupport-Zy9xWvUtSrQpOnMlKjIhGfEdCbA_987"
RECEIVER_OWN_SHEET: str = "1receiver-own-table-B3c4D5e6F7g8H9i0JkLmNoPqRs"
STAMP: str = "29-09-2026_150000"        # 12:00 UTC — 15:00 по Киеву, поясу поставки
CONTACTS: str = "@livecraft_help, help@example.com"
VERSION_OFFSET: int = 4                 # байт версии токена — сразу после магии


def _root(tmp_path: Path, name: str) -> LivecraftPaths:
    """Корень установки: настройки поставки, каналы из примера, client_secret.json — как у человека."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path / name)
    paths.ensure_dirs()
    SettingsFile.of(paths).install_shipped()
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, paths.file(FileName.CHANNELS))
    paths.file(FileName.CLIENT_SECRET).write_text(CLIENT_SECRET_STUB, encoding="utf-8")
    return paths


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


def _create(paths: LivecraftPaths, days: str = "3") -> TokenVerdict:
    return _panel(paths).create(TokenDraft(days_text=days), _own(paths))


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
    assert _token_files(creator) == [f"livecraft_{STAMP}{TOKEN_SUFFIX}"]
    assert verdict.text.split("\n")[:2] == [
        msg.SETUP_TOKENS_CREATED.format(token=f"tokens\\livecraft_{STAMP}{TOKEN_SUFFIX}"),
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
    assert panel.contents_line(_own(creator)) == msg.SETUP_TOKENS_CONTENTS.format(items=items)
    verdict: TokenVerdict = panel.create(TokenDraft(days_text="3"), _own(creator))
    assert verdict.text.split("\n")[2] == msg.SETUP_TOKENS_INSIDE.format(items=items)
    for value in (*OWN_VALUES.values(), BOT_TOKEN, FORM_URL, PRIVATE_CHAT_ID, *FOREIGN_TOKEN_VALUES.values()):
        assert value not in verdict.text and value not in panel.contents_line(_own(creator))


@pytest.mark.parametrize("days", ["0", "-1", "три", "", "3651", "1.5"])
def test_the_period_is_a_whole_number_of_days_in_bounds(creator: LivecraftPaths, days: str) -> None:
    verdict: TokenVerdict = _create(creator, days=days)
    assert not verdict.is_ok
    assert verdict.text == msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOKENS_DAYS_PROBLEM.format(maximum=3650))
    assert _token_files(creator) == []


def test_without_own_values_there_is_nothing_to_pass(receiver: LivecraftPaths) -> None:
    """Только значения из чужого токена — передавать нечего: дальше они не идут (§14 решение 16)."""
    write_token_vault(receiver, FOREIGN_TOKEN_VALUES)
    panel: TokenPanel = _panel(receiver)
    assert panel.contents_line(_own(receiver)) == msg.SETUP_TOKENS_NOTHING
    verdict: TokenVerdict = panel.create(TokenDraft(days_text="3"), _own(receiver))
    assert verdict.text == msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOKENS_NOTHING)
    assert _token_files(receiver) == []


def test_without_network_no_token_is_created(creator: LivecraftPaths) -> None:
    verdict: TokenVerdict = _panel(creator, network_down()).create(TokenDraft(days_text="3"), _own(creator))
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
    assert panel.contents_line(_own(creator)).endswith(msg.TOKEN_SETTING_LABELS["docs.contacts"] + ".")
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
    assert msg.TOKEN_SETTING_LABELS["docs.contacts"] not in _panel(creator).contents_line(_own(creator))
    _create(creator)
    set_contacts(receiver, "@receiver_contacts")
    assert _panel(receiver).load(_file(creator)).is_ok
    assert SettingsFile.of(receiver).load().docs.contacts == "@receiver_contacts"


def test_the_contacts_label_is_one_for_the_token_and_the_window() -> None:
    assert msg.TOKEN_SETTING_LABELS["docs.contacts"] is msg.SETUP_SETTINGS_FIELD_LABELS["docs.contacts"]
    assert OPEN_KEYS[-1] is SettingKey.DOCS_CONTACTS and set(msg.TOKEN_SETTING_LABELS) == {key.value for key in OPEN_KEYS}


def test_the_token_never_carries_foreign_token_values_channels_or_google_logins(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    """В токен идут только свои значения и открытые настройки: ни значения из чужого токена, ни каналы, ни входы в
    Google, ни client_secret.json (§7.3, §14 решение 16)."""
    creator.token_file("kanal.x").write_text("{}", encoding="utf-8")
    creator.file(FileName.SHEETS_TOKEN).write_text("{}", encoding="utf-8")
    _create(creator)
    _panel(receiver).load(_file(creator))
    loaded: VaultLoad = VaultStore.open(receiver).load()
    assert SecretField.DRIVE_FOLDER not in loaded.vault.entries
    assert not receiver.token_file("kanal.x").exists() and not receiver.file(FileName.SHEETS_TOKEN).exists()
    assert receiver.file(FileName.CHANNELS).read_bytes() == REPO_CHANNELS_EXAMPLE.read_bytes()
    assert receiver.file(FileName.CLIENT_SECRET).read_text(encoding="utf-8") == CLIENT_SECRET_STUB


def test_an_own_support_bot_goes_into_the_token_and_a_support_bot_from_a_token_goes_no_further(
    creator: LivecraftPaths, receiver: LivecraftPaths
) -> None:
    """Бот поддержки — своё значение, как другие: уходит в токен, и получатель отправляет логи в поддержку без
    настройки; у получателя он «из токена» — в его новый токен не идёт (§7.3, §14 решение 58)."""
    save_own_values(creator, {SecretField.SUPPORT_BOT_TOKEN: SUPPORT_BOT_TOKEN})
    _create(creator)
    _panel(receiver).load(_file(creator))
    loaded: VaultLoad = VaultStore.open(receiver).load()
    assert _values(loaded, VaultOrigin.TOKEN)[SecretField.SUPPORT_BOT_TOKEN] == SUPPORT_BOT_TOKEN
    assert SecretField.SUPPORT_BOT_TOKEN not in _panel(receiver).contents(_own(receiver)).vault.entries


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
        _create(creator)
        _panel(receiver).load(_file(creator))
    text: str = "\n".join((*setup_log.messages(), *vault_log.messages()))
    assert "token_created until=" in text and "token_loaded" in text
    for value in (*OWN_VALUES.values(), BOT_TOKEN, FORM_URL, PRIVATE_CHAT_ID):
        assert value not in text


def test_a_new_token_replaces_the_previous_token_values(creator: LivecraftPaths, receiver: LivecraftPaths) -> None:
    write_token_vault(receiver, FOREIGN_TOKEN_VALUES)
    _create(creator)
    _panel(receiver).load(_file(creator))
    assert SecretField.DRIVE_FOLDER not in VaultStore.open(receiver).load().token.entries


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