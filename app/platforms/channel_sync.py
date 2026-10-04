"""Сверка каналов при старте и выравнивание ника, названия и файла токена по id YouTube (CLAUDE.md §3 шаг 2.2,
§6 инвариант 5, §14 решение 25).

Id канала на YouTube не меняется никогда, а ник и название владелец может сменить. Если канал подтверждается по id
(паспорт каналов), программа сама переписывает ник и название в channels.json, переименовывает файл токена и
обновляет паспорт — повторный вход владельцу не нужен. Новый канал, у которого вместо названия ник, так же получает
название с YouTube.

При старте (`ChannelSync.run`) — по каждому каналу channels.json, без браузера (`StartCheck`); что делать, решает
`Channel.check`, итог записывается в объект `Channel`:
  - токен по нику есть: подтверждён — READY; тот же канал с другим ником или названием — выровнять, READY;
    не тот канал и паспорт его id не подтверждает — токен чужой: файл удаляется, NEEDS_LOGIN;
    нужен вход (токен отозван) — NEEDS_LOGIN; сбой площадки — FAILED;
  - токена по нику нет: токен ищется по записям паспорта, чьих ников нет в channels.json (ник поправили руками) —
    канал за таким токеном с ником из channels.json — тот же канал: токен переименовывается, READY; иначе — NEEDS_LOGIN.
Канал, которому нужен вход, получает причину (`LoginNeed`: токена нет, токен отозван, токен чужой) и строку лога
`login_needed`. Перед вопросом YouTube о канале по его файлу входа — строка консоли (`ChannelConsole.on_check`), если
консоль дали. Браузер здесь не открывается: вход — в фазе входов (`ChannelBook`). За старт channels.json
переписывается один раз (прежний — в channels.previous.json). Вход в фазе входов выравнивает тем же кодом (`align_in_run`).
"""
from __future__ import annotations

import dataclasses
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.config.channel import ChannelConfig, ChannelHandle, ConfiguredChannels
from app.config.files import ChannelsFile
from app.config.json_node import ConfigError
from app.core.clock import Clock
from app.core.dates import format_datetime_text
from app.google.auth import AuthError, GoogleLogin
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.paths import DataDir, FileName, LivecraftPaths
from app.platforms.base import BroadcastPlatform
from app.platforms.channel import Channel, ChannelCheck, ChannelRefusal, ChannelStatus, CheckVerdict, LoginNeed
from app.platforms.channel_console import ChannelConsole
from app.platforms.channel_event import ChannelEvent
from app.platforms.channel_info import ChannelInfo
from app.platforms.error import PlatformCode, PlatformError
from app.platforms.passport import ChannelPassport, ChannelVerification
from app.ui.messages import msg

LOGGER = get_logger(LogArea.PLATFORMS)


class StartEvent(str, Enum):
    """События сверки при старте в логе."""

    LOGIN_NEEDED = "login_needed"


