from __future__ import annotations

import dataclasses

from app.config.loader import (
    ChannelConfig,
    Platform,
    Privacy,
    load_channels,
    render_channels_file,
)
from app.paths import LivecraftPaths
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.panels.channels_panel import ChannelsPanel, ChannelsPanelEdit
from app.tests.conftest import REPO_CHANNELS_EXAMPLE
from app.ui import messages_ru as msg

BROKEN_JSON: bytes = b'{"channels": [ {"platform": "youtube",'
NEW_DRAFT: ChannelDraft = ChannelDraft(
    account_name="  Канал HU ",
    handle="@kanal_hu",
    google_account=" owner@gmail.com ",
    languages="hu",
    privacy="public",
)


def _draft(**changes: str) -> ChannelDraft:
    return dataclasses.replace(NEW_DRAFT, **changes)


def _added(panel: ChannelsPanel, draft: ChannelDraft) -> ChannelsPanel:
    edit: ChannelsPanelEdit = panel.add(draft)
    assert edit.is_applied, edit.problem
    return edit.panel


# --- чтение


def test_the_panel_opens_on_the_channels_of_the_file(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    assert panel.channels == load_channels(REPO_CHANNELS_EXAMPLE)
    assert panel.loaded == panel.channels
    assert panel.load_problem is None
    assert not panel.is_dirty
    assert panel.problem is None
    assert panel.notices == ()


def test_the_drafts_show_the_channels_as_text(ready_paths: LivecraftPaths) -> None:
    drafts: tuple[ChannelDraft, ...] = ChannelsPanel.from_paths(ready_paths).drafts
    assert drafts[1] == ChannelDraft(
        account_name="Канал RU", handle="@kanal_ru", google_account="you@gmail.com", languages="ru, en",
        privacy="unlisted",
    )


def test_a_draft_of_a_channel_goes_back_unchanged(ready_paths: LivecraftPaths) -> None:
    """Черновик годного канала, отданный обратно без правок, даёт тот же канал."""
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: ChannelsPanelEdit = panel.update(1, panel.drafts[1])
    assert edit.is_applied
    assert edit.panel.channels == panel.channels
    assert not edit.panel.is_dirty


def test_the_privacy_options_come_from_the_loader_enum(ready_paths: LivecraftPaths) -> None:
    assert ChannelsPanel.from_paths(ready_paths).privacy_options == tuple(item.value for item in Privacy)


# --- правки


def test_adding_a_good_channel_gives_a_new_panel_and_keeps_the_old_one(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    before: tuple[ChannelConfig, ...] = panel.channels
    added: ChannelsPanel = _added(panel, NEW_DRAFT)
    assert added.channels[:-1] == before
    assert added.channels[-1] == ChannelConfig(
        platform=Platform.YOUTUBE,
        account_name="Канал HU",
        handle="@kanal_hu",
        google_account="owner@gmail.com",
        languages=("hu",),
        privacy=Privacy.PUBLIC,
    )
    assert added.is_dirty
    assert panel.channels == before
    assert not panel.is_dirty


def test_a_handle_without_the_at_sign_gets_one(ready_paths: LivecraftPaths) -> None:
    added: ChannelsPanel = _added(ChannelsPanel.from_paths(ready_paths), _draft(handle=" kanal_hu "))
    assert added.channels[-1].handle == "@kanal_hu"


def test_an_empty_handle_is_named_empty_by_the_loader(ready_paths: LivecraftPaths) -> None:
    edit: ChannelsPanelEdit = ChannelsPanel.from_paths(ready_paths).add(_draft(handle="  "))
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("handle", msg.CONFIG_PROBLEM_NON_EMPTY_STRING)


def test_uppercase_languages_are_a_problem_named_by_the_loader(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: ChannelsPanelEdit = panel.add(_draft(languages="UK"))
    assert not edit.is_applied
    assert edit.panel is panel
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("languages", msg.CONFIG_PROBLEM_LANGUAGES)


def test_languages_split_on_commas_and_spaces(ready_paths: LivecraftPaths) -> None:
    added: ChannelsPanel = _added(ChannelsPanel.from_paths(ready_paths), _draft(languages="uk, ru  en,"))
    assert added.channels[-1].languages == ("uk", "ru", "en")


def test_a_handle_repeated_in_another_case_is_a_problem(ready_paths: LivecraftPaths) -> None:
    edit: ChannelsPanelEdit = ChannelsPanel.from_paths(ready_paths).add(_draft(handle="@KANAL_UA"))
    assert edit.problem is not None
    assert edit.problem.key == "handle"
    assert edit.problem.text == msg.CONFIG_PROBLEM_HANDLE_DUPLICATE.format(value="@KANAL_UA", other="@kanal_ua")


def test_an_unknown_privacy_is_a_problem(ready_paths: LivecraftPaths) -> None:
    edit: ChannelsPanelEdit = ChannelsPanel.from_paths(ready_paths).add(_draft(privacy="private"))
    assert edit.problem is not None
    assert edit.problem.key == "privacy"
    assert edit.problem.text == msg.CONFIG_PROBLEM_CHOICE.format(allowed="public, unlisted")


def test_update_replaces_one_channel(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: ChannelsPanelEdit = panel.update(0, _draft(handle="@kanal_ua_new", languages="uk"))
    assert edit.is_applied
    assert edit.panel.channels[0].handle == "@kanal_ua_new"
    assert edit.panel.channels[1] == panel.channels[1]


def test_update_keeps_the_own_handle_of_the_channel_legal(ready_paths: LivecraftPaths) -> None:
    """Правка канала не спорит сама с собой: тот же ник в другом регистре — не дубль."""
    edit: ChannelsPanelEdit = ChannelsPanel.from_paths(ready_paths).update(0, _draft(handle="@Kanal_UA"))
    assert edit.is_applied
    assert edit.panel.channels[0].handle == "@Kanal_UA"


def test_a_bad_update_leaves_the_panel_as_it_was(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: ChannelsPanelEdit = panel.update(1, _draft(google_account="not-an-email"))
    assert edit.panel is panel
    assert edit.problem is not None
    assert edit.problem.key == "google_account"


def test_remove_drops_one_channel(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    removed: ChannelsPanel = panel.remove(0)
    assert removed.channels == panel.channels[1:]
    assert removed.is_dirty
    assert removed.problem is None


# --- запись


def test_save_writes_the_loader_text_and_keeps_the_previous_file(ready_paths: LivecraftPaths) -> None:
    old: bytes = ready_paths.channels_file.read_bytes()
    changed: ChannelsPanel = _added(ChannelsPanel.from_paths(ready_paths), NEW_DRAFT)
    edit: ChannelsPanelEdit = changed.save(ready_paths)
    assert edit.is_applied
    assert ready_paths.channels_file.read_text(encoding="utf-8") == render_channels_file(changed.channels)
    assert ready_paths.channels_previous_file.read_bytes() == old
    assert edit.panel.channels == changed.channels
    assert edit.panel.loaded == changed.channels
    assert not edit.panel.is_dirty


def test_an_empty_list_is_a_problem_and_is_not_saved(ready_paths: LivecraftPaths) -> None:
    old: bytes = ready_paths.channels_file.read_bytes()
    empty: ChannelsPanel = ChannelsPanel.from_paths(ready_paths).remove(1).remove(0)
    assert empty.channels == ()
    assert empty.problem is not None
    assert (empty.problem.key, empty.problem.text) == ("channels", msg.CONFIG_PROBLEM_CHANNELS_EMPTY)
    edit: ChannelsPanelEdit = empty.save(ready_paths)
    assert edit.panel is empty
    assert edit.problem == empty.problem
    assert ready_paths.channels_file.read_bytes() == old
    assert not ready_paths.channels_previous_file.exists()


def test_without_a_channels_file_the_panel_is_empty_and_says_so(livecraft_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(livecraft_paths)
    assert panel.channels == ()
    assert panel.loaded is None
    assert panel.is_file_missing
    assert panel.notices == (msg.SETUP_CHANNELS_NOTICE_FILE_MISSING,)
    assert panel.problem is not None
    assert not panel.is_dirty


def test_the_first_channel_on_a_clean_install_is_saved(livecraft_paths: LivecraftPaths) -> None:
    edit: ChannelsPanelEdit = _added(ChannelsPanel.from_paths(livecraft_paths), NEW_DRAFT).save(livecraft_paths)
    assert edit.is_applied
    assert load_channels(livecraft_paths.channels_file) == edit.panel.channels
    assert not livecraft_paths.channels_previous_file.exists()


def test_a_broken_file_is_named_and_kept_aside_on_save(livecraft_paths: LivecraftPaths) -> None:
    livecraft_paths.channels_file.write_bytes(BROKEN_JSON)
    panel: ChannelsPanel = ChannelsPanel.from_paths(livecraft_paths)
    assert panel.channels == ()
    assert panel.loaded is None
    assert not panel.is_file_missing
    assert panel.load_problem is not None
    assert panel.load_problem.key == msg.CONFIG_ROOT_KEY
    assert panel.notices == (
        msg.SETUP_CHANNELS_NOTICE_UNREADABLE.format(key=panel.load_problem.key, problem=panel.load_problem.text),
    )
    edit: ChannelsPanelEdit = _added(panel, NEW_DRAFT).save(livecraft_paths)
    assert edit.is_applied
    assert load_channels(livecraft_paths.channels_file) == edit.panel.channels
    assert livecraft_paths.channels_previous_file.read_bytes() == BROKEN_JSON
    assert edit.panel.notices == ()
