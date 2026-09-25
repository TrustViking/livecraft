from __future__ import annotations

import dataclasses
import logging
import os
from collections.abc import Iterator

import pytest

from app.config.loader import FormSettings, LivecraftSettings, load_settings, save_settings_file
from app.paths import LivecraftPaths
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.setup.migration import FormUrlMigration, FormUrlMigrationResult, MigrationOutcome
from app.setup.readiness import Readiness
from app.tests.conftest import LEGACY_FORM_URL, REPO_SETTINGS_FILE, SUPPLIED_VALUES, LogCollector, write_supplied_vault
from app.ui import messages_ru as msg

OWN_FORM_URL: str = "https://forms.gle/OwnFormCode12345"
OWN_SHEETS_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"
SET_FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-already-set/viewform"
BAD_FORM_URL: str = "http://example.com/forms/secret-form-code"
UNPARSABLE_FORM_URL: str = "https://[bad"


@pytest.fixture
def setup_log() -> Iterator[LogCollector]:
    """Записи логгера livecraft.setup за время теста."""
    logger: logging.Logger = logging.getLogger("livecraft.setup")
    collector: LogCollector = LogCollector()
    level: int = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(level)


def _save_own(paths: LivecraftPaths, values: dict[SecretField, str]) -> None:
    """Личный сейф пишется тем же путём, что и настройщиком: VaultStore.save_local."""
    own: Vault = Vault.empty()
    for field, value in values.items():
        own = own.with_field(field, SecretValue(field=field, value=value), VaultOrigin.OWN)
    VaultStore.open(paths).save_local(own)


def _own_layer(paths: LivecraftPaths) -> Vault:
    return VaultStore.open(paths).load().own


def _planned(paths: LivecraftPaths) -> FormUrlMigration:
    migration: FormUrlMigration | None = FormUrlMigration.plan(paths, Readiness.check(paths))
    assert migration is not None
    return migration


def _texts(result: FormUrlMigrationResult, log: LogCollector) -> str:
    return "\n".join((result.console_line, result.log_line, repr(result), *log.messages()))


# --- когда перенос нужен


def test_nothing_to_move_without_the_legacy_field(ready_paths: LivecraftPaths) -> None:
    assert FormUrlMigration.plan(ready_paths, Readiness.check(ready_paths)) is None


def test_nothing_to_move_when_the_form_url_is_already_set(ready_paths: LivecraftPaths) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    settings: LivecraftSettings = load_settings(ready_paths.config_file)
    form_set: FormSettings = dataclasses.replace(settings.form, url=SET_FORM_URL)
    save_settings_file(ready_paths.config_file, dataclasses.replace(settings, form=form_set))
    assert FormUrlMigration.plan(ready_paths, Readiness.check(ready_paths)) is None


def test_the_move_works_without_channels(ready_paths: LivecraftPaths) -> None:
    """Боевой случай 24-09-2026: channels.json ещё нет — ссылка всё равно переезжает, каналы ей не нужны."""
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    ready_paths.channels_file.unlink()
    result: FormUrlMigrationResult = _planned(ready_paths).run()
    assert result.moved
    assert load_settings(ready_paths.config_file).form.url == OWN_FORM_URL
    assert _own_layer(ready_paths).get(SecretField.KEY_FORM_URL) is None


def test_nothing_to_move_when_the_settings_do_not_read(ready_paths: LivecraftPaths) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    ready_paths.config_file.unlink()
    assert FormUrlMigration.plan(ready_paths, Readiness.check(ready_paths)) is None


def test_the_plan_masks_the_link_in_repr(ready_paths: LivecraftPaths) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    migration: FormUrlMigration = _planned(ready_paths)
    assert migration.source is VaultOrigin.OWN
    assert OWN_FORM_URL not in repr(migration)


# --- перенос из личного слоя


def test_the_own_link_moves_to_the_settings_and_leaves_the_own_vault(
    ready_paths: LivecraftPaths, setup_log: LogCollector
) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL, SecretField.SHEETS_ID: OWN_SHEETS_ID})
    before: LivecraftSettings = load_settings(ready_paths.config_file)
    result: FormUrlMigrationResult = _planned(ready_paths).run()
    assert result.moved and result.outcome is MigrationOutcome.MOVED
    assert result.source is VaultOrigin.OWN and result.local_cleared
    after: LivecraftSettings = load_settings(ready_paths.config_file)
    assert after.form.url == OWN_FORM_URL
    assert dataclasses.replace(after, form=before.form) == before                   # остальное как было
    assert dataclasses.replace(after.form, url="") == before.form
    own: Vault = _own_layer(ready_paths)
    assert own.get(SecretField.KEY_FORM_URL) is None
    kept: SecretValue | None = own.get(SecretField.SHEETS_ID)
    assert kept is not None and kept.reveal() == OWN_SHEETS_ID                     # другие свои поля на месте
    assert FormUrlMigration.plan(ready_paths, Readiness.check(ready_paths)) is None   # второй раз не нужен


