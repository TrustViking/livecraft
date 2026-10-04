"""Блок повторной передачи ключей без окна (app\\setup\\panels\\broadcasts_panel.py, §8.2, §14 решение 36): нажатие
сразу пишет раздел broadcasts через загрузчик поверх свежего файла; сохранение вкладки «Дополнительно» его не
откатывает."""
from __future__ import annotations

import json
from typing import Any

from app.config.broadcasts import BroadcastSettings
from app.config.files import SettingsFile
from app.core.text_format import TEXT_ENCODING
from app.paths import LivecraftPaths
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.panels.broadcasts_panel import BroadcastsPanel
from app.setup.panels.panel_edit import PanelEdit
from app.setup.panels.settings_panel import SettingsPanel
from app.tests.fixtures.drafts import draft_with


def _data(paths: LivecraftPaths) -> dict[str, Any]:
    data: Any = json.loads(SettingsFile.of(paths).path.read_text(encoding=TEXT_ENCODING))
    assert isinstance(data, dict)
    return data


def _without_broadcasts(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key != "broadcasts"}


def test_the_block_shows_the_section_of_the_file(ready_paths: LivecraftPaths) -> None:
    panel: BroadcastsPanel = BroadcastsPanel.from_paths(ready_paths)
    assert panel.broadcasts == BroadcastSettings(False)


def test_switching_resend_writes_it_at_once_and_nothing_else(ready_paths: LivecraftPaths) -> None:
    before: dict[str, Any] = _data(ready_paths)
    edit: PanelEdit[BroadcastsPanel] = BroadcastsPanel.from_paths(ready_paths).switch_resend(True)
    assert edit.is_applied and edit.panel.broadcasts == BroadcastSettings(True)
    after: dict[str, Any] = _data(ready_paths)
    assert after["broadcasts"] == {"resend_keys": True}
    assert _without_broadcasts(after) == _without_broadcasts(before)
    assert SettingsFile.of(ready_paths).load().broadcasts == edit.panel.broadcasts      # разбор загрузчиком
    assert edit.panel.switch_resend(False).panel.broadcasts == BroadcastSettings(False)


def test_the_block_writes_over_the_fresh_file(ready_paths: LivecraftPaths) -> None:
    """Блок открыт до сохранения «Дополнительно»: его запись правку вкладки не откатывает."""
    block: BroadcastsPanel = BroadcastsPanel.from_paths(ready_paths)
    settings: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    draft: SettingsDraft = draft_with(settings.draft, keep_days="12")
    settings.apply(draft).panel.save()
    block.switch_resend(True)
    assert _data(ready_paths)["keep_days"] == 12
    assert SettingsFile.of(ready_paths).load().broadcasts.resend_keys


def test_saving_the_advanced_tab_does_not_roll_back_the_block(ready_paths: LivecraftPaths) -> None:
    """Вкладка «Дополнительно» открыта до нажатия в блоке: её сохранение берёт раздел broadcasts с диска."""
    settings: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    BroadcastsPanel.from_paths(ready_paths).switch_resend(True)
    saved: SettingsPanel = settings.apply(draft_with(settings.draft, keep_days="12")).panel.save().panel
    assert saved.settings.keep_days == 12
    assert saved.settings.broadcasts == BroadcastSettings(True)
    assert SettingsFile.of(ready_paths).load() == saved.settings and not saved.is_dirty
