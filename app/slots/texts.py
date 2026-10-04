"""Тексты слота: название и описание эфира и подгонка под правила YouTube (CLAUDE.md §3, §4, §14 решения 30, 32).

`SlotTexts` — окончательные тексты одного слота; откуда они, помнит `SlotTextOrigin`. Какие тексты получит слот,
решает правило «умного merge» (решение 32, `SlotGroup.video_texts`): merge не нужен — тексты видео как есть
(`from_sources`); merge удался — тексты модели через тот же объект; merge нужен и не удался — тексты «по номерам»
(`numbered`): «1) …», «2) …» из названий и описаний видео целиком, без обрезки. Такие тексты — не для YouTube
(`is_for_youtube`): слот с ними идёт в документ и Telegram, но не в пакет.

Контур B тексты не редактирует (§4), поэтому правила площадки применяет сам объект (`for_youtube`): YouTube Data
API v3 (videos.snippet) принимает название не длиннее 100 знаков, описание не длиннее 5000 знаков (решение 30) и не
принимает символы < и > ни там, ни там. Обрезка — всегда по границе `safe_trim_right`: не посреди слова и не посреди
ссылки.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Final

from app.core.safe_trim import SafeTrimResult, safe_trim_right
from app.core.text_format import NEWLINE, PARAGRAPH_BREAK
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SLOTS)

SIZE_CHANGE_TEMPLATE: Final[str] = "{before}->{after}"     # размер до и после подгонки в одном поле лога
NUMBERED_ITEM_TEMPLATE: Final[str] = "{number}) {text}"    # строка текстов «по номерам»: номер видео в слоте и текст


class SlotTextOrigin(str, Enum):
    """Откуда тексты слота: из источников, «по номерам», из ответа модели на merge (`app\\llm\\merges\\job.py`) или из
    пакета (режим Б)."""

    SOURCE_SINGLE = "source_single"          # один источник: его название и описание как есть
    SOURCE_COMPOSED = "source_composed"      # несколько источников, merge не нужен: название первого, описания подряд
    MERGED = "merged"                        # одно название и одно описание от модели на весь слот (merge)
    NUMBERED = "numbered"                    # merge нужен и не удался: «1) … 2) …», не для YouTube (решение 32)
    PACKAGE = "package"                      # из пакета plan_*.bcast (режим Б): в пакет идут только тексты для YouTube


class SlotProblem(str, Enum):
    """Почему слот дальше не идёт."""

    EMPTY_TITLE = "empty_title"      # название пустое после подгонки под правила YouTube

    @property
    def human(self) -> str:
        """Строка причины для человека; текст — в каталоге msg (§11)."""
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
    DESCRIPTION_MAX_CHARS: ClassVar[int] = 5000
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

    @classmethod
    def numbered(cls, sources: Sequence[SourceText]) -> SlotTexts:
        """Тексты «по номерам» (решение 32): названия видео — «1) …» с новой строки, описания — «1) …» через пустую
        строку. Номер — место видео в слоте: видео без описания в перечне описаний нет, но его номер не переходит к
        другому. Тексты целиком, без обрезки: на YouTube они не идут."""
        item: str = NUMBERED_ITEM_TEMPLATE
        titles: list[str] = [item.format(number=number, text=source.title) for number, source in enumerate(sources, 1)]
        descriptions: list[str] = [
            item.format(number=number, text=text)
            for number, source in enumerate(sources, 1)
            if (text := source.description.strip())
        ]
        return cls(
            title=NEWLINE.join(titles),
            description=PARAGRAPH_BREAK.join(descriptions),
            origin=SlotTextOrigin.NUMBERED,
        )

    def for_youtube(self, slot_id: str | None = None) -> SlotTexts:
        """Те же тексты по правилам площадки: замена < и >, название ≤100 знаков, описание ≤5000 знаков.

        `slot_id` — только для строки лога. Любая замена или обрезка — строка `slot_texts_fitted`.
        """
        replacements: int = self._forbidden_count(self.title) + self._forbidden_count(self.description)
        title: SafeTrimResult = safe_trim_right(self._replace_forbidden(self.title), max_length=self.TITLE_MAX_CHARS)
        description: SafeTrimResult = safe_trim_right(
            self._replace_forbidden(self.description), max_length=self.DESCRIPTION_MAX_CHARS
        )
        fitted: SlotTexts = SlotTexts(title=title.text, description=description.text, origin=self.origin)
        if replacements or title.trimmed or description.trimmed:
            event: LogEvent = LogEvent.of(SlotTextsEvent.FITTED, slot=slot_id, replaced=replacements)
            event = event.extended(title_reason=title.reason, description_reason=description.reason)
            event.extended(**self._size_changes(fitted)).emit(LOGGER)
        return fitted

    @property
    def is_for_youtube(self) -> bool:
        """Годятся ли тексты для эфира на YouTube: тексты «по номерам» — нет (решение 32)."""
        return self.origin is not SlotTextOrigin.NUMBERED

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

    def _size_changes(self, fitted: SlotTexts) -> dict[str, str]:
        """Длины до и после подгонки: знаки названия и описания."""
        change: str = SIZE_CHANGE_TEMPLATE
        return dict(
            title_chars=change.format(before=self.title_chars, after=fitted.title_chars),
            description_chars=change.format(before=self.description_chars, after=fitted.description_chars),
        )

    @classmethod
    def _replace_forbidden(cls, text: str) -> str:
        for forbidden, replacement in cls.FORBIDDEN_CHARS.items():
            text = text.replace(forbidden, replacement)
        return text

    @classmethod
    def _forbidden_count(cls, text: str) -> int:
        return sum(text.count(forbidden) for forbidden in cls.FORBIDDEN_CHARS)
