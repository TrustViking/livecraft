"""Файлы secrets\\, которые несёт токен (app\\setup\\panels\\token_files.py, token_scope.py; CLAUDE.md §14 решения 65, 70,
77)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config.channel import ChannelConfig, ConfiguredChannels, Platform, Privacy
from app.config.files import ChannelsFile, SettingsFile
from app.paths import DataDir, FileName, LivecraftPaths
from app.platforms.passport import ChannelPassport, PassportEntry
from app.setup.panels.token_file import ReceivedFiles, TokenFile
from app.setup.panels.token_files import TokenFiles
from app.setup.panels.token_scope import TokenItem, TokenScope
from app.tests.fixtures.google_client import choose_project, client_text, project_file
from app.tests.fixtures.logs import LogCapture
from app.observability.log_event import LogArea
from app.ui import messages_ru as msg

PROJECT: TokenScope = TokenScope.of(TokenItem.GOOGLE_PROJECT)
CHANNELS: TokenScope = TokenScope.of(TokenItem.YOUTUBE_CHANNELS)
BOTH: TokenScope = TokenScope.of(TokenItem.GOOGLE_PROJECT, TokenItem.YOUTUBE_CHANNELS)
SENDER_ID: str = "sender.apps.googleusercontent.com"
OTHER_ID: str = "other.apps.googleusercontent.com"
SENDER_CLIENT: str = client_text(project="sender-project", client_id=SENDER_ID)
RECEIVER_CLIENT: str = client_text(project="receiver-project", client_id="receiver.apps.googleusercontent.com")


def _login(refresh: str, access: str = "ya29.access-1", client_id: str = SENDER_ID) -> str:
    """Файл входа Google — как его пишет Credentials.to_json; по умолчанию вход через проект отправителя."""
    return json.dumps({"token": access, "refresh_token": refresh, "client_id": client_id, "client_secret": "secret"})


def _channel(handle: str, account: str = "kanal@example.com") -> ChannelConfig:
    return ChannelConfig(
        platform=Platform.YOUTUBE, account_name=handle.removeprefix("@"), handle=handle, google_account=account,
        languages=("uk",), privacy=Privacy.PUBLIC,
    )


def _entry(handle: str) -> PassportEntry:
    return PassportEntry(
        handle=handle, account_name=handle.removeprefix("@"), youtube_channel_id="UC" + handle.removeprefix("@"),
        youtube_title=handle.removeprefix("@"), youtube_handle_raw=handle, google_account="kanal@example.com",
        token_file=handle + ".token.json", channel_url="https://www.youtube.com/channel/UC" + handle.removeprefix("@"),
        handle_url="https://www.youtube.com/" + handle, first_verified_at="01-10-2026 12:00",
        last_verified_at="01-10-2026 12:00",
    )


def _root(tmp_path: Path, name: str) -> LivecraftPaths:
    paths: LivecraftPaths = LivecraftPaths(tmp_path / name)
    paths.ensure_dirs()
    return paths


def _install(paths: LivecraftPaths, channels: tuple[ChannelConfig, ...], logins: dict[str, str]) -> None:
    """Каналы, их записи паспорта и файлы входов (ник → refresh_token) на установке `paths`."""
    ChannelsFile.of(paths).save(ConfiguredChannels(channels))
    passport: ChannelPassport = ChannelPassport(paths.file(FileName.PASSPORT))
    for channel in channels:
        passport.record(_entry(channel.handle))
    assert passport.save() is None
    for handle, refresh in logins.items():
        paths.token_file(handle).write_text(_login(refresh), encoding="utf-8")


def _receive(paths: LivecraftPaths, *files: Path) -> None:
    """Файлы установки — как полученные с токеном."""
    ReceivedFiles.load(paths).with_written([TokenFile.read(path) for path in files]).save()


@pytest.fixture
def sender(tmp_path: Path) -> LivecraftPaths:
    """Свои клиент и вход оператора, два канала со своим входом, канал без входа."""
    paths: LivecraftPaths = _root(tmp_path, "sender")
    project_file(paths).write_text(SENDER_CLIENT, encoding="utf-8")
    choose_project(paths, project_file(paths))
    paths.file(FileName.SHEETS_TOKEN).write_text(_login("1//operator"), encoding="utf-8")
    channels: tuple[ChannelConfig, ...] = (_channel("@kanal_ua"), _channel("@kanal_ru"), _channel("@kanal_new"))
    _install(paths, channels, {"@kanal_ua": "1//sender-ua", "@kanal_ru": "1//sender-ru"})
    return paths


def _names(files: TokenFiles) -> set[str]:
    return {file.name for file in files.files}


def _handles(paths: LivecraftPaths) -> list[str]:
    return [channel.handle for channel in ChannelsFile.of(paths).load().channels]


# --- что войдёт в токен


def test_without_switches_no_file_goes(sender: LivecraftPaths) -> None:
    assert TokenScope().collect(sender).files == ()


def test_the_project_switch_carries_the_own_client_and_the_operator_login(sender: LivecraftPaths) -> None:
    files: TokenFiles = PROJECT.collect(sender)
    assert files.mapping == {"client_secret.json": SENDER_CLIENT, "sheets.token.json": _login("1//operator")}
    assert files.labels == ("проект Google sender-project", "вход оператора Google")


def test_a_received_project_does_not_go_even_with_the_project_switch(sender: LivecraftPaths) -> None:
    """Проект получен с токеном — он не идёт, а с ним и вход оператора через него (§14 решение 67)."""
    _receive(sender, project_file(sender))
    assert PROJECT.collect(sender).files == ()


def test_the_channels_switch_carries_channels_and_their_logins_without_the_project(sender: LivecraftPaths) -> None:
    """Входы каналов отбираются по выбранному проекту, хотя сам проект в токен не идёт (§14 решение 70)."""
    files: TokenFiles = CHANNELS.collect(sender)
    assert _names(files) == {"channels.json", "channels_passport.json", "@kanal_ua.token.json", "@kanal_ru.token.json"}
    assert files.labels == ("каналы: @kanal_ua, @kanal_ru, @kanal_new", "входы каналов: @kanal_ua, @kanal_ru")
    assert files.client is None


def test_with_both_switches_own_channels_logins_passport_and_operator_go(sender: LivecraftPaths) -> None:
    files: TokenFiles = BOTH.collect(sender)
    assert _names(files) == {
        "client_secret.json", "channels.json", "channels_passport.json", "@kanal_ua.token.json",
        "@kanal_ru.token.json", "sheets.token.json",
    }
    channels: ConfiguredChannels = ChannelsFile.of(sender).parse(json.loads(files.mapping["channels.json"]))
    assert [channel.handle for channel in channels.channels] == ["@kanal_ua", "@kanal_ru", "@kanal_new"]
    assert files.labels == (
        "проект Google sender-project", "каналы: @kanal_ua, @kanal_ru, @kanal_new", "входы каналов: @kanal_ua, @kanal_ru",
        "вход оператора Google",
    )
    assert files.client is not None and files.client.project_id == "sender-project"
    assert files.channels is not None and files.channels.handles == ("@kanal_ua", "@kanal_ru", "@kanal_new")


def test_logins_through_another_project_do_not_go(sender: LivecraftPaths) -> None:
    """Вход, сделанный не через проект токена, в токен не идёт: канал едет без входа, оператор — тоже без входа
    (§14 решение 67)."""
    sender.token_file("@kanal_ru").write_text(_login("1//other-ru", client_id=OTHER_ID), encoding="utf-8")
    sender.file(FileName.SHEETS_TOKEN).write_text(_login("1//other-operator", client_id=OTHER_ID), encoding="utf-8")
    files: TokenFiles = BOTH.collect(sender)
    assert _names(files) == {"client_secret.json", "channels.json", "channels_passport.json", "@kanal_ua.token.json"}
    assert files.channels is not None and files.channels.handles == ("@kanal_ua", "@kanal_ru", "@kanal_new")
    assert files.labels == (
        "проект Google sender-project", "каналы: @kanal_ua, @kanal_ru, @kanal_new", "входы каналов: @kanal_ua",
    )
    assert _names(PROJECT.collect(sender)) == {"client_secret.json"}
    assert _names(CHANNELS.collect(sender)) == {
        "channels.json", "channels_passport.json", "@kanal_ua.token.json"
    }


def test_without_an_own_project_the_logins_do_not_go(sender: LivecraftPaths) -> None:
    """Проект получен с токеном — токен его не несёт, а с ним и входов через него: каналы едут без входов."""
    _receive(sender, project_file(sender))
    files: TokenFiles = BOTH.collect(sender)
    assert _names(files) == {"channels.json", "channels_passport.json"}
    assert files.labels == ("каналы: @kanal_ua, @kanal_ru, @kanal_new",)


def test_a_client_file_that_does_not_fit_is_named_so() -> None:
    """Клиент в токене не годится (не Desktop, не JSON) — проекта нет; строка окна так и говорит."""
    files: TokenFiles = TokenFiles.of({"client_secret.json": client_text(kind="web")})
    assert files.client is None and files.channels is None
    assert files.labels == ("файл проекта Google, который не годится",)


def test_received_channel_logins_and_operator_do_not_go_further(sender: LivecraftPaths) -> None:
    """Канал с полученным входом и полученный вход оператора в новый токен не идут — с записью паспорта тоже."""
    _receive(sender, sender.token_file("@kanal_ru"), sender.file(FileName.SHEETS_TOKEN))
    files: TokenFiles = BOTH.collect(sender)
    assert _names(files) == {"client_secret.json", "channels.json", "channels_passport.json", "@kanal_ua.token.json"}
    listed: list[str] = [item["handle"] for item in json.loads(files.mapping["channels.json"])["channels"]]
    recorded: list[str] = [item["handle"] for item in json.loads(files.mapping["channels_passport.json"])["channels"]]
    assert listed == ["@kanal_ua", "@kanal_new"] and recorded == ["@kanal_new", "@kanal_ua"]


def test_the_login_fingerprint_follows_only_the_refresh_token() -> None:
    """Программа переписывает файл входа при каждом обновлении доступа: refresh_token тот же — файл тот же."""
    first: TokenFile = TokenFile("@kanal_ua.token.json", _login("1//same", access="ya29.first"))
    refreshed: TokenFile = TokenFile("@kanal_ua.token.json", _login("1//same", access="ya29.second") + "\n")
    relogged: TokenFile = TokenFile("@kanal_ua.token.json", _login("1//other", access="ya29.first"))
    assert first.fingerprint == refreshed.fingerprint != relogged.fingerprint
    assert TokenFile("client_secret.json", SENDER_CLIENT).fingerprint != TokenFile("client_secret.json", "{}").fingerprint


def test_a_record_of_earlier_builds_reads_as_no_received_settings(tmp_path: Path) -> None:
    """Учёт прежних сборок — только файлы: настроек с токеном не получали; следующая запись сохраняет оба раздела."""
    paths: LivecraftPaths = _root(tmp_path, "earlier")
    record: Path = paths.file(FileName.TOKEN_RECEIVED)
    record.write_text(json.dumps({"files": {"sheets.token.json": "abc"}}), encoding="utf-8")
    received: ReceivedFiles = ReceivedFiles.load(paths)
    assert (dict(received.prints), dict(received.settings)) == ({"sheets.token.json": "abc"}, {})
    assert not received.is_received_setting("form.url", "https://example.com/form")
    received.with_settings({"form.url": "https://example.com/form"}).save()
    again: ReceivedFiles = ReceivedFiles.load(paths)
    assert dict(again.prints) == {"sheets.token.json": "abc"}
    assert again.is_received_setting("form.url", "https://example.com/form")
    assert not again.is_received_setting("form.url", "https://example.com/other")


# --- загрузка


def test_on_an_empty_installation_everything_lands_and_is_recorded(sender: LivecraftPaths, tmp_path: Path) -> None:
    receiver: LivecraftPaths = _root(tmp_path, "receiver")
    sent: TokenFiles = BOTH.collect(sender)
    assert TokenFiles.of(sent.mapping).apply(receiver) == ()
    assert project_file(receiver, "sender-project").read_text(encoding="utf-8") == SENDER_CLIENT
    assert SettingsFile.placed(receiver).project_file == project_file(receiver, "sender-project")
    assert receiver.file(FileName.SHEETS_TOKEN).read_text(encoding="utf-8") == _login("1//operator")
    for handle in ("@kanal_ua", "@kanal_ru"):
        assert receiver.token_file(handle).read_text(encoding="utf-8") == _login("1//sender-" + handle[-2:])
    assert not receiver.token_file("@kanal_new").exists()
    assert _handles(receiver) == ["@kanal_ua", "@kanal_ru", "@kanal_new"]
    assert {entry.handle for entry in ChannelPassport.load(receiver.file(FileName.PASSPORT)).entries} == {
        "@kanal_ua", "@kanal_ru", "@kanal_new"
    }
    received: ReceivedFiles = ReceivedFiles.load(receiver)
    assert set(received.prints) == {
        "google_project_sender-project.json", "sheets.token.json", "@kanal_ua.token.json", "@kanal_ru.token.json"
    }
    assert BOTH.collect(receiver).mapping == {
        "channels.json": ChannelsFile.of(receiver).render(ConfiguredChannels((_channel("@kanal_new"),))),
        "channels_passport.json": ChannelPassport(receiver.file(FileName.PASSPORT), (_entry("@kanal_new"),)).render(),
    }


def test_own_files_stay_and_received_ones_are_replaced(sender: LivecraftPaths, tmp_path: Path) -> None:
    """Свой выбранный проект, свой вход оператора и канал со своим входом не тронуты; проект из токена сохранён рядом,
    и итог говорит, что рабочим остался свой; канал, полученный прежним токеном, — заменён; новый канал — в конце;
    прежний channels.json — в channels.previous.json."""
    receiver: LivecraftPaths = _root(tmp_path, "receiver")
    project_file(receiver).write_text(RECEIVER_CLIENT, encoding="utf-8")
    choose_project(receiver, project_file(receiver))
    receiver.file(FileName.SHEETS_TOKEN).write_text(_login("1//receiver-operator"), encoding="utf-8")
    own_ua: ChannelConfig = _channel("@Kanal_UA", account="receiver@example.com")
    _install(receiver, (own_ua, _channel("@kanal_ru", account="old@example.com")), {
        "@Kanal_UA": "1//receiver-ua", "@kanal_ru": "1//earlier-ru",
    })
    _receive(receiver, receiver.token_file("@kanal_ru"))
    before: bytes = receiver.file(FileName.CHANNELS).read_bytes()
    notes: tuple[str, ...] = TokenFiles.of(BOTH.collect(sender).mapping).apply(receiver)
    sent_file: str = str(Path("secrets") / "google_project_sender-project.json")
    assert notes == (msg.SETUP_TOKENS_PROJECT_KEPT.format(project="sender-project", file=sent_file, own="receiver-project"),)
    assert SettingsFile.placed(receiver).project_file == project_file(receiver)
    assert project_file(receiver).read_text(encoding="utf-8") == RECEIVER_CLIENT
    assert project_file(receiver, "sender-project").read_text(encoding="utf-8") == SENDER_CLIENT
    assert receiver.file(FileName.SHEETS_TOKEN).read_text(encoding="utf-8") == _login("1//receiver-operator")
    assert receiver.token_file("@Kanal_UA").read_text(encoding="utf-8") == _login("1//receiver-ua")
    assert receiver.token_file("@kanal_ru").read_text(encoding="utf-8") == _login("1//sender-ru")
    channels: tuple[ChannelConfig, ...] = ChannelsFile.of(receiver).load().channels
    assert channels == (own_ua, _channel("@kanal_ru"), _channel("@kanal_new"))
    assert receiver.file(FileName.CHANNELS_PREVIOUS).read_bytes() == before
    assert set(ReceivedFiles.load(receiver).prints) == {"@kanal_ru.token.json", "google_project_sender-project.json"}


def test_the_client_lands_by_project_id_and_replaces_only_a_received_one(sender: LivecraftPaths, tmp_path: Path) -> None:
    """Проект Google едет в токене как client_secret.json, у получателя ложится google_project_<ID>.json и становится
    рабочим вместо полученного прежде; свой рабочий проект главнее (§14 решения 65, 66)."""
    receiver: LivecraftPaths = _root(tmp_path, "receiver")
    project_file(receiver, "earlier-project").write_text(RECEIVER_CLIENT, encoding="utf-8")
    _receive(receiver, project_file(receiver, "earlier-project"))
    choose_project(receiver, project_file(receiver, "earlier-project"))
    sent: dict[str, str] = PROJECT.collect(sender).mapping
    assert sent == {"client_secret.json": SENDER_CLIENT, "sheets.token.json": _login("1//operator")}
    assert TokenFiles.of(sent).apply(receiver) == ()
    assert SettingsFile.of(receiver).load().google.project_file == str(Path("secrets") / "google_project_sender-project.json")
    assert PROJECT.collect(receiver).files == ()
    own: LivecraftPaths = _root(tmp_path, "own")
    project_file(own, "receiver-project").write_text(RECEIVER_CLIENT, encoding="utf-8")
    choose_project(own, project_file(own, "receiver-project"))
    assert len(TokenFiles.of(sent).apply(own)) == 1
    assert SettingsFile.placed(own).project_file == project_file(own, "receiver-project")
    assert PROJECT.collect(own).mapping == {"client_secret.json": RECEIVER_CLIENT}


def test_a_token_with_channels_only_leaves_the_project_of_the_receiver(sender: LivecraftPaths, tmp_path: Path) -> None:
    """Токен с каналами без проекта: получатель получает каналы и входы в них, его проект и livecraft.json — те же."""
    receiver: LivecraftPaths = _root(tmp_path, "receiver")
    project_file(receiver, "receiver-project").write_text(RECEIVER_CLIENT, encoding="utf-8")
    choose_project(receiver, project_file(receiver, "receiver-project"))
    settings: bytes = receiver.file(FileName.CONFIG).read_bytes()
    assert TokenFiles.of(CHANNELS.collect(sender).mapping).apply(receiver) == ()
    assert receiver.file(FileName.CONFIG).read_bytes() == settings
    assert not project_file(receiver, "sender-project").exists() and not receiver.file(FileName.SHEETS_TOKEN).exists()
    assert _handles(receiver) == ["@kanal_ua", "@kanal_ru", "@kanal_new"]
    for handle in ("@kanal_ua", "@kanal_ru"):
        assert receiver.token_file(handle).read_text(encoding="utf-8") == _login("1//sender-" + handle[-2:])
    assert set(ReceivedFiles.load(receiver).prints) == {"@kanal_ua.token.json", "@kanal_ru.token.json"}


def test_a_chosen_file_that_is_gone_gives_way_to_the_client_of_the_token(sender: LivecraftPaths, tmp_path: Path) -> None:
    """Свой файл по пути из настроек убрали — проект из токена становится рабочим."""
    receiver: LivecraftPaths = _root(tmp_path, "receiver")
    choose_project(receiver, tmp_path / "gone.json")
    assert TokenFiles.of(PROJECT.collect(sender).mapping).apply(receiver) == ()
    assert SettingsFile.placed(receiver).project_file == project_file(receiver, "sender-project")


def test_a_token_of_the_earlier_format_touches_no_project(tmp_path: Path) -> None:
    """Токен прежних сборок файлов не несёт: проект и настройки не трогаются."""
    receiver: LivecraftPaths = _root(tmp_path, "receiver")
    assert TokenFiles.of({}).apply(receiver) == ()
    assert not receiver.file(FileName.CONFIG).exists()
    assert list(receiver.dir(DataDir.SECRETS).iterdir()) == []


def test_a_file_of_an_unknown_kind_is_written_nowhere(sender: LivecraftPaths, tmp_path: Path) -> None:
    """Имя файла из токена не выбирает, куда писать: имя вне известных видов — строка лога, на диске ничего."""
    receiver: LivecraftPaths = _root(tmp_path, "receiver")
    planted: dict[str, str] = {"..\\run.bat": "echo planted", "cookies.txt": "planted", "@x.token.json": "{}"}
    with LogCapture.on(LogArea.SETUP) as capture:
        TokenFiles.of(planted).apply(receiver)
    assert [path for path in receiver.root.rglob("*") if path.is_file()] == []
    assert not (receiver.dir(DataDir.SECRETS).parent / "run.bat").exists()
    assert sum("token_file_skipped" in line for line in capture.messages()) == len(planted)
