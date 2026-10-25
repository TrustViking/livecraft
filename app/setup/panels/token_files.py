"""Файлы secrets\\, которые несёт токен доступа (CLAUDE.md §7.3, §9, §14 решения 65–67, 70, 77).

Какие файлы войдут, решают ползунки «Проект Google» и «Каналы YouTube» вкладки «Токены» (`TokenScope`,
app\\setup\\panels\\token_scope.py): проект — файл клиента и вход оператора, каналы — каналы channels.json с записями
паспорта и входы в них (`TokenChannels`). Проект едет под именем client_secret.json (`TokenFileName.CLIENT`), у
получателя ложится файлом secrets\\google_project_<ID>.json (`ArrivedClient`). В токен идёт только своё: полученное с
токеном помнит учёт `ReceivedFiles` (`app\\setup\\panels\\token_file.py`).

Загрузка — «полученное заменяет полученное, своё главнее» (`TokenFiles.apply`): клиент и вход оператора пишутся, когда
своего файла нет или он получен; клиент становится рабочим проектом, если проект не выбран, его файла нет или он
получен, — иначе рабочим остаётся свой, итог загрузки говорит это строкой; канал токена встаёт в channels.json на место
канала с тем же ником (или в конец), если вход этого канала не свой. Файл токена с именем вне этих видов и клиент без
ID проекта не пишутся никуда: имя из чужого файла не выбирает, куда писать.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.config.channel import ChannelConfig, ChannelHandle, ConfiguredChannels
from app.config.files import ChannelsFile, SettingsFile
from app.config.google import GoogleSettings
from app.config.json_node import JsonNode
from app.core.text_format import TEXT_ENCODING
from app.google.oauth_client import OAuthClient
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import TOKEN_FILE_TEMPLATE, DataDir, FileName, LivecraftPaths, write_text_atomically
from app.platforms.passport import ChannelPassport, PassportEntry, PassportKey
from app.setup.panels.token_file import ReceivedFiles, TokenFile
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)


class TokenFileKind(str, Enum):
    """Вид файлов токена — для строк окна (`msg.TOKEN_FILE_LABELS`); проект Google называет себя сам
    (`OAuthClient.label_of`)."""

    CHANNELS = "channels"
    LOGINS = "logins"
    OPERATOR = "operator"


class TokenFileName(str, Enum):
    """Имена файлов в токене, которые не совпадают с именем файла на диске (формат токена, не путь)."""

    CLIENT = "client_secret.json"     # проект Google; на диске — google_project_<ID>.json (§14 решение 66)


class TokenFilesEvent(str, Enum):
    """События файлов токена в логе."""

    SKIPPED = "token_file_skipped"


# Имена файлов токена известных видов; входы каналов — по нику взятого канала.
FIXED_FILES: Final[tuple[str, ...]] = (
    TokenFileName.CLIENT.value, FileName.SHEETS_TOKEN.value, FileName.CHANNELS.value, FileName.PASSPORT.value
)


@dataclass(frozen=True)
class TokenChannels:
    """Каналы токена: каналы channels.json, записи их паспорта и файлы их входов по простому имени (`logins`)."""

    channels: ConfiguredChannels
    entries: tuple[PassportEntry, ...]
    logins: Mapping[str, TokenFile]

    @classmethod
    def collect(
        cls, paths: LivecraftPaths, received: ReceivedFiles, project: OAuthClient | None
    ) -> TokenChannels | None:
        """Каналы установки, чей вход не получен с токеном, их свои входы через проект токена `project` (входа через
        него нет — канал идёт без файла) и записи паспорта; channels.json не читается или таких каналов нет — None."""
        configured: ConfiguredChannels | None = ChannelsFile.of(paths).read().value
        if configured is None:
            return None
        taken: list[ChannelConfig] = []
        logins: dict[str, TokenFile] = {}
        for channel in configured.channels:
            login: Path = cls.login_path(paths, channel)
            if login.is_file() and received.own(login) is None:
                continue
            taken.append(channel)
            own: TokenFile | None = received.own_login(login, project)
            if own is not None:
                logins[own.name] = own
        if not taken:
            return None
        passport: ChannelPassport = ChannelPassport.load(paths.file(FileName.PASSPORT))
        entries: tuple[PassportEntry | None, ...] = tuple(passport.find_by_key(channel.key) for channel in taken)
        return cls(ConfiguredChannels(tuple(taken)), tuple(entry for entry in entries if entry is not None), logins)

    @classmethod
    def of(cls, files: Mapping[str, TokenFile]) -> TokenChannels | None:
        """Каналы из файлов токена; channels.json в токене нет — None."""
        listed: TokenFile | None = files.get(FileName.CHANNELS.value)
        if listed is None:
            return None
        channels: ConfiguredChannels = ConfiguredChannels.from_node(
            JsonNode(value=json.loads(listed.text), source=Path(listed.name))
        )
        passport: TokenFile | None = files.get(FileName.PASSPORT.value)
        items: list[object] = [] if passport is None else json.loads(passport.text)[PassportKey.CHANNELS.value]
        entries: tuple[PassportEntry, ...] = tuple(PassportEntry.of_json(item, index) for index, item in enumerate(items))
        return cls(channels=channels, entries=entries, logins=files)

    @classmethod
    def login_path(cls, paths: LivecraftPaths, channel: ChannelConfig) -> Path:
        """Файл входа канала — тот же, что берёт проверка канала: secrets\\<ник>.token.json."""
        return paths.token_file(ChannelHandle.of(channel.handle).token_file_stem)

    @classmethod
    def login_name(cls, handle: str) -> str:
        """Простое имя файла входа канала с ником `handle` — его имя и в токене."""
        return TOKEN_FILE_TEMPLATE.format(stem=ChannelHandle.of(handle).token_file_stem)

    @property
    def handles(self) -> tuple[str, ...]:
        return tuple(channel.handle for channel in self.channels.channels)

    @property
    def logged_handles(self) -> str:
        """Ники каналов, чей вход есть среди файлов токена, — строкой; входов нет — пусто."""
        return msg.LIST_JOINER.join(handle for handle in self.handles if self.login_name(handle) in self.logins)

    def files(self, paths: LivecraftPaths) -> tuple[TokenFile, ...]:
        """Файлы для токена: channels.json и паспорт — только эти каналы и их записи; затем файлы входов."""
        listed: TokenFile = TokenFile(FileName.CHANNELS.value, ChannelsFile.of(paths).render(self.channels))
        passport: ChannelPassport = ChannelPassport(paths.file(FileName.PASSPORT), self.entries)
        recorded: tuple[TokenFile, ...] = (TokenFile(FileName.PASSPORT.value, passport.render()),) if self.entries else ()
        return (listed, *recorded, *self.logins.values())

    def apply(self, paths: LivecraftPaths, received: ReceivedFiles) -> tuple[TokenFile, ...]:
        """Каналы токена — в channels.json (канал со своим входом остаётся своим), их файлы входов и записи паспорта —
        на место; записанные файлы входов. Сбой — OSError."""
        channels: ChannelsFile = ChannelsFile.of(paths)
        configured: ConfiguredChannels | None = channels.read().value     # channels.json нет или не читается — никаких
        merged: list[ChannelConfig] = [] if configured is None else list(configured.channels)
        taken: tuple[ChannelConfig, ...] = tuple(
            channel for channel in self.channels.channels if not self._keeps_own(paths, received, merged, channel)
        )
        if not taken:
            return ()
        for channel in taken:
            place: int | None = next((index for index, local in enumerate(merged) if local.key == channel.key), None)
            if place is None:
                merged.append(channel)
            else:
                merged[place] = channel
        channels.save(ConfiguredChannels(tuple(merged)))
        self._record_passport(paths, frozenset(channel.key for channel in taken))
        logins: tuple[TokenFile, ...] = tuple(
            login for login in (self.logins.get(self.login_name(channel.handle)) for channel in taken) if login
        )
        for login in logins:
            login.write(paths.dir(DataDir.SECRETS))
        return logins

    def _keeps_own(
        self, paths: LivecraftPaths, received: ReceivedFiles, local: list[ChannelConfig], channel: ChannelConfig
    ) -> bool:
        """Канал с тем же ником уже есть и вход его — свой: канал установки остаётся."""
        same: ChannelConfig | None = next((item for item in local if item.key == channel.key), None)
        return same is not None and received.own(self.login_path(paths, same)) is not None

    def _record_passport(self, paths: LivecraftPaths, keys: frozenset[str]) -> None:
        """Записи паспорта взятых каналов — в паспорт установки (одна запись на канал). Сбой — OSError."""
        recorded: tuple[PassportEntry, ...] = tuple(entry for entry in self.entries if entry.key in keys)
        if not recorded:
            return
        passport: ChannelPassport = ChannelPassport.load(paths.file(FileName.PASSPORT))
        for entry in recorded:
            passport.record(entry)
        write_text_atomically(passport.path, passport.render(), TEXT_ENCODING)


@dataclass(frozen=True)
class ClientPlacement:
    """Что сделала загрузка с проектом Google из токена: записанный файл (`written`) и строки итога (`notes`)."""

    written: tuple[TokenFile, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArrivedClient:
    """Проект Google из токена у получателя: клиент и его файл secrets\\google_project_<ID>.json (`file`, `target`)."""

    client: OAuthClient
    file: TokenFile
    target: Path

    @classmethod
    def of(cls, paths: LivecraftPaths, files: Mapping[str, TokenFile]) -> ArrivedClient | None:
        """Клиент токена; его нет или из него не прочитать ID проекта — None."""
        carried: TokenFile | None = files.get(TokenFileName.CLIENT.value)
        client: OAuthClient | None = None if carried is None else OAuthClient.of_text(carried.text)
        if carried is None or client is None:
            return None
        target: Path = paths.received_project_file(client.project_id)
        return cls(client=client, file=TokenFile(target.name, carried.text), target=target)

    def apply(self, paths: LivecraftPaths, received: ReceivedFiles) -> ClientPlacement:
        """Файл клиента — в secrets\\ (свой под тем же именем не заменяется) и рабочим проектом, если проект не выбран,
        его файла нет или он получен; рабочим остался свой — строка, что файл из токена сохранён. Сбой — OSError."""
        written: tuple[TokenFile, ...] = ()
        if received.own(self.target) is None:
            self.file.write(self.target.parent)
            written = (self.file,)
        chosen: Path | None = SettingsFile.placed(paths).project_file
        if chosen is None or received.own(chosen) is None:
            SettingsFile.of(paths).save_google(GoogleSettings(project_file=paths.shown(self.target)))
            return ClientPlacement(written=written)
        own: OAuthClient | None = OAuthClient.of_file(chosen)     # свой рабочий проект; файл не клиент — его имя
        kept: str = msg.SETUP_TOKENS_PROJECT_KEPT.format(
            project=self.client.project_id, file=paths.shown(self.target), own=own.project_id if own else chosen.name
        )
        return ClientPlacement(written=written, notes=(kept,) if written else ())


@dataclass(frozen=True)
class TokenFiles:
    """Файлы, которые несёт токен."""

    files: tuple[TokenFile, ...]

    @classmethod
    def of(cls, mapping: Mapping[str, str]) -> TokenFiles:
        """Файлы из содержимого токена."""
        return cls(tuple(TokenFile(name=name, text=text) for name, text in mapping.items()))

    @property
    def mapping(self) -> dict[str, str]:
        """Файлы для содержимого токена: имя → текст."""
        return {file.name: file.text for file in self.files}

    @property
    def client(self) -> OAuthClient | None:
        """Проект Google, который несёт токен; клиента нет или он не годится — None."""
        file: TokenFile | None = self._by_name.get(TokenFileName.CLIENT.value)
        return None if file is None else OAuthClient.of_text(file.text)

    @property
    def channels(self) -> TokenChannels | None:
        """Каналы, которые несёт токен; channels.json в нём нет — None."""
        return TokenChannels.of(self._by_name)

    @property
    def labels(self) -> tuple[str, ...]:
        """Что несут файлы — названиями: «проект Google <ID>», каналы и входы каналов ником, вход оператора."""
        names: dict[str, TokenFile] = self._by_name
        channels: TokenChannels | None = self.channels
        client: TokenFile | None = names.get(TokenFileName.CLIENT.value)
        labels: list[str] = [] if client is None else [OAuthClient.label_of(client.text)]
        if channels is not None:
            handles: str = msg.LIST_JOINER.join(channels.handles)
            labels.append(msg.TOKEN_FILE_LABELS[TokenFileKind.CHANNELS.value].format(handles=handles))
            if channels.logged_handles:
                labels.append(msg.TOKEN_FILE_LABELS[TokenFileKind.LOGINS.value].format(handles=channels.logged_handles))
        if FileName.SHEETS_TOKEN.value in names:
            labels.append(msg.TOKEN_FILE_LABELS[TokenFileKind.OPERATOR.value])
        return tuple(labels)

    def apply(self, paths: LivecraftPaths) -> tuple[str, ...]:
        """Файлы токена — на место по правилу «полученное заменяет полученное, своё главнее»; записанное — в учёт.
        Строки итога загрузки: проект Google из токена сохранён, а рабочим остался свой. Сбой диска — OSError."""
        received: ReceivedFiles = ReceivedFiles.load(paths)
        names: dict[str, TokenFile] = self._by_name
        arrived: ArrivedClient | None = ArrivedClient.of(paths, names)
        placed: ClientPlacement = ClientPlacement() if arrived is None else arrived.apply(paths, received)
        written: list[TokenFile] = list(placed.written)
        operator: TokenFile | None = names.get(FileName.SHEETS_TOKEN.value)
        if operator is not None and received.own(paths.file(FileName.SHEETS_TOKEN)) is None:
            operator.write(paths.dir(DataDir.SECRETS))
            written.append(operator)
        channels: TokenChannels | None = TokenChannels.of(names)
        if channels is not None:
            written.extend(channels.apply(paths, received))
        self._log_skipped({*FIXED_FILES, *(file.name for file in written)})
        if written:
            received.with_written(written).save()
        return placed.notes

    @property
    def _by_name(self) -> dict[str, TokenFile]:
        return {file.name: file for file in self.files}

    def _log_skipped(self, known: set[str]) -> None:
        """Файлы токена вне известных видов и входы невзятых каналов — строкой лога, на диск не пишутся."""
        for file in self.files:
            if file.name not in known:
                LogEvent.of(TokenFilesEvent.SKIPPED, file=file.name).emit(LOGGER, logging.WARNING)