@dataclass(frozen=True)
class ChannelAlignment:
    """Что выровнять у одного канала: значения channels.json до и после, что прислал YouTube, откуда и куда
    переименовать файл токена."""

    before: ChannelConfig
    after: ChannelConfig
    info: ChannelInfo
    token_source: Path
    token_target: Path

    @classmethod
    def plan(
        cls, before: ChannelConfig, info: ChannelInfo, token_source: Path, paths: LivecraftPaths
    ) -> ChannelAlignment:
        """Значения после выравнивания: ник — как прислал YouTube (тот же по ключу — прежнее написание), название —
        с YouTube."""
        youtube: ChannelHandle = ChannelHandle.from_custom_url(info.handle_raw or "")
        handle: str = before.handle if youtube.key == before.key else youtube.text
        after: ChannelConfig = dataclasses.replace(before, handle=handle, account_name=info.account_name)
        target: Path = paths.token_file(ChannelHandle.of(handle).token_file_stem)
        return cls(before, after, info, token_source, target)

    @classmethod
    def unchanged(cls, channel: ChannelConfig, info: ChannelInfo, token_file: Path) -> ChannelAlignment:
        """Канал подтверждён как есть: значения и файл токена прежние."""
        return cls(channel, channel, info, token_file, token_file)

    @property
    def problem(self) -> str | None:
        """Ник или название с YouTube, которые не прошли бы проверку channels.json, не пишутся: что с ними не так."""
        if not self.after.account_name:
            return msg.CHANNEL_ALIGN_TITLE_EMPTY
        return None if self.after.problem is None else self.after.problem.text

    @property
    def is_token_moved(self) -> bool:
        return str(self.token_source) != str(self.token_target)

    @property
    def aligned_text(self) -> str:
        return msg.WARNING_CHANNEL_ALIGNED.format(
            youtube_channel_id=self.info.youtube_channel_id,
            title_before=self.before.account_name,
            handle_before=self.before.handle,
            title_after=self.after.account_name,
            handle_after=self.after.handle,
        )

    def failure_text(self, reason: str) -> str:
        return msg.WARNING_CHANNEL_ALIGN_FAILED.format(
            account_name=self.before.account_name,
            handle=self.before.handle,
            youtube_channel_id=self.info.youtube_channel_id,
            reason=reason,
        )

    def verification(self, verified_at: str) -> ChannelVerification:
        return ChannelVerification(self.before, self.after, self.info, self.token_target.name, verified_at)

    def rename_token(self) -> str | None:
        """Файл токена — под новый ник, без перезаписи. None — переименован или не нужно; иначе предупреждение."""
        if not self.is_token_moved:
            return None
        if self.token_target.exists() and not os.path.samefile(self.token_source, self.token_target):
            skipped: LogEvent = ChannelEvent.TOKEN_RENAME_SKIPPED.of(
                self.before, source=self.token_source.name, target=self.token_target.name
            )
            skipped.extended(youtube_channel_id=self.info.youtube_channel_id).emit(LOGGER, logging.WARNING)
            return msg.WARNING_TOKEN_RENAME_SKIPPED.format(
                account_name=self.before.account_name,
                handle=self.before.handle,
                youtube_channel_id=self.info.youtube_channel_id,
                handle_after=self.after.handle,
                target=self.token_target,
            )
        try:
            os.rename(self.token_source, self.token_target)   # имена, одинаковые без учёта регистра, — тот же файл
        except OSError as error:
            return self.failure_text(str(error))
        return None

    def restore_token(self) -> None:
        """channels.json не записан: файл токена — обратно под прежний ник."""
        if not self.is_token_moved:
            return
        try:
            os.rename(self.token_target, self.token_source)
        except OSError as error:
            failed: LogEvent = LogEvent.of(
                ChannelEvent.TOKEN_RESTORE_FAILED, source=self.token_target, target=self.token_source, error=error
            )
            failed.emit(LOGGER, logging.ERROR)

    def log_aligned(self) -> None:
        aligned: LogEvent = LogEvent.of(
            ChannelEvent.CHANNEL_ALIGNED,
            handle_before=self.before.handle,
            handle_after=self.after.handle,
            title_before=Quoted(self.before.account_name),
            title_after=Quoted(self.after.account_name),
        )
        aligned = aligned.extended(youtube_channel_id=self.info.youtube_channel_id, token_before=self.token_source.name)
        aligned.extended(token_after=self.token_target.name).emit(LOGGER)


