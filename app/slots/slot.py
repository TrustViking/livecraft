"""Слот эфира — единственный объект, пересекающий границу контуров (CLAUDE.md §4).

`SlotKey` — чем слот отличается от другого: момент старта в зоне программы и язык; отсюда `slot_id`
`{DD-MM-YYYY}_{HHMM}_{язык}` — правило самого ключа — и порядок слотов (`sort_key`).
`StreamSlot` несёт ровно поля схемы §4 плюс происхождение текстов и сам строит свою запись схемы — ту, что читает
пакет plan_*.bcast (`SlotRecordKey` — ключи записи в порядке схемы).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar, Final

from app.core.dates import ISO_TIMESPEC, SLOT_TIME_FORMAT, format_date, format_time
from app.core.text_format import SPACE, TEXT_ENCODING
from app.observability.log_event import LogField
from app.slots.preview import Preview
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.ui import messages_ru as msg

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
    """Один эфир плана: когда, на каком языке, с какими текстами, обложками и источниками (§4)."""

    slot_id: str                        # {DD-MM-YYYY}_{HHMM}_{lang}
    date: str                           # DD-MM-YYYY — для людей и для формы
    time: str                           # HH:MM — для людей, в форму не уходит
    start: datetime                     # момент старта со смещением — для сравнения с YouTube
    language: str
    title: str                          # ≤100 символов после safe_trim
    description: str                    # ≤5000 байт после safe_trim
    previews: tuple[Preview, ...]       # обложки источников в порядке рядов; может быть пусто
    sources: tuple[str, ...]            # ссылки watch?v=<id> в порядке рядов; ссылка без id — как есть
    text_origin: SlotTextOrigin

    @classmethod
    def of(
        cls, key: SlotKey, texts: SlotTexts, previews: tuple[Preview, ...], sources: tuple[str, ...]
    ) -> StreamSlot:
        """Слот из ключа, окончательных текстов, обложек и ссылок источников — в том порядке, в каком их дали."""
        return cls(
            slot_id=key.slot_id,
            date=key.date_text,
            time=key.time_text,
            start=key.start,
            language=key.language,
            title=texts.title,
            description=texts.description,
            previews=previews,
            sources=sources,
            text_origin=texts.origin,
        )

    @property
    def problem(self) -> str | None:
        """Почему слот дальше не идёт; None — годен. Пустое описание — не проблема."""
        if not self.title.strip():
            return msg.SLOT_EMPTY_TITLE
        return None

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
            title_chars=len(self.title),
            description_chars=len(self.description),
            description_bytes=len(self.description.encode(TEXT_ENCODING)),
        )

    @property
    def log_line(self) -> str:
        """Сводка key=value для строк лога других объектов о слоте."""
        return SPACE.join(LogField(name, value).text for name, value in self.log_fields.items())
