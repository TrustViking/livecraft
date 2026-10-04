from __future__ import annotations

import dataclasses

import pytest

from app.config.channel import ChannelConfig, ChannelKey, ConfiguredChannels, Platform, Privacy
from app.config.files import ChannelsFile
from app.paths import FileName, LivecraftPaths
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.panels.channels_panel import ChannelsPanel
from app.setup.panels.panel_edit import PanelEdit
from app.tests.conftest import REPO_CHANNELS_EXAMPLE
from app.tests.fixtures.config import channels_of
from app.tests.fixtures.drafts import draft_with
from app.ui import messages_ru as msg

BROKEN_JSON: bytes = b'{"channels": [ {"platform": "youtube",'
# Новый канал: названия человек не вводит — его даёт ник (§14 решение 25).
NEW_DRAFT: ChannelDraft = ChannelDraft(
    handle="@kanal_hu",
    google_account=" owner@gmail.com ",
    languages=("hu",),
    privacy="public",
)


def _draft(**changes: object) -> ChannelDraft:
    return draft_with(NEW_DRAFT, **changes)


def _added(panel: ChannelsPanel, draft: ChannelDraft) -> ChannelsPanel:
    edit: PanelEdit[ChannelsPanel] = panel.add(draft)
    assert edit.is_applied, edit.problem
    return edit.panel


# --- чтение


