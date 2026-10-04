"""Входы владельцев каналов и клиенты YouTube API (CLAUDE.md §6 инвариант 5, §9).

Клиент строится лениво и кешируется по ключу канала: один токен — один канал. Вход — `GoogleLogin.owner`, токен
`secrets\\<ник>.token.json`. Новый вход в браузере живёт в памяти, пока канал за ним не подтверждён: токен пишет
только `keep` (иначе чужой токен запоминается навсегда — planers, 17-09-2026). `drop` забывает клиент, вход и
ChannelInfo канала; следующий вход — браузером, мимо файла токена. Браузер открывается, только когда вход разрешён
явно (`allow_login`).
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from app.config.channel import ChannelConfig, ChannelHandle
from app.google.auth import AuthError, AuthErrorReason, GoogleLogin
from app.observability.log_event import LogArea, get_logger
from app.paths import LivecraftPaths
from app.platforms.channel_info import ChannelInfo
from app.platforms.error import PlatformCode, PlatformError
from app.platforms.youtube_event import YouTubeEvent

LOGGER = get_logger(LogArea.PLATFORMS)
YOUTUBE_API_NAME: Final[str] = "youtube"
YOUTUBE_API_VERSION: Final[str] = "v3"
# Клиент YouTube Data API v3 по учётным данным входа.
YOUTUBE_CLIENT: Final[Callable[..., Resource]] = functools.partial(
    build, YOUTUBE_API_NAME, YOUTUBE_API_VERSION, cache_discovery=False
)


@dataclass(frozen=True)
class OwnerLogins:
    """Вход владельца канала по нику: файл токена — по правилу ника (`ChannelHandle.token_file_stem`)."""

    paths: LivecraftPaths

    def __call__(self, channel: ChannelConfig) -> GoogleLogin:
        stem: str = ChannelHandle.of(channel.handle).token_file_stem
        return GoogleLogin.owner(self.paths, stem, channel.google_account)


@dataclass
class ChannelLogins:
    """Клиенты, входы и описания каналов за запуск; всё — по ключу канала.

    `login` — вход канала (`OwnerLogins` или подделка с теми же `credentials`, `save`, `token_file`); `client` —
    клиент API по учётным данным (`YOUTUBE_CLIENT` или подделка).
    """

    login: Callable[[ChannelConfig], GoogleLogin]
    client: Callable[..., Resource] = YOUTUBE_CLIENT
    services: dict[str, Resource] = field(default_factory=dict)
    infos: dict[str, ChannelInfo] = field(default_factory=dict)
    new_logins: dict[str, Credentials] = field(default_factory=dict)   # вход есть, канал ещё не подтверждён
    fresh: set[str] = field(default_factory=set)                       # следующий вход — браузером, мимо токена

    @classmethod
    def of(cls, paths: LivecraftPaths) -> ChannelLogins:
        return cls(login=OwnerLogins(paths))

    def service(self, channel: ChannelConfig, allow_login: bool) -> Resource:
        """Клиент канала; вход не удался — PlatformError: loginRequired (вход нужен, но запрещён) или authFailed."""
        cached: Resource | None = self.services.get(channel.key)
        if cached is not None:
            return cached
        logged_in: list[bool] = []
        try:
            credentials: Credentials = self.login(channel).credentials(
                allow_login=allow_login, force_reauth=channel.key in self.fresh, on_login=lambda: logged_in.append(True)
            )
        except AuthError as error:
            required: bool = error.reason is AuthErrorReason.LOGIN_REQUIRED
            code: PlatformCode = PlatformCode.LOGIN_REQUIRED if required else PlatformCode.AUTH_FAILED
            raise PlatformError.of_login(error, code) from error
        if logged_in:
            self.new_logins[channel.key] = credentials
        service: Resource = self.client(credentials=credentials)
        self.services[channel.key] = service
        return service

    def keep(self, channel: ChannelConfig) -> None:
        """Канал подтверждён: учётные данные нового входа — в файл токена; нового входа не было — ничего."""
        credentials: Credentials | None = self.new_logins.pop(channel.key, None)
        if credentials is None:
            return
        self.fresh.discard(channel.key)
        login: GoogleLogin = self.login(channel)
        try:
            login.save(credentials)
        except AuthError as error:
            raise PlatformError.of_login(error, PlatformCode.AUTH_FAILED) from error
        YouTubeEvent.TOKEN_CREATED.of(channel, file=login.token_file.name).emit(LOGGER)

    def drop(self, channel: ChannelConfig) -> None:
        """Клиент, вход и ChannelInfo канала забыты; следующий вход — браузером, токен не читается."""
        self.services.pop(channel.key, None)
        self.infos.pop(channel.key, None)
        self.new_logins.pop(channel.key, None)
        self.fresh.add(channel.key)
        YouTubeEvent.LOGIN_DROPPED.of(channel).emit(LOGGER)
