"""Сборка слотов запуска из годных источников (CLAUDE.md §3 шаги 2.3–2.6, §4).

`SlotBuilder` раскладывает годные источники по группам слотов: ключ группы — дата, время и язык — даёт сам источник
(`SourceVideo.slot_key`). `SlotGroup` — источники одного слота в порядке рядов: из них слот берёт обложки, ссылки
и — без нейросети — тексты; какие тексты получит слот, решает прогон (`PlanIntake`). Повторов ссылки в группе нет:
та же ссылка в тот же момент снимается ещё на рядах таблицы. `SlotBuild` — итог: годные слоты и слоты с проблемой.
Слот с проблемой не выбрасывается: он остаётся в `refused`, причина — в лог, дальше не идёт (§0).
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from zoneinfo import ZoneInfo

from app.core.counts import Counts
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.slots.preview import Preview
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTexts
from app.sources.video import SourceVideo
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.SLOTS)


class SlotsEvent(str, Enum):
    """События сборки слотов в логе."""

    SLOT = "slot"
    REFUSED = "slot_refused"
    BUILT = "slots_built"


@dataclass(frozen=True)
class SlotGroup:
    """Источники одного слота в порядке рядов."""

    key: SlotKey
    videos: tuple[SourceVideo, ...]

    @property
    def previews(self) -> tuple[Preview, ...]:
        """Обложки источников, у которых они есть, в порядке рядов."""
        return tuple(video.preview for video in self.videos if video.preview is not None)

    @property
    def sources(self) -> tuple[str, ...]:
        """Ссылки источников `watch?v=<id>` в порядке рядов."""
        return tuple(video.watch_url for video in self.videos)

    @property
    def source_texts(self) -> SlotTexts:
        """Тексты слота без нейросети — из текстов источников, подогнанные под правила YouTube."""
        return SlotTexts.from_sources([video.text for video in self.videos]).for_youtube(self.key.slot_id)

    def slot(self, texts: SlotTexts) -> StreamSlot:
        """Слот группы с окончательными текстами."""
        return StreamSlot(key=self.key, texts=texts, previews=self.previews, sources=self.sources)


@dataclass(frozen=True)
class SlotBuild:
    """Итог сборки слотов запуска: годные слоты и слоты с проблемой — в порядке слотов."""

    slots: tuple[StreamSlot, ...]
    refused: tuple[StreamSlot, ...]

    @classmethod
    def of(cls, slots: Sequence[StreamSlot]) -> SlotBuild:
        """Годный слот — строкой INFO, с проблемой — WARNING с причиной; итог — строкой `slots_built`."""
        for slot in slots:
            if slot.problem is None:
                LogEvent.of(SlotsEvent.SLOT, **slot.log_fields).emit(LOGGER)
            else:
                LogEvent.of(SlotsEvent.REFUSED, **slot.log_fields, problem=slot.problem).emit(LOGGER, logging.WARNING)
        build: SlotBuild = cls(
            slots=tuple(slot for slot in slots if slot.problem is None),
            refused=tuple(slot for slot in slots if slot.problem is not None),
        )
        LogEvent.of(SlotsEvent.BUILT, **build.log_fields).emit(LOGGER)
        return build

    @property
    def languages(self) -> Counts[str]:
        """Годные слоты по языкам в порядке первого появления."""
        return Counts.of(slot.language for slot in self.slots)

    @property
    def has_errors(self) -> bool:
        """Слот с проблемой — ошибка запуска (§10)."""
        return bool(self.refused)

    @property
    def log_fields(self) -> Mapping[str, object]:
        return dict(slots=len(self.slots), refused=len(self.refused), languages=self.languages.log_value)

    @property
    def console_line(self) -> str:
        """Строка для оператора: сколько слотов, по языкам, и сколько отказано (причины — в логе)."""
        languages: str = self.languages.wrapped(msg.INTAKE_SLOTS_LANGUAGES, msg.INTAKE_COUNT_ITEM, msg.LIST_JOINER, str)
        refused: str = msg.INTAKE_SLOTS_REFUSED.format(count=len(self.refused)) if self.refused else ""
        return msg.INTAKE_SLOTS_LINE.format(count=len(self.slots), languages=languages, refused=refused)


@dataclass(frozen=True)
class SlotBuilder:
    """Раскладка источников запуска по слотам в зоне программы (`LivecraftSettings.zone`)."""

    zone: ZoneInfo

    def groups(self, videos: Sequence[SourceVideo]) -> tuple[SlotGroup, ...]:
        """Группы только из годных источников; порядок — `SlotKey.sort_key`, внутри — порядок источников.

        Группа определяется `slot_id`: две записи одного местного часа и языка — один слот (§4).
        """
        keys: dict[str, SlotKey] = {}
        members: dict[str, list[SourceVideo]] = {}
        for video in videos:
            key: SlotKey | None = video.slot_key(self.zone)
            if key is None:
                continue
            keys.setdefault(key.slot_id, key)
            members.setdefault(key.slot_id, []).append(video)
        ordered: list[SlotKey] = sorted(keys.values(), key=lambda item: item.sort_key)
        return tuple(SlotGroup(key, tuple(members[key.slot_id])) for key in ordered)
