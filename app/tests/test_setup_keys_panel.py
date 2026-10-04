from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from app.core.text_format import TEXT_ENCODING
from app.paths import FileName, LivecraftPaths
from app.secretsafe.crypto import VaultFileKey
from app.secretsafe.dpapi import Dpapi, DpapiUnavailable
from app.secretsafe.store import VaultLayerState, VaultStore
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.page import SetupPage
from app.setup.fields.secret_input import SHEETS_ID_MIN_LENGTH
from app.setup.panels.keys_panel import KeyRow, KeysPanel, RowAction
from app.setup.panels.panel_edit import PanelEdit
from app.setup.setup_vault import SetupVault
from app.tests.conftest import TOKEN_VALUES, write_token_vault
from app.tests.fixtures.telegram import BOT_TOKEN
from app.ui import messages_ru as msg

OWN_OPENAI_KEY: str = "sk-proj-own-Zy9xWvUtSrQpOnMlKjIhGfEdCbA9876543210"
OWN_SHEET_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"
OWN_SHEET_URL: str = f"https://docs.google.com/spreadsheets/d/{OWN_SHEET_ID}/edit#gid=0"
REPLACE_ONLY: frozenset[RowAction] = frozenset({RowAction.REPLACE})
PLAN: SetupPage = SetupPage.PLAN
MERGE: SetupPage = SetupPage.MERGE
TELEGRAM: SetupPage = SetupPage.TELEGRAM
OWN_STATUS: str = msg.SETUP_KEY_STATUS_OWN.partition("{")[0]              # «✓ задано (»
SUPPLIED_STATUS: str = msg.SETUP_KEY_STATUS_TOKEN.partition("{")[0]    # «✓ из токена (»
OWN_ACTIONS: frozenset[RowAction] = frozenset({RowAction.REPLACE, RowAction.RESET, RowAction.REVEAL})
ENTER_ONLY: frozenset[RowAction] = frozenset({RowAction.ENTER})


@pytest.fixture
def store(ready_paths: LivecraftPaths) -> VaultStore:
    """Готовый корень: значения из токена на все поля, личного файла нет; сейф собран боевым путём."""
    return VaultStore.open(ready_paths)


@pytest.fixture
def bare_store(livecraft_paths: LivecraftPaths) -> VaultStore:
    """Чистая установка: ни значений из токена, ни личного сейфа."""
    return VaultStore.open(livecraft_paths)


def _no_dpapi_store(paths: LivecraftPaths) -> VaultStore:
    """Сейф на машине без DPAPI: объект без библиотек честно отказывает в работе."""
    return VaultStore(
        local_path=paths.file(FileName.VAULT_LOCAL), token_path=paths.file(FileName.VAULT_TOKEN), dpapi=Dpapi()
    )


def _row(panel: KeysPanel, field: SecretField) -> KeyRow:
    return next(row for row in panel.rows if row.field is field)


def _problem(edit: PanelEdit[KeysPanel]) -> str:
    """Текст проблемы отказа; ключ проблемы — поле сейфа."""
    assert edit.problem is not None
    return edit.problem.text


def _applied(edit: PanelEdit[KeysPanel]) -> KeysPanel:
    assert edit.is_applied, edit.problem
    return edit.panel


def _visible_texts(panel: KeysPanel) -> list[str]:
    texts: list[str] = list(panel.notices)
    for row in panel.rows:
        texts.extend((row.label, row.hint, row.status, repr(row)))
    texts.append(repr(panel))
    return texts


def _all_secret_values(*panels: KeysPanel) -> set[str]:
    """Значения сейфа — эталон теста: reveal() зовёт тест, а не код вкладки."""
    values: set[str] = set()
    for panel in panels:
        for vault in (panel.token, panel.own, panel.vault):
            values.update(secret.reveal() for secret in vault.secrets())
    return values


# --- строки вкладки


@pytest.mark.parametrize(
    ("page", "field"),
    [(PLAN, SecretField.SHEETS_ID), (MERGE, SecretField.OPENAI_API_KEY), (TELEGRAM, SecretField.TELEGRAM_BOT_TOKEN)],
)
def test_rows_follow_the_fields_of_the_page(store: VaultStore, page: SetupPage, field: SecretField) -> None:
    """«Таблица плана» — таблица, «Нейросеть» — ключ OpenAI, «Telegram» — токен бота (§8.2, §14 решение 37)."""
    panel: KeysPanel = KeysPanel.of(SetupVault(store), page)
    [row] = panel.rows
    assert panel.fields == (field,) and row.field is field
    assert (row.label, row.hint) == (msg.SETUP_KEY_FIELD_LABELS[field.value], msg.SETUP_KEY_FIELD_HINTS.get(field.value, ""))
    assert panel.title == msg.SETUP_TAB_TITLES[page.value]


