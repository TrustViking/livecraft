"""Слот эфира — единственный объект, пересекающий границу контуров (CLAUDE.md §4).

`SlotKey` — чем слот отличается от другого: момент старта в зоне программы и язык; отсюда `slot_id`
`{DD-MM-YYYY}_{HHMM}_{язык}` (restreamer `planned_video_slot_key`) и порядок слотов (`language_sort_key`).
`StreamSlot` несёт ровно поля схемы §4 плюс происхождение текстов и сам строит свою запись схемы
(restreamer `_build_package_slot`), которую читает planers `_ManifestParser._slot`.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Final
from zoneinfo import ZoneInfo

from app.core.dates import build_slot_id, format_date, format_time
from app.core.sheet_text import extract_youtube_video_id
from app.slots.texts import TEXT_ENCODING, SlotTextOrigin, SlotTexts
from app.ui import messages_ru as msg

if TYPE_CHECKING:      # только для аннотаций: слот берёт у источника ряд, ссылку, язык и обложку
    from app.sources.preview import Preview
    from app.sources.video import SourceVideo

ISO_TIMESPEC: Final[str] = "seconds"
YOUTUBE_WATCH_URL_TEMPLATE: Final[str] = "https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class SlotKey:
    """Ключ слота: момент старта в зоне программы и код языка."""

    LANGUAGE_PRIORITY: ClassVar[dict[str, int]] = {"uk": 0, "en": 1}
    OTHER_LANGUAGE_PRIORITY: ClassVar[int] = 2

    start: datetime
    language: str

    @classmethod
    def of(cls, video: SourceVideo, zone: ZoneInfo) -> SlotKey:
        """Ключ годного источника; у негодного нет момента или языка — ValueError."""
        start: datetime | None = video.row.start
        language: str | None = video.language_code
        if start is None or not language:
            raise ValueError(f"source row {video.row.row_number} has no start or language")
        return cls(start=start.astimezone(zone), language=language)

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
        return build_slot_id(self.date_text, self.time_text, self.language)

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
    sources: tuple[str, ...]            # ссылки https://www.youtube.com/watch?v=<id> в порядке рядов
    text_origin: SlotTextOrigin

    @classmethod
    def of(cls, key: SlotKey, texts: SlotTexts, videos: Sequence[SourceVideo]) -> StreamSlot:
        """Слот из ключа, окончательных текстов и источников; порядок источников — порядок рядов."""
        ordered: list[SourceVideo] = sorted(videos, key=lambda video: video.row.row_number)
        return cls(
            slot_id=key.slot_id,
            date=key.date_text,
            time=key.time_text,
            start=key.start,
            language=key.language,
            title=texts.title,
            description=texts.description,
            previews=tuple(video.preview for video in ordered if video.preview is not None),
            sources=tuple(cls._source_url(video.link) for video in ordered),
            text_origin=texts.origin,
        )

    @staticmethod
    def _source_url(link: str) -> str:
        """Ссылка источника в записи слота: по id видео, если он извлекается; иначе как есть (донор)."""
        video_id: str | None = extract_youtube_video_id(link)
        return YOUTUBE_WATCH_URL_TEMPLATE.format(video_id=video_id) if video_id else link

    @property
    def problem(self) -> str | None:
        """Почему слот дальше не идёт; None — годен. Пустое описание — не проблема."""
        if not self.title.strip():
            return msg.SLOT_EMPTY_TITLE
        return None

    def to_record(self, preview_names: tuple[str, ...]) -> dict[str, object]:
        """Запись слота схемы §4: `start` — ISO-8601 с секундами, `previews` — имена файлов обложек
        по одному на каждую обложку слота в том же порядке. Происхождение текстов в запись не входит.
        """
        if len(preview_names) != len(self.previews):
            raise ValueError(
                f"slot {self.slot_id}: {len(preview_names)} preview names for {len(self.previews)} previews"
            )
        return {
            "slot_id": self.slot_id,
            "date": self.date,
            "time": self.time,
            "start": self.start.isoformat(timespec=ISO_TIMESPEC),
            "language": self.language,
            "title": self.title,
            "description": self.description,
            "previews": list(preview_names),
            "sources": list(self.sources),
        }

    @property
    def log_line(self) -> str:
        """Сводка key=value без названия и описания: они длинные, в строке — только их длины."""
        return (
            f"slot={self.slot_id} start={self.start.isoformat(timespec=ISO_TIMESPEC)} "
            f"language={self.language} sources={len(self.sources)} previews={len(self.previews)} "
            f"texts={self.text_origin.value} title_chars={len(self.title)} "
            f"description_chars={len(self.description)} "
            f"description_bytes={len(self.description.encode(TEXT_ENCODING))}"
        )
