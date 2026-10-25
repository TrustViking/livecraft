"""Проект Google на вкладке «Главная» без окна: выбор и проверка (CLAUDE.md §8.2 п.1, §9, §14 решение 66).

Проект Google — файл клиента Google типа Desktop (`OAuthClient`). Файл лежит где угодно и называется как угодно:
настройки помнят путь к нему (`google.project_file`), его берут новые входы в браузере и токен доступа. Выбранный
проект как он на диске — `ChosenProject`: не выбран, файл не найден, файл не годится — строкой готовности с путём.
Выбор (`ClientFiles.choose`): годный клиент — путь к нему в livecraft.json, файл не копируется и не переименовывается;
негодный файл настройку не меняет. Сменить проект — выбрать другой файл. Программа работает только через выбранный
проект (§14 решение 67): вход, сделанный через другой проект, при запуске делается заново через выбранный.

Проверка (`ClientCheck.run`) — сама после выбора и по кнопке: знает ли Google клиент (`ClientProbe` — запрос без
входа) и через какой проект сделаны вход оператора и входы каналов этого компьютера (`ClientLogins`). Проверка у
Google запись не останавливает: её итог — строкой. Итог — `ClientVerdict`: строки для окна; в строках и логе нет ни
секрета, ни id клиента — только ID проекта и ники. Работа идёт в фоновом потоке окна: модель не знает ни потоков,
ни Tk.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.config.channel import ConfiguredChannels
from app.config.files import ChannelsFile, SettingsFile
from app.config.google import GoogleSettings
from app.core.errors import os_error_reason
from app.core.text_format import NEWLINE, TEXT_ENCODING
from app.google.login_file import LoginFile
from app.google.oauth_client import ClientAnswer, ClientProbe, OAuthClient
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.paths import FileName, LivecraftPaths
from app.secretsafe.field import VaultOrigin
from app.setup.panels.token_file import ReceivedFiles, TokenFile
from app.setup.panels.token_files import TokenChannels
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)

OPERATOR_LOG_NAME: Final[str] = "operator"     # вход оператора среди ников строки лога


class ClientCheckEvent(str, Enum):
    """События проекта Google в логе."""

    CHECKED = "google_client_checked"
    CHOSEN = "google_client_chosen"


@dataclass(frozen=True)
class ClientVerdict:
    """Итог выбора или проверки проекта Google: удалось ли и строки для окна."""

    is_ok: bool
    text: str

    @classmethod
    def failed(cls, problem: str) -> ClientVerdict:
        return cls(is_ok=False, text=msg.CHECK_PROBLEM_LINE.format(line=problem))

    def then(self, after: ClientVerdict) -> ClientVerdict:
        """Строки выбора, затем строки проверки; удалось — когда удалось и то, и другое."""
        return ClientVerdict(is_ok=self.is_ok and after.is_ok, text=NEWLINE.join((self.text, after.text)))


@dataclass(frozen=True)
class LoginGroup:
    """Входы одного проекта: есть ли среди них вход оператора и ники каналов."""

    has_operator: bool
    handles: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.has_operator and not self.handles

    @property
    def who(self) -> str:
        """Чьи это входы — словами: вход оператора и каналы по нику."""
        parts: list[str] = [msg.SETUP_CLIENT_WHO_OPERATOR] if self.has_operator else []
        if self.handles:
            parts.append(msg.SETUP_CLIENT_WHO_CHANNELS.format(handles=msg.LIST_JOINER.join(self.handles)))
        return msg.SETUP_CLIENT_WHO_JOINER.join(parts)

    @property
    def log_names(self) -> tuple[str, ...]:
        return (*((OPERATOR_LOG_NAME,) if self.has_operator else ()), *self.handles)


@dataclass(frozen=True)
class ClientLogins:
    """Входы этого компьютера и id клиента, через который сделан каждый: вход оператора (`operator`; входа нет — None)
    и входы каналов channels.json по нику (`channels`; канала без входа здесь нет)."""

    operator: str | None
    channels: dict[str, str]

    @classmethod
    def of(cls, paths: LivecraftPaths) -> ClientLogins:
        """Вход оператора и входы каналов channels.json; channels.json нет или не читается — только оператор."""
        configured: ConfiguredChannels | None = ChannelsFile.of(paths).read().value
        listed: tuple[tuple[str, str | None], ...] = () if configured is None else tuple(
            (channel.handle, LoginFile.of(TokenChannels.login_path(paths, channel)).client_id)
            for channel in configured.channels
        )
        logins: dict[str, str] = {handle: client_id for handle, client_id in listed if client_id is not None}
        return cls(operator=LoginFile.of(paths.file(FileName.SHEETS_TOKEN)).client_id, channels=logins)

    def group(self, client: OAuthClient, is_this: bool) -> LoginGroup:
        """Входы через проект `client` (`is_this`) или через другой."""
        return LoginGroup(
            has_operator=self.operator is not None and (self.operator == client.client_id) is is_this,
            handles=tuple(handle for handle, used in self.channels.items() if (used == client.client_id) is is_this),
        )

    def lines(self, client: OAuthClient) -> tuple[str, ...]:
        """Строки окна: чьи входы через этот проект и чьи через другой; входа нет — не упоминается."""
        this: LoginGroup = self.group(client, is_this=True)
        other: LoginGroup = self.group(client, is_this=False)
        lines: list[str] = [] if this.is_empty else [msg.SETUP_CLIENT_LOGINS_THIS.format(who=this.who)]
        if not other.is_empty:
            relogin: str = msg.SETUP_CLIENT_LOGINS_RELOGIN if other.handles else ""
            lines.append(msg.SETUP_CLIENT_LOGINS_OTHER.format(who=other.who) + relogin)
        return tuple(lines)


@dataclass(frozen=True)
class ChosenProject:
    """Проект Google, выбранный в настройках, как он на диске сейчас: файл (`path`; не выбран — None), путь для людей
    (`shown`), есть ли файл (`exists`) и клиент из него (`client`; файла нет или он не клиент Desktop — None)."""

    path: Path | None
    shown: str
    exists: bool
    client: OAuthClient | None

    @classmethod
    def of(cls, paths: LivecraftPaths) -> ChosenProject:
        """Проект путей `paths` (с файлом проекта из настроек — `SettingsFile.placed`)."""
        path: Path | None = paths.project_file
        if path is None:
            return cls(path=None, shown="", exists=False, client=None)
        return cls(path=path, shown=paths.shown(path), exists=path.is_file(), client=OAuthClient.of_file(path))

    @property
    def gap(self) -> str | None:
        """Чего не хватает проекту — строкой (`problem`); годится — None."""
        return None if self.client is not None else self.problem

    @property
    def problem(self) -> str:
        """Почему проекта нет: не выбран, файл не найден или не годится — строкой с путём."""
        if self.path is None:
            return msg.READINESS_GAP_CLIENT_SECRET
        template: str = msg.READINESS_GAP_PROJECT_UNFIT if self.exists else msg.READINESS_GAP_PROJECT_MISSING
        return template.format(path=self.shown)

    @property
    def name(self) -> str:
        """Как назвать проект человеку: ID проекта; файл не годится — путь к нему."""
        return self.shown if self.client is None else self.client.project_id


@dataclass(frozen=True)
class ClientFiles:
    """Проект Google установки: путь к выбранному файлу — в livecraft.json (`google.project_file`), сам файл — где его
    положил человек или загрузка токена."""

    paths: LivecraftPaths

    @property
    def chosen(self) -> ChosenProject:
        """Выбранный проект по настройкам, как они на диске сейчас: их мог поменять загруженный токен доступа."""
        return ChosenProject.of(SettingsFile.placed(self.paths))

    @property
    def status_line(self) -> str:
        """Строка окна: «✓ проект <ID> — путь — чей он»; не выбран, файла нет или он не годится — «✗» с причиной."""
        chosen: ChosenProject = self.chosen
        if chosen.path is None or chosen.client is None:
            return msg.CHECK_PROBLEM_LINE.format(line=chosen.problem)
        own: TokenFile | None = ReceivedFiles.load(self.paths).own(chosen.path)
        origin: VaultOrigin = VaultOrigin.TOKEN if own is None else VaultOrigin.OWN
        return msg.SETUP_CLIENT_STATUS_SET.format(
            project=chosen.client.label, path=chosen.shown, origin=origin.human_label
        )

    def choose(self, source: Path) -> ClientVerdict:
        """Годный клиент из файла `source` — путь к нему в livecraft.json (внутри папки программы — от корня); файл не
        копируется и не переименовывается. Негодный файл настройку не меняет."""
        try:
            text: str = source.read_text(encoding=TEXT_ENCODING)
        except OSError as error:
            return ClientVerdict.failed(msg.SETUP_CLIENT_UNREADABLE.format(reason=os_error_reason(error)))
        except UnicodeDecodeError:
            return ClientVerdict.failed(msg.SETUP_CLIENT_NOT_DESKTOP)
        client: OAuthClient | None = OAuthClient.of_text(text)
        if client is None:
            return ClientVerdict.failed(msg.SETUP_CLIENT_NOT_DESKTOP)
        shown: str = self.paths.shown(source)
        try:
            SettingsFile.of(self.paths).save_google(GoogleSettings(project_file=shown))
        except OSError as error:
            return ClientVerdict.failed(msg.SETUP_CLIENT_WRITE_FAILED.format(reason=os_error_reason(error)))
        LogEvent.of(ClientCheckEvent.CHOSEN, project=client.project_id, file=Quoted(shown)).emit(LOGGER)
        return ClientVerdict(is_ok=True, text=msg.SETUP_CLIENT_CHOSEN.format(project=client.label))


@dataclass(frozen=True)
class ClientCheck:
    """Проект Google установки: файлы (`files`) и вопрос Google о клиенте (`probe`; в тестах — подделка запросов)."""

    files: ClientFiles
    probe: ClientProbe

    @classmethod
    def of(cls, paths: LivecraftPaths) -> ClientCheck:
        return cls(files=ClientFiles(paths), probe=ClientProbe())

    def run(self, _on_login: Callable[[], None]) -> ClientVerdict:
        """Знает ли Google выбранный клиент и через какой проект сделаны входы; проект не выбран, файла нет или он не
        годится — строка с причиной. Входа в Google у проверки нет: браузер не открывается."""
        chosen: ChosenProject = self.files.chosen
        client: OAuthClient | None = chosen.client
        if client is None:
            return ClientVerdict.failed(chosen.problem)
        answer: ClientAnswer = self.probe.answer(client)
        logins: ClientLogins = ClientLogins.of(self.files.paths)
        LogEvent.of(ClientCheckEvent.CHECKED, project=client.project_id, known=answer.log_mark).extended(
            this=logins.group(client, is_this=True).log_names, other=logins.group(client, is_this=False).log_names
        ).emit(LOGGER)
        mark: str = msg.CHECK_OK_LINE if answer.is_known else msg.CHECK_PROBLEM_LINE
        first: str = mark.format(line=msg.SETUP_CLIENT_ANSWER.format(project=client.label, answer=answer.human))
        return ClientVerdict(is_ok=answer.is_known, text=NEWLINE.join((first, *logins.lines(client))))

    def choose(self, source: Path) -> ClientVerdict:
        """Выбрать файл `source` и проверить выбранное; файл не годится — проверки нет."""
        chosen: ClientVerdict = self.files.choose(source)
        return chosen.then(self.run(lambda: None)) if chosen.is_ok else chosen