class ChannelSync:
    """Один экземпляр на запуск: общий паспорт для сверки при старте и для входов (`ChannelBook`)."""

    def __init__(self, platform: BroadcastPlatform, paths: LivecraftPaths, clock: Clock) -> None:
        self._platform: BroadcastPlatform = platform
        self._paths: LivecraftPaths = paths
        self._file: ChannelsFile = ChannelsFile.of(paths)
        self._verified_at: str = format_datetime_text(clock.now())
        self._warnings: list[str] = []
        self._channels: list[Channel] = []   # объекты каналов после run; забирает take_channels
        self._passport: ChannelPassport = ChannelPassport.load(paths.file(FileName.PASSPORT))
        if self._passport.problem is not None:
            self._warnings.append(msg.WARNING_PASSPORT_UNREADABLE.format(path=self._passport.path))

    @property
    def platform(self) -> BroadcastPlatform:
        return self._platform

    @property
    def paths(self) -> LivecraftPaths:
        return self._paths

    @property
    def passport(self) -> ChannelPassport:
        return self._passport

    def token_file(self, channel: ChannelConfig) -> Path:
        return self._paths.token_file(ChannelHandle.of(channel.handle).token_file_stem)

    def new_channel(self, config: ChannelConfig) -> Channel:
        """Объект канала до проверки: файл токена и запись паспорта по нику."""
        return Channel(
            config=config, token_file=self.token_file(config), passport_entry=self._passport.find_by_key(config.key)
        )

    def take_channels(self) -> list[Channel]:
        taken: list[Channel] = list(self._channels)
        self._channels.clear()
        return taken

    def add_warning(self, text: str) -> None:
        self._warnings.append(text)

    def take_warnings(self) -> list[str]:
        """Предупреждения запуска, накопленные с прошлого вызова."""
        taken: list[str] = list(self._warnings)
        self._warnings.clear()
        return taken

    def run(self, channels: ConfiguredChannels, console: ChannelConsole | None = None) -> ConfiguredChannels:
        """Сверка при старте: каналы после выравнивания; строки по каналам — в `console`. Объекты каналов —
        `take_channels`, предупреждения — `take_warnings`."""
        check: StartCheck = StartCheck(self, frozenset(config.key for config in channels.channels), console)
        checked: dict[str, Channel] = {config.key: self.new_channel(config) for config in channels.channels}
        planned: list[ChannelAlignment] = []
        for channel in checked.values():
            found: ChannelAlignment | None = check.alignment(channel)
            if found is not None:
                planned.append(found)
        for item in self._apply(planned):
            checked[item.before.key].realign(item.after, item.token_target)
        self._save_passport()
        for channel in checked.values():
            channel.passport_entry = self._passport.find_by_key(channel.key)
        self._channels = list(checked.values())
        return ConfiguredChannels(tuple(channel.config for channel in self._channels))

    def confirm(self, channel: ChannelConfig, info: ChannelInfo) -> None:
        """Канал проверен без выравнивания: запись паспорта создать или обновить и сразу сохранить."""
        self.record(ChannelAlignment.unchanged(channel, info, self.token_file(channel)))
        self._save_passport()

    def align_in_run(self, channel: ChannelConfig, info: ChannelInfo) -> ChannelAlignment | None:
        """Выравнивание при входе: файлы и паспорт обновлены — выравнивание; не вышло — None."""
        alignment: ChannelAlignment | None = self.plan(channel, info, self.token_file(channel))
        if alignment is None:
            return None
        applied: tuple[ChannelAlignment, ...] = self._apply((alignment,))
        self._save_passport()
        return applied[0] if applied else None

    def plan(self, before: ChannelConfig, info: ChannelInfo, token_source: Path) -> ChannelAlignment | None:
        """Что выровнять; ник или название, которые не прошли бы проверку channels.json, — предупреждение и None."""
        alignment: ChannelAlignment = ChannelAlignment.plan(before, info, token_source, self._paths)
        problem: str | None = alignment.problem
        if problem is None:
            return alignment
        skipped: LogEvent = ChannelEvent.ALIGN_SKIPPED.of(
            before, youtube_channel_id=info.youtube_channel_id, problem=Quoted(problem)
        )
        skipped.emit(LOGGER, logging.WARNING)
        self._warnings.append(alignment.failure_text(problem))
        return None

    def record(self, alignment: ChannelAlignment) -> None:
        """Канал подтверждён: запись паспорта по значениям после выравнивания."""
        self._passport.record_verified(alignment.verification(self._verified_at))

    def _apply(self, alignments: Sequence[ChannelAlignment]) -> tuple[ChannelAlignment, ...]:
        """Токены → channels.json (один раз) → паспорт. Не записался channels.json — токены возвращаются."""
        renamed: list[ChannelAlignment] = []
        for item in alignments:
            warning: str | None = item.rename_token()
            if warning is None:
                renamed.append(item)
            else:
                self._warnings.append(warning)
        if not renamed:
            return ()
        replacements: dict[str, ChannelConfig] = {item.before.key: item.after for item in renamed}
        try:
            current: ConfiguredChannels = self._file.load()
            self._file.save(ConfiguredChannels(tuple(replacements.get(item.key, item) for item in current.channels)))
        except (ConfigError, OSError) as error:
            failed: LogEvent = LogEvent.of(ChannelEvent.CHANNELS_WRITE_FAILED, path=self._file.path, error=error)
            failed.emit(LOGGER, logging.WARNING)
            for item in renamed:
                item.restore_token()
                self._warnings.append(item.failure_text(str(error)))
            return ()
        for item in renamed:
            item.log_aligned()
            self._warnings.append(item.aligned_text)
            self.record(item)
        return tuple(renamed)

    def _save_passport(self) -> None:
        problem: str | None = self._passport.save()
        if problem is not None:
            self._warnings.append(msg.WARNING_PASSPORT_WRITE_FAILED.format(path=self._passport.path, error=problem))


