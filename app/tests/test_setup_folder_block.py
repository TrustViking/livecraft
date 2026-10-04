"""Папка материалов на Google Диске в окне настройщика (CLAUDE.md §8.2, §14 решения 27, 37, 39): поле сейфа и его
проверка на «Превью» и на «Google-документе» — одно поле на двух вкладках; поле шаблона подпапки превью на «Превью»,
готовность линии «Превью на Google Диске» на «Главной».

Проверка папки идёт в фоновом потоке; тест ждёт её итог, прокручивая события окна. К Google тесты не ходят: Диск —
подделка в памяти, она знает папку только по id — годный итог значит, что id из сейфа дошёл до Диска.
"""
from __future__ import annotations

from collections.abc import Iterator
from tkinter import font, ttk

import pytest

from app.config.files import SettingsFile
from app.config.setting_key import SettingKey
from app.paths import FileName, LivecraftPaths
from app.run.mode import RunPart
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.tabs.folder_block import FolderBlock
from app.setup.tabs.key_rows import KeyRowView
from app.sheets.preview import PREVIEW_HEADER
from app.tests.fixtures.drive import ROOT_FOLDER_ID, ROOT_FOLDER_NAME, FakeDriveService
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.tests.fixtures.settings import DRIVE_FOLDER_URL
from app.ui import messages_ru as msg

FIELD: SecretField = SecretField.DRIVE_FOLDER


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


def _save(block: FolderBlock, driver: SetupWindowDriver, text: str) -> KeyRowView:
    row: KeyRowView = block.row
    driver.type(row.entry, text)
    row.accept_button.invoke()
    return row


def _vault(driver: SetupWindowDriver) -> Vault:
    return VaultStore.open(driver.window.paths).load().vault


def _status(row: KeyRowView) -> str:
    return str(row.status.cget("text"))


def test_the_folder_field_is_on_both_tabs_with_its_label_hint_and_a_check_button(driver: SetupWindowDriver) -> None:
    texts: list[str] = driver.visible_texts()
    assert texts.count(msg.SETUP_KEY_FIELD_LABELS[FIELD.value]) == 2
    assert texts.count(msg.SETUP_KEY_FIELD_HINTS[FIELD.value]) == 2
    assert texts.count(msg.SETUP_FOLDER_BUTTON_CHECK) == 2
    for block in (driver.folder, driver.doc_folder):
        assert _status(block.row) == msg.SETUP_STATUS_NOT_SET
        assert block.line.result_text == "" and not block.line.is_running


def test_saving_the_folder_link_puts_the_id_into_the_vault_and_checks_the_folder(driver: SetupWindowDriver) -> None:
    """Ссылка — в личный сейф id папки своим значением; в livecraft.json её нет; статус — маска, а не ссылка."""
    service: FakeDriveService = FakeDriveService()
    driver.check_folder_on(service)
    row: KeyRowView = _save(driver.folder, driver, DRIVE_FOLDER_URL)
    secret: SecretValue | None = _vault(driver).get(FIELD)
    assert secret is not None and secret.reveal() == ROOT_FOLDER_ID       # эталон теста, а не вызов в коде
    assert _vault(driver).origin_of(FIELD) is VaultOrigin.OWN
    assert ROOT_FOLDER_ID not in driver.window.paths.file(FileName.CONFIG).read_text(encoding="utf-8")
    assert _status(row) == msg.SETUP_KEY_STATUS_OWN.format(mask=secret.short_mask)
    assert ROOT_FOLDER_ID not in _status(row)
    assert driver.folder.line.is_running
    driver.wait_for_folder_check()
    assert driver.folder.line.result_text == msg.SETUP_FOLDER_OK.format(name=ROOT_FOLDER_NAME)
    assert service.calls == ["files.get"]
    assert not driver.tabs.previews.is_dirty


def test_a_link_that_is_not_a_drive_folder_is_refused_on_the_spot(driver: SetupWindowDriver) -> None:
    service: FakeDriveService = FakeDriveService()
    driver.check_folder_on(service)
    row: KeyRowView = _save(driver.folder, driver, "https://docs.google.com/document/d/abc/edit")
    assert row.problem.text == msg.SETUP_INPUT_DRIVE_FOLDER
    assert _vault(driver).get(FIELD) is None
    assert not driver.folder.line.is_running and service.calls == []


