from __future__ import annotations

import json
import logging
import os
from typing import Any

import pytest

from app.paths import LivecraftPaths
from app.secretsafe.crypto import KEY_WRAPPED, VaultFormatError
from app.secretsafe.dpapi import Dpapi, DpapiUnavailable
from app.secretsafe.store import VAULT_FILE_ENCODING, LocalVaultState, ProgramKey, VaultStore
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.setup.panels.keys_panel import KeyRow, KeysPanel, KeysPanelEdit, RowAction
from app.tests.conftest import SUPPLIED_VALUES, write_supplied_vault
from app.ui import messages_ru as msg

OWN_OPENAI_KEY: str = "sk-proj-own-Zy9xWvUtSrQpOnMlKjIhGfEdCbA9876543210"
OWN_SHEET_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"
OWN_SHEET_URL: str = f"https://docs.google.com/spreadsheets/d/{OWN_SHEET_ID}/edit#gid=0"
OWN_RANGE: str = "'План стримов'!A2:F"
LEGACY_FORM_URL: str = "https://forms.gle/OwnFormCode12345"
REPLACE_ONLY: frozenset[RowAction] = frozenset({RowAction.REPLACE})
OWN_ACTIONS: frozenset[RowAction] = frozenset({RowAction.REPLACE, RowAction.RESET, RowAction.REVEAL})
ENTER_ONLY: frozenset[RowAction] = frozenset({RowAction.ENTER})


@pytest.fixture
def store(ready_paths: LivecraftPaths) -> VaultStore:
    """Готовый корень: поставочный сейф на все поля, личного файла нет; сейф собран боевым путём."""
    return VaultStore.open(ready_paths)


@pytest.fixture
def bare_store(livecraft_paths: LivecraftPaths) -> VaultStore:
    """Чистая установка: ни поставочного, ни личного сейфа."""
    return VaultStore.open(livecraft_paths)


def _no_dpapi_store(paths: LivecraftPaths) -> VaultStore:
    """Сейф на машине без DPAPI: объект без библиотек честно отказывает в работе."""
    return VaultStore(
        supplied_path=paths.vault_file,
        local_path=paths.vault_local_file,
        program_key=ProgramKey.load(paths.program_key_file),
        dpapi=Dpapi(),
    )


def _row(panel: KeysPanel, field: SecretField) -> KeyRow:
    return next(row for row in panel.rows if row.field is field)


def _applied(edit: KeysPanelEdit) -> KeysPanel:
    assert edit.is_applied, edit.problem
    return edit.panel


def _visible_texts(panel: KeysPanel) -> list[str]:
    texts: list[str] = list(panel.notices)
    for row in panel.rows:
        texts.extend((row.label, row.origin_label, row.display, repr(row)))
    texts.append(repr(panel))
    return texts


def _all_secret_values(*panels: KeysPanel) -> set[str]:
    """Значения сейфа — эталон теста: reveal() зовёт тест, а не код вкладки."""
    values: set[str] = set()
    for panel in panels:
        for vault in (panel.supplied, panel.own, panel.vault):
            values.update(secret.reveal() for secret in vault.secrets())
    return values


# --- строки вкладки


