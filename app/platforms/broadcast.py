"""Эфир на площадке: запланированный, только что созданный и факты после действий (CLAUDE.md §6 инварианты 1, 7)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UpcomingBroadcast:
    """Запланированный эфир из списка площадки. Ссылки на эфир здесь нет — её строит `YouTubeVideoId.watch_url`."""

    broadcast_id: str
    start_utc: datetime        # aware, UTC
    title: str
    description: str
    stream_id: str | None      # привязанный поток; None — поток не привязан
    live_chat_id: str | None = None   # чат заведён; включением чата API не управляет
    category_id: str | None = None   # snippet.categoryId; None — площадка его в списке эфиров не вернула
    privacy_status: str | None = None       # status.privacyStatus
    auto_start: bool | None = None          # contentDetails.enableAutoStart
    auto_stop: bool | None = None           # contentDetails.enableAutoStop
    latency_preference: str | None = None   # contentDetails.latencyPreference
    thumbnail_sha: str | None = None        # отпечаток картинки размера default (PlaceholderMark.sha); None — не скачали
    published_utc: datetime | None = None   # snippet.publishedAt — когда эфир создан на площадке (aware UTC)


@dataclass(frozen=True)
class CreatedBroadcast:
    """Эфир с привязанным потоком: ключ и адреса — только из ответа площадки (инвариант 1)."""

    broadcast_id: str
    broadcast_url: str
    stream_id: str
    stream_url: str
    stream_key: str


@dataclass(frozen=True)
class BroadcastFacts:
    """Что по факту лежит на площадке после действий программы.

    Язык, аудитория и возрастное ограничение в списке эфиров не приходят: их видно только у ресурса videos с тем же
    id. Без этого разбирать расхождения нечем.
    """

    broadcast_id: str
    title: str
    description: str
    start_utc: datetime | None
    privacy_status: str | None
    made_for_kids: bool | None
    age_restricted: bool          # ytRating == ytAgeRestricted; через API только читается
    default_language: str | None
    default_audio_language: str | None
    category_id: str | None
    bound_stream_id: str | None
    stream_marker: str | None
    live_chat_id: str | None = None
    thumbnail_url: str | None = None
    # у ресурса videos этих полей нет: они из списка эфиров того же эфира
    auto_start: bool | None = None
    auto_stop: bool | None = None
    latency_preference: str | None = None
