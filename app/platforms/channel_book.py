"""Каналы запуска: проверка без браузера и фаза входов (CLAUDE.md §3 шаги 2.2 и 8, §6 инварианты 5, 9).

`ChannelBook` — все каналы запуска. Порядок: проверка без браузера (`check_without_login`, статусы READY /
NEEDS_LOGIN / REFUSED / FAILED) → фаза входов (`log_in_needed`: каналы с эфирами и статусом NEEDS_LOGIN входят
подряд) → работа с площадкой только по каналам READY (`VerifiedPlatform`, app\\platforms\\verified.py). После фазы
входов браузер в этом запуске не открывается. Токен нового входа пишется только после подтверждения канала. Вход, не
завершённый за LOGIN_TIMEOUT_SEC, — FAILED без второй попытки: человека нет у компьютера. Канал, выровненный при
входе, получает новые значения в том же запуске (§14 решение 25); книга находит его и по прежнему нику.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

from app.config.channel import ChannelConfig, ConfiguredChannels
from app.google.auth import LOGIN_TIMEOUT_SEC, AuthErrorReason
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.platforms.base import BroadcastPlatform
from app.platforms.channel import (
    LOGIN_MAX_ATTEMPTS, Channel, ChannelCheck, ChannelRefusal, ChannelStatus, CheckVerdict, LoginNeed,
)
from app.platforms.channel_console import ChannelConsole
from app.platforms.channel_event import ChannelEvent
from app.platforms.channel_info import ChannelInfo
from app.platforms.channel_sync import ChannelAlignment, ChannelSync
from app.platforms.error import PlatformError
from app.ui.messages import msg

LOGGER = get_logger(LogArea.PLATFORMS)


class ChannelBook:
    """Все каналы запуска — один экземпляр; канал ищется по ключу ника (`ChannelConfig.key`)."""

    def __init__(self, platform: BroadcastPlatform, sync: ChannelSync, console: ChannelConsole | None = None) -> None:
        self._platform: BroadcastPlatform = platform
        self._sync: ChannelSync = sync
        self._console: ChannelConsole | None = console
        self._channels: dict[str, Channel] = {}

    @property
    def sync(self) -> ChannelSync:
        """Сверка каналов запуска: паспорт и предупреждения (`take_warnings`)."""
        return self._sync

    def check_without_login(self, channels: ConfiguredChannels) -> ConfiguredChannels:
        """Проверка всех каналов без браузера: каналы после выравнивания; предупреждения — `sync.take_warnings`.
        Перед ней и перед вопросом YouTube о каждом канале — строки в консоль: сверка идёт по сети, и повторы обращения
        к YouTube без строки — тишина."""
        if self._console is not None:
            self._console.console.say(msg.PROGRESS_CHANNELS_CHECK.format(count=len(channels.channels)))
        synced: ConfiguredChannels = self._sync.run(channels, self._console)
        self._channels = {channel.key: channel for channel in self._sync.take_channels()}
        return synced

    def channel(self, config: ChannelConfig) -> Channel:
        """Объект канала; без проверки при старте (--auth) — новый, со статусом NEEDS_LOGIN."""
        found: Channel | None = self._channels.get(config.key)
        if found is None:
            found = self._sync.new_channel(config)
            self._channels[config.key] = found
        return found

    def log_in_needed(self, channels: Sequence[ChannelConfig]) -> None:
        """Фаза входов: каждый канал из списка со статусом NEEDS_LOGIN входит, один за другим."""
        seen: set[str] = set()
        for config in channels:
            if config.key in seen:
                continue
            seen.add(config.key)
            if self.channel(config).status is ChannelStatus.NEEDS_LOGIN:
                self.log_in(config)
        LogEvent.of(ChannelEvent.LOGIN_PHASE_DONE, channels=len(seen)).emit(LOGGER)

    def log_in(self, config: ChannelConfig, *, force: bool = False) -> Channel:
        """Вход одного канала — одно место для запуска, --check и --auth; попыток — не больше LOGIN_MAX_ATTEMPTS.

        force (--auth) — вход при любом статусе, причина входа — FORCED; прежний токен остаётся, пока новый вход не
        подтверждён.
        """
        channel: Channel = self.channel(config)
        if force:
            channel.login_need = LoginNeed.FORCED
        elif channel.status is not ChannelStatus.NEEDS_LOGIN:
            return channel
        again: bool = True
        while again and channel.can_try_login:
            again = self._attempt(channel)
        return channel

    def _attempt(self, channel: Channel) -> bool:
        """Одна попытка входа; True — нужна ещё одна (в браузере выбран не тот канал)."""
        config: ChannelConfig = channel.config
        channel.login_attempts += 1
        self._platform.drop_login(config)
        started: LogEvent = ChannelEvent.LOGIN_STARTED.of(config, google_account=Quoted(config.google_account))
        started.extended(attempt=channel.login_attempts, max_attempts=LOGIN_MAX_ATTEMPTS).emit(LOGGER)
        if self._console is not None:
            self._console.on_login(config, channel.login_need)
        try:
            info: ChannelInfo = self._platform.describe_channel(config, allow_login=True)
        except PlatformError as error:
            self._fail(channel, error)
            return False
        channel.passport_entry = self._sync.passport.find_by_key(channel.key)
        check: ChannelCheck = channel.check(info)
        if check.refusal is not None:
            return self._wrong_channel(channel, info, check.refusal)
        self._confirm(channel, info, check)
        return False

    def _fail(self, channel: Channel, error: PlatformError) -> None:
        """Сбой входа — FAILED, второй попытки нет (в том числе по таймауту: человека нет у компьютера)."""
        failed: LogEvent = ChannelEvent.LOGIN_FAILED.of(channel.config, code=error.code, message=Quoted(error.message))
        failed.emit(LOGGER, logging.ERROR)
        self._platform.drop_login(channel.config)
        if error.login_reason is AuthErrorReason.LOGIN_TIMEOUT:
            ChannelEvent.LOGIN_TIMEOUT.of(channel.config, timeout_sec=LOGIN_TIMEOUT_SEC).emit(LOGGER, logging.WARNING)
        channel.mark_failed(error)
        if self._console is not None:
            self._console.on_login_failed(channel.config, error)

    def _wrong_channel(self, channel: Channel, info: ChannelInfo, refusal: ChannelRefusal) -> bool:
        """Не тот канал: токен не пишется; попытки остались — ещё вход, иначе REFUSED."""
        self._platform.drop_login(channel.config)
        will_retry: bool = channel.can_try_login
        wrong: LogEvent = ChannelEvent.LOGIN_WRONG_CHANNEL.of(
            channel.config, youtube_title=Quoted(info.title), handle_raw=info.handle_raw
        )
        wrong = wrong.extended(youtube_channel_id=info.youtube_channel_id, code=refusal)
        wrong.extended(attempt=channel.login_attempts, max_attempts=LOGIN_MAX_ATTEMPTS).emit(LOGGER, logging.WARNING)
        if self._console is not None:
            self._console.on_wrong_channel(channel.config, info, will_retry)
        if will_retry:
            return True
        channel.log_refused(info, refusal)
        channel.mark_refused(info, channel.refusal(info, refusal))
        return False

    def _confirm(self, channel: Channel, info: ChannelInfo, check: ChannelCheck) -> None:
        """Токен — до выравнивания: выравнивание ника переименовывает уже записанный файл. Выровненный канал работает
        с новыми значениями в этом же запуске и находится книгой и по прежнему, и по новому нику."""
        self._keep_login(channel.config)
        alignment: ChannelAlignment | None = None
        if check.verdict is CheckVerdict.ALIGN:
            alignment = self._sync.align_in_run(channel.config, info)
        if alignment is None:
            self._sync.confirm(channel.config, info)
        else:
            channel.realign(alignment.after, alignment.token_target)
            channel.passport_entry = self._sync.passport.find_by_key(channel.key)
            self._channels[channel.key] = channel
        channel.mark_ready(info)
        confirmed: LogEvent = ChannelEvent.LOGIN_CONFIRMED.of(channel.config, youtube_channel_id=info.youtube_channel_id)
        confirmed.extended(verdict=check.verdict).emit(LOGGER)
        if self._console is not None:
            self._console.on_channel_ready(channel.config, info)

    def _keep_login(self, config: ChannelConfig) -> None:
        """Не записался файл — канал в этом запуске всё равно работает: учётные данные в памяти."""
        try:
            self._platform.keep_login(config)
        except PlatformError as error:
            failed: LogEvent = ChannelEvent.TOKEN_SAVE_FAILED.of(config, code=error.code, message=Quoted(error.message))
            failed.emit(LOGGER, logging.WARNING)
            self._sync.add_warning(
                msg.WARNING_TOKEN_SAVE_FAILED.format(account_name=config.account_name, handle=config.handle, error=error.human)
            )
