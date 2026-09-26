"""Тексты слота: название и описание эфира и их подгонка под правила YouTube (CLAUDE.md §3 шаг 2.5, §4).

`SlotTexts` — окончательные тексты одного слота. Без нейросети они собираются из текстов источников (`SourceText`,
`from_sources`), merge даёт свои через тот же объект. Контур B тексты не редактирует (§4), поэтому правила площадки
применяет сам объект (`for_youtube`): YouTube Data API v3 (videos.snippet) принимает название не длиннее
100 символов, описание не длиннее 5000 байт и не принимает символы < и > ни там, ни там.
Обрезка — всегда по границе `safe_trim_right`, а не посреди слова.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Final

from app.core.safe_trim import SafeTrimResult, safe_trim_right
from app.core.text_format import PARAGRAPH_BREAK, TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.SLOTS)

SIZE_CHANGE_TEMPLATE: Final[str] = "{before}->{after}"     # размер до и после подгонки в одном поле лога


class SlotTextOrigin(str, Enum):
    """Откуда тексты слота: из источников без нейросети или из ответа модели на merge (`app\\llm\\merges\\job.py`)."""

    SOURCE_SINGLE = "source_single"          # один источник: его название и описание как есть
    SOURCE_COMPOSED = "source_composed"      # несколько источников: название первого, описания подряд
    MERGED = "merged"                        # одно название и одно описание от модели на весь слот (merge)


class SlotProblem(str, Enum):
    """Почему слот дальше не идёт."""

    EMPTY_TITLE = "empty_title"      # название пустое после подгонки под правила YouTube

    @property
    def human(self) -> str:
        """Русская строка причины; текст — в messages_ru (§11)."""
        return msg.SLOT_PROBLEMS[self.value]


class SlotTextsEvent(str, Enum):
    """События текстов слота в логе."""

    FITTED = "slot_texts_fitted"


@dataclass(frozen=True)
class SourceText:
    """Название и описание одного источника слота; у видео без данных — пустые строки."""

    title: str
    description: str


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
    def from_sources(cls, sources: Sequence[SourceText]) -> SlotTexts:
        """Тексты без нейросети в порядке источников слота: один источник — как есть; несколько — название первого,
        непустые описания через пустую строку.
        """
        origin: SlotTextOrigin = SlotTextOrigin.SOURCE_SINGLE if len(sources) == 1 else SlotTextOrigin.SOURCE_COMPOSED
        return cls(
            title=sources[0].title,
            description=PARAGRAPH_BREAK.join(source.description for source in sources if source.description),
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
            event: LogEvent = LogEvent.of(SlotTextsEvent.FITTED, slot=slot_id, replaced=replacements)
            event = event.extended(title_reason=title.reason, description_reason=description.reason)
            event.extended(**self._size_changes(fitted)).emit(LOGGER)
        return fitted

    @property
    def problem(self) -> SlotProblem | None:
        """Почему с этими текстами эфир не ставится; None — годны. Пустое описание — не проблема."""
        return SlotProblem.EMPTY_TITLE if not self.title.strip() else None

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

    def _size_changes(self, fitted: SlotTexts) -> dict[str, str]:
        """Длины до и после подгонки: символы названия, символы и байты описания."""
        change: str = SIZE_CHANGE_TEMPLATE
        return dict(
            title_chars=change.format(before=self.title_chars, after=fitted.title_chars),
            description_chars=change.format(before=self.description_chars, after=fitted.description_chars),
            description_bytes=change.format(before=self.description_bytes, after=fitted.description_bytes),
        )

    @classmethod
    def _replace_forbidden(cls, text: str) -> str:
        for forbidden, replacement in cls.FORBIDDEN_CHARS.items():
            text = text.replace(forbidden, replacement)
        return text

    @classmethod
    def _forbidden_count(cls, text: str) -> int:
        return sum(text.count(forbidden) for forbidden in cls.FORBIDDEN_CHARS)