def test_a_moved_link_keeps_the_rest_of_the_settings_file_byte_for_byte(ready_paths: LivecraftPaths) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    _planned(ready_paths).run()
    expected: str = REPO_SETTINGS_FILE.read_text(encoding="utf-8").replace(
        '"url": ""', f'"url": "{OWN_FORM_URL}"', 1
    )
    assert ready_paths.config_file.read_text(encoding="utf-8") == expected


def test_the_own_link_overrides_the_supplied_one(ready_paths: LivecraftPaths) -> None:
    write_supplied_vault(ready_paths, {**SUPPLIED_VALUES, SecretField.KEY_FORM_URL: LEGACY_FORM_URL})
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    _planned(ready_paths).run()
    assert load_settings(ready_paths.config_file).form.url == OWN_FORM_URL


# --- перенос из поставочного слоя


def test_the_supplied_link_moves_and_the_supplied_vault_stays_untouched(ready_paths: LivecraftPaths) -> None:
    write_supplied_vault(ready_paths, {**SUPPLIED_VALUES, SecretField.KEY_FORM_URL: LEGACY_FORM_URL})
    before: bytes = ready_paths.vault_file.read_bytes()
    stat_before: os.stat_result = ready_paths.vault_file.stat()
    result: FormUrlMigrationResult = _planned(ready_paths).run()
    assert result.moved and result.source is VaultOrigin.SUPPLIED and not result.local_cleared
    assert load_settings(ready_paths.config_file).form.url == LEGACY_FORM_URL
    assert ready_paths.vault_file.read_bytes() == before
    assert ready_paths.vault_file.stat().st_mtime_ns == stat_before.st_mtime_ns
    assert not ready_paths.vault_local_file.exists()                               # личного сейфа не появилось
    assert FormUrlMigration.plan(ready_paths, Readiness.check(ready_paths)) is None


# --- негодная ссылка


@pytest.mark.parametrize("bad_url", [BAD_FORM_URL, UNPARSABLE_FORM_URL])
def test_a_bad_link_writes_nothing_and_warns(ready_paths: LivecraftPaths, bad_url: str) -> None:
    """Ссылка, на которой urlsplit бросает ValueError, — такой же исход INVALID, а не падение каждого запуска."""
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: bad_url})
    settings_before: bytes = ready_paths.config_file.read_bytes()
    local_before: bytes = ready_paths.vault_local_file.read_bytes()
    result: FormUrlMigrationResult = _planned(ready_paths).run()
    assert not result.moved and result.outcome is MigrationOutcome.INVALID
    assert result.reason == msg.CONFIG_PROBLEM_FORM_URL
    assert result.console_line == msg.FORM_URL_MIGRATION_FAILED.format(reason=msg.CONFIG_PROBLEM_FORM_URL)
    assert ready_paths.config_file.read_bytes() == settings_before
    assert ready_paths.vault_local_file.read_bytes() == local_before


def test_a_settings_write_failure_keeps_the_vault(ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    local_before: bytes = ready_paths.vault_local_file.read_bytes()

    def _refuse(*_: object) -> None:
        raise PermissionError(13, "Отказано в доступе")

    monkeypatch.setattr("app.setup.migration.save_settings_file", _refuse)
    result: FormUrlMigrationResult = _planned(ready_paths).run()
    assert result.outcome is MigrationOutcome.WRITE_FAILED and not result.moved
    assert result.reason == "Отказано в доступе"
    assert ready_paths.vault_local_file.read_bytes() == local_before


# --- ссылка не уходит ни в лог, ни в консоль (§7.4)


@pytest.mark.parametrize("value", [OWN_FORM_URL, BAD_FORM_URL])
def test_no_line_carries_the_link(ready_paths: LivecraftPaths, setup_log: LogCollector, value: str) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: value})
    result: FormUrlMigrationResult = _planned(ready_paths).run()
    text: str = _texts(result, setup_log)
    assert value not in text
    assert SecretValue(field=SecretField.KEY_FORM_URL, value=value).log_label in result.log_line
    assert result.log_line.isascii()


def test_the_log_line_names_outcome_source_and_cleanup(ready_paths: LivecraftPaths) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    line: str = _planned(ready_paths).run().log_line
    assert "outcome=moved" in line and "source=own" in line and "local_cleared=True" in line


def test_the_vault_load_after_moving_holds_no_link(ready_paths: LivecraftPaths) -> None:
    _save_own(ready_paths, {SecretField.KEY_FORM_URL: OWN_FORM_URL})
    _planned(ready_paths).run()
    loaded: VaultLoad = VaultStore.open(ready_paths).load()
    assert loaded.vault.get(SecretField.KEY_FORM_URL) is None
    assert loaded.vault.is_ready