def test_the_panel_opens_on_the_channels_of_the_file(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    assert panel.channels == channels_of(REPO_CHANNELS_EXAMPLE)
    assert panel.loaded == panel.channels
    assert panel.load_problem is None
    assert not panel.is_dirty
    assert panel.problem is None
    assert panel.notices == ()


def test_the_drafts_show_the_channels_as_text(ready_paths: LivecraftPaths) -> None:
    drafts: tuple[ChannelDraft, ...] = ChannelsPanel.from_paths(ready_paths).drafts
    assert drafts[1] == ChannelDraft(
        handle="@kanal_ru", google_account="you@gmail.com", languages=("ru",), privacy="unlisted",
        account_name="Канал RU",
    )


def test_a_draft_of_a_channel_goes_back_unchanged(ready_paths: LivecraftPaths) -> None:
    """Черновик годного канала, отданный обратно без правок, даёт тот же канал."""
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: PanelEdit[ChannelsPanel] = panel.update(1, panel.drafts[1])
    assert edit.is_applied
    assert edit.panel.channels == panel.channels
    assert not edit.panel.is_dirty


def test_the_privacy_choices_come_from_the_loader_enum() -> None:
    [privacy] = [field for field in ChannelDraft.FIELDS if field.key is ChannelKey.PRIVACY]
    assert privacy.choices == tuple(item.value for item in Privacy)
    assert ChannelDraft.blank().privacy == Privacy.PUBLIC.value


def test_the_privacy_is_shown_in_words_and_goes_to_the_file_as_its_value() -> None:
    """Видимость в окне — словами; в черновик и channels.json уходит значение Privacy."""
    [privacy] = [field for field in ChannelDraft.FIELDS if field.key is ChannelKey.PRIVACY]
    assert privacy.options == (msg.SETUP_PRIVACY_LABELS["public"], msg.SETUP_PRIVACY_LABELS["unlisted"])
    assert privacy.shown(Privacy.UNLISTED.value) == "по ссылке"
    assert privacy.draft_value("для всех") == Privacy.PUBLIC.value
    assert _draft(privacy=privacy.draft_value("по ссылке")).to_data()["privacy"] == Privacy.UNLISTED.value


def test_the_account_name_is_not_a_field_of_the_window() -> None:
    assert ChannelKey.ACCOUNT_NAME not in [field.key for field in ChannelDraft.FIELDS]


def test_a_new_channel_is_named_by_its_handle_without_the_at_sign(ready_paths: LivecraftPaths) -> None:
    added: ChannelsPanel = _added(ChannelsPanel.from_paths(ready_paths), _draft(handle="Lena.Live"))
    assert (added.channels[-1].handle, added.channels[-1].account_name) == ("@Lena.Live", "Lena.Live")


def test_a_channel_from_the_file_keeps_its_name_on_update(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edited: ChannelDraft = draft_with(panel.drafts[1], google_account="other@gmail.com")
    edit: PanelEdit[ChannelsPanel] = panel.update(1, edited)
    assert edit.is_applied
    assert edit.panel.channels[1].account_name == "Канал RU"
    assert edit.panel.channels[1].google_account == "other@gmail.com"


def test_a_channel_added_from_a_shown_draft_is_named_anew(ready_paths: LivecraftPaths) -> None:
    """«Добавить» после выбора строки таблицы: новый канал — с названием по своему нику, а не выбранного."""
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    draft: ChannelDraft = draft_with(panel.drafts[1], handle="@kanal_new").as_new()
    assert _added(panel, draft).channels[-1].account_name == "kanal_new"


# --- правки


def test_adding_a_good_channel_gives_a_new_panel_and_keeps_the_old_one(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    before: tuple[ChannelConfig, ...] = panel.channels
    added: ChannelsPanel = _added(panel, NEW_DRAFT)
    assert added.channels[:-1] == before
    assert added.channels[-1] == ChannelConfig(
        platform=Platform.YOUTUBE,
        account_name="kanal_hu",
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
    """Пустой ник — пустое и название нового канала: загрузчик называет его первым, а окно подписывает ником."""
    edit: PanelEdit[ChannelsPanel] = ChannelsPanel.from_paths(ready_paths).add(_draft(handle="  "))
    assert edit.problem is not None
    assert edit.problem.text == msg.CONFIG_PROBLEM_NON_EMPTY_STRING
    assert msg.SETUP_CHANNEL_FIELD_LABELS[edit.problem.key] == msg.SETUP_CHANNEL_FIELD_LABELS["handle"]


def test_uppercase_languages_are_a_problem_named_by_the_loader(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: PanelEdit[ChannelsPanel] = panel.add(_draft(languages=("UK",)))
    assert not edit.is_applied
    assert edit.panel is panel
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == (
        "languages", msg.CONFIG_PROBLEM_LANGUAGE_UNKNOWN.format(value="UK")
    )


@pytest.mark.parametrize("code", ["ua", "uk-ua"])
def test_a_language_outside_iso_639_1_is_a_problem_named_by_the_loader(ready_paths: LivecraftPaths, code: str) -> None:
    """Код вне справочника (из старого файла или из формы) отклоняет загрузчик — проблемой поля, не исключением."""
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: PanelEdit[ChannelsPanel] = panel.add(_draft(languages=(code,)))
    assert not edit.is_applied
    assert edit.panel is panel
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == (
        "languages", msg.CONFIG_PROBLEM_LANGUAGE_UNKNOWN.format(value=code)
    )


def test_every_code_of_the_draft_goes_to_the_file(ready_paths: LivecraftPaths) -> None:
    added: ChannelsPanel = _added(ChannelsPanel.from_paths(ready_paths), _draft(languages=("uk", "ru", "en")))
    assert added.channels[-1].languages == ("uk", "ru", "en")


def test_a_handle_repeated_in_another_case_is_a_problem(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[ChannelsPanel] = ChannelsPanel.from_paths(ready_paths).add(_draft(handle="@KANAL_UA"))
    assert edit.problem is not None
    assert edit.problem.key == "handle"
    assert edit.problem.text == msg.CONFIG_PROBLEM_HANDLE_DUPLICATE.format(value="@KANAL_UA", other="@kanal_ua")


def test_an_unknown_privacy_is_a_problem(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[ChannelsPanel] = ChannelsPanel.from_paths(ready_paths).add(_draft(privacy="private"))
    assert edit.problem is not None
    assert edit.problem.key == "privacy"
    assert edit.problem.text == msg.CONFIG_PROBLEM_CHOICE.format(allowed="public, unlisted")


def test_update_replaces_one_channel(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: PanelEdit[ChannelsPanel] = panel.update(0, _draft(handle="@kanal_ua_new", languages=("uk",)))
    assert edit.is_applied
    assert edit.panel.channels[0].handle == "@kanal_ua_new"
    assert edit.panel.channels[1] == panel.channels[1]


def test_update_keeps_the_own_handle_of_the_channel_legal(ready_paths: LivecraftPaths) -> None:
    """Правка канала не спорит сама с собой: тот же ник в другом регистре — не дубль."""
    edit: PanelEdit[ChannelsPanel] = ChannelsPanel.from_paths(ready_paths).update(0, _draft(handle="@Kanal_UA"))
    assert edit.is_applied
    assert edit.panel.channels[0].handle == "@Kanal_UA"


def test_a_bad_update_leaves_the_panel_as_it_was(ready_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(ready_paths)
    edit: PanelEdit[ChannelsPanel] = panel.update(1, _draft(google_account="not-an-email"))
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
    old: bytes = ready_paths.file(FileName.CHANNELS).read_bytes()
    changed: ChannelsPanel = _added(ChannelsPanel.from_paths(ready_paths), NEW_DRAFT)
    edit: PanelEdit[ChannelsPanel] = changed.save()
    assert edit.is_applied
    assert ready_paths.file(FileName.CHANNELS).read_text(encoding="utf-8") == ChannelsFile.of(ready_paths).render(
        ConfiguredChannels(channels=changed.channels)
    )
    assert ready_paths.file(FileName.CHANNELS_PREVIOUS).read_bytes() == old
    assert edit.panel.channels == changed.channels
    assert edit.panel.loaded == changed.channels
    assert not edit.panel.is_dirty


def test_an_empty_list_is_a_problem_and_is_not_saved(ready_paths: LivecraftPaths) -> None:
    old: bytes = ready_paths.file(FileName.CHANNELS).read_bytes()
    empty: ChannelsPanel = ChannelsPanel.from_paths(ready_paths).remove(1).remove(0)
    assert empty.channels == ()
    assert empty.problem is not None
    assert (empty.problem.key, empty.problem.text) == ("channels", msg.CONFIG_PROBLEM_CHANNELS_EMPTY)
    edit: PanelEdit[ChannelsPanel] = empty.save()
    assert edit.panel is empty
    assert edit.problem == empty.problem
    assert ready_paths.file(FileName.CHANNELS).read_bytes() == old
    assert not ready_paths.file(FileName.CHANNELS_PREVIOUS).exists()


def test_without_a_channels_file_the_panel_is_empty_and_says_so(livecraft_paths: LivecraftPaths) -> None:
    panel: ChannelsPanel = ChannelsPanel.from_paths(livecraft_paths)
    assert panel.channels == ()
    assert panel.loaded is None
    assert panel.is_file_missing
    assert panel.notices == (msg.SETUP_CHANNELS_NOTICE_FILE_MISSING,)
    assert panel.problem is not None
    assert not panel.is_dirty


def test_the_first_channel_on_a_clean_install_is_saved(livecraft_paths: LivecraftPaths) -> None:
    edit: PanelEdit[ChannelsPanel] = _added(ChannelsPanel.from_paths(livecraft_paths), NEW_DRAFT).save()
    assert edit.is_applied
    assert channels_of(livecraft_paths.file(FileName.CHANNELS)) == edit.panel.channels
    assert not livecraft_paths.file(FileName.CHANNELS_PREVIOUS).exists()


def test_a_broken_file_is_named_and_kept_aside_on_save(livecraft_paths: LivecraftPaths) -> None:
    livecraft_paths.file(FileName.CHANNELS).write_bytes(BROKEN_JSON)
    panel: ChannelsPanel = ChannelsPanel.from_paths(livecraft_paths)
    assert panel.channels == ()
    assert panel.loaded is None
    assert not panel.is_file_missing
    assert panel.load_problem is not None
    assert panel.load_problem.key == msg.CONFIG_ROOT_KEY
    assert panel.notices == (
        msg.SETUP_CHANNELS_NOTICE_UNREADABLE.format(key=panel.load_problem.key, problem=panel.load_problem.text),
    )
    edit: PanelEdit[ChannelsPanel] = _added(panel, NEW_DRAFT).save()
    assert edit.is_applied
    assert channels_of(livecraft_paths.file(FileName.CHANNELS)) == edit.panel.channels
    assert livecraft_paths.file(FileName.CHANNELS_PREVIOUS).read_bytes() == BROKEN_JSON
    assert edit.panel.notices == ()


# --- черновик: поля и данные файла


def test_the_draft_fields_are_the_draft_attributes_in_file_order() -> None:
    """Поля окна — все поля черновика, кроме названия канала, в порядке файла после площадки и названия."""
    names: list[str] = [field.name for field in dataclasses.fields(ChannelDraft) if field.name != "account_name"]
    assert [field.name for field in ChannelDraft.FIELDS] == names
    assert [field.key_path for field in ChannelDraft.FIELDS] == list(ChannelKey.leaves())[2:]


def test_the_draft_data_follows_the_channel_keys() -> None:
    """Площадка — всегда YouTube; текст — без пробелов по краям, ник — с «@», языки — списком."""
    data: dict[str, object] = _draft(handle=" kanal_hu ", languages=("hu",)).to_data()
    assert list(data) == list(ChannelKey.leaves())
    assert data == {
        "platform": "youtube",
        "account_name": "kanal_hu",
        "handle": "@kanal_hu",
        "google_account": "owner@gmail.com",
        "languages": ["hu"],
        "privacy": "public",
    }


def test_an_empty_handle_stays_empty_in_the_data() -> None:
    assert _draft(handle="   ").to_data()["handle"] == ""
