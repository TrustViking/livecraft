"""Один API моделей вкладок настройщика: `title`, `notices`, `is_dirty`, `save` (CLAUDE.md §8.2).

Одинаковый набор проверок гоняется по моделям вкладок с правкой (поля сейфа «Таблицы плана» и «Telegram», каналы,
дополнительные настройки): окно работает с ними одинаково, и API держит этот тест, а не общий интерфейс.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField
from app.secretsafe.store import VaultStore
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.page import SetupPage
from app.setup.panels.channels_panel import ChannelsPanel
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.panel_edit import PanelEdit
from app.setup.panels.settings_panel import SettingsPanel
from app.setup.setup_vault import SetupVault
from app.tests.fixtures.drafts import draft_with
from app.tests.fixtures.telegram import BOT_TOKEN
from app.ui import messages_ru as msg

Panel = KeysPanel | ChannelsPanel | SettingsPanel


def _keys_changed(panel: Panel) -> Panel:
    assert isinstance(panel, KeysPanel)
    edit: PanelEdit[KeysPanel] = panel.replace(SecretField.SHEETS_ID, "1own-changed-Ab3dEfGhIjKlMnOpQrStUv")
    assert edit.is_applied
    return edit.panel


def _token_changed(panel: Panel) -> Panel:
    assert isinstance(panel, KeysPanel)
    edit: PanelEdit[KeysPanel] = panel.replace(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
    assert edit.is_applied
    return edit.panel


def _channels_changed(panel: Panel) -> Panel:
    assert isinstance(panel, ChannelsPanel)
    draft: ChannelDraft = draft_with(ChannelDraft.blank(), handle="@kanal_hu", google_account="owner@gmail.com",
                                     languages=("hu",))
    edit: PanelEdit[ChannelsPanel] = panel.add(draft)
    assert edit.is_applied
    return edit.panel


def _settings_changed(panel: Panel) -> Panel:
    assert isinstance(panel, SettingsPanel)
    edit: PanelEdit[SettingsPanel] = panel.apply(draft_with(panel.draft, keep_days="7"))
    assert edit.is_applied
    return edit.panel


def _keys_of(page: SetupPage) -> Callable[[LivecraftPaths], Panel]:
    """Как открыть поля сейфа вкладки `page` на этой установке."""
    return lambda paths: KeysPanel.of(SetupVault(VaultStore.open(paths)), page)


@dataclass(frozen=True)
class PanelCase:
    """Модель вкладки для общего набора проверок: как открыть, как изменить и её заголовок."""

    opened: Callable[[LivecraftPaths], Panel]
    changed: Callable[[Panel], Panel]
    title: str


CASES: dict[str, PanelCase] = {
    "keys": PanelCase(_keys_of(SetupPage.PLAN), _keys_changed, msg.SETUP_TAB_TITLES["plan"]),
    "token": PanelCase(_keys_of(SetupPage.TELEGRAM), _token_changed, msg.SETUP_TAB_TITLES["telegram"]),
    "channels": PanelCase(ChannelsPanel.from_paths, _channels_changed, msg.SETUP_TAB_TITLES["broadcasts"]),
    "settings": PanelCase(SettingsPanel.from_paths, _settings_changed, msg.SETUP_TAB_TITLES["advanced"]),
}


@pytest.fixture(params=sorted(CASES))
def case(request: pytest.FixtureRequest) -> PanelCase:
    return CASES[request.param]


def test_the_title_is_the_tab_name(case: PanelCase, ready_paths: LivecraftPaths) -> None:
    assert case.opened(ready_paths).title == case.title


def test_the_notices_are_lines_of_text(case: PanelCase, ready_paths: LivecraftPaths) -> None:
    notices: tuple[str, ...] = case.opened(ready_paths).notices
    assert isinstance(notices, tuple)
    assert all(isinstance(line, str) and line for line in notices)


def test_an_opened_panel_has_nothing_unsaved(case: PanelCase, ready_paths: LivecraftPaths) -> None:
    assert not case.opened(ready_paths).is_dirty


def test_a_change_is_unsaved_and_the_old_panel_stays_clean(case: PanelCase, ready_paths: LivecraftPaths) -> None:
    opened: Panel = case.opened(ready_paths)
    changed: Panel = case.changed(opened)
    assert changed.is_dirty
    assert not opened.is_dirty


def test_save_gives_a_clean_panel_read_again(case: PanelCase, ready_paths: LivecraftPaths) -> None:
    changed: Panel = case.changed(case.opened(ready_paths))
    edit: PanelEdit[Panel] = changed.save()
    assert edit.is_applied and edit.problem is None
    assert not edit.panel.is_dirty
    assert edit.panel == case.opened(ready_paths)
    assert edit.panel.title == case.title


def test_a_panel_edit_without_a_problem_is_applied() -> None:
    assert PanelEdit(panel="panel").is_applied
