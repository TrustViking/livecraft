"""Спека эфира — единственное место, задающее «одинаковый» (CLAUDE.md §4, §6 инвариант 1).

Сравнение идёт между двумя `BroadcastSpec` — «как должно быть» (`from_slot`) и «как есть» (`from_platform`,
`from_facts`), — поэтому тексты обеих сторон проходят одно правило (`SpecTexts.fitted`): нормализация и безопасная
обрезка по пределам площадки. Иначе длинное название правилось бы на каждом запуске. Сверяется всё, что программа
диктует площадке (`ChangedField`); время старта сюда не входит — по нему эфир опознают. Спека живёт в площадке, а не
в `pipeline`: в цепочке 6B площадка стоит раньше плана, и тело эфира строится из спеки.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final

from app.config.channel import ChannelConfig
from app.config.settings import LivecraftSettings
from app.core.dates import ISO_TIMESPEC, to_minute
from app.core.safe_trim import safe_trim_right
from app.core.text_format import NEWLINE
from app.observability.log_event import LogEvent, Quoted
from app.platforms.broadcast import BroadcastFacts, UpcomingBroadcast
from app.platforms.limits import PlatformLimits
from app.platforms.stream import StreamInfo
from app.slots.slot import StreamSlot

EMPTY_MARKER: Final[str] = ""
LOG_DESCRIPTION_HEAD_CHARS: Final[int] = 80   # описание в строке лога — только начало


class LineBreak(str, Enum):
    """Переводы строк, которые описание приводит к `NEWLINE`."""

    CRLF = "\r\n"
    CR = "\r"


class ChangedField(str, Enum):
    """Поля спеки, которые программа диктует площадке. Время старта сюда не входит: по нему эфир опознают."""

    TITLE = "title"
    DESCRIPTION = "description"
    CATEGORY = "category"
    PRIVACY = "privacy"
    MARKER = "marker"
    THUMBNAIL = "thumbnail"
    AUTO_START = "auto_start"
    AUTO_STOP = "auto_stop"
    LATENCY = "latency"


# Поле спеки для каждого сверяемого поля: diff, лог и отчёт идут по одному списку.
SPEC_ATTRIBUTES: Final[dict[ChangedField, str]] = {
    ChangedField.TITLE: "title",
    ChangedField.DESCRIPTION: "description",
    ChangedField.CATEGORY: "category_id",
    ChangedField.PRIVACY: "privacy",
    ChangedField.MARKER: "marker",
    ChangedField.THUMBNAIL: "has_own_thumbnail",
    ChangedField.AUTO_START: "auto_start",
    ChangedField.AUTO_STOP: "auto_stop",
    ChangedField.LATENCY: "latency_preference",
}

SpecValue = str | bool | None


@dataclass(frozen=True)
class SpecTexts:
    """Название и описание эфира до правила спеки."""

    title: str
    description: str

    def fitted(self, limits: PlatformLimits) -> SpecTexts:
        """Одно правило для обеих сторон сверки: у названия сняты края; в описании переводы строк — LF, хвостовые
        пробелы строк и края сняты; затем безопасная обрезка по пределам площадки."""
        return SpecTexts(
            title=safe_trim_right(self.title.strip(), max_length=limits.title_max_chars).text,
            description=safe_trim_right(self._normalized_description, max_length=limits.description_max_chars).text,
        )

    @property
    def _normalized_description(self) -> str:
        unified: str = self.description.replace(LineBreak.CRLF.value, NEWLINE).replace(LineBreak.CR.value, NEWLINE)
        return NEWLINE.join(line.rstrip() for line in unified.split(NEWLINE)).strip()


@dataclass(frozen=True)
class BroadcastSpec:
    """Как эфир должен выглядеть или как он выглядит.

    None у поля «как есть» — площадка это поле не вернула: сравнивать не с чем, расхождением это не считается (так
    YouTube ведёт себя с категорией в списке эфиров — её держит ресурс videos).
    """

    start_minute: datetime   # aware UTC, секунды обнулены
    marker: str              # slot_id в названии привязанного потока
    title: str
    description: str
    privacy: str | None = None             # status.privacyStatus
    category_id: str | None = None         # snippet.categoryId
    auto_start: bool | None = None         # contentDetails.enableAutoStart
    auto_stop: bool | None = None          # contentDetails.enableAutoStop
    latency_preference: str | None = None  # contentDetails.latencyPreference
    # своя обложка: картинка эфира не совпадает с заглушкой канала; None — не сверяется
    has_own_thumbnail: bool | None = None

    @classmethod
    def from_slot(
        cls, slot: StreamSlot, limits: PlatformLimits, channel: ChannelConfig, settings: LivecraftSettings
    ) -> BroadcastSpec:
        """Всё, что программа отправляет площадке: тексты — из слота, видимость — из канала, категория, автостарт и
        обложка — из livecraft.json, автостоп и задержка — от площадки (§6 инвариант 7)."""
        texts: SpecTexts = SpecTexts(slot.title, slot.description).fitted(limits)
        return cls(
            start_minute=to_minute(slot.start),
            marker=slot.slot_id,
            title=texts.title,
            description=texts.description,
            privacy=channel.privacy.value,
            category_id=settings.category_id,
            auto_start=settings.auto_start,
            auto_stop=limits.auto_stop,
            latency_preference=limits.latency_preference,
            # обложку программа ставит, только если так велит livecraft.json и у слота есть превью
            has_own_thumbnail=True if settings.set_thumbnail and slot.previews else None,
        )

    @classmethod
    def from_platform(
        cls,
        broadcast: UpcomingBroadcast,
        stream: StreamInfo | None,
        limits: PlatformLimits,
        placeholders: frozenset[str] = frozenset(),
    ) -> BroadcastSpec:
        """placeholders — отпечатки заглушек канала: картинка эфира из них — обложки нет."""
        texts: SpecTexts = SpecTexts(broadcast.title, broadcast.description).fitted(limits)
        has_own_thumbnail: bool | None = (
            None if broadcast.thumbnail_sha is None else broadcast.thumbnail_sha not in placeholders
        )
        return cls(
            start_minute=to_minute(broadcast.start_utc),
            marker=stream.title if stream is not None else EMPTY_MARKER,
            title=texts.title,
            description=texts.description,
            privacy=broadcast.privacy_status,
            category_id=broadcast.category_id,
            auto_start=broadcast.auto_start,
            auto_stop=broadcast.auto_stop,
            latency_preference=broadcast.latency_preference,
            has_own_thumbnail=has_own_thumbnail,
        )

    @classmethod
    def from_facts(cls, facts: BroadcastFacts, limits: PlatformLimits, start_minute: datetime) -> BroadcastSpec:
        """Факты после действий в той же форме; start_minute — если площадка времени не вернула.

        Обложка здесь не сверяется: картинка сразу после записи может ещё не смениться — её сверяет список эфиров
        следующего запуска.
        """
        texts: SpecTexts = SpecTexts(facts.title, facts.description).fitted(limits)
        return cls(
            start_minute=to_minute(facts.start_utc) if facts.start_utc is not None else start_minute,
            marker=facts.stream_marker or EMPTY_MARKER,
            title=texts.title,
            description=texts.description,
            privacy=facts.privacy_status,
            category_id=facts.category_id,
            auto_start=facts.auto_start,
            auto_stop=facts.auto_stop,
            latency_preference=facts.latency_preference,
        )

    def logged(self, event: LogEvent) -> LogEvent:
        """Та же строка лога со спекой в конце — одно правило на «как должно быть» и «как есть» (broadcast_expected и
        broadcast_found): тексты — длиной и в кавычках, описание — началом."""
        return event.extended(
            start=self.start_minute.isoformat(timespec=ISO_TIMESPEC),
            marker=self.marker,
            title=Quoted(self.title),
            title_len=len(self.title),
            description_len=len(self.description),
            description_head=Quoted(self.description[:LOG_DESCRIPTION_HEAD_CHARS]),
            privacy=self.privacy,
            category_id=self.category_id,
            auto_start=self.auto_start,
            auto_stop=self.auto_stop,
            latency=self.latency_preference,
            has_own_thumbnail=self.has_own_thumbnail,
        )

    def value(self, changed: ChangedField) -> SpecValue:
        return getattr(self, SPEC_ATTRIBUTES[changed])

    def diff(self, other: BroadcastSpec) -> tuple[ChangedField, ...]:
        """Все диктуемые поля, метка тоже; по времени эфир опознают, а не исправляют. Поле, которое одна из сторон
        не вернула (None), сравнивать не с чем."""
        return tuple(
            candidate
            for candidate in ChangedField
            if None not in (self.value(candidate), other.value(candidate))
            and self.value(candidate) != other.value(candidate)
        )

    def not_compared(self, other: BroadcastSpec) -> tuple[ChangedField, ...]:
        """Поля, по которым diff промолчал: одна из сторон — None. Пропажа поля не должна быть беззвучной."""
        return tuple(
            candidate
            for candidate in ChangedField
            if self.value(candidate) is None or other.value(candidate) is None
        )
