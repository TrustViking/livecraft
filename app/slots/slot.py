"""Слот эфира — единственный объект, пересекающий границу контуров (CLAUDE.md §4).

`SlotKey` — чем слот отличается от другого: момент старта в зоне программы и язык; отсюда `slot_id`
`{DD-MM-YYYY}_{HHMM}_{язык}` — правило самого ключа, и обратно: ключ по `slot_id` (`parse`), — порядок слотов (`sort_key`) и дата для людей `DD.MM.YYYY`
(`human_date`, §14 решение 31).
`StreamSlot` — ключ, окончательные тексты, обложки и источники; поля схемы §4 — его свойства. Слот сам строит свою
запись схемы — ту, что читает пакет plan_*.bcast (`SlotRecordKey` — ключи записи в порядке схемы), и имена файлов
своих обложек (`preview_file_names`) — для пакета и Telegram. В пакет и на YouTube
идёт только слот для YouTube (`is_for_youtube`): слот с текстами «по номерам» — нет (§14 решение 32).
`SlotEntry` — та же запись, разобранная обратно (режим Б, §14 решение 18): поле записи читает `RecordValues`,
негодное поле — `SlotRecordError`; слот из записи получает обложки отдельно (`SlotEntry.slot`).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from enum import Enum
from typing import ClassVar, Final

from app.core.alphabet import LATIN_LOWER
from app.core.dates import (
    DATE_FORMAT,
    ISO_TIMESPEC,
    SLOT_TIME_FORMAT,
    format_date,
    format_human_date,
    format_time,
    parse_iso_start,
)
from app.observability.log_event import Quoted
from app.slots.preview import PREVIEW_FILE_TEMPLATE, Preview
from app.slots.texts import SlotProblem, SlotTextOrigin, SlotTexts

SLOT_ID_TEMPLATE: Final[str] = "{date}_{time}_{language}"
RECORD_ERROR_TEMPLATE: Final[str] = "{key}: {fault} {value!r}"     # SlotRecordError — только для трассировки
DESCRIPTION_HEAD_CHARS: Final[int] = 120    # начало описания в строке лога слота
# Вид `slot_id`: дата DD-MM-YYYY, время HHMM, код языка строчной латиницей; группы — дата, время, язык.
SLOT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(rf"(\d{{2}}-\d{{2}}-\d{{4}})_(\d{{4}})_([{LATIN_LOWER}]+)")


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


class RecordFault(str, Enum):
    """Что не так с полем записи слота."""

    MISSING = "missing"          # поля нет
    BAD_VALUE = "bad_value"      # значение не того вида или не сходится с другими полями записи


class SlotRecordError(ValueError):
    """Поле записи слота не годится: какое, что с ним и его значение. До человека не доходит: читатель пакета
    превращает её в отказ пакета с путём поля (app\\packages\\)."""

    def __init__(self, key: SlotRecordKey, fault: RecordFault, value: object) -> None:
        self.key: SlotRecordKey = key
        self.fault: RecordFault = fault
        self.value: object = value
        super().__init__(RECORD_ERROR_TEMPLATE.format(key=key.value, fault=fault.value, value=value))


@dataclass(frozen=True)
class RecordValues:
    """Запись слота, как её дал разбор JSON: поле одного вида читается одним правилом, негодное — SlotRecordError."""

    record: Mapping[str, object]

    def value(self, key: SlotRecordKey) -> object:
        if key.value not in self.record:
            raise SlotRecordError(key, RecordFault.MISSING, None)
        return self.record[key.value]

    def text(self, key: SlotRecordKey) -> str:
        """Непустая строка."""
        value: object = self.value(key)
        if not isinstance(value, str) or not value.strip():
            raise SlotRecordError(key, RecordFault.BAD_VALUE, value)
        return value

    def string(self, key: SlotRecordKey) -> str:
        """Строка, которая может быть пустой (описание эфира)."""
        value: object = self.value(key)
        if not isinstance(value, str):
            raise SlotRecordError(key, RecordFault.BAD_VALUE, value)
        return value

    def names(self, key: SlotRecordKey) -> tuple[str, ...]:
        """Список непустых строк; пустой список годен."""
        value: object = self.value(key)
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise SlotRecordError(key, RecordFault.BAD_VALUE, value)
        return tuple(str(item) for item in value)

    def start(self, zone: tzinfo) -> datetime:
        """Момент старта: ISO-8601 со смещением → в зоне программы."""
        text: str = self.text(SlotRecordKey.START)
        try:
            return parse_iso_start(text).astimezone(zone)
        except ValueError as error:
            raise SlotRecordError(SlotRecordKey.START, RecordFault.BAD_VALUE, text) from error

    def expect(self, key: SlotRecordKey, expected: str) -> None:
        """Поле сходится с ключом слота; иначе — негодное значение."""
        found: str = self.text(key)
        if found != expected:
            raise SlotRecordError(key, RecordFault.BAD_VALUE, found)


@dataclass(frozen=True)
class SlotKey:
    """Ключ слота: момент старта в зоне программы и код языка."""

    LANGUAGE_PRIORITY: ClassVar[dict[str, int]] = {"uk": 0, "en": 1}
    OTHER_LANGUAGE_PRIORITY: ClassVar[int] = 2

    start: datetime
    language: str

    @classmethod
    def parse(cls, text: str, zone: tzinfo) -> SlotKey | None:
        """Ключ по `slot_id` в зоне программы — так метка программы в названии потока снова становится слотом.

        Не тот вид или ключ, собранный обратно, даёт другой `slot_id` (99-99-2027, 7-03-2027) — None: это не метка
        программы.
        """
        found: re.Match[str] | None = SLOT_ID_PATTERN.fullmatch(text)
        if found is None:
            return None
        date_text, time_text, language = found.groups()
        try:
            start: datetime = datetime.strptime(date_text + time_text, DATE_FORMAT + SLOT_TIME_FORMAT)
        except ValueError:
            return None
        key: SlotKey = cls(start.replace(tzinfo=zone), language)
        return key if key.slot_id == text else None

    @property
    def date_text(self) -> str:
        """Дата старта DD-MM-YYYY по местному времени (§6 инвариант 4)."""
        return format_date(self.start.date())

    @property
    def human_date(self) -> str:
        """Дата старта DD.MM.YYYY по местному времени — для текстов людям (§14 решение 31)."""
        return format_human_date(self.start.date())

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
        """DD-MM-YYYY — `slot_id`, пакет и группировка по датам."""
        return self.key.date_text

    @property
    def human_date(self) -> str:
        """DD.MM.YYYY — для текстов людям."""
        return self.key.human_date

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
        """≤5000 знаков после safe_trim; у текстов «по номерам» — целиком."""
        return self.texts.description

    @property
    def text_origin(self) -> SlotTextOrigin:
        return self.texts.origin

    @property
    def is_for_youtube(self) -> bool:
        """Идёт ли слот в пакет и на YouTube; правило — у текстов слота (§14 решение 32)."""
        return self.texts.is_for_youtube

    @property
    def problem(self) -> SlotProblem | None:
        """Почему слот дальше не идёт; None — годен. Правило — у текстов слота."""
        return self.texts.problem

    @property
    def preview_file_names(self) -> tuple[str, ...]:
        """Имена файлов обложек «{slot_id}_{номер}.jpg», номер с 1 в порядке обложек: одно правило для пакета и
        Telegram."""
        return tuple(
            PREVIEW_FILE_TEMPLATE.format(slot_id=self.slot_id, index=index)
            for index, _ in enumerate(self.previews, start=1)
        )

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
        """Поля строки лога (§14 решение 38): ссылки источников, происхождение и длины текстов, название целиком и
        начало описания — `DESCRIPTION_HEAD_CHARS` знаков."""
        return dict(
            slot=self.slot_id,
            start=self.start.isoformat(timespec=ISO_TIMESPEC),
            language=self.language,
            sources=len(self.sources),
            links=self.sources,
            previews=len(self.previews),
            texts=self.text_origin,
            title_chars=self.texts.title_chars,
            description_chars=self.texts.description_chars,
            title=Quoted(self.title),
            description_head=Quoted(self.description[:DESCRIPTION_HEAD_CHARS]),
        )


@dataclass(frozen=True)
class SlotEntry:
    """Запись слота из пакета plan_*.bcast, разобранная обратно (`StreamSlot.to_record` наоборот): ключ, тексты, пути
    обложек в архиве и источники. Сами обложки — отдельно (`slot`): их читают только у будущих слотов, прошедшему
    слоту они не нужны.
    """

    key: SlotKey
    texts: SlotTexts
    preview_names: tuple[str, ...]
    sources: tuple[str, ...]

    @classmethod
    def of_record(cls, record: Mapping[str, object], zone: tzinfo) -> SlotEntry:
        """Ключ — по `start` в зоне программы и языку; `slot_id`, дата и время записи должны с ним сходиться: иначе
        метка эфира на площадке разошлась бы со слотом. Негодное поле — SlotRecordError."""
        values: RecordValues = RecordValues(record)
        for key in (SlotRecordKey.DATE, SlotRecordKey.TIME, SlotRecordKey.SLOT_ID):
            values.text(key)
        slot_key: SlotKey = SlotKey(values.start(zone), values.text(SlotRecordKey.LANGUAGE))
        values.expect(SlotRecordKey.SLOT_ID, slot_key.slot_id)
        values.expect(SlotRecordKey.DATE, slot_key.date_text)
        values.expect(SlotRecordKey.TIME, slot_key.time_text)
        title: str = values.text(SlotRecordKey.TITLE)
        texts: SlotTexts = SlotTexts(title, values.string(SlotRecordKey.DESCRIPTION), SlotTextOrigin.PACKAGE)
        return cls(slot_key, texts, values.names(SlotRecordKey.PREVIEWS), values.names(SlotRecordKey.SOURCES))

    @property
    def slot_id(self) -> str:
        return self.key.slot_id

    @property
    def start(self) -> datetime:
        return self.key.start

    @property
    def language(self) -> str:
        return self.key.language

    @property
    def title(self) -> str:
        return self.texts.title

    def slot(self, previews: tuple[Preview, ...]) -> StreamSlot:
        """Слот с обложками из архива в порядке записи."""
        return StreamSlot(self.key, self.texts, previews, self.sources)
