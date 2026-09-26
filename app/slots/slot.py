"""Слот эфира — единственный объект, пересекающий границу контуров (CLAUDE.md §4).

`SlotKey` — чем слот отличается от другого: момент старта в зоне программы и язык; отсюда `slot_id`
`{DD-MM-YYYY}_{HHMM}_{язык}` — правило самого ключа — и порядок слотов (`sort_key`).
`StreamSlot` — ключ, окончательные тексты, обложки и источники; поля схемы §4 — его свойства. Слот сам строит свою
запись схемы — ту, что читает пакет plan_*.bcast (`SlotRecordKey` — ключи записи в порядке схемы).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar, Final

from app.core.dates import ISO_TIMESPEC, SLOT_TIME_FORMAT, format_date, format_time
from app.slots.preview import Preview
from app.slots.texts import SlotProblem, SlotTextOrigin, SlotTexts

SLOT_ID_TEMPLATE: Final[str] = "{date}_{time}_{language}"


class SlotRecordKey(str, Enum):
    """Ключи записи слота схемы §4 в порядке схемы."""

    SLOT_ID = "slot_id"
    DATE = "date"
    TIME = "time"
    START = "start"
    LANGUAGE = "language"
    TITLE = "title"
    DESCRIPTION = "description"
    PREVIEWS = "previews"
    SOURCES = "sources"


@dataclass(frozen=True)
class SlotKey:
    """Ключ слота: момент старта в зоне программы и код языка."""

    LANGUAGE_PRIORITY: ClassVar[dict[str, int]] = {"uk": 0, "en": 1}
    OTHER_LANGUAGE_PRIORITY: ClassVar[int] = 2

    start: datetime
    language: str

    @property
    def date_text(self) -> str:
        """Дата старта DD-MM-YYYY по местному времени (§6 инвариант 4)."""
        return format_date(self.start.date())

    @property
    def time_text(self) -> str:
        """Время старта HH:MM по местному времени."""
        return format_time(self.start.time())

    @property
    def slot_id(self) -> str:
        """`{DD-MM-YYYY}_{HHMM}_{язык}` по местному времени старта (§4)."""
        return SLOT_ID_TEMPLATE.format(
            date=self.date_text, time=self.start.strftime(SLOT_TIME_FORMAT), language=self.language
        )

    @property
    def sort_key(self) -> tuple[datetime, int, str]:
        """Порядок слотов: момент старта, затем uk, en, прочие языки, затем код языка."""
        code: str = self.language.strip().lower()
        return (self.start, self.LANGUAGE_PRIORITY.get(code, self.OTHER_LANGUAGE_PRIORITY), code)


@dataclass(frozen=True)
class StreamSlot:
    """Один эфир плана: ключ (когда и на каком языке), окончательные тексты, обложки и источники (§4).

    Поля схемы §4 — свойства: они выводятся из ключа и текстов, а не хранятся второй раз.
    """

    key: SlotKey
    texts: SlotTexts
    previews: tuple[Preview, ...]       # обложки источников в порядке рядов; может быть пусто
    sources: tuple[str, ...]            # ссылки watch?v=<id> в порядке рядов

    @property
    def slot_id(self) -> str:
        """{DD-MM-YYYY}_{HHMM}_{lang}."""
        return self.key.slot_id

    @property
    def date(self) -> str:
        """DD-MM-YYYY — для людей и для формы."""
        return self.key.date_text

    @property
    def time(self) -> str:
        """HH:MM — для людей, в форму не уходит."""
        return self.key.time_text

    @property
    def start(self) -> datetime:
        """Момент старта со смещением — для сравнения с YouTube."""
        return self.key.start

    @property
    def language(self) -> str:
        return self.key.language

    @property
    def title(self) -> str:
        """≤100 символов после safe_trim."""
        return self.texts.title

    @property
    def description(self) -> str:
        """≤5000 байт после safe_trim."""
        return self.texts.description

    @property
    def text_origin(self) -> SlotTextOrigin:
        return self.texts.origin

    @property
    def problem(self) -> SlotProblem | None:
        """Почему слот дальше не идёт; None — годен. Правило — у текстов слота."""
        return self.texts.problem

    def to_record(self, preview_names: tuple[str, ...]) -> dict[str, object]:
        """Запись слота схемы §4: `start` — ISO-8601 с секундами, `previews` — имена файлов обложек слота
        в том же порядке, что и обложки. Происхождение текстов в запись не входит.
        """
        values: tuple[object, ...] = (
            self.slot_id,
            self.date,
            self.time,
            self.start.isoformat(timespec=ISO_TIMESPEC),
            self.language,
            self.title,
            self.description,
            list(preview_names),
            list(self.sources),
        )
        return {key.value: value for key, value in zip(SlotRecordKey, values, strict=True)}

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Поля строки лога без названия и описания: они длинные, в строке — только их длины."""
        return dict(
            slot=self.slot_id,
            start=self.start.isoformat(timespec=ISO_TIMESPEC),
            language=self.language,
            sources=len(self.sources),
            previews=len(self.previews),
            texts=self.text_origin,
            title_chars=self.texts.title_chars,
            description_chars=self.texts.description_chars,
            description_bytes=self.texts.description_bytes,
        )
