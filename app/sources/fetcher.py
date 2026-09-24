"""Получение данных источника: причина отказа, итог одного обращения, интерфейс получателя (CLAUDE.md §2).

`MetadataFetcher` — Protocol, которого §2 требует от получателя метаданных: боевой — `YtDlpFetcher`
(app\\sources\\ytdlp.py), в тестах — подделка с тем же `fetch`. Отказ — обычный исход, а не исключение:
`SourceFetch` несёт причину, и один отказ не останавливает остальные источники (§6 инвариант 9).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol

from app.sources.metadata import SourceMetadata
from app.ui import messages_ru as msg

NO_DETAIL: Final[str] = "-"


class SourceFailureReason(str, Enum):
    """Почему данных источника нет или они не годятся."""

    TOOL_MISSING = "tool_missing"    # нет tools\yt-dlp.exe — yt-dlp не вызывался
    PRIVATE = "private"              # приватное видео или нужен вход через cookies
    UNAVAILABLE = "unavailable"      # удалено или заблокировано
    TIMEOUT = "timeout"              # yt-dlp не уложился в своё время
    BAD_OUTPUT = "bad_output"        # ответ yt-dlp — не объект JSON
    NO_TITLE = "no_title"            # ответ разобран, но названия нет
    FAILED = "failed"                # прочий отказ yt-dlp
    NO_LANGUAGE = "no_language"      # язык видео не определился; yt-dlp эту причину не выдаёт — её ставит SourceVideo

    @property
    def human(self) -> str:
        """Русская строка причины; текст — в messages_ru (§11)."""
        return msg.SOURCE_FAILURE_REASONS[self.value]


@dataclass(frozen=True)
class SourceFetch:
    """Итог одного обращения за данными источника.

    `metadata` есть и у удачного итога, и у отказа NO_TITLE (объект построен, но не годен — §0);
    `detail` — короткая подробность для лога (первая строка stderr, имя исключения), не для человека.
    """

    url: str
    metadata: SourceMetadata | None
    failure: SourceFailureReason | None
    detail: str = NO_DETAIL

    @classmethod
    def from_metadata(cls, url: str, metadata: SourceMetadata) -> SourceFetch:
        """Разобранный ответ: годен, если у объекта нет проблемы; без названия — отказ NO_TITLE."""
        if metadata.problem is not None:
            return cls(url=url, metadata=metadata, failure=SourceFailureReason.NO_TITLE)
        return cls(url=url, metadata=metadata, failure=None)

    @classmethod
    def failed(cls, url: str, reason: SourceFailureReason, detail: str = NO_DETAIL) -> SourceFetch:
        return cls(url=url, metadata=None, failure=reason, detail=detail or NO_DETAIL)

    @property
    def is_ok(self) -> bool:
        return self.failure is None and self.metadata is not None

    @property
    def log_line(self) -> str:
        """`ok` и сводка метаданных либо `reason=… detail=…`."""
        if self.is_ok and self.metadata is not None:
            return f"ok {self.metadata.log_line}"
        reason: str = self.failure.value if self.failure is not None else NO_DETAIL
        return f"reason={reason} detail={self.detail!r}"


class MetadataFetcher(Protocol):
    """Получатель данных источника: одна ссылка — один итог, отказ — итогом, а не исключением."""

    def fetch(self, url: str) -> SourceFetch: ...
