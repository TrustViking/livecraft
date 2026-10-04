from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest

from app.config.files import SettingsFile
from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.secretsafe.dpapi import Dpapi
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.migration import DriveFolderMigration, TextSourceMigration
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


def test_the_link_moves_into_the_own_vault_as_the_folder_id_and_leaves_the_file(
    ready_paths: LivecraftPaths, setup_log: LogCapture
) -> None:
    _with_legacy_link(ready_paths, DRIVE_LINK)
    assert DriveFolderMigration.apply(ready_paths) == (msg.DRIVE_FOLDER_MIGRATED,)
    loaded: Vault = VaultStore.open(ready_paths).load().vault
    secret: SecretValue | None = loaded.get(SecretField.DRIVE_FOLDER)
    assert secret is not None and secret.reveal() == DRIVE_ID              # эталон теста, а не вызов в коде
    assert loaded.origin_of(SecretField.DRIVE_FOLDER) is VaultOrigin.OWN
    text: str = ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert "folder_url" not in text and DRIVE_ID not in text
    assert SettingsFile.of(ready_paths).load().drive.preview_path_template == "preview/{date}/{language}"
    [line] = setup_log.messages()
    assert line == f"drive_folder_migrated outcome=moved value={secret.log_label}" and DRIVE_ID not in line


def test_the_move_keeps_the_other_own_values_of_the_vault(ready_paths: LivecraftPaths) -> None:
    _save_own(ready_paths, {SecretField.SHEETS_ID: OWN_SHEETS_ID})
    _with_legacy_link(ready_paths, DRIVE_ID)
    DriveFolderMigration.apply(ready_paths)
    own: Vault = _own_layer(ready_paths)
    assert own.missing_of((SecretField.SHEETS_ID, SecretField.DRIVE_FOLDER)) == ()


def test_an_empty_old_key_is_removed_without_a_line(ready_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    _with_legacy_link(ready_paths, "")
    assert DriveFolderMigration.apply(ready_paths) == ()
    assert "folder_url" not in ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert SettingsFile.of(ready_paths).read().error is None
    assert not ready_paths.file(FileName.VAULT_LOCAL).exists()
    assert setup_log.messages() == ["drive_folder_migrated outcome=empty value=-"]


def test_a_bad_link_is_removed_and_the_line_says_to_paste_it_on_the_previews_tab(
    ready_paths: LivecraftPaths, setup_log: LogCapture
) -> None:
    bad: str = "https://docs.google.com/document/d/secret-doc-code/edit"
    _with_legacy_link(ready_paths, bad)
    lines: tuple[str, ...] = DriveFolderMigration.apply(ready_paths)
    assert lines == (msg.DRIVE_FOLDER_MIGRATION_FAILED.format(reason=msg.SETUP_INPUT_DRIVE_FOLDER),)
    assert "folder_url" not in ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert _own_layer(ready_paths).get(SecretField.DRIVE_FOLDER) is None
    assert setup_log.messages(logging.WARNING) == ["drive_folder_not_migrated outcome=invalid value=-"]
    assert all("secret-doc-code" not in line for line in (*lines, *setup_log.messages()))


def test_without_dpapi_the_key_is_removed_and_the_line_says_why(
    ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_legacy_link(ready_paths, DRIVE_ID)
    monkeypatch.setattr(Dpapi, "load", classmethod(lambda cls: cls()))
    lines: tuple[str, ...] = DriveFolderMigration.apply(ready_paths)
    assert lines == (msg.DRIVE_FOLDER_MIGRATION_FAILED.format(reason=msg.SETUP_INPUT_OWN_UNAVAILABLE),)
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
    assert lines == (msg.DRIVE_FOLDER_MIGRATION_FAILED.format(reason=msg.DRIVE_FOLDER_MIGRATION_LOCAL_UNREAD),)
    assert ready_paths.file(FileName.VAULT_LOCAL).read_bytes() == broken


# --- переключатель источника текстов ушёл (§14 решение 50): ключ — из livecraft.json


def _with_text_source(paths: LivecraftPaths, value: object) -> None:
    """livecraft.json версии до решения 50: ключ broadcasts.text_source перед повторной передачей."""
    config = paths.file(FileName.CONFIG)
    data: dict[str, dict[str, object]] = json.loads(config.read_text(encoding="utf-8"))
    data["broadcasts"] = {"text_source": value, **data["broadcasts"]}
    config.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_the_text_source_key_goes_and_the_file_reads_again(ready_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    """С прежним ключом разбор файл отвергает; перенос убирает ключ — остальное как было, строка лога, консоль молчит."""
    _with_text_source(ready_paths, "llm")
    file: SettingsFile = SettingsFile.of(ready_paths)
    assert file.read().value is None                           # неизвестное поле — ошибка разбора
    before: dict[str, object] = json.loads(file.path.read_text(encoding="utf-8"))
    TextSourceMigration.apply(ready_paths)
    after: dict[str, object] = json.loads(file.path.read_text(encoding="utf-8"))
    assert after["broadcasts"] == {"resend_keys": False}
    assert {key: value for key, value in after.items() if key != "broadcasts"} == {
        key: value for key, value in before.items() if key != "broadcasts"
    }
    assert file.read().value is not None
    assert setup_log.messages() == ["text_source_dropped value=llm"]


def test_without_the_text_source_key_the_file_is_not_touched(ready_paths: LivecraftPaths, setup_log: LogCapture) -> None:
    before: bytes = ready_paths.file(FileName.CONFIG).read_bytes()
    TextSourceMigration.apply(ready_paths)
    assert ready_paths.file(FileName.CONFIG).read_bytes() == before and setup_log.messages() == []


def test_a_file_that_does_not_take_the_write_keeps_the_key_and_says_why(
    ready_paths: LivecraftPaths, setup_log: LogCapture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Файл не записался — ключ остаётся (о файле скажет разбор настроек), причина — предупреждением в лог."""
    _with_text_source(ready_paths, "package")

    def _refuse(self: SettingsFile, key: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(SettingsFile, "drop_legacy", _refuse)
    TextSourceMigration.apply(ready_paths)
    [line] = setup_log.messages(logging.WARNING)
    assert line.startswith("text_source_not_dropped value=package reason=")
