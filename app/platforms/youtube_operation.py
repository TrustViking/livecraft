"""Операции YouTube Data API v3 и что делать с их отказами (CLAUDE.md §6 инвариант 9, §9).

`YouTubeOperation` — операция API: её цена в единицах квоты (`QUOTA_UNITS`, §9 — по факту Google Cloud Console за
20-09-2026 и 21-09-2026: все чтения и записи трансляций — 1, `videos.update` и `thumbnails.set` — 50) и признак
создающей (`CREATING_OPERATIONS`). Цена начисляется за каждую попытку: Google берёт минимум 1 ед. и за отказ.

`ErrorBehavior` — пять поведений на отказ: повторить / не повторять этот вызов / не вызывать эту операцию на канале /
не обращаться к каналу / не обращаться к YouTube. Поведение по причине — таблица `REASON_BEHAVIORS`, пара «операция,
причина» главнее причины — `OPERATION_REASON_BEHAVIORS`. Решает их один объект — отказ попытки (`YouTubeFailure`).
"""
from __future__ import annotations

from enum import Enum
from typing import Final

from app.platforms.error import PlatformCode


class YouTubeOperation(str, Enum):
    """Операция API; значение — её имя в Google Cloud Console и в строках лога."""

    CHANNELS_LIST = "channels.list"
    BROADCASTS_LIST = "liveBroadcasts.list"
    STREAMS_LIST = "liveStreams.list"
    VIDEOS_LIST = "videos.list"
    BROADCASTS_INSERT = "liveBroadcasts.insert"
    BROADCASTS_UPDATE = "liveBroadcasts.update"
    BROADCASTS_BIND = "liveBroadcasts.bind"
    STREAMS_INSERT = "liveStreams.insert"
    STREAMS_UPDATE = "liveStreams.update"
    VIDEOS_UPDATE = "videos.update"
    THUMBNAILS_SET = "thumbnails.set"

    @property
    def quota_units(self) -> int:
        """Цена одной попытки в единицах суточной квоты проекта."""
        return QUOTA_UNITS[self]

    @property
    def is_creating(self) -> bool:
        """Создающий, неидемпотентный вызов: повтор после неизвестного исхода завёл бы второй эфир или поток."""
        return self in CREATING_OPERATIONS


# Какая из четырёх записей создания эфира (insert эфира, insert потока, bind, thumbnails.set) стоит 50, по дням
# 20–21-09-2026 не различить (число вызовов одинаковое) — отнесено к thumbnails.set.
QUOTA_UNITS: Final[dict[YouTubeOperation, int]] = {
    YouTubeOperation.CHANNELS_LIST: 1,
    YouTubeOperation.BROADCASTS_LIST: 1,
    YouTubeOperation.STREAMS_LIST: 1,
    YouTubeOperation.VIDEOS_LIST: 1,
    YouTubeOperation.BROADCASTS_INSERT: 1,
    YouTubeOperation.BROADCASTS_UPDATE: 1,
    YouTubeOperation.BROADCASTS_BIND: 1,
    YouTubeOperation.STREAMS_INSERT: 1,
    YouTubeOperation.STREAMS_UPDATE: 1,
    YouTubeOperation.VIDEOS_UPDATE: 50,
    YouTubeOperation.THUMBNAILS_SET: 50,
}
# Отказ с неизвестным исходом (обрыв связи, 5xx) у создающих вызовов не повторяется: объект остаётся несозданным,
# эфир доделает следующий запуск. Явный отказ сервера (лимит частоты) повторяется как у всех.
CREATING_OPERATIONS: Final[frozenset[YouTubeOperation]] = frozenset(
    {YouTubeOperation.BROADCASTS_INSERT, YouTubeOperation.STREAMS_INSERT}
)


class ErrorBehavior(str, Enum):
    """Что делать с отказом YouTube."""

    RETRY = "retry"          # повторить с паузой
    CALL = "call"            # не повторять; следующий такой же вызов — как обычно
    OPERATION = "operation"  # не повторять; эту операцию на этом канале до конца запуска не вызывать
    CHANNEL = "channel"      # не повторять; к этому каналу до конца запуска не обращаться
    PROJECT = "project"      # не повторять; к YouTube до конца запуска не обращаться


# Причины отказа (errors[0].reason в ответе Google) и коды самой программы — единственная таблица поведения.
REASON_BEHAVIORS: Final[dict[str, ErrorBehavior]] = {
    "backendError": ErrorBehavior.RETRY,
    "internalError": ErrorBehavior.RETRY,
    "rateLimitExceeded": ErrorBehavior.RETRY,
    "userRateLimitExceeded": ErrorBehavior.RETRY,
    "userRequestsExceedRateLimit": ErrorBehavior.RETRY,
    "uploadRateLimitExceeded": ErrorBehavior.OPERATION,
    "userBroadcastsExceedLimit": ErrorBehavior.OPERATION,
    "liveStreamingNotEnabled": ErrorBehavior.OPERATION,
    "livePermissionBlocked": ErrorBehavior.OPERATION,
    "insufficientLivePermissions": ErrorBehavior.OPERATION,
    "authError": ErrorBehavior.CHANNEL,
    "insufficientPermissions": ErrorBehavior.CHANNEL,
    "channelClosed": ErrorBehavior.CHANNEL,
    "channelSuspended": ErrorBehavior.CHANNEL,
    "authenticatedUserAccountClosed": ErrorBehavior.CHANNEL,
    "authenticatedUserAccountSuspended": ErrorBehavior.CHANNEL,
    "authenticatedUserNotChannel": ErrorBehavior.CHANNEL,
    PlatformCode.AUTH_FAILED.value: ErrorBehavior.CHANNEL,       # после отказа входа браузер повторно не открывается
    PlatformCode.LOGIN_REQUIRED.value: ErrorBehavior.CALL,       # вход запретил вызывающий: обычный вызов потом войдёт
    "quotaExceeded": ErrorBehavior.PROJECT,
    "invalidImage": ErrorBehavior.CALL,
    "mediaBodyRequired": ErrorBehavior.CALL,
    "videoNotFound": ErrorBehavior.CALL,
    PlatformCode.BAD_RESPONSE.value: ErrorBehavior.CALL,
    PlatformCode.UNEXPECTED_STREAM_KEY.value: ErrorBehavior.CALL,
    PlatformCode.CHANNEL_NOT_FOUND.value: ErrorBehavior.CALL,    # совпадает с причиной Google channelNotFound
    PlatformCode.NOT_LISTED.value: ErrorBehavior.RETRY,          # пустое чтение по id: площадка отстаёт после записи
    PlatformCode.TRANSPORT_FAILED.value: ErrorBehavior.RETRY,    # обрыв связи: ответа нет вовсе
}
# Пара (операция, причина) главнее причины: forbidden у обложки — канал не подтверждён, у прочих — разовый отказ.
# Таблица пар спрашивается раньше правила создающих вызовов: пары с liveBroadcasts.insert и liveStreams.insert сюда не
# добавлять — иначе защита от повтора создающего вызова молча отключится.
OPERATION_REASON_BEHAVIORS: Final[dict[tuple[YouTubeOperation, str], ErrorBehavior]] = {
    (YouTubeOperation.THUMBNAILS_SET, "forbidden"): ErrorBehavior.OPERATION,
}
