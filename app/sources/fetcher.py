"""Получение данных источника: итог одного обращения и интерфейс получателя (CLAUDE.md §2).

`MetadataFetcher` — Protocol, которого §2 требует от получателя метаданных: боевой — `YtDlpFetcher`
(app\\sources\\ytdlp.py), в тестах — подделка с тем же `fetch`. Отказ — обычный исход, а не исключение:
`SourceFetch` несёт причину, и один отказ не останавливает остальные источники (§6 инвариант 9).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.observability.log_event import LogValue
from app.sources.metadata import SourceFailureReason, SourceMetadata


@dataclass(frozen=True)
class SourceFetch:
    """Итог одного обращения за данными источника.

    `metadata` есть и у удачного итога, и у отказа NO_TITLE (объект построен, но не годен — §0);
    `detail` — короткая подробность для лога (первая строка stderr, имя исключения), не для человека.
    """

    url: str
    metadata: SourceMetadata | None
    failure: SourceFailureReason | None
    detail: str = LogValue.EMPTY.value

    @classmethod
    def from_metadata(cls, url: str, metadata: SourceMetadata) -> SourceFetch:
        """Разобранный ответ: годен, если у значения нет проблемы; иначе отказ с его причиной."""
        return cls(url=url, metadata=metadata, failure=metadata.problem)

    @classmethod
    def failed(cls, url: str, reason: SourceFailureReason, detail: str = LogValue.EMPTY.value) -> SourceFetch:
        return cls(url=url, metadata=None, failure=reason, detail=detail or LogValue.EMPTY.value)

    @property
    def ready_metadata(self) -> SourceMetadata | None:
        """Данные видео, по которым можно работать: отказа нет. У отказа — None, даже если значение построено."""
        return self.metadata if self.failure is None else None

    @property
    def is_ok(self) -> bool:
        return self.ready_metadata is not None

    @property
    def log_fields(self) -> Mapping[str, object]:
        """`result=ok` и сводка данных видео либо `result=<причина>` и подробность."""
        if self.ready_metadata is not None:
            return dict(result=LogValue.OK, **self.ready_metadata.log_fields)
        return dict(result=self.failure, detail=self.detail)


class MetadataFetcher(Protocol):
    """Получатель данных источника: одна ссылка — один итог, отказ — итогом, а не исключением."""

    def fetch(self, url: str) -> SourceFetch: ...
