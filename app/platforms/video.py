"""Настройки ресурса видео эфира: что программа задаёт, что пришлось поправить и что площадка записала
(CLAUDE.md §6 инвариант 7)."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TypeVar

from app.platforms.broadcast import BroadcastFacts

T = TypeVar("T")


@dataclass(frozen=True)
class VideoSettings:
    """Что программа задаёт ресурсу видео: язык — из слота, категория — из livecraft.json, видимость — из канала.
    Аудитория — всегда «не для детей»."""

    language: str
    category_id: str
    privacy: str


@dataclass(frozen=True)
class AppliedVideo:
    """Что вернул ответ записи ресурса видео: записанные значения глазами самой площадки.

    None в поле — площадка его в ответе не прислала; сравнивать тогда не с чем.
    """

    language: str | None = None
    audio_language: str | None = None
    category_id: str | None = None
    privacy: str | None = None
    made_for_kids: bool | None = None


@dataclass(frozen=True)
class VideoFixes:
    """Что пришлось поправить у ресурса видео: владелец должен знать о расхождении."""

    language_set: bool = False
    category_set: bool = False
    audience_cleared: bool = False
    privacy_set: bool = False
    applied: AppliedVideo | None = None   # ответ записи; None — записи не было

    @property
    def any_fix(self) -> bool:
        return self.language_set or self.category_set or self.audience_cleared or self.privacy_set

    def apply_to_facts(self, facts: BroadcastFacts) -> BroadcastFacts:
        """Поле, записанное этим запуском, — из ответа записи; остальные остаются перечитанными.

        Перечитывание сразу после записи может вернуть ещё старое значение: реплика площадки изменения не увидела
        (planers, 15-09-2026: язык uk записан, videos.list через секунду отдал ru). Ответ записи приходит от узла,
        который её принял, — сравнивать надо с ним. Следующий запуск сверяет то же поле уже без гонки.
        """
        if self.applied is None:
            return facts
        applied: AppliedVideo = self.applied
        return dataclasses.replace(
            facts,
            default_language=self._written(self.language_set, applied.language, facts.default_language),
            default_audio_language=self._written(
                self.language_set, applied.audio_language, facts.default_audio_language
            ),
            category_id=self._written(self.category_set, applied.category_id, facts.category_id),
            privacy_status=self._written(self.privacy_set, applied.privacy, facts.privacy_status),
            made_for_kids=self._written(self.audience_cleared, applied.made_for_kids, facts.made_for_kids),
        )

    def _written(self, is_set: bool, written: T | None, read: T | None) -> T | None:
        """Значение, которое этот запуск записал и площадка вернула; иначе — перечитанное."""
        return written if is_set and written is not None else read
