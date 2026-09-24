"""Тексты слота: название и описание эфира и их подгонка под правила YouTube (CLAUDE.md §3 шаг 2.5, §4).

`SlotTexts` — окончательные тексты одного слота. Без LLM они берутся из источников (`from_sources`), merge
позже подставит свои через тот же объект. Контур B тексты не редактирует (§4), поэтому правила площадки
применяет сам объект (`for_youtube`): YouTube Data API v3 (videos.snippet) принимает название не длиннее
100 символов, описание не длиннее 5000 байт и не принимает символы < и > ни там, ни там.
Обрезка — всегда по границе `safe_trim_right`, а не посреди слова.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Final

from app.core.safe_trim import SafeTrimResult, safe_trim_right
from app.observability.logging_setup import get_logger
from app.ui import messages_ru as msg

if TYPE_CHECKING:      # только для аннотаций: тексты берут у источника название и описание
    from app.sources.video import SourceVideo

LOGGER_NAME: Final[str] = "slots"
LOGGER = get_logger(LOGGER_NAME)

TEXT_ENCODING: Final[str] = "utf-8"
DESCRIPTION_JOINER: Final[str] = "\n\n"      # описания нескольких источников — через пустую строку
NO_SLOT: Final[str] = "-"


class SlotTextOrigin(str, Enum):
    """Откуда тексты слота. `merged` появится вместе с merge (задачи 3.6 и дальше)."""

    SOURCE_SINGLE = "source_single"          # один источник: его название и описание как есть
    SOURCE_COMPOSED = "source_composed"      # несколько источников: название первого, описания подряд


@dataclass(frozen=True)
class SlotTexts:
    """Название и описание эфира одного слота и откуда они взялись."""

    TITLE_MAX_CHARS: ClassVar[int] = 100
    DESCRIPTION_MAX_BYTES: ClassVar[int] = 5000
    FORBIDDEN_CHARS: ClassVar[dict[str, str]] = {"<": "‹", ">": "›"}

    title: str
    description: str
    origin: SlotTextOrigin

    @classmethod
    def from_sources(cls, videos: Sequence[SourceVideo]) -> SlotTexts:
        """Тексты без LLM: один источник — как есть; несколько — название первого по номеру ряда,
        непустые описания через пустую строку в порядке рядов. Без источников слота не бывает — ValueError.
        """
        if not videos:
            raise ValueError("slot texts need at least one source video")
        ordered: list[SourceVideo] = sorted(videos, key=lambda video: video.row.row_number)
        titles: list[str] = [video.metadata.title if video.metadata is not None else "" for video in ordered]
        descriptions: list[str] = [
            video.metadata.description for video in ordered if video.metadata is not None
        ]
        origin: SlotTextOrigin = (
            SlotTextOrigin.SOURCE_SINGLE if len(ordered) == 1 else SlotTextOrigin.SOURCE_COMPOSED
        )
        return cls(
            title=titles[0],
            description=DESCRIPTION_JOINER.join(text for text in descriptions if text),
            origin=origin,
        )

    def for_youtube(self, slot_id: str | None = None) -> SlotTexts:
        """Те же тексты по правилам площадки: замена < и >, название ≤100 символов, описание ≤5000 байт.

        `slot_id` — только для строки лога. Любая замена или обрезка — строка `slot_texts_fitted`.
        """
        replacements: int = self._forbidden_count(self.title) + self._forbidden_count(self.description)
        title: SafeTrimResult = safe_trim_right(self._replace_forbidden(self.title), max_length=self.TITLE_MAX_CHARS)
        description: SafeTrimResult = self._fit_description(self._replace_forbidden(self.description))
        fitted: SlotTexts = SlotTexts(title=title.text, description=description.text, origin=self.origin)
        if replacements or title.trimmed or description.trimmed:
            LOGGER.info(
                "slot_texts_fitted slot=%s replaced=%d title_reason=%s description_reason=%s %s",
                slot_id or NO_SLOT, replacements, title.reason, description.reason,
                self._sizes_line(fitted),
            )
        return fitted

    @property
    def problem(self) -> str | None:
        """Почему с этими текстами эфир не ставится; None — годны. Пустое описание — не проблема."""
        if not self.title.strip():
            return msg.SLOT_EMPTY_TITLE
        return None

    @property
    def title_chars(self) -> int:
        return len(self.title)

    @property
    def description_chars(self) -> int:
        return len(self.description)

    @property
    def description_bytes(self) -> int:
        return len(self.description.encode(TEXT_ENCODING))

    def _fit_description(self, text: str) -> SafeTrimResult:
        """Обрезка до DESCRIPTION_MAX_BYTES байт: предел в символах сначала равен пределу в байтах,
        затем, пока байтов больше, уменьшается на избыток и обрезка исходного текста повторяется.
        Предел каждый раз меньше хотя бы на 1, на нуле текст пуст — цикл конечен.
        """
        limit: int = self.DESCRIPTION_MAX_BYTES
        result: SafeTrimResult = safe_trim_right(text, max_length=limit)
        excess: int = len(result.text.encode(TEXT_ENCODING)) - self.DESCRIPTION_MAX_BYTES
        while excess > 0:
            limit -= excess
            result = safe_trim_right(text, max_length=limit)
            excess = len(result.text.encode(TEXT_ENCODING)) - self.DESCRIPTION_MAX_BYTES
        return result

    def _sizes_line(self, fitted: SlotTexts) -> str:
        """Длины до и после подгонки: символы названия, символы и байты описания."""
        return (
            f"title_chars={self.title_chars}->{fitted.title_chars} "
            f"description_chars={self.description_chars}->{fitted.description_chars} "
            f"description_bytes={self.description_bytes}->{fitted.description_bytes}"
        )

    @classmethod
    def _replace_forbidden(cls, text: str) -> str:
        for forbidden, replacement in cls.FORBIDDEN_CHARS.items():
            text = text.replace(forbidden, replacement)
        return text

    @classmethod
    def _forbidden_count(cls, text: str) -> int:
        return sum(text.count(forbidden) for forbidden in cls.FORBIDDEN_CHARS)
