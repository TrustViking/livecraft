"""Сбой площадки — единственное исключение, которое площадка выпускает наружу (CLAUDE.md §6 инвариант 9, §11).

`PlatformError.code` — причина отказа Google (`errors[0].reason`: liveStreamingNotEnabled, quotaExceeded…) или свой код
программы (`PlatformCode`): что делать с отказом, решает таблица поведений по этому коду. `message` — английская
подробность только для лога; текст для человека — `human` из каталога `msg` по коду, неизвестный код — общий текст с
кодом. Контракт ошибок §11: `str(error) == error.human`.
"""
from __future__ import annotations

from enum import Enum

from app.google.auth import AuthError, AuthErrorReason
from app.observability.log_event import LogEvent, Quoted
from app.ui.messages import msg


class PlatformCode(str, Enum):
    """Коды отказов, которые программа называет сама: ответа Google с причиной за ними нет."""

    CHANNEL_NOT_FOUND = "channelNotFound"    # channels.list(mine=true) пуст: у аккаунта нет канала
    NOT_LISTED = "notListed"                 # чтение по id пусто и после повторов: площадка отстаёт после записи
    AUTH_FAILED = "authFailed"               # вход в канал не удался
    LOGIN_REQUIRED = "loginRequired"         # нужен вход в браузере, а вызывающий его запретил
    TRANSPORT_FAILED = "transportFailed"     # сеть или 5xx: ответа нет или исход неизвестен
    BAD_RESPONSE = "badResponse"             # ответ не того вида
    UNEXPECTED_STREAM_KEY = "unexpectedStreamKeyFormat"   # ключ созданного потока не того вида
    UNKNOWN = "unknown"                      # Google отказал, не назвав причины


class PlatformDetail(str, Enum):
    """Английская подробность отказа — только в лог."""

    CHANNEL_EMPTY = "channels.list(mine=true) is empty for {channel}"
    NOT_LISTED = "{operation} is empty for {object_id} after {attempts} attempts"
    NOT_OBJECT = "{key} is not an object"
    NOT_LIST = "{key} is not a list"
    BAD_VALUE = "{key}={value!r}"
    NOT_MAPPING = "{operation} returned {kind}"
    TRANSPORT = "{operation} on {channel}: {error}"
    HTTP = "HTTP {status}: {detail}"
    AUTH = "{reason}: {detail}"
    CHANNEL_REFUSED = "channels.json {handle}, YouTube {youtube_handle} {youtube_channel_id}"

    def text(self, **values: object) -> str:
        return self.value.format(**values)


class PlatformEvent(str, Enum):
    FAILED = "platform_failed"


class PlatformError(Exception):
    """Отказ площадки: код (причина Google или `PlatformCode`) и подробность для лога.

    `login_reason` — причина отказа входа в канал (`AuthErrorReason`), если отказ — вход: по ней решают, был ли это
    таймаут, и говорят человеку, почему вход не удался. Ставит её только отказ входа (`of_login`).
    """

    def __init__(self, code: str, message: str, login_reason: AuthErrorReason | None = None) -> None:
        self.code: str = code.value if isinstance(code, PlatformCode) else code
        self.message: str = message
        self.login_reason: AuthErrorReason | None = login_reason
        super().__init__(self.human)

    @classmethod
    def of_login(cls, error: AuthError, code: PlatformCode) -> PlatformError:
        """Отказ входа в канал: причина входа — полем, её подробность — в лог."""
        return cls(code, PlatformDetail.AUTH.text(reason=error.reason.value, detail=error.detail), error.reason)

    @property
    def human(self) -> str:
        """Что случилось — для человека: у отказа входа — его причина; иначе текст причины из каталога; причины нет в
        каталоге — общий текст с кодом."""
        if self.login_reason is not None:
            return self.login_reason.human
        known: str | None = msg.YOUTUBE_REASON_TEXT.get(self.code)
        return known if known is not None else msg.YOUTUBE_REASON_UNKNOWN.format(code=self.code)

    @property
    def log_line(self) -> str:
        return LogEvent.of(PlatformEvent.FAILED, code=self.code, message=Quoted(self.message)).text

    def __str__(self) -> str:
        return self.human
