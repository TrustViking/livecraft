from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest

from app.config.files import SettingsFile
from app.observability.log_event import LogArea
from app.paths import DataDir, FileName, LivecraftPaths
from app.secretsafe.dpapi import Dpapi
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.migration import DriveFolderMigration, DroppedSettingKeys, ProjectConnection
from app.setup.panels.token_file import ReceivedFiles, TokenFile
from app.setup.panels.token_scope import TokenItem, TokenScope
from app.tests.fixtures.google_client import client_text, project_file
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

OWN_SHEETS_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"


@pytest.fixture
def setup_log() -> Iterator[LogCapture]:
    """Записи логгера livecraft.setup за время теста."""
    with LogCapture.on(LogArea.SETUP, logging.DEBUG) as capture:
        yield capture


def _save_own(paths: LivecraftPaths, values: dict[SecretField, str]) -> None:
    """Личный сейф пишется тем же путём, что и настройщиком: VaultStore.save_local."""
    own: Vault = Vault.empty()
    for field, value in values.items():
        own = own.with_field(field, SecretValue(field=field, value=value), VaultOrigin.OWN)
    VaultStore.open(paths).save_local(own)


def _own_layer(paths: LivecraftPaths) -> Vault:
    return VaultStore.open(paths).load().own


# --- ссылка на папку Google Диска: из livecraft.json в сейф (§14 решение 39)

DRIVE_LINK: str = "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz0123-_?usp=sharing"
DRIVE_ID: str = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123-_"
DRIVE_FIELDS: tuple[SecretField, ...] = (SecretField.DRIVE_PREVIEWS_FOLDER, SecretField.DRIVE_DOCS_FOLDER)


def _with_legacy_link(paths: LivecraftPaths, link: str) -> bytes:
    """livecraft.json версии до решения 39: ключ drive.folder_url рядом с шаблоном подпапок; текст файла до переноса."""
    config = paths.file(FileName.CONFIG)
    data: dict[str, dict[str, object]] = json.loads(config.read_text(encoding="utf-8"))
    data["drive"] = {"folder_url": link, **data["drive"]}
    config.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return config.read_bytes()


def test_without_the_old_key_nothing_moves_and_nothing_is_written(ready_paths: LivecraftPaths) -> None:
    before: bytes = ready_paths.file(FileName.CONFIG).read_bytes()
    assert DriveFolderMigration.apply(ready_paths) == ()
    assert ready_paths.file(FileName.CONFIG).read_bytes() == before
    assert not ready_paths.file(FileName.VAULT_LOCAL).exists()


def test_the_link_moves_into_both_own_drive_folders_as_the_folder_id_and_leaves_the_file(
    ready_paths: LivecraftPaths, setup_log: LogCapture
) -> None:
    """Ссылка из livecraft.json — папкой превью и папкой документов (§14 решения 39, 60)."""
    _with_legacy_link(ready_paths, DRIVE_LINK)
    assert DriveFolderMigration.apply(ready_paths) == (msg.DRIVE_LINK_MIGRATED,)
    loaded: Vault = VaultStore.open(ready_paths).load().vault
    secrets: list[SecretValue] = []
    for field in DRIVE_FIELDS:
        secret: SecretValue | None = loaded.get(field)
        assert secret is not None and secret.reveal() == DRIVE_ID          # эталон теста, а не вызов в коде
        assert loaded.origin_of(field) is VaultOrigin.OWN
        secrets.append(secret)
    text: str = ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert "folder_url" not in text and DRIVE_ID not in text
    assert SettingsFile.of(ready_paths).load().drive.preview_path_template == "preview/{date}/{language}"
    [line] = setup_log.messages()
    labels: str = ",".join(secret.log_label for secret in secrets)
    assert line == f"drive_folder_migrated outcome=moved fields={labels}" and DRIVE_ID not in line