@dataclass
class StartCheck:
    """Сверка при старте, канал за каналом, без браузера. `known` — ключи каналов channels.json, `console` — строки
    по каналам (None — молчит), `claimed` — записи паспорта, чей токен уже отдан другому каналу."""

    sync: ChannelSync
    known: frozenset[str]
    console: ChannelConsole | None = None
    claimed: set[str] = field(default_factory=set)

    def alignment(self, channel: Channel) -> ChannelAlignment | None:
        """Статус канала — в объект; наружу — что выровнять. Нужен вход — строка лога с причиной."""
        alignment: ChannelAlignment | None = self._checked(channel)
        if channel.status is ChannelStatus.NEEDS_LOGIN:
            config: ChannelConfig = channel.config
            needed: LogEvent = LogEvent.of(StartEvent.LOGIN_NEEDED, channel=Quoted(config.account_name))
            needed.extended(handle=config.handle, reason=channel.login_need).emit(LOGGER)
        return alignment

    def _checked(self, channel: Channel) -> ChannelAlignment | None:
        """Файла токена нет — токен под прежним ником, иначе первый вход; есть — вопрос YouTube: канал, отозванный
        токен (вход заново) или сбой."""
        if not channel.token_file.is_file():
            moved: ChannelAlignment | None = self._find_moved_token(channel.config)
            if moved is None:
                channel.mark_needs_login(LoginNeed.NO_TOKEN)
            else:
                channel.mark_ready(moved.info)
            return moved
        if self.console is not None:
            self.console.on_check(channel.config)
        answer: ChannelInfo | PlatformError = self._ask(channel.config)
        if isinstance(answer, ChannelInfo):
            return self._decide(channel, answer)
        if answer.code == PlatformCode.LOGIN_REQUIRED.value:
            channel.mark_needs_login(LoginNeed.TOKEN_REVOKED)
        else:
            channel.mark_failed(answer)
        return None

    def _decide(self, channel: Channel, info: ChannelInfo) -> ChannelAlignment | None:
        """Решение — `Channel.check`: подтверждён — паспорт; тот же канал — выровнять; не тот — отказ или чужой токен."""
        check: ChannelCheck = channel.check(info)
        if check.refusal is not None:
            self._refuse(channel, info, check.refusal)
            return None
        channel.mark_ready(info)
        if check.verdict is CheckVerdict.ALIGN:
            alignment: ChannelAlignment | None = self.sync.plan(channel.config, info, channel.token_file)
            if alignment is not None:
                return alignment
        self.sync.record(ChannelAlignment.unchanged(channel.config, info, channel.token_file))
        return None

    def _refuse(self, channel: Channel, info: ChannelInfo, refusal: ChannelRefusal) -> None:
        """Паспорт подтверждает id (у канала пропал ник) — отказ до конца запуска; иначе токен чужой."""
        if channel.is_confirmed_by_passport(info):
            channel.log_refused(info, refusal)
            channel.mark_refused(info, channel.refusal(info, refusal))
            return
        self._reject_token(channel, info, refusal)

    def _reject_token(self, channel: Channel, info: ChannelInfo, refusal: ChannelRefusal) -> None:
        """Токен ведёт не на тот канал: файл удаляется, канал входит заново в фазе входов."""
        config: ChannelConfig = channel.config
        rejected: LogEvent = ChannelEvent.TOKEN_REJECTED.of(config, youtube_title=Quoted(info.title), code=refusal)
        rejected.extended(handle_raw=info.handle_raw, youtube_channel_id=info.youtube_channel_id).emit(
            LOGGER, logging.WARNING
        )
        self.sync.platform.drop_login(config)
        stem: str = ChannelHandle.of(config.handle).token_file_stem
        try:
            GoogleLogin.owner(self.sync.paths, stem, config.google_account).drop()
        except AuthError as error:
            channel.mark_failed(PlatformError.of_login(error, PlatformCode.AUTH_FAILED))
            return
        channel.mark_needs_login(LoginNeed.FOREIGN_TOKEN)
        self.sync.add_warning(
            msg.WARNING_TOKEN_REJECTED.format(
                account_name=config.account_name,
                handle=config.handle,
                youtube_title=info.title,
                youtube_handle=info.handle_text,
                youtube_channel_id=info.youtube_channel_id,
            )
        )

    def _find_moved_token(self, config: ChannelConfig) -> ChannelAlignment | None:
        """Ник поправили руками: токен лежит под прежним ником из паспорта, которого в channels.json нет."""
        for entry in self.sync.passport.entries:
            source: Path = self.sync.paths.dir(DataDir.SECRETS) / entry.token_file
            if entry.key in self.known or entry.key in self.claimed or not source.is_file():
                continue
            answer: ChannelInfo | PlatformError = self._ask(entry.channel_for(config))
            if isinstance(answer, ChannelInfo) and answer.handle_key == config.key:
                self.claimed.add(entry.key)
                return self.sync.plan(config, answer, source)
        return None

    def _ask(self, config: ChannelConfig) -> ChannelInfo | PlatformError:
        """Канал за токеном без браузера; отказ площадки — значением: что с ним делать, решает вызывающий."""
        try:
            return self.sync.platform.describe_channel(config, allow_login=False)
        except PlatformError as error:
            ChannelEvent.SYNC_SKIPPED.of(config, code=error.code).emit(LOGGER)
            return error
