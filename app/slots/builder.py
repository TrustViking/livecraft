"""Сборка слотов запуска из годных источников (CLAUDE.md §3 шаги 2.3–2.6, §4).

`SlotGroup` — источники одного слота: одинаковые дата, время и язык. Страховка повторов — правило донора
`deduplicate_planned_videos_within_slot_language` (restreamer): одна ссылка в слоте второй раз не идёт,
остаётся ранний ряд. Отсев 3.1 такие повторы уже убирает («та же ссылка — тот же момент»), здесь — рубеж.
`SlotBuilder` раскладывает источники по группам в порядке слотов; `SlotBuild` — итог: годные слоты и слоты
с проблемой. Слот с проблемой не выбрасывается: он остаётся в `refused`, причина — в лог, дальше не идёт (§0).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from zoneinfo import ZoneInfo

from app.observability.logging_setup import get_logger
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTexts
from app.sources.video import SourceVideo

LOGGER_NAME: Final[str] = "slots"
LOGGER = get_logger(LOGGER_NAME)

NO_VALUE: Final[str] = "-"
COUNT_JOINER: Final[str] = ","


@dataclass(frozen=True)
class SlotGroup:
    """Источники одного слота в порядке рядов, без повторов ссылки."""

    key: SlotKey
    videos: tuple[SourceVideo, ...]

    @classmethod
    def of(cls, key: SlotKey, videos: Sequence[SourceVideo]) -> SlotGroup:
        """Группа по ключу: источники по номеру ряда; ссылка второй раз — WARNING, остаётся ранний ряд."""
        kept: dict[str, SourceVideo] = {}
        for video in sorted(videos, key=lambda item: item.row.row_number):
            earlier: SourceVideo | None = kept.get(video.link)
            if earlier is None:
                kept[video.link] = video
                continue
            LOGGER.warning(
                "slot_duplicate_link slot=%s link=%s kept_row=%d skipped_row=%d",
                key.slot_id, video.link, earlier.row.row_number, video.row.row_number,
            )
        return cls(key=key, videos=tuple(kept.values()))

    def texts(self) -> SlotTexts:
        """Окончательные тексты слота без LLM, подогнанные под правила YouTube."""
        return SlotTexts.from_sources(self.videos).for_youtube(self.key.slot_id)

    def slot(self) -> StreamSlot:
        return StreamSlot.of(self.key, self.texts(), self.videos)


@dataclass(frozen=True)
class SlotBuild:
    """Итог сборки слотов запуска: группы, годные слоты и слоты с проблемой — в порядке слотов."""

    groups: tuple[SlotGroup, ...]
    slots: tuple[StreamSlot, ...]
    refused: tuple[StreamSlot, ...]

    @classmethod
    def of(cls, groups: tuple[SlotGroup, ...]) -> SlotBuild:
        """Слот из каждой группы; годный — строкой INFO, с проблемой — WARNING с причиной."""
        slots: list[StreamSlot] = []
        refused: list[StreamSlot] = []
        for group in groups:
            slot: StreamSlot = group.slot()
            if slot.problem is None:
                LOGGER.info("slot %s", slot.log_line)
                slots.append(slot)
            else:
                LOGGER.warning("slot_refused %s problem=%r", slot.log_line, slot.problem)
                refused.append(slot)
        return cls(groups=groups, slots=tuple(slots), refused=tuple(refused))

    @property
    def languages(self) -> Counter[str]:
        """Годные слоты по языкам в порядке первого появления."""
        return Counter(slot.language for slot in self.slots)

    @property
    def log_line(self) -> str:
        by_language: str = COUNT_JOINER.join(
            f"{code}:{count}" for code, count in self.languages.items()
        ) or NO_VALUE
        return f"slots={len(self.slots)} refused={len(self.refused)} languages={by_language}"


@dataclass(frozen=True)
class SlotBuilder:
    """Раскладка источников запуска по слотам в зоне программы (`LivecraftSettings.zone`)."""

    zone: ZoneInfo

    def groups(self, videos: Sequence[SourceVideo]) -> tuple[SlotGroup, ...]:
        """Группы только из годных источников; порядок — `SlotKey.sort_key`, внутри — по номеру ряда.

        Группа определяется `slot_id`: две записи одного местного часа и языка — один слот (§4).
        """
        keys: dict[str, SlotKey] = {}
        members: dict[str, list[SourceVideo]] = {}
        for video in videos:
            if not video.is_ready:
                continue
            key: SlotKey = SlotKey.of(video, self.zone)
            keys.setdefault(key.slot_id, key)
            members.setdefault(key.slot_id, []).append(video)
        ordered: list[SlotKey] = sorted(keys.values(), key=lambda item: item.sort_key)
        return tuple(SlotGroup.of(key, members[key.slot_id]) for key in ordered)

    def build(self, videos: Sequence[SourceVideo]) -> SlotBuild:
        """Слоты запуска из источников; итог — строкой `slots_built` в лог."""
        build: SlotBuild = SlotBuild.of(self.groups(videos))
        LOGGER.info("slots_built %s", build.log_line)
        return build