def test_rows_follow_the_order_of_the_vault_fields(store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.from_store(store)
    assert tuple(row.field for row in panel.rows) == SecretField.current()
    assert tuple(row.label for row in panel.rows) == tuple(field.human_label for field in SecretField.current())


def test_the_legacy_form_url_has_no_row_even_when_it_lies_in_the_vault(ready_paths: LivecraftPaths) -> None:
    """Ссылка на форму — открытая настройка (§14 решение 15): строки на вкладке ключей у неё нет."""
    write_supplied_vault(ready_paths, {**SUPPLIED_VALUES, SecretField.KEY_FORM_URL: LEGACY_FORM_URL})
    panel: KeysPanel = KeysPanel.from_store(VaultStore.open(ready_paths))
    assert panel.vault.get(SecretField.KEY_FORM_URL) is not None
    assert SecretField.KEY_FORM_URL not in [row.field for row in panel.rows]


def test_the_legacy_form_url_cannot_be_entered(store: VaultStore) -> None:
    before: KeysPanel = KeysPanel.from_store(store)
    edit: KeysPanelEdit = before.replace(SecretField.KEY_FORM_URL, LEGACY_FORM_URL)
    assert not edit.is_applied
    assert edit.problem == msg.SETUP_INPUT_LEGACY_FIELD
    assert edit.panel is before


def test_a_supplied_field_offers_only_replace_and_shows_the_mask(store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.from_store(store)
    for row in panel.rows:
        assert row.actions == REPLACE_ONLY
        assert row.origin_label == msg.VAULT_ORIGIN_SUPPLIED
        expected: SecretValue | None = panel.supplied.get(row.field)
        assert expected is not None
        assert row.display == expected.masked
        assert SUPPLIED_VALUES[row.field] not in row.display


def test_an_own_field_offers_replace_reset_reveal_and_shows_the_mask(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    row: KeyRow = _row(panel, SecretField.OPENAI_API_KEY)
    assert row.actions == OWN_ACTIONS
    assert row.origin_label == msg.VAULT_ORIGIN_OWN
    assert row.display == SecretValue(field=SecretField.OPENAI_API_KEY, value=OWN_OPENAI_KEY).masked
    assert OWN_OPENAI_KEY not in row.display


def test_an_empty_field_offers_only_enter_and_says_none(bare_store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.from_store(bare_store)
    for row in panel.rows:
        assert row.actions == ENTER_ONLY
        assert row.origin_label == msg.READINESS_FIELD_ABSENT
        assert row.display == msg.READINESS_FIELD_ABSENT


# --- замена своим


def test_replace_with_good_input_makes_the_field_own_and_leaves_the_old_panel(store: VaultStore) -> None:
    before: KeysPanel = KeysPanel.from_store(store)
    edit: KeysPanelEdit = before.replace(SecretField.SHEETS_ID, OWN_SHEET_URL)
    after: KeysPanel = _applied(edit)
    assert edit.problem is None
    assert _row(after, SecretField.SHEETS_ID).origin_label == msg.VAULT_ORIGIN_OWN
    assert after.vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    own_id: SecretValue | None = after.own.get(SecretField.SHEETS_ID)
    assert own_id is not None and own_id.reveal() == OWN_SHEET_ID     # в сейф ушёл id, а не ссылка
    assert _row(before, SecretField.SHEETS_ID).origin_label == msg.VAULT_ORIGIN_SUPPLIED
    assert before.own == Vault.empty()


def test_replace_with_bad_input_names_the_problem_and_changes_nothing(store: VaultStore) -> None:
    before: KeysPanel = KeysPanel.from_store(store)
    edit: KeysPanelEdit = before.replace(SecretField.SHEETS_RANGE, "A")
    assert not edit.is_applied
    assert edit.problem == msg.SETUP_INPUT_SHEETS_RANGE
    assert edit.panel is before
    assert edit.panel.rows == before.rows


def test_replace_with_empty_input_without_an_own_value_asks_for_input(store: VaultStore) -> None:
    """Под строкой только поставочное значение: сброса нет — текст просит ввести значение."""
    edit: KeysPanelEdit = KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, "   ")
    assert edit.problem == msg.SETUP_INPUT_EMPTY


def test_replace_with_empty_input_over_the_supply_names_the_return_button(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    edit: KeysPanelEdit = panel.replace(SecretField.SHEETS_RANGE, "")
    assert not edit.is_applied and edit.panel is panel
    assert edit.problem == msg.SETUP_INPUT_EMPTY_RESET.format(button=msg.SETUP_KEYS_BUTTON_RESET_TO_SUPPLIED)
    assert "Вернуть значение программы" in edit.problem


def test_replace_with_empty_input_without_supply_names_the_delete_button(bare_store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(bare_store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    edit: KeysPanelEdit = panel.replace(SecretField.OPENAI_API_KEY, " 	 ")
    assert not edit.is_applied and edit.panel is panel
    assert edit.problem == msg.SETUP_INPUT_EMPTY_RESET.format(button=msg.SETUP_KEYS_BUTTON_DELETE_OWN)
    assert "Удалить своё значение" in edit.problem


def test_replace_with_empty_input_in_an_empty_field_asks_for_input(bare_store: VaultStore) -> None:
    edit: KeysPanelEdit = KeysPanel.from_store(bare_store).replace(SecretField.SHEETS_ID, "")
    assert edit.problem == msg.SETUP_INPUT_EMPTY


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_input_into_the_legacy_form_url_still_says_it_cannot_be_entered(store: VaultStore, raw: str) -> None:
    edit: KeysPanelEdit = KeysPanel.from_store(store).replace(SecretField.KEY_FORM_URL, raw)
    assert edit.problem == msg.SETUP_INPUT_LEGACY_FIELD


def test_every_row_names_a_real_button_for_empty_input(store: VaultStore) -> None:
    """Текст о пустом вводе называет ровно подпись сброса своей строки, а у строки без сброса — никакую."""
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    for row in panel.rows:
        if row.reset_label is None:
            assert row.empty_input_problem == msg.SETUP_INPUT_EMPTY
        else:
            assert f"«{row.reset_label}»" in row.empty_input_problem


def test_enter_fills_an_empty_field_as_own(bare_store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(bare_store).replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    row: KeyRow = _row(panel, SecretField.SHEETS_RANGE)
    assert row.actions == OWN_ACTIONS
    assert row.origin_label == msg.VAULT_ORIGIN_OWN


# --- сброс к поставке


def test_reset_over_a_supplied_value_brings_the_supplied_mask_back(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    reset: KeysPanel = edited.reset(SecretField.SHEETS_RANGE)
    row: KeyRow = _row(reset, SecretField.SHEETS_RANGE)
    supplied: SecretValue | None = reset.supplied.get(SecretField.SHEETS_RANGE)
    assert supplied is not None
    assert row.origin_label == msg.VAULT_ORIGIN_SUPPLIED
    assert row.display == supplied.masked
    assert row.actions == REPLACE_ONLY
    assert _row(edited, SecretField.SHEETS_RANGE).origin_label == msg.VAULT_ORIGIN_OWN   # прежняя не менялась


def test_reset_without_a_supplied_value_leaves_no_field(bare_store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.from_store(bare_store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    reset: KeysPanel = edited.reset(SecretField.OPENAI_API_KEY)
    row: KeyRow = _row(reset, SecretField.OPENAI_API_KEY)
    assert reset.vault.get(SecretField.OPENAI_API_KEY) is None
    assert row.origin_label == msg.READINESS_FIELD_ABSENT
    assert row.display == msg.READINESS_FIELD_ABSENT
    assert row.actions == ENTER_ONLY


def test_reset_of_a_saved_own_field_shows_the_supplied_one_under_it(store: VaultStore) -> None:
    """Поставочный слой не теряется при наложении: под сохранённым своим видно поставочное (§8.2)."""
    saved: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).save(store)
    reset: KeysPanel = saved.reset(SecretField.SHEETS_ID)
    supplied: SecretValue | None = saved.supplied.get(SecretField.SHEETS_ID)
    assert supplied is not None and supplied.reveal() == SUPPLIED_VALUES[SecretField.SHEETS_ID]
    assert _row(reset, SecretField.SHEETS_ID).display == supplied.masked



# --- подпись кнопки сброса


def test_reset_label_of_an_own_field_over_the_supply_returns_the_program_value(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    assert _row(panel, SecretField.SHEETS_RANGE).reset_label == msg.SETUP_KEYS_BUTTON_RESET_TO_SUPPLIED


def test_reset_label_of_an_own_field_without_supply_deletes_it(bare_store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(bare_store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    assert _row(panel, SecretField.OPENAI_API_KEY).reset_label == msg.SETUP_KEYS_BUTTON_DELETE_OWN


def test_reset_label_of_a_saved_own_field_over_the_supply_returns_the_program_value(store: VaultStore) -> None:
    saved: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).save(store)
    assert _row(saved, SecretField.SHEETS_ID).reset_label == msg.SETUP_KEYS_BUTTON_RESET_TO_SUPPLIED


def test_supplied_and_empty_fields_have_no_reset_label(store: VaultStore, bare_store: VaultStore) -> None:
    for panel in (KeysPanel.from_store(store), KeysPanel.from_store(bare_store)):
        for row in panel.rows:
            assert RowAction.RESET not in row.actions
            assert row.reset_label is None


def test_reset_label_follows_the_reset_action_only() -> None:
    assert KeyRow.of(SecretField.SHEETS_ID, None, can_save_own=True, has_supplied=True).reset_label is None


# --- несохранённые изменения


def test_a_freshly_read_panel_is_not_dirty(store: VaultStore) -> None:
    assert not KeysPanel.from_store(store).is_dirty


def test_replace_makes_the_panel_dirty(store: VaultStore) -> None:
    assert _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE)).is_dirty


def test_a_rejected_replace_leaves_the_panel_clean(store: VaultStore) -> None:
    assert not KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, "1:5").panel.is_dirty


def test_reset_of_a_saved_own_field_makes_the_panel_dirty(store: VaultStore) -> None:
    saved: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE)).save(store)
    assert not saved.is_dirty
    assert saved.reset(SecretField.SHEETS_RANGE).is_dirty


def test_replace_then_reset_back_to_the_read_state_is_clean(store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.from_store(store)
    edited: KeysPanel = _applied(panel.replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    assert not edited.reset(SecretField.SHEETS_RANGE).is_dirty


def test_the_panel_is_clean_after_save(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    assert not edited.save(store).is_dirty


# --- запись


def test_save_writes_only_the_local_file(store: VaultStore) -> None:
    """Поставочный файл — побайтно и по времени правки тот же (§7.4)."""
    before: bytes = store.supplied_path.read_bytes()
    stat_before: os.stat_result = store.supplied_path.stat()
    assert not store.local_path.exists()
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    panel.save(store)
    assert store.local_path.is_file()
    assert store.supplied_path.read_bytes() == before
    stat_after: os.stat_result = store.supplied_path.stat()
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns
    assert stat_after.st_size == stat_before.st_size


def test_after_save_the_reread_panel_shows_own(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    saved: KeysPanel = panel.save(store)
    reread: KeysPanel = KeysPanel.from_store(store)
    for current in (saved, reread):
        row: KeyRow = _row(current, SecretField.SHEETS_RANGE)
        assert row.origin_label == msg.VAULT_ORIGIN_OWN
        assert row.actions == OWN_ACTIONS
        assert current.local_state is LocalVaultState.READ
    own: SecretValue | None = reread.own.get(SecretField.SHEETS_RANGE)
    assert own is not None and own.reveal() == OWN_RANGE


def test_save_after_reset_removes_the_field_from_the_local_file(store: VaultStore) -> None:
    saved: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE)).save(store)
    after: KeysPanel = saved.reset(SecretField.SHEETS_RANGE).save(store)
    assert after.own == Vault.empty()
    assert _row(after, SecretField.SHEETS_RANGE).origin_label == msg.VAULT_ORIGIN_SUPPLIED


def test_save_without_dpapi_goes_out_as_dpapi_unavailable(ready_paths: LivecraftPaths) -> None:
    """Сказать о недоступном DPAPI человеку — дело окна; модель ошибку не глотает."""
    panel: KeysPanel = KeysPanel.from_store(_no_dpapi_store(ready_paths))
    with pytest.raises(DpapiUnavailable):
        panel.save(_no_dpapi_store(ready_paths))
    assert not ready_paths.vault_local_file.exists()


# --- без DPAPI своих значений нет


def test_without_dpapi_replace_and_enter_are_not_offered(ready_paths: LivecraftPaths) -> None:
    panel: KeysPanel = KeysPanel.from_store(_no_dpapi_store(ready_paths))
    assert not panel.can_save_own
    for row in panel.rows:
        assert RowAction.REPLACE not in row.actions
        assert RowAction.ENTER not in row.actions
    assert msg.SETUP_KEYS_NOTICE_NO_OWN in panel.notices


def test_without_dpapi_an_empty_field_offers_nothing(livecraft_paths: LivecraftPaths) -> None:
    panel: KeysPanel = KeysPanel.from_store(_no_dpapi_store(livecraft_paths))
    assert all(row.actions == frozenset() for row in panel.rows)


def test_without_dpapi_replace_is_refused_with_a_reason(ready_paths: LivecraftPaths) -> None:
    panel: KeysPanel = KeysPanel.from_store(_no_dpapi_store(ready_paths))
    edit: KeysPanelEdit = panel.replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert edit.problem == msg.SETUP_INPUT_OWN_UNAVAILABLE
    assert edit.panel is panel


def test_with_dpapi_the_no_own_notice_is_absent(store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.from_store(store)
    assert panel.can_save_own
    assert msg.SETUP_KEYS_NOTICE_NO_OWN not in panel.notices


# --- нечитаемый личный файл


def _break_local_key(store: VaultStore) -> None:
    """Личный файл есть, но без записи «key»: он целый, но не наш — UNREADABLE (§14, решение 9)."""
    data: dict[str, Any] = json.loads(store.local_path.read_text(encoding=VAULT_FILE_ENCODING))
    del data[KEY_WRAPPED]
    store.local_path.write_text(json.dumps(data), encoding=VAULT_FILE_ENCODING)


def test_an_unreadable_local_file_is_announced_with_the_replacement_notice(store: VaultStore) -> None:
    _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).save(store)
    _break_local_key(store)
    panel: KeysPanel = KeysPanel.from_store(store)
    assert panel.local_state is LocalVaultState.UNREADABLE
    assert msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE in panel.notices
    assert _row(panel, SecretField.SHEETS_ID).origin_label == msg.VAULT_ORIGIN_SUPPLIED


def test_a_readable_local_file_has_no_replacement_notice(store: VaultStore) -> None:
    _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).save(store)
    assert msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE not in KeysPanel.from_store(store).notices


def test_the_first_save_replaces_the_unreadable_local_file(store: VaultStore) -> None:
    _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).save(store)
    _break_local_key(store)
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    saved: KeysPanel = panel.save(store)
    assert saved.local_state is LocalVaultState.READ
    assert saved.own.origin_of(SecretField.SHEETS_RANGE) is VaultOrigin.OWN
    assert saved.own.get(SecretField.SHEETS_ID) is None



# --- повреждённый личный файл — вкладка открывается и первое сохранение его заменяет (D9)

BROKEN_LOCAL_TEXT: str = "{ не json"


def test_a_broken_local_file_opens_the_panel_with_the_broken_notice(store: VaultStore) -> None:
    store.local_path.write_text(BROKEN_LOCAL_TEXT, encoding=VAULT_FILE_ENCODING)
    panel: KeysPanel = KeysPanel.from_store(store)
    assert panel.local_state is LocalVaultState.BROKEN
    assert msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN in panel.notices
    assert msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE not in panel.notices
    assert panel.own.entries == {} and not panel.is_dirty
    assert all(row.origin_label == msg.VAULT_ORIGIN_SUPPLIED for row in panel.rows)


def test_a_broken_local_file_is_replaced_by_the_first_save(store: VaultStore) -> None:
    store.local_path.write_text(BROKEN_LOCAL_TEXT, encoding=VAULT_FILE_ENCODING)
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    saved: KeysPanel = panel.save(store)
    assert saved.local_state is LocalVaultState.READ
    assert msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN not in saved.notices
    assert saved.own.get(SecretField.SHEETS_ID) == SecretValue(field=SecretField.SHEETS_ID, value=OWN_SHEET_ID)
    assert store.load().local_state is LocalVaultState.READ


def test_a_broken_local_file_without_dpapi_keeps_the_no_own_notice(ready_paths: LivecraftPaths) -> None:
    """«Сохранение заменит» честно только там, где сохранить можно."""
    ready_paths.vault_local_file.write_text(BROKEN_LOCAL_TEXT, encoding=VAULT_FILE_ENCODING)
    panel: KeysPanel = KeysPanel.from_store(_no_dpapi_store(ready_paths))
    assert panel.local_state is LocalVaultState.BROKEN
    assert msg.SETUP_KEYS_NOTICE_NO_OWN in panel.notices
    assert msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN not in panel.notices


def test_a_broken_supplied_file_still_stops_the_panel(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_file.write_text(BROKEN_LOCAL_TEXT, encoding=VAULT_FILE_ENCODING)
    with pytest.raises(VaultFormatError) as raised:
        KeysPanel.from_store(VaultStore.open(ready_paths))
    assert raised.value.advice == msg.VAULT_FILE_ADVICE_SUPPLIED


# --- оговорка §7.2 и отсутствие значений в выводе


def test_the_protection_notice_is_always_first(
    store: VaultStore, bare_store: VaultStore, ready_paths: LivecraftPaths
) -> None:
    for panel in (KeysPanel.from_store(store), KeysPanel.from_store(bare_store),
                  KeysPanel.from_store(_no_dpapi_store(ready_paths))):
        assert panel.notices[0] == msg.SETUP_KEYS_NOTICE_PROTECTION


def test_no_vault_value_shows_in_rows_or_notices(store: VaultStore) -> None:
    read: KeysPanel = KeysPanel.from_store(store)
    edited: KeysPanel = _applied(read.replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    edited = _applied(edited.replace(SecretField.SHEETS_ID, OWN_SHEET_URL))
    edited = _applied(edited.replace(SecretField.SHEETS_RANGE, OWN_RANGE))
    saved: KeysPanel = edited.save(store)
    panels: tuple[KeysPanel, ...] = (read, edited, saved, saved.reset(SecretField.SHEETS_RANGE))
    values: set[str] = _all_secret_values(*panels)
    assert len(values) == 2 * len(SecretField.current())       # поставочные и свои — все шесть в эталоне
    for panel in panels:
        for text in _visible_texts(panel):
            for value in values:
                assert value not in text


def test_the_supplied_and_own_layers_come_from_the_store(store: VaultStore, ready_paths: LivecraftPaths) -> None:
    write_supplied_vault(ready_paths, {SecretField.SHEETS_RANGE: SUPPLIED_VALUES[SecretField.SHEETS_RANGE]})
    panel: KeysPanel = KeysPanel.from_store(VaultStore.open(ready_paths))
    assert tuple(panel.supplied.entries) == (SecretField.SHEETS_RANGE,)
    assert _row(panel, SecretField.OPENAI_API_KEY).actions == ENTER_ONLY


# --- «показать своё» (задача 2.3a, §14 решение 11): единственная точка раскрытия значения в настройщике


def _count_reveals(monkeypatch: pytest.MonkeyPatch) -> list[SecretField]:
    """Считает раскрытия значения, не меняя их: проверка, что поставочное не раскрывается даже внутри модели."""
    calls: list[SecretField] = []
    original = SecretValue.reveal

    def _counting(self: SecretValue) -> str:
        calls.append(self.field)
        return original(self)

    monkeypatch.setattr(SecretValue, "reveal", _counting)
    return calls


def test_own_value_of_an_own_field_is_the_entered_value(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    assert panel.own_value(SecretField.OPENAI_API_KEY) == OWN_OPENAI_KEY


def test_own_value_of_a_saved_own_field_is_read_back(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    assert edited.save(store).own_value(SecretField.OPENAI_API_KEY) == OWN_OPENAI_KEY


def test_own_value_of_a_supplied_field_is_none_and_nothing_is_revealed(
    store: VaultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[SecretField] = _count_reveals(monkeypatch)
    panel: KeysPanel = KeysPanel.from_store(store)
    for field in SecretField:
        assert panel.own_value(field) is None
    assert calls == []


def test_own_value_of_an_absent_field_is_none(bare_store: VaultStore, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[SecretField] = _count_reveals(monkeypatch)
    panel: KeysPanel = KeysPanel.from_store(bare_store)
    assert all(panel.own_value(field) is None for field in SecretField)
    assert calls == []


def test_own_value_after_reset_over_the_supply_is_none(store: VaultStore, monkeypatch: pytest.MonkeyPatch) -> None:
    edited: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    reset: KeysPanel = edited.reset(SecretField.OPENAI_API_KEY)
    calls: list[SecretField] = _count_reveals(monkeypatch)
    assert reset.own_value(SecretField.OPENAI_API_KEY) is None
    assert calls == []


def test_own_value_reveals_only_its_own_field(store: VaultStore, monkeypatch: pytest.MonkeyPatch) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    calls: list[SecretField] = _count_reveals(monkeypatch)
    panel.own_value(SecretField.OPENAI_API_KEY)
    panel.own_value(SecretField.SHEETS_ID)
    assert calls == [SecretField.OPENAI_API_KEY]


def test_own_value_writes_nothing_to_the_log(store: VaultStore, caplog: pytest.LogCaptureFixture) -> None:
    panel: KeysPanel = _applied(KeysPanel.from_store(store).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="livecraft"):
        for field in SecretField:
            panel.own_value(field)
    assert caplog.records == []
