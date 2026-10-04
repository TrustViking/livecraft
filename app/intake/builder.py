"""Сборка слотов запуска из годных источников (CLAUDE.md §3 шаги 2.3–2.6, §4, §14 решения 32, 50).

`SlotBuilder` раскладывает годные источники по группам слотов: ключ группы — дата, время и язык — даёт сам источник
(`SourceVideo.slot_key`). `SlotGroup` — источники одного слота в порядке рядов: из них слот берёт обложки, ссылки
и тексты видео. Правило «умного merge» — у группы (`video_texts`): merge не нужен (`needs_merge` ложно: одно видео или
меньше двух непустых описаний) — тексты видео как есть по правилам YouTube; merge нужен, а текстов модели нет —
тексты «по номерам», не для YouTube. Тексты модели слот получает от стадии merge. Нейросеть не идёт — правило без неё
(`people_texts`, решение 50): одно видео — его тексты целиком, несколько — «по номерам». Повторов ссылки в группе нет:
та же ссылка в тот же момент снимается ещё на рядах таблицы.

`SlotBuild` — итог: годные слоты и слоты с проблемой и шла ли стадия merge (`has_merge`). Слот с проблемой не
выбрасывается: он остаётся в `refused`, причина — в лог, дальше не идёт (§0). Годный слот с текстами «по номерам» идёт
в превью, документ и Telegram, но не в пакет и не на YouTube (`for_youtube`); когда merge шёл, такой слот — его отказ:
строка консоли на слот, и запуск кончается ошибкой (код 1). Без нейросети «по номерам» — настройка, а не ошибка.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from zoneinfo import ZoneInfo

from app.core.counts import Counts
from app.llm.merges.job import MergeSources
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.slots.preview import Preview
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTexts, SourceText
from app.sources.video import SourceVideo
from app.ui.messages import msg

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
    def needs_merge(self) -> bool:
        """Нужен ли слоту merge: непустых описаний у видео не меньше двух (`MergeSources.needs_merge`)."""
        return MergeSources(self.videos).needs_merge

    @property
    def video_texts(self) -> SlotTexts:
        """Тексты слота без ответа модели (§14 решение 32): merge не нужен — тексты видео как есть по правилам YouTube
        (одно видео — его название и описание); merge нужен — тексты «по номерам», не для YouTube."""
        sources: list[SourceText] = [video.text for video in self.videos]
        if self.needs_merge:
            return SlotTexts.numbered(sources)
        return SlotTexts.from_sources(sources).for_youtube(self.key.slot_id)

    @property
    def people_texts(self) -> SlotTexts:
        """Тексты слота, когда нейросеть не идёт (§14 решение 50): одно видео — его название и описание целиком,
        несколько — «по номерам». Такие слоты — только для людей: пакет и эфиры от таблицы без нейросети не идут."""
        sources: list[SourceText] = [video.text for video in self.videos]
        return SlotTexts.from_sources(sources) if len(sources) == 1 else SlotTexts.numbered(sources)

    def slot(self, texts: SlotTexts) -> StreamSlot:
        """Слот группы с окончательными текстами."""
        return StreamSlot(key=self.key, texts=texts, previews=self.previews, sources=self.sources)


@dataclass(frozen=True)
class SlotBuild:
    """Итог сборки слотов запуска: годные слоты и слоты с проблемой — в порядке слотов; шла ли стадия merge."""

    slots: tuple[StreamSlot, ...]
    refused: tuple[StreamSlot, ...]
    has_merge: bool

    @classmethod
    def of(cls, slots: Sequence[StreamSlot], has_merge: bool) -> SlotBuild:
        """Годный слот — строкой INFO, с проблемой — WARNING с причиной; итог — строкой `slots_built`."""
        for slot in slots:
            if slot.problem is None:
                LogEvent.of(SlotsEvent.SLOT, **slot.log_fields).emit(LOGGER)
            else:
                LogEvent.of(SlotsEvent.REFUSED, **slot.log_fields, problem=slot.problem).emit(LOGGER, logging.WARNING)
        build: SlotBuild = cls(
            slots=tuple(slot for slot in slots if slot.problem is None),
            refused=tuple(slot for slot in slots if slot.problem is not None),
            has_merge=has_merge,
        )
        LogEvent.of(SlotsEvent.BUILT, **build.log_fields).emit(LOGGER)
        return build

    @property
    def languages(self) -> Counts[str]:
        """Годные слоты по языкам в порядке первого появления."""
        return Counts.of(slot.language for slot in self.slots)

    @property
    def for_youtube(self) -> tuple[StreamSlot, ...]:
        """Годные слоты, которые идут в пакет и на YouTube."""
        return tuple(slot for slot in self.slots if slot.is_for_youtube)

    @property
    def not_for_youtube(self) -> tuple[StreamSlot, ...]:
        """Годные слоты с текстами «по номерам»: только для людей (§14 решения 32, 50)."""
        return tuple(slot for slot in self.slots if not slot.is_for_youtube)

    @property
    def merge_refused(self) -> tuple[StreamSlot, ...]:
        """Слоты, которым не удался merge: «по номерам» при идущей нейросети; без неё таких нет."""
        return self.not_for_youtube if self.has_merge else ()

    @property
    def has_errors(self) -> bool:
        """Слот с проблемой или слот, которому не удался merge, — ошибка запуска (§10, §14 решение 32)."""
        return bool(self.refused) or bool(self.merge_refused)

    @property
    def log_fields(self) -> Mapping[str, object]:
        return dict(
            slots=len(self.slots),
            not_for_youtube=len(self.not_for_youtube),
            refused=len(self.refused),
            languages=self.languages.log_value,
        )

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Строки для оператора: сколько слотов, по языкам, и сколько отказано (причины — в логе); затем по строке
        на слот, которому не удался merge, — язык, время и дата для людей."""
        languages: str = self.languages.wrapped(msg.INTAKE_SLOTS_LANGUAGES, msg.INTAKE_COUNT_ITEM, msg.LIST_JOINER, str)
        refused: str = msg.INTAKE_SLOTS_REFUSED.format(count=len(self.refused)) if self.refused else ""
        total: str = msg.INTAKE_SLOTS_LINE.format(count=len(self.slots), languages=languages, refused=refused)
        numbered: tuple[str, ...] = tuple(
            msg.INTAKE_SLOT_NOT_FOR_YOUTUBE.format(language=slot.language.upper(), time=slot.time, date=slot.human_date)
            for slot in self.merge_refused
        )
        return (total, *numbered)


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