def test_the_move_keeps_the_other_own_values_of_the_vault(ready_paths: LivecraftPaths) -> None:
    _save_own(ready_paths, {SecretField.SHEETS_ID: OWN_SHEETS_ID})
    _with_legacy_link(ready_paths, DRIVE_ID)
    DriveFolderMigration.apply(ready_paths)
    own: Vault = _own_layer(ready_paths)
    assert own.missing_of((SecretField.SHEETS_ID, *DRIVE_FIELDS)) == ()


def test_an_empty_old_key_is_removed_without_a_line(ready_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    _with_legacy_link(ready_paths, "")
    assert DriveFolderMigration.apply(ready_paths) == ()
    assert "folder_url" not in ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert SettingsFile.of(ready_paths).read().error is None
    assert not ready_paths.file(FileName.VAULT_LOCAL).exists()
    assert setup_log.messages() == ["drive_folder_migrated outcome=empty fields=-"]


def test_a_bad_link_is_removed_and_the_line_says_to_paste_it_on_the_previews_tab(
    ready_paths: LivecraftPaths, setup_log: LogCapture
) -> None:
    bad: str = "https://docs.google.com/document/d/secret-doc-code/edit"
    _with_legacy_link(ready_paths, bad)
    lines: tuple[str, ...] = DriveFolderMigration.apply(ready_paths)
    assert lines == (msg.DRIVE_LINK_MIGRATION_FAILED.format(reason=msg.SETUP_INPUT_DRIVE_LINK),)
    assert "folder_url" not in ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert _own_layer(ready_paths).missing_of(DRIVE_FIELDS) == DRIVE_FIELDS
    assert setup_log.messages(logging.WARNING) == ["drive_folder_not_migrated outcome=invalid fields=-"]
    assert all("secret-doc-code" not in line for line in (*lines, *setup_log.messages()))


def test_without_dpapi_the_key_is_removed_and_the_line_says_why(
    ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_legacy_link(ready_paths, DRIVE_ID)
    monkeypatch.setattr(Dpapi, "load", classmethod(lambda cls: cls()))
    lines: tuple[str, ...] = DriveFolderMigration.apply(ready_paths)
    assert lines == (msg.DRIVE_LINK_MIGRATION_FAILED.format(reason=msg.SETUP_INPUT_OWN_UNAVAILABLE),)
    assert SettingsFile.of(ready_paths).read().error is None


def test_an_unreadable_own_vault_is_not_overwritten(ready_paths: LivecraftPaths) -> None:
    """Запись поверх не прочитанного личного сейфа стёрла бы введённые раньше значения: id туда не пишется."""
    _save_own(ready_paths, {SecretField.SHEETS_ID: OWN_SHEETS_ID})
    local: bytes = ready_paths.file(FileName.VAULT_LOCAL).read_bytes()
    data: dict[str, object] = json.loads(local.decode("utf-8"))
    data["key"] = "AAAA"
    ready_paths.file(FileName.VAULT_LOCAL).write_text(json.dumps(data), encoding="utf-8")
    broken: bytes = ready_paths.file(FileName.VAULT_LOCAL).read_bytes()
    _with_legacy_link(ready_paths, DRIVE_ID)
    lines: tuple[str, ...] = DriveFolderMigration.apply(ready_paths)
    assert lines == (msg.DRIVE_LINK_MIGRATION_FAILED.format(reason=msg.DRIVE_LINK_MIGRATION_LOCAL_UNREAD),)
    assert ready_paths.file(FileName.VAULT_LOCAL).read_bytes() == broken


# --- переключатель источника текстов (§14 решение 50) и чат поддержки (§14 решение 62) ушли: ключи — из livecraft.json


def _with_legacy(paths: LivecraftPaths, section: str, leaf: str, value: object) -> None:
    """livecraft.json прежней версии: ключ `section.leaf` первым в своём разделе."""
    config = paths.file(FileName.CONFIG)
    data: dict[str, dict[str, object]] = json.loads(config.read_text(encoding="utf-8"))
    data[section] = {leaf: value, **data[section]}
    config.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_the_text_source_key_goes_and_the_file_reads_again(ready_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    """С прежним ключом разбор файл отвергает; перенос убирает ключ — остальное как было, строка лога, консоль молчит."""
    _with_legacy(ready_paths, "broadcasts", "text_source", "llm")
    file: SettingsFile = SettingsFile.of(ready_paths)
    assert file.read().value is None                           # неизвестное поле — ошибка разбора
    before: dict[str, object] = json.loads(file.path.read_text(encoding="utf-8"))
    DroppedSettingKeys.apply(ready_paths)
    after: dict[str, object] = json.loads(file.path.read_text(encoding="utf-8"))
    assert after["broadcasts"] == {"resend_keys": False}
    assert {key: value for key, value in after.items() if key != "broadcasts"} == {
        key: value for key, value in before.items() if key != "broadcasts"
    }
    assert file.read().value is not None
    assert setup_log.messages() == ["setting_key_dropped key=broadcasts.text_source value=llm"]


def test_the_support_chat_key_goes_and_the_file_reads_again(ready_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    """Чат поддержки прежней версии: ключ уходит, чаты объявлений остаются, файл снова разбирается, строка лога."""
    _with_legacy(ready_paths, "telegram", "support_chat_id", "-1002000000002")
    file: SettingsFile = SettingsFile.of(ready_paths)
    assert file.read().value is None
    before: dict[str, object] = json.loads(file.path.read_text(encoding="utf-8"))
    DroppedSettingKeys.apply(ready_paths)
    after: dict[str, object] = json.loads(file.path.read_text(encoding="utf-8"))
    telegram: object = before["telegram"]
    assert isinstance(telegram, dict)
    assert after["telegram"] == {leaf: value for leaf, value in telegram.items() if leaf != "support_chat_id"}
    assert file.read().value is not None
    assert setup_log.messages() == ["setting_key_dropped key=telegram.support_chat_id value=-1002000000002"]


def test_both_old_keys_go_in_one_pass(ready_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    _with_legacy(ready_paths, "broadcasts", "text_source", "package")
    _with_legacy(ready_paths, "telegram", "support_chat_id", "")
    DroppedSettingKeys.apply(ready_paths)
    assert SettingsFile.of(ready_paths).read().value is not None
    assert setup_log.messages() == [
        "setting_key_dropped key=broadcasts.text_source value=package",
        "setting_key_dropped key=telegram.support_chat_id value=-",
    ]


def test_without_old_keys_the_file_is_not_touched(ready_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    before: bytes = ready_paths.file(FileName.CONFIG).read_bytes()
    DroppedSettingKeys.apply(ready_paths)
    assert ready_paths.file(FileName.CONFIG).read_bytes() == before and setup_log.messages() == []


def test_a_file_that_does_not_take_the_write_keeps_the_key_and_says_why(
    ready_paths: LivecraftPaths, setup_log: LogCapture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Файл не записался — ключ остаётся (о файле скажет разбор настроек), причина — предупреждением в лог."""
    _with_legacy(ready_paths, "telegram", "support_chat_id", "111000111")

    def _refuse(self: SettingsFile, key: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(SettingsFile, "drop_legacy", _refuse)
    DroppedSettingKeys.apply(ready_paths)
    [line] = setup_log.messages(logging.WARNING)
    assert line.startswith("setting_key_not_dropped key=telegram.support_chat_id value=111000111 reason=")


# --- проект Google не выбран: запуск подключает его файл из secrets (§14 решение 66)


def _shipped(paths: LivecraftPaths) -> LivecraftPaths:
    """Корень с поставочными настройками: проект Google не выбран."""
    paths.ensure_dirs()
    SettingsFile.of(paths).install_shipped()
    return paths


def test_the_old_client_file_is_connected_where_it_lies(livecraft_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    """client_secret.json — рабочим проектом: путь от корня в настройках, файл не переименован; второй запуск — ничего."""
    paths: LivecraftPaths = _shipped(livecraft_paths)
    paths.file(FileName.CLIENT_SECRET).write_text(client_text(), encoding="utf-8")
    project_file(paths, "other").write_text(client_text(project="other"), encoding="utf-8")
    assert ProjectConnection.apply(paths) == ("Проект Google: подключён secrets\\client_secret.json",)
    assert SettingsFile.of(paths).load().google.project_file == "secrets\\client_secret.json"
    assert SettingsFile.placed(paths).project_file == paths.file(FileName.CLIENT_SECRET)
    assert paths.file(FileName.CLIENT_SECRET).read_text(encoding="utf-8") == client_text()
    assert 'google_project_connected file="secrets\\\\client_secret.json"' in setup_log.messages()
    assert ProjectConnection.apply(paths) == ()


def test_the_only_project_file_of_secrets_is_connected_and_the_previous_one_is_not(
    livecraft_paths: LivecraftPaths,
) -> None:
    """Файл сборки 9.21 — google_project_<ID>.json — подключается; прежний (.previous.json) не берётся."""
    paths: LivecraftPaths = _shipped(livecraft_paths)
    project_file(paths).write_text(client_text(), encoding="utf-8")
    (paths.dir(DataDir.SECRETS) / "google_project_guests.previous.json").write_text("{}", encoding="utf-8")
    assert ProjectConnection.apply(paths) == ("Проект Google: подключён secrets\\google_project_kanal-test.json",)
    assert SettingsFile.placed(paths).project_file == project_file(paths)


def test_a_received_client_stays_received_and_does_not_go_into_a_new_token(livecraft_paths: LivecraftPaths) -> None:
    """Подключённый клиент, полученный с токеном, остаётся полученным: в новый токен он не идёт (§14 решение 65)."""
    paths: LivecraftPaths = _shipped(livecraft_paths)
    paths.file(FileName.CLIENT_SECRET).write_text(client_text(), encoding="utf-8")
    ReceivedFiles.load(paths).with_written([TokenFile.read(paths.file(FileName.CLIENT_SECRET))]).save()
    ProjectConnection.apply(paths)
    assert SettingsFile.placed(paths).project_file == paths.file(FileName.CLIENT_SECRET)
    assert TokenScope.of(TokenItem.GOOGLE_PROJECT).collect(paths).files == ()


def test_several_project_files_connect_nothing(livecraft_paths: LivecraftPaths) -> None:
    """Файлов проекта несколько и client_secret.json нет: какой подключить, не сказать — проект выберут в окне."""
    paths: LivecraftPaths = _shipped(livecraft_paths)
    project_file(paths).write_text(client_text(), encoding="utf-8")
    project_file(paths, "other").write_text(client_text(project="other"), encoding="utf-8")
    assert ProjectConnection.apply(paths) == ()
    assert SettingsFile.of(paths).load().google.project_file == ""


def test_a_chosen_project_is_not_replaced(ready_paths: LivecraftPaths) -> None:
    """Путь уже задан — запуск ничего не подключает, даже когда client_secret.json лежит рядом."""
    ready_paths.file(FileName.CLIENT_SECRET).write_text(client_text(project="other"), encoding="utf-8")
    before: bytes = ready_paths.file(FileName.CONFIG).read_bytes()
    assert ProjectConnection.apply(ready_paths) == ()
    assert ready_paths.file(FileName.CONFIG).read_bytes() == before


def test_without_readable_settings_nothing_is_connected(livecraft_paths: LivecraftPaths) -> None:
    """Настройки не читаются — о них скажет готовность; файл настроек не пишется."""
    livecraft_paths.ensure_dirs()
    livecraft_paths.file(FileName.CLIENT_SECRET).write_text(client_text(), encoding="utf-8")
    assert ProjectConnection.apply(livecraft_paths) == ()
    assert not livecraft_paths.file(FileName.CONFIG).exists()