def test_deleting_the_folder_does_not_check_anything(driver: SetupWindowDriver) -> None:
    service: FakeDriveService = FakeDriveService()
    driver.check_folder_on(service)
    row: KeyRowView = _save(driver.folder, driver, ROOT_FOLDER_ID)
    driver.wait_for_folder_check()
    service.calls.clear()
    row.reset_button.invoke()
    assert _vault(driver).get(FIELD) is None and _status(row) == msg.SETUP_STATUS_NOT_SET
    assert not driver.folder.line.is_running and service.calls == []


def test_the_button_checks_the_saved_folder(driver: SetupWindowDriver) -> None:
    service: FakeDriveService = FakeDriveService()
    driver.check_folder_on(service)
    _save(driver.folder, driver, ROOT_FOLDER_ID)
    driver.wait_for_folder_check()
    driver.folder.line.button.invoke()
    driver.wait_for_folder_check()
    assert service.calls == ["files.get", "files.get"]


def test_the_folder_saved_on_the_document_tab_shows_on_previews_and_is_checked_there(
    driver: SetupWindowDriver,
) -> None:
    """Одно поле на двух вкладках: сохранено на «Google-документе» — проверка там, та же маска на «Превью»."""
    service: FakeDriveService = FakeDriveService()
    driver.check_folder_on(service)
    row: KeyRowView = _save(driver.doc_folder, driver, ROOT_FOLDER_ID)
    driver.wait_for(driver.doc_folder.line)
    assert driver.doc_folder.line.result_text == msg.SETUP_FOLDER_OK.format(name=ROOT_FOLDER_NAME)
    assert _status(driver.folder.row) == _status(row) != msg.SETUP_STATUS_NOT_SET
    assert not driver.folder.line.is_running and service.calls == ["files.get"]


def test_saving_the_folder_makes_its_line_ready(driver: SetupWindowDriver) -> None:
    """Превью на Google Диске не хватает папки — ✗ с её названием; папка сохранена — ✓ готово."""
    gap: str = msg.VAULT_FIELD_DRIVE_FOLDER          # без вкладки: её называет «Перейти» рядом
    state = driver.tabs.home.lines[RunPart.DRIVE_PREVIEWS].state
    assert str(state.cget("text")) == msg.SETUP_LINE_BLOCKED.format(gaps=gap)
    _save(driver.folder, driver, ROOT_FOLDER_ID)
    driver.wait_for_folder_check()
    assert str(state.cget("text")) == msg.SETUP_LINE_READY


def test_the_previews_tab_has_the_drive_preview_template(driver: SetupWindowDriver) -> None:
    key: str = SettingKey.DRIVE_PREVIEW_PATH_TEMPLATE.value
    texts: list[str] = driver.visible_texts()
    assert msg.SETUP_SETTINGS_FIELD_LABELS[key] in texts and msg.SETUP_SETTINGS_FIELD_HINTS[key] in texts
    assert "drive_preview_path_template" in driver.tabs.previews.drive.inputs
    assert "folder_url" not in SettingsFile.of(driver.window.paths).load().to_data()[SettingKey.DRIVE.value]


def test_the_table_sample_shows_the_preview_column_and_the_new_rule(driver: SetupWindowDriver) -> None:
    texts: list[str] = driver.visible_texts()
    assert PREVIEW_HEADER in texts and msg.SETUP_TABLE_SAMPLE_BY_PROGRAM in texts
    assert msg.SETUP_TABLE_TEXT_AFTER.format(timezone="Europe/Kyiv") in texts


def test_the_document_access_field_is_not_narrower_than_its_longest_value(driver: SetupWindowDriver) -> None:
    """Смотр окна 29-09-2026: «все по ссылке — правк…» обрезалось; поле выбора шире самой длинной подписи."""
    box: ttk.Combobox = driver.tabs.doc.doc.inputs["docs_access"]  # type: ignore[assignment]
    driver.window.root.update_idletasks()
    longest: str = max(msg.SETUP_DOC_ACCESS_LABELS.values(), key=len)
    text_font: font.Font = font.nametofont(str(box.cget("font")) or "TkTextFont", root=driver.window.root)
    assert box.winfo_reqwidth() > text_font.measure(longest)
