"""Вход в канал глазами владельца: строки консоли проверки каналов при старте, фазы входов, --check и --auth
(CLAUDE.md §3 шаги 2.2 и 8, §9).

Печатает `Console`, тексты — каталог msg; ник канала на YouTube — как его прислал YouTube (`ChannelInfo.handle_text`).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config.channel import ChannelConfig
from app.google.auth import AuthErrorReason
from app.platforms.channel import LoginNeed
from app.platforms.channel_info import ChannelInfo
from app.platforms.error import PlatformError
from app.ui.console import Console
from app.ui.messages import msg


@dataclass(frozen=True)
class ChannelConsole:
    """Строки входа в канал: проверка по сохранённому входу, перед браузером, не тот канал, вход не удался, канал
    подтверждён."""

    console: Console

    def on_check(self, channel: ChannelConfig) -> None:
        """Ровно перед вопросом YouTube о канале по сохранённому входу: при повторах обращения это не тишина."""
        started: str = msg.PROGRESS_CHANNEL_CHECK_STARTED
        self.console.say(started.format(account_name=channel.account_name, handle=channel.handle))

    def on_login(self, channel: ChannelConfig, need: LoginNeed) -> None:
        """Ровно перед открытием браузера: почему нужен вход, какой аккаунт и какой канал выбирать."""
        name, handle = channel.account_name, channel.handle
        self.console.say(msg.AUTH_STARTING.format(account_name=name, handle=handle, reason=need.human))
        self.console.say(msg.AUTH_CHOOSE_ACCOUNT.format(google_account=channel.google_account, account_name=name, handle=handle))
        self.console.say(msg.AUTH_CHOOSE_RIGHT_CHANNEL.format(account_name=name, handle=handle))
        self.console.say(msg.AUTH_UNVERIFIED_APP_WARNING)

    def on_wrong_channel(self, channel: ChannelConfig, info: ChannelInfo, will_retry: bool) -> None:
        """В браузере выбран не тот канал: будет ещё попытка или попытки кончились."""
        template: str = msg.AUTH_WRONG_CHANNEL_RETRY if will_retry else msg.AUTH_WRONG_CHANNEL_GIVE_UP
        self.console.say(
            template.format(
                account_name=channel.account_name,
                handle=channel.handle,
                youtube_title=info.title,
                youtube_handle=info.handle_text,
            )
        )

    def on_login_failed(self, channel: ChannelConfig, error: PlatformError) -> None:
        """Вход не удался: причина для человека; подсказка про разрешение youtube — если экран согласия был."""
        failed: str = msg.AUTH_FAILED.format(account_name=channel.account_name, handle=channel.handle, reason=error.human)
        self.console.say(failed)
        if error.login_reason is not AuthErrorReason.LOGIN_TIMEOUT:
            self.console.say(msg.AUTH_SCOPE_HINT)

    def on_channel_ready(self, channel: ChannelConfig, info: ChannelInfo) -> None:
        """Вход выполнен, канал подтверждён."""
        self.console.say(
            msg.AUTH_OK.format(
                account_name=channel.account_name,
                handle=channel.handle,
                title=info.title,
                youtube_handle=info.handle_text,
                youtube_channel_id=info.youtube_channel_id,
            )
        )
