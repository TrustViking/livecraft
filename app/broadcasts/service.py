"""Служебные запуски по каналам: --check и --auth (CLAUDE.md §10; поведение planers main.py `_run_check`, `_run_auth`).

--check — все каналы channels.json тем же путём, что запуск: проверка без браузера (её предупреждения — сразу),
фаза входов, по каждому каналу — название, ник и id на YouTube, язык канала на YouTube, языки стримов из channels.json и
число запланированных эфиров; сбой — строка канала. --auth <ник>|all — вход заново при любом статусе канала: прежний
токен заменяется только подтверждённым входом (правило то же, что в запуске, `ChannelBook.log_in`). Код 1 — хоть один
канал не прошёл; неизвестный ник — строка со списком ников и код 1.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.broadcasts.services import BroadcastServices
from app.config.channel import ChannelConfig, ChannelHandle, ConfiguredChannels
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.paths import FileName
from app.platforms.channel import Channel, ChannelBindingError, ChannelStatus
from app.platforms.channel_info import ChannelInfo
from app.platforms.error import PlatformError
from app.run.exit_code import RunOutcome
from app.ui.console import Console
from app.ui.messages import msg

LOGGER = get_logger(LogArea.BROADCASTS)


class AuthTarget(str, Enum):
    """Особое значение --auth."""

    ALL = "all"          # все каналы channels.json


class ServiceEvent(str, Enum):
    """События служебных запусков в логе."""

    CHECK_FAILED = "check_failed"


@dataclass(frozen=True)
class ChannelService:
    """Зависимости запуска, прочитанные каналы и консоль оператора."""

    services: BroadcastServices
    channels: ConfiguredChannels
    console: Console

    def run(self, auth_handle: str | None) -> RunOutcome:
        """Ник для входа есть только у --auth (`RunRequest.auth_handle`): без него — --check."""
        return self.check() if auth_handle is None else self.auth(auth_handle)

    def check(self) -> RunOutcome:
        """Шапка, предупреждения проверки без браузера, фаза входов, строка на канал, итог."""
        self.console.say(msg.CHECK_HEADER.format(path=self.services.paths.file(FileName.CHANNELS)))
        channels: ConfiguredChannels = self.services.book.check_without_login(self.channels)
        self._say_warnings()
        self.services.book.log_in_needed(channels.channels)
        failed: int = sum(1 for config in channels.channels if not self._checked(config))
        self._say_warnings()
        self.console.say(msg.CHECK_CHANNEL_LANGUAGE_NOTE)
        self.console.say(msg.CHECK_HAS_PROBLEMS if failed else msg.CHECK_ALL_OK)
        return RunOutcome.FAILED if failed else RunOutcome.DONE

    def auth(self, target: str) -> RunOutcome:
        """Вход заново каждого канала цели; не подтверждён — строка канала."""
        configs: tuple[ChannelConfig, ...] | None = self._targets(target)
        if configs is None:
            return RunOutcome.FAILED
        failed: int = 0
        for config in configs:
            channel: Channel = self.services.book.log_in(config, force=True)
            if channel.status is not ChannelStatus.READY:
                failed += 1
                self._say_not_ready(channel)
        self._say_warnings()
        return RunOutcome.FAILED if failed else RunOutcome.DONE

    def _targets(self, target: str) -> tuple[ChannelConfig, ...] | None:
        """all — все каналы; иначе канал по нику. Неизвестный ник — строка со списком ников, None."""
        if target == AuthTarget.ALL.value:
            return self.channels.channels
        found: ChannelConfig | None = self.channels.by_handle.get(ChannelHandle.of(target).key)
        if found is not None:
            return (found,)
        known: str = msg.LIST_JOINER.join(
            msg.CHANNEL_LISTED.format(handle=config.handle, account_name=config.account_name)
            for config in self.channels.channels
        )
        path: Path = self.services.paths.file(FileName.CHANNELS)
        self.console.say(msg.AUTH_UNKNOWN_CHANNEL.format(path=path, handle=target, known=known))
        return None

    def _checked(self, config: ChannelConfig) -> bool:
        """Строка канала после фазы входов: подтверждён и площадка ответила — сведения; иначе — причина."""
        channel: Channel = self.services.book.channel(config)
        info: ChannelInfo | None = channel.info
        if channel.status is not ChannelStatus.READY or info is None:
            self._say_not_ready(channel)
            return False
        try:
            upcoming: int = len(self.services.platform.list_upcoming(channel.config))
        except PlatformError as error:
            self._say_failed(channel.config, error)
            return False
        self.console.say(
            msg.CHECK_CHANNEL_OK.format(
                account_name=channel.config.account_name,
                handle=channel.config.handle,
                title=info.title,
                youtube_handle=info.handle_text,
                youtube_channel_id=info.youtube_channel_id,
                channel_language=info.default_language or msg.CHECK_CHANNEL_LANGUAGE_UNSET,
                languages=msg.LIST_JOINER.join(channel.config.languages),
                upcoming=upcoming,
            )
        )
        return True

    def _say_not_ready(self, channel: Channel) -> None:
        """Отказ — готовым текстом; сбой входа уже назван в момент входа (строка ChannelConsole)."""
        if isinstance(channel.error, ChannelBindingError):
            self.console.say(msg.CHECK_CHANNEL_REFUSED.format(message=channel.error.human))
            return
        if channel.status is ChannelStatus.FAILED and channel.login_attempts:
            return
        error: PlatformError | None = channel.access_error()
        if error is not None:
            self._say_failed(channel.config, error)

    def _say_failed(self, config: ChannelConfig, error: PlatformError) -> None:
        failed: LogEvent = LogEvent.of(ServiceEvent.CHECK_FAILED, channel=Quoted(config.account_name))
        failed.extended(handle=config.handle, code=error.code).emit(LOGGER, logging.WARNING)
        self.console.say(
            msg.CHECK_CHANNEL_FAILED.format(account_name=config.account_name, handle=config.handle, reason=error.human)
        )

    def _say_warnings(self) -> None:
        """Предупреждения сверки каналов и входов — строками внимания."""
        for warning in self.services.book.sync.take_warnings():
            self.console.say(msg.CONSOLE_ATTENTION_TEXT.format(text=warning))