def test_the_bot_token_row_without_a_value_offers_only_enter(store: VaultStore) -> None:
    """Токен бота — шаг 1 вкладки «Telegram» (§8.2 п.3); в поставке его нет — «не задано» и ввод своего."""
    [row] = KeysPanel.of(SetupVault(store), TELEGRAM).rows
    assert row.actions == ENTER_ONLY
    assert (row.status, row.is_set) == (msg.SETUP_STATUS_NOT_SET, False)
    assert (row.label, row.hint) == (msg.SETUP_KEY_FIELD_LABELS["telegram_bot_token"], "")


def test_a_supplied_field_offers_only_replace_and_shows_the_mask(store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    for row in panel.rows:      # в токене — ключ OpenAI и таблица
        assert row.actions == REPLACE_ONLY
        expected: SecretValue | None = panel.token.get(row.field)
        assert expected is not None
        assert row.status == msg.SETUP_KEY_STATUS_TOKEN.format(mask=expected.short_mask) and row.is_set
        assert TOKEN_VALUES[row.field] not in row.status


def test_an_own_field_offers_replace_reset_reveal_and_shows_the_mask(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    row: KeyRow = _row(panel, SecretField.OPENAI_API_KEY)
    assert row.actions == OWN_ACTIONS
    assert row.status == msg.SETUP_KEY_STATUS_OWN.format(mask="sk-…3210") and row.is_set
    assert OWN_OPENAI_KEY not in row.status


def test_an_empty_field_offers_only_enter_and_says_none(bare_store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.of(SetupVault(bare_store), PLAN)
    for row in panel.rows:
        assert row.actions == ENTER_ONLY
        assert (row.status, row.is_set) == (msg.SETUP_STATUS_NOT_SET, False)


# --- замена своим


def test_replace_with_good_input_makes_the_field_own_and_leaves_the_old_panel(store: VaultStore) -> None:
    before: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    edit: PanelEdit[KeysPanel] = before.replace(SecretField.SHEETS_ID, OWN_SHEET_URL)
    after: KeysPanel = _applied(edit)
    assert edit.problem is None
    assert _row(after, SecretField.SHEETS_ID).status.startswith(OWN_STATUS)
    assert after.vault.origin_of(SecretField.SHEETS_ID) is VaultOrigin.OWN
    own_id: SecretValue | None = after.own.get(SecretField.SHEETS_ID)
    assert own_id is not None and own_id.reveal() == OWN_SHEET_ID     # в сейф ушёл id, а не ссылка
    assert _row(before, SecretField.SHEETS_ID).status.startswith(SUPPLIED_STATUS)
    assert before.own == Vault.empty()


def test_replace_with_bad_input_names_the_problem_and_changes_nothing(store: VaultStore) -> None:
    before: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    edit: PanelEdit[KeysPanel] = before.replace(SecretField.SHEETS_ID, "A")
    assert not edit.is_applied
    assert _problem(edit) == msg.SETUP_INPUT_SHEETS_ID.format(minimum=SHEETS_ID_MIN_LENGTH)
    assert edit.panel is before
    assert edit.panel.rows == before.rows


def test_replace_with_empty_input_without_an_own_value_asks_for_input(store: VaultStore) -> None:
    """Под строкой только поставочное значение: сброса нет — текст просит ввести значение."""
    edit: PanelEdit[KeysPanel] = KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, "   ")
    assert _problem(edit) == msg.SETUP_INPUT_EMPTY


def test_replace_with_empty_input_over_the_supply_names_the_return_button(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    edit: PanelEdit[KeysPanel] = panel.replace(SecretField.SHEETS_ID, "")
    assert not edit.is_applied and edit.panel is panel
    assert _problem(edit) == msg.SETUP_INPUT_EMPTY_RESET.format(button=msg.SETUP_KEYS_BUTTON_RESET_TO_TOKEN)
    assert "Вернуть значение из токена" in _problem(edit)


def test_replace_with_empty_input_without_supply_names_the_delete_button(bare_store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(bare_store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    edit: PanelEdit[KeysPanel] = panel.replace(SecretField.OPENAI_API_KEY, " 	 ")
    assert not edit.is_applied and edit.panel is panel
    assert _problem(edit) == msg.SETUP_INPUT_EMPTY_RESET.format(button=msg.SETUP_KEYS_BUTTON_DELETE_OWN)
    assert "«Удалить»" in _problem(edit)


def test_replace_with_empty_input_in_an_empty_field_asks_for_input(bare_store: VaultStore) -> None:
    edit: PanelEdit[KeysPanel] = KeysPanel.of(SetupVault(bare_store), PLAN).replace(SecretField.SHEETS_ID, "")
    assert _problem(edit) == msg.SETUP_INPUT_EMPTY


def test_every_row_names_a_real_button_for_empty_input(store: VaultStore) -> None:
    """Текст о пустом вводе называет ровно подпись сброса своей строки, а у строки без сброса — никакую."""
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    for row in panel.rows:
        if row.reset_label is None:
            assert row.empty_input_problem == msg.SETUP_INPUT_EMPTY
        else:
            assert f"«{row.reset_label}»" in row.empty_input_problem


def test_enter_fills_an_empty_field_as_own(bare_store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(bare_store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    row: KeyRow = _row(panel, SecretField.SHEETS_ID)
    assert row.actions == OWN_ACTIONS
    assert row.status.startswith(OWN_STATUS)


# --- сброс к поставке


def test_reset_over_a_supplied_value_brings_the_supplied_mask_back(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    reset: KeysPanel = edited.reset(SecretField.SHEETS_ID)
    row: KeyRow = _row(reset, SecretField.SHEETS_ID)
    supplied: SecretValue | None = reset.token.get(SecretField.SHEETS_ID)
    assert supplied is not None
    assert row.status == msg.SETUP_KEY_STATUS_TOKEN.format(mask=supplied.short_mask)
    assert row.actions == REPLACE_ONLY
    assert _row(edited, SecretField.SHEETS_ID).status.startswith(OWN_STATUS)   # прежняя не менялась


def test_reset_without_a_supplied_value_leaves_no_field(bare_store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(bare_store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    reset: KeysPanel = edited.reset(SecretField.OPENAI_API_KEY)
    row: KeyRow = _row(reset, SecretField.OPENAI_API_KEY)
    assert reset.vault.get(SecretField.OPENAI_API_KEY) is None
    assert (row.status, row.is_set) == (msg.SETUP_STATUS_NOT_SET, False)
    assert row.actions == ENTER_ONLY


def test_reset_of_a_saved_own_field_shows_the_supplied_one_under_it(store: VaultStore) -> None:
    """Поставочный слой не теряется при наложении: под сохранённым своим видно поставочное (§8.2)."""
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    saved: KeysPanel = edited.save().panel
    reset: KeysPanel = saved.reset(SecretField.SHEETS_ID)
    supplied: SecretValue | None = saved.token.get(SecretField.SHEETS_ID)
    assert supplied is not None and supplied.reveal() == TOKEN_VALUES[SecretField.SHEETS_ID]
    assert _row(reset, SecretField.SHEETS_ID).status == msg.SETUP_KEY_STATUS_TOKEN.format(mask=supplied.short_mask)


# --- подпись кнопки сброса


def test_reset_label_of_an_own_field_over_the_supply_returns_the_program_value(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    assert _row(panel, SecretField.SHEETS_ID).reset_label == msg.SETUP_KEYS_BUTTON_RESET_TO_TOKEN


def test_reset_label_of_an_own_field_without_supply_deletes_it(bare_store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(bare_store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    assert _row(panel, SecretField.OPENAI_API_KEY).reset_label == msg.SETUP_KEYS_BUTTON_DELETE_OWN


def test_reset_label_of_a_saved_own_field_over_the_supply_returns_the_program_value(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    saved: KeysPanel = edited.save().panel
    assert _row(saved, SecretField.SHEETS_ID).reset_label == msg.SETUP_KEYS_BUTTON_RESET_TO_TOKEN


def test_supplied_and_empty_fields_have_no_reset_label(store: VaultStore, bare_store: VaultStore) -> None:
    for panel in (KeysPanel.of(SetupVault(store), PLAN), KeysPanel.of(SetupVault(bare_store), PLAN)):
        for row in panel.rows:
            assert RowAction.RESET not in row.actions
            assert row.reset_label is None


def test_reset_label_follows_the_reset_action_only() -> None:
    assert KeyRow.of(SecretField.SHEETS_ID, None, can_save_own=True, has_token=True).reset_label is None


# --- несохранённые изменения


def test_a_freshly_read_panel_is_not_dirty(store: VaultStore) -> None:
    assert not KeysPanel.of(SetupVault(store), PLAN).is_dirty


def test_replace_makes_the_panel_dirty(store: VaultStore) -> None:
    assert _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).is_dirty


def test_a_rejected_replace_leaves_the_panel_clean(store: VaultStore) -> None:
    assert not KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, "1:5").panel.is_dirty


def test_reset_of_a_saved_own_field_makes_the_panel_dirty(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    saved: KeysPanel = edited.save().panel
    assert not saved.is_dirty
    assert saved.reset(SecretField.SHEETS_ID).is_dirty


def test_replace_then_reset_back_to_the_read_state_is_clean(store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    edited: KeysPanel = _applied(panel.replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    assert not edited.reset(SecretField.SHEETS_ID).is_dirty


def test_the_panel_is_clean_after_save(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    assert not edited.save().panel.is_dirty


# --- запись


def test_save_writes_only_the_local_file(store: VaultStore) -> None:
    """Файл токена — побайтно и по времени правки тот же (§7.4)."""
    before: bytes = store.token_path.read_bytes()
    stat_before: os.stat_result = store.token_path.stat()
    assert not store.local_path.exists()
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    panel.save()
    assert store.local_path.is_file()
    assert store.token_path.read_bytes() == before
    stat_after: os.stat_result = store.token_path.stat()
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns
    assert stat_after.st_size == stat_before.st_size


def test_after_save_the_reread_panel_shows_own(store: VaultStore) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    saved: KeysPanel = panel.save().panel
    reread: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    for current in (saved, reread):
        row: KeyRow = _row(current, SecretField.SHEETS_ID)
        assert row.status.startswith(OWN_STATUS)
        assert row.actions == OWN_ACTIONS
        assert current.local_state is VaultLayerState.READ
    own: SecretValue | None = reread.own.get(SecretField.SHEETS_ID)
    assert own is not None and own.reveal() == OWN_SHEET_ID


def test_save_after_reset_removes_the_field_from_the_local_file(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    saved: KeysPanel = edited.save().panel
    after: KeysPanel = saved.reset(SecretField.SHEETS_ID).save().panel
    assert after.own == Vault.empty()
    assert _row(after, SecretField.SHEETS_ID).status.startswith(SUPPLIED_STATUS)


def test_save_without_dpapi_goes_out_as_dpapi_unavailable(ready_paths: LivecraftPaths) -> None:
    """Сказать о недоступном DPAPI человеку — дело окна; модель ошибку не глотает."""
    panel: KeysPanel = KeysPanel.of(SetupVault(_no_dpapi_store(ready_paths)), PLAN)
    with pytest.raises(DpapiUnavailable):
        panel.save()
    assert not ready_paths.file(FileName.VAULT_LOCAL).exists()


# --- без DPAPI своих значений нет


def test_without_dpapi_replace_and_enter_are_not_offered(ready_paths: LivecraftPaths) -> None:
    panel: KeysPanel = KeysPanel.of(SetupVault(_no_dpapi_store(ready_paths)), PLAN)
    assert not panel.can_save_own
    for row in panel.rows:
        assert RowAction.REPLACE not in row.actions
        assert RowAction.ENTER not in row.actions
    assert msg.SETUP_KEYS_NOTICE_NO_OWN in panel.notices


def test_without_dpapi_an_empty_field_offers_nothing(livecraft_paths: LivecraftPaths) -> None:
    panel: KeysPanel = KeysPanel.of(SetupVault(_no_dpapi_store(livecraft_paths)), PLAN)
    assert all(row.actions == frozenset() for row in panel.rows)


def test_without_dpapi_replace_is_refused_with_a_reason(ready_paths: LivecraftPaths) -> None:
    panel: KeysPanel = KeysPanel.of(SetupVault(_no_dpapi_store(ready_paths)), MERGE)
    edit: PanelEdit[KeysPanel] = panel.replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert _problem(edit) == msg.SETUP_INPUT_OWN_UNAVAILABLE
    assert edit.panel is panel


def test_with_dpapi_the_no_own_notice_is_absent(store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    assert panel.can_save_own
    assert msg.SETUP_KEYS_NOTICE_NO_OWN not in panel.notices


# --- нечитаемый личный файл


def _break_local_key(store: VaultStore) -> None:
    """Личный файл есть, но без записи «key»: он целый, но не наш — UNREADABLE (§14, решение 9)."""
    data: dict[str, Any] = json.loads(store.local_path.read_text(encoding=TEXT_ENCODING))
    del data[VaultFileKey.WRAPPED_KEY.value]
    store.local_path.write_text(json.dumps(data), encoding=TEXT_ENCODING)


def test_an_unreadable_local_file_is_announced_with_the_replacement_notice(store: VaultStore) -> None:
    _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).save()
    _break_local_key(store)
    panel: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    assert panel.local_state is VaultLayerState.UNREADABLE
    assert msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE in panel.notices
    assert _row(panel, SecretField.SHEETS_ID).status.startswith(SUPPLIED_STATUS)


def test_a_readable_local_file_has_no_replacement_notice(store: VaultStore) -> None:
    _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).save()
    assert msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE not in KeysPanel.of(SetupVault(store), PLAN).notices


def test_the_first_save_replaces_the_unreadable_local_file(store: VaultStore) -> None:
    _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID)).save()
    _break_local_key(store)
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    saved: KeysPanel = panel.save().panel
    assert saved.local_state is VaultLayerState.READ
    assert saved.own.origin_of(SecretField.OPENAI_API_KEY) is VaultOrigin.OWN
    assert saved.own.get(SecretField.SHEETS_ID) is None


# --- повреждённый личный файл — вкладка открывается и первое сохранение его заменяет (D9)

BROKEN_LOCAL_TEXT: str = "{ не json"


def test_a_broken_local_file_opens_the_panel_with_the_broken_notice(store: VaultStore) -> None:
    store.local_path.write_text(BROKEN_LOCAL_TEXT, encoding=TEXT_ENCODING)
    panel: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    assert panel.local_state is VaultLayerState.BROKEN
    assert msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN in panel.notices
    assert msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE not in panel.notices
    assert panel.own.entries == {} and not panel.is_dirty
    assert all(row.status.startswith(SUPPLIED_STATUS) for row in panel.rows)


def test_a_broken_local_file_is_replaced_by_the_first_save(store: VaultStore) -> None:
    store.local_path.write_text(BROKEN_LOCAL_TEXT, encoding=TEXT_ENCODING)
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    saved: KeysPanel = panel.save().panel
    assert saved.local_state is VaultLayerState.READ
    assert msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN not in saved.notices
    assert saved.own.get(SecretField.SHEETS_ID) == SecretValue(field=SecretField.SHEETS_ID, value=OWN_SHEET_ID)
    assert store.load().local_state is VaultLayerState.READ


def test_a_broken_local_file_without_dpapi_keeps_the_no_own_notice(ready_paths: LivecraftPaths) -> None:
    """«Сохранение заменит» честно только там, где сохранить можно."""
    ready_paths.file(FileName.VAULT_LOCAL).write_text(BROKEN_LOCAL_TEXT, encoding=TEXT_ENCODING)
    panel: KeysPanel = KeysPanel.of(SetupVault(_no_dpapi_store(ready_paths)), PLAN)
    assert panel.local_state is VaultLayerState.BROKEN
    assert msg.SETUP_KEYS_NOTICE_NO_OWN in panel.notices
    assert msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN not in panel.notices


@pytest.mark.parametrize("broken", ["damaged", "foreign"])
def test_a_lost_token_file_opens_the_panel_with_the_load_again_notice(ready_paths: LivecraftPaths, broken: str) -> None:
    """Файл токена повреждён или не наш: вкладка открывается, своё вписать можно, оговорка — загрузить токен заново."""
    token_file: Path = ready_paths.file(FileName.VAULT_TOKEN)
    if broken == "damaged":
        token_file.write_text(BROKEN_LOCAL_TEXT, encoding=TEXT_ENCODING)
    else:
        data: dict[str, Any] = json.loads(token_file.read_text(encoding=TEXT_ENCODING))
        data[VaultFileKey.WRAPPED_KEY.value] = "YmxvYiBmcm9tIGFub3RoZXIgYWNjb3VudA=="
        token_file.write_text(json.dumps(data), encoding=TEXT_ENCODING)
    panel: KeysPanel = KeysPanel.of(SetupVault(VaultStore.open(ready_paths)), MERGE)
    assert panel.token == Vault.empty()
    assert msg.SETUP_KEYS_NOTICE_TOKEN_UNREADABLE in panel.notices
    assert [row.actions for row in panel.rows] == [ENTER_ONLY]
    assert _applied(panel.replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)).is_dirty


# --- оговорка §7.2 и отсутствие значений в выводе


def test_the_protection_notice_is_first_when_the_page_has_a_supplied_value(
    store: VaultStore, ready_paths: LivecraftPaths
) -> None:
    """Оговорка §7.2 — только там, где есть значение из токена: в токене тестов нет токена бота. Без DPAPI файл токена не
    разворачивается — значений из токена нет, и оговорки тоже."""
    assert KeysPanel.of(SetupVault(store), PLAN).notices[0] == msg.SETUP_KEYS_NOTICE_PROTECTION
    assert msg.SETUP_KEYS_NOTICE_PROTECTION not in KeysPanel.of(SetupVault(store), TELEGRAM).notices
    assert KeysPanel.of(SetupVault(_no_dpapi_store(ready_paths)), PLAN).notices == (msg.SETUP_KEYS_NOTICE_NO_OWN,)


def test_without_supplied_values_there_is_no_protection_notice(bare_store: VaultStore) -> None:
    panel: KeysPanel = KeysPanel.of(SetupVault(bare_store), PLAN)
    assert msg.SETUP_KEYS_NOTICE_PROTECTION not in panel.notices
    own_only: KeysPanel = _applied(panel.replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    assert msg.SETUP_KEYS_NOTICE_PROTECTION not in own_only.notices


def test_no_vault_value_shows_in_rows_or_notices(store: VaultStore) -> None:
    read: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    edited: KeysPanel = _applied(read.replace(SecretField.SHEETS_ID, OWN_SHEET_URL))
    edited = _applied(edited.replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    saved: KeysPanel = edited.save().panel
    read_key: KeysPanel = KeysPanel.of(SetupVault(store), MERGE)
    edited_key: KeysPanel = _applied(read_key.replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    panels: tuple[KeysPanel, ...] = (
        read, edited, saved, saved.reset(SecretField.SHEETS_ID), read_key, edited_key, edited_key.save().panel
    )
    values: set[str] = _all_secret_values(*panels)
    assert len(values) == len(TOKEN_VALUES) * 2      # из токена и свои
    for panel in panels:
        for text in _visible_texts(panel):
            for value in values:
                assert value not in text


def test_the_supplied_and_own_layers_come_from_the_store(store: VaultStore, ready_paths: LivecraftPaths) -> None:
    write_token_vault(ready_paths, {SecretField.SHEETS_ID: TOKEN_VALUES[SecretField.SHEETS_ID]})
    panel: KeysPanel = KeysPanel.of(SetupVault(VaultStore.open(ready_paths)), MERGE)
    assert tuple(panel.token.entries) == (SecretField.SHEETS_ID,)
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
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    assert panel.own_value(SecretField.OPENAI_API_KEY) == OWN_OPENAI_KEY


def test_own_value_of_a_saved_own_field_is_read_back(store: VaultStore) -> None:
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    assert edited.save().panel.own_value(SecretField.OPENAI_API_KEY) == OWN_OPENAI_KEY


def test_own_value_of_a_supplied_field_is_none_and_nothing_is_revealed(
    store: VaultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[SecretField] = _count_reveals(monkeypatch)
    panel: KeysPanel = KeysPanel.of(SetupVault(store), PLAN)
    for field in SecretField:
        assert panel.own_value(field) is None
    assert calls == []


def test_own_value_of_an_absent_field_is_none(bare_store: VaultStore, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[SecretField] = _count_reveals(monkeypatch)
    panel: KeysPanel = KeysPanel.of(SetupVault(bare_store), PLAN)
    assert all(panel.own_value(field) is None for field in SecretField)
    assert calls == []


def test_own_value_after_reset_over_the_supply_is_none(store: VaultStore, monkeypatch: pytest.MonkeyPatch) -> None:
    edited: KeysPanel = _applied(KeysPanel.of(SetupVault(store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    reset: KeysPanel = edited.reset(SecretField.OPENAI_API_KEY)
    calls: list[SecretField] = _count_reveals(monkeypatch)
    assert reset.own_value(SecretField.OPENAI_API_KEY) is None
    assert calls == []


def test_own_value_reveals_only_its_own_field(store: VaultStore, monkeypatch: pytest.MonkeyPatch) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    calls: list[SecretField] = _count_reveals(monkeypatch)
    panel.own_value(SecretField.OPENAI_API_KEY)
    panel.own_value(SecretField.SHEETS_ID)
    assert calls == [SecretField.OPENAI_API_KEY]


def test_own_value_writes_nothing_to_the_log(store: VaultStore, caplog: pytest.LogCaptureFixture) -> None:
    panel: KeysPanel = _applied(KeysPanel.of(SetupVault(store), MERGE).replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY))
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="livecraft"):
        for field in SecretField:
            panel.own_value(field)
    assert caplog.records == []


# --- две вкладки сейфа пишут только свои поля (§8.2 п.2, п.3)


def test_the_telegram_page_saves_its_token_without_touching_the_google_fields(store: VaultStore) -> None:
    """Обе вкладки открыты одновременно в одном окне: каждая пишет свои поля поверх личного слоя, каким его знает
    сейф окна после записи другой."""
    window: SetupVault = SetupVault(store)
    google: KeysPanel = KeysPanel.of(window, MERGE)
    telegram: KeysPanel = KeysPanel.of(window, TELEGRAM)
    _applied(google.replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)).save()
    saved: KeysPanel = _applied(telegram.replace(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)).save().panel
    own: Vault = store.load().own
    assert {field for field in own.entries} == {SecretField.OPENAI_API_KEY, SecretField.TELEGRAM_BOT_TOKEN}
    assert saved.own.get(SecretField.OPENAI_API_KEY) is not None and not saved.is_dirty


def test_the_google_page_saves_and_resets_without_touching_the_token(store: VaultStore) -> None:
    window: SetupVault = SetupVault(store)
    telegram: KeysPanel = _applied(KeysPanel.of(window, TELEGRAM).replace(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN))
    google: KeysPanel = _applied(KeysPanel.of(window, PLAN).replace(SecretField.SHEETS_ID, OWN_SHEET_ID))
    telegram.save()
    google.save().panel.reset(SecretField.SHEETS_ID).save()
    own: Vault = store.load().own
    assert tuple(own.entries) == (SecretField.TELEGRAM_BOT_TOKEN,)


def test_only_the_fields_of_the_page_make_it_unsaved(store: VaultStore) -> None:
    """Несохранённое вкладки — только в её полях: чужое поле в личном слое модели вкладку не пачкает."""
    telegram: KeysPanel = KeysPanel.of(SetupVault(store), TELEGRAM)
    assert _applied(telegram.replace(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)).is_dirty
    assert not _applied(telegram.replace(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)).is_dirty
    assert not KeysPanel.of(SetupVault(store), MERGE).is_dirty


def test_the_status_mask_does_not_repeat_the_field_name(store: VaultStore) -> None:
    """Поле уже названо подписью строки: в статусе — короткая маска без названия, значения нет."""
    for row in KeysPanel.of(SetupVault(store), PLAN).rows:
        assert row.field.human_label not in row.status
        assert TOKEN_VALUES[row.field] not in row.status
    sheet: KeyRow = _row(KeysPanel.of(SetupVault(store), PLAN), SecretField.SHEETS_ID)
    fingerprint: str = SecretValue(field=SecretField.SHEETS_ID, value=TOKEN_VALUES[SecretField.SHEETS_ID]).fingerprint
    assert sheet.status == msg.SETUP_KEY_STATUS_TOKEN.format(mask=f"…{fingerprint}")


def test_own_value_of_a_field_of_another_page_is_none(store: VaultStore) -> None:
    """Своё значение показывает только вкладка, на которой оно вводится."""
    saved: KeysPanel = _applied(
        KeysPanel.of(SetupVault(store), TELEGRAM).replace(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
    ).save().panel
    assert saved.own_value(SecretField.TELEGRAM_BOT_TOKEN) == BOT_TOKEN
    assert KeysPanel.of(SetupVault(store), PLAN).own_value(SecretField.TELEGRAM_BOT_TOKEN) is None
