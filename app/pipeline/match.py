"""Что сверка нашла на площадке по одному эфиру и ключ, который объект взял с неё (CLAUDE.md §6 инварианты 1, 1a).

Ключ и адрес потока — только с площадки: у найденного эфира — из его привязанного потока, у эфира, созданного или
получившего поток в этом запуске, — из ответа площадки (`take_new_key`); второй главнее первого. Ссылка на эфир —
по id эфира (`YouTubeVideoId.watch_url`).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Final

from app.core.youtube_video import YouTubeVideoId
from app.pipeline.decision import Decision
from app.pipeline.fixes import FieldFixes
from app.platforms.broadcast import BroadcastFacts, CreatedBroadcast, UpcomingBroadcast
from app.platforms.spec import BroadcastSpec
from app.platforms.stream import StreamInfo

# Решения, при которых эфир на площадке — эфир программы: ему ставятся настройки видео и снимаются факты.
OWN_DECISIONS: Final[frozenset[Decision]] = frozenset({Decision.CREATE, Decision.UPDATE, Decision.MATCH})


@dataclass
class BroadcastMatch:
    """Изменяемый намеренно: сверка и действия заполняют его по шагам.

    `found` и `stream` — опознанный эфир и его поток; `actual` — как эфир выглядит (спека с площадки); `facts` — что
    лежит на площадке после действий; `fixes` — расхождения и их исправление; `ambiguous_urls` — AMBIGUOUS: ссылки на
    все эфиры-кандидаты; `stream_attached` — эфир был без потока, поток привязан этим запуском; `published` — эфир
    создан или поток привязан этим запуском.
    """

    found: UpcomingBroadcast | None = None
    stream: StreamInfo | None = None
    actual: BroadcastSpec | None = None
    facts: BroadcastFacts | None = None
    fixes: FieldFixes = field(default_factory=FieldFixes)
    ambiguous_urls: tuple[str, ...] = ()
    stream_attached: bool = False
    published: CreatedBroadcast | None = None

    @property
    def key(self) -> CreatedBroadcast | None:
        """Эфир, поток, ключ и адрес, какие они сейчас на площадке; потока нет — None."""
        if self.published is not None:
            return self.published
        if self.found is None or self.stream is None:
            return None
        return CreatedBroadcast(
            broadcast_id=self.found.broadcast_id,
            broadcast_url=YouTubeVideoId(self.found.broadcast_id).watch_url,
            stream_id=self.stream.stream_id,
            stream_url=self.stream.ingestion_address,
            stream_key=self.stream.stream_name,
        )

    @property
    def stream_key(self) -> str | None:
        key: CreatedBroadcast | None = self.key
        return None if key is None else key.stream_key

    @property
    def has_full_key(self) -> bool:
        """Ключ и адрес потока есть оба: прочитанный с площадки поток бывает и без них."""
        key: CreatedBroadcast | None = self.key
        return key is not None and bool(key.stream_key) and bool(key.stream_url)

    @property
    def broadcast_id(self) -> str | None:
        """Эфир объекта сейчас: с ключом — эфир ключа, без потока — найденный, иначе None."""
        key: CreatedBroadcast | None = self.key
        if key is not None:
            return key.broadcast_id
        return None if self.found is None else self.found.broadcast_id

    def own_broadcast_id(self, decision: Decision) -> str | None:
        """Эфир, который программа считает своим для настроек видео и снимка фактов: создан, привязан, исправлен или
        совпал. Прочие решения (не допущен, too_late, AMBIGUOUS, ошибка) — не её дело: None."""
        return self.broadcast_id if decision in OWN_DECISIONS else None

    @property
    def found_url(self) -> str | None:
        return None if self.found is None else YouTubeVideoId(self.found.broadcast_id).watch_url

    def take_new_key(self, created: CreatedBroadcast) -> None:
        """Ключ получен в этом запуске: эфир создан или поток привязан."""
        self.published = created

    def apply_recorded_thumbnail(self, recorded_broadcast_id: str | None) -> bool:
        """Память знает, что обложку этому же эфиру ставила программа, — обложка своя, картинка-заглушка не решает.

        True — память переопределила то, что показала картинка. Эфир другой (удалён и создан заново) или записи нет —
        всё по картинке.
        """
        if self.actual is None or self.found is None or recorded_broadcast_id != self.found.broadcast_id:
            return False
        if self.actual.has_own_thumbnail is True:
            return False
        self.actual = replace(self.actual, has_own_thumbnail=True)
        return True
