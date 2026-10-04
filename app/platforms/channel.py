"""Объект-канал: всё, что программа знает о канале за запуск, и правило его проверки (CLAUDE.md §3 шаг 2.2, §6 инвариант 5).

Channel — один канал channels.json: значения файла, файл токена, запись паспорта, что прислал YouTube, статус и готовая
ошибка для отчёта. Правило «ник → id по паспорту → название» — `Channel.check`; выравнивание файлов по его решению
делает `ChannelSync` (app\\platforms\\channel_sync.py), вход — `ChannelBook` (app\\platforms\\channel_book.py).

Статусы: READY — канал подтверждён, к площадке можно; NEEDS_LOGIN — токена нет, он отозван или убран как чужой;
REFUSED — вход был, но канал не тот; FAILED — сбой площадки или входа. Почему каналу нужен вход, канал помнит сам
(`LoginNeed`): строка консоли перед браузером называет причину.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.config.channel import ChannelConfig
from app.google.auth import AuthErrorReason
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.platforms.channel_event import ChannelEvent
from app.platforms.channel_info import ChannelInfo
from app.platforms.error import PlatformCode, PlatformDetail, PlatformError
from app.platforms.passport import PassportEntry
from app.ui.messages import msg

LOGGER = get_logger(LogArea.PLATFORMS)
LOGIN_MAX_ATTEMPTS: Final[int] = 2   # входов в браузере на канал за запуск


class ChannelStatus(str, Enum):
    READY = "ready"              # канал подтверждён: к площадке можно
    NEEDS_LOGIN = "needs_login"  # токена нет, он отозван или убран как чужой
    REFUSED = "refused"          # вход был, но канал не тот — после всех попыток
    FAILED = "failed"            # сбой площадки или входа


class LoginNeed(str, Enum):
    """Почему каналу нужен вход в браузере. Значение — идентификатор для лога."""

    NO_TOKEN = "no_token"              # файла токена ещё нет — первый вход
    TOKEN_REVOKED = "token_revoked"    # Google больше не принимает токен
    FOREIGN_TOKEN = "foreign_token"    # токен вёл на другой канал и удалён
    FORCED = "forced"                  # вход заново по --auth

    @property
    def human(self) -> str:
        return msg.AUTH_LOGIN_NEEDS[self.value]


class CheckVerdict(str, Enum):
    CONFIRMED = "confirmed"   # ник и id подтверждены, название совпало
    ALIGN = "align"           # тот же канал (по нику или по id), ник или название выровнять
    REFUSED = "refused"       # не тот канал: почему — `ChannelRefusal`


class ChannelRefusal(str, Enum):
    """Почему канал за токеном не тот; значение — код отказа в отчёте и в логе."""

    HANDLE_MISSING = "channelHandleMissing"     # у канала на YouTube нет ника
    HANDLE_MISMATCH = "channelHandleMismatch"   # ник другой, и паспорт не подтверждает тот же id
    ID_MISMATCH = "channelIdMismatch"           # ник тот же, а id не тот, что в паспорте

    @property
    def template(self) -> str:
        """Текст отказа для владельца канала: значение channels.json и то, что прислал YouTube."""
        return REFUSAL_TEMPLATES[self]


REFUSAL_TEMPLATES: Final[dict[ChannelRefusal, str]] = {
    ChannelRefusal.HANDLE_MISSING: msg.AUTH_CHANNEL_HANDLE_MISSING,
    ChannelRefusal.HANDLE_MISMATCH: msg.AUTH_CHANNEL_HANDLE_MISMATCH,
    ChannelRefusal.ID_MISMATCH: msg.AUTH_CHANNEL_ID_MISMATCH,
}


@dataclass(frozen=True)
class ChannelCheck:
    """Решение проверки канала; `refusal` — почему не тот канал (только у REFUSED)."""

    verdict: CheckVerdict
    refusal: ChannelRefusal | None = None


class ChannelBindingError(PlatformError):
    """Канал за токеном не тот: `human` — готовый текст для владельца, `message` — подробность для лога."""

    def __init__(self, refusal: ChannelRefusal, text: str, detail: str) -> None:
        self.text: str = text
        super().__init__(refusal.value, detail)

    @property
    def human(self) -> str:
        return self.text


@dataclass
class Channel:
    """Изменяемый намеренно: заполняется по ходу запуска. `config` — значения channels.json этого запуска; канал,
    выровненный при входе, получает новые значения в том же запуске (§14 решение 25)."""

    config: ChannelConfig
    token_file: Path
    passport_entry: PassportEntry | None = None
    info: ChannelInfo | None = None        # что прислал YouTube
    status: ChannelStatus = ChannelStatus.NEEDS_LOGIN
    error: PlatformError | None = None     # готовая ошибка для отчёта: REFUSED и FAILED
    login_attempts: int = 0
    login_need: LoginNeed = LoginNeed.NO_TOKEN   # почему нужен вход: строка перед браузером

    @property
    def key(self) -> str:
        return self.config.key

    @property
    def can_try_login(self) -> bool:
        return self.login_attempts < LOGIN_MAX_ATTEMPTS

    def check(self, info: ChannelInfo) -> ChannelCheck:
        """Ник → id по паспорту → название. Название разное при совпавшем нике — выравнивание, не отказ."""
        handle_key: str | None = info.handle_key
        if handle_key is None:
            return ChannelCheck(CheckVerdict.REFUSED, ChannelRefusal.HANDLE_MISSING)
        is_same_id: bool = self.is_confirmed_by_passport(info)
        if handle_key != self.key:
            if is_same_id:
                return ChannelCheck(CheckVerdict.ALIGN)
            return ChannelCheck(CheckVerdict.REFUSED, ChannelRefusal.HANDLE_MISMATCH)
        if self.passport_entry is not None and not is_same_id:
            return ChannelCheck(CheckVerdict.REFUSED, ChannelRefusal.ID_MISMATCH)
        if info.account_name != self.config.account_name:
            return ChannelCheck(CheckVerdict.ALIGN)
        return ChannelCheck(CheckVerdict.CONFIRMED)

    def is_confirmed_by_passport(self, info: ChannelInfo) -> bool:
        """Паспорт по нику из channels.json знает этот же id YouTube."""
        return self.passport_entry is not None and self.passport_entry.youtube_channel_id == info.youtube_channel_id

    def refusal(self, info: ChannelInfo, refusal: ChannelRefusal) -> ChannelBindingError:
        """Отказ с текстом для владельца: значение из channels.json и то, что прислал YouTube."""
        entry: PassportEntry | None = self.passport_entry
        text: str = refusal.template.format(
            account_name=self.config.account_name,
            handle=self.config.handle,
            youtube_title=info.title,
            youtube_handle=info.handle_text,
            youtube_channel_id=info.youtube_channel_id,
            passport_channel_id=None if entry is None else entry.youtube_channel_id,
        )
        detail: str = PlatformDetail.CHANNEL_REFUSED.text(
            handle=self.config.handle, youtube_handle=info.handle_raw, youtube_channel_id=info.youtube_channel_id
        )
        return ChannelBindingError(refusal, text, detail)

    def access_error(self) -> PlatformError | None:
        """Почему к площадке по этому каналу нельзя; None — можно."""
        if self.status is ChannelStatus.READY:
            return None
        if self.error is not None:
            return self.error
        detail: str = PlatformDetail.AUTH.text(reason=AuthErrorReason.LOGIN_REQUIRED.value, detail=self.config.handle)
        return PlatformError(PlatformCode.LOGIN_REQUIRED, detail)

    def realign(self, config: ChannelConfig, token_file: Path) -> None:
        """Ник или название выровнены по YouTube: значения channels.json и файл токена — новые."""
        self.config, self.token_file = config, token_file

    def mark_ready(self, info: ChannelInfo) -> None:
        self.status, self.info, self.error = ChannelStatus.READY, info, None

    def mark_needs_login(self, need: LoginNeed) -> None:
        self.status, self.info, self.error, self.login_need = ChannelStatus.NEEDS_LOGIN, None, None, need

    def mark_refused(self, info: ChannelInfo, error: ChannelBindingError) -> None:
        self.status, self.info, self.error = ChannelStatus.REFUSED, info, error

    def mark_failed(self, error: PlatformError) -> None:
        self.status, self.error = ChannelStatus.FAILED, error

    def log_refused(self, info: ChannelInfo, refusal: ChannelRefusal) -> None:
        entry: PassportEntry | None = self.passport_entry
        refused: LogEvent = ChannelEvent.CHANNEL_REFUSED.of(
            self.config, code=refusal, youtube_title=Quoted(info.title), handle_raw=info.handle_raw
        )
        refused = refused.extended(
            youtube_channel_id=info.youtube_channel_id,
            passport_channel_id=None if entry is None else entry.youtube_channel_id,
            login_attempts=self.login_attempts,
        )
        refused.emit(LOGGER, logging.ERROR)
