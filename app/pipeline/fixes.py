"""Какие расхождения программа исправляет и каким вызовом площадки, о каких только сообщает (CLAUDE.md §6 инвариант 1).

Одно место деления полей: исправимые (`FIX_CALLS`, `FIXABLE_FIELDS`) — решение UPDATE, программа приводит эфир к плану
только нужными вызовами; только сообщаемые (`REPORTED_FIELDS`) — решения не меняют, но доходят до владельца: лог,
«внимание:» в консоли, отчёт. `FieldFixes` — расхождения одного эфира и итог их исправления в этом запуске.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.platforms.spec import ChangedField
from app.platforms.video import VideoFixes


class FixCall(str, Enum):
    """Вызов площадки, которым исправляется поле; при правке эфира зовутся только вызовы полей, что разошлись."""

    BROADCAST = "broadcast"    # liveBroadcasts.update (название, описание; время и категория идут с ними)
    VIDEO = "video"            # videos.update — проход настроек видео (apply_video_settings)
    STREAM = "stream"          # liveStreams.update — метка потока (set_stream_marker)
    THUMBNAIL = "thumbnail"    # thumbnails.set


# Исправимые поля и вызов, которым каждое исправляется, — один источник.
FIX_CALLS: Final[dict[ChangedField, FixCall]] = {
    ChangedField.TITLE: FixCall.BROADCAST,
    ChangedField.DESCRIPTION: FixCall.BROADCAST,
    ChangedField.CATEGORY: FixCall.VIDEO,
    ChangedField.PRIVACY: FixCall.VIDEO,
    ChangedField.MARKER: FixCall.STREAM,
    ChangedField.THUMBNAIL: FixCall.THUMBNAIL,
}
FIXABLE_FIELDS: Final[frozenset[ChangedField]] = frozenset(FIX_CALLS)
# Эти поля живут в contentDetails эфира, а liveBroadcasts.update шлёт только snippet: contentDetails у update требует
# monitorStream. Гонять их через UPDATE значило бы на каждом запуске «исправлять» неисправимое и слать ключ заново.
REPORTED_FIELDS: Final[frozenset[ChangedField]] = frozenset(
    {ChangedField.AUTO_START, ChangedField.AUTO_STOP, ChangedField.LATENCY}
)


@dataclass
class FieldFixes:
    """Расхождения эфира с планом и итог исправления по факту. Изменяемый намеренно: исправления идут по шагам.

    `changed` — исправимые, `reported` — только сообщаемые; `fixed` и `unfixed` — что этот запуск на площадке исправил
    и что не смог; меняются только своими методами. Порядок полей всюду — порядок `ChangedField`.
    """

    changed: tuple[ChangedField, ...] = ()
    reported: tuple[ChangedField, ...] = ()
    fixed: tuple[ChangedField, ...] = ()
    unfixed: tuple[ChangedField, ...] = ()

    def split_changed(self, changed: tuple[ChangedField, ...]) -> None:
        """Изменившиеся поля — на исправимые и только сообщаемые; решение по ним принимает вызывающий."""
        self.changed = tuple(name for name in changed if name in FIXABLE_FIELDS)
        self.reported = tuple(name for name in changed if name in REPORTED_FIELDS)

    @property
    def fix_calls(self) -> frozenset[FixCall]:
        """Вызовы площадки, которых требуют расхождения этого эфира."""
        return frozenset(FIX_CALLS[name] for name in self.changed)

    def fields_fixed_by(self, call: FixCall) -> tuple[ChangedField, ...]:
        """Разошедшиеся поля, которые исправляет этот вызов."""
        return tuple(name for name in self.changed if FIX_CALLS[name] is call)

    def mark_fixed(self, fields: tuple[ChangedField, ...]) -> None:
        """Поля, которые этот запуск на площадке действительно исправил; единственное место изменения."""
        done: set[ChangedField] = {*self.fixed, *fields}
        self.fixed = tuple(name for name in ChangedField if name in done)
        self.unfixed = tuple(name for name in self.unfixed if name not in done)

    def take_video_fixes(self, video: VideoFixes) -> tuple[ChangedField, ...]:
        """Категория и видимость, исправленные у ресурса видео найденного эфира, — исправление эфира.

        Категорию список эфиров YouTube не возвращает, поэтому её расхождение видно только здесь. Возвращает поля,
        которых среди расхождений не было: из-за них совпавший эфир становится исправленным.
        """
        video_fields: dict[ChangedField, bool] = {
            ChangedField.CATEGORY: video.category_set,
            ChangedField.PRIVACY: video.privacy_set,
        }
        fixed: tuple[ChangedField, ...] = tuple(name for name, is_set in video_fields.items() if is_set)
        self.mark_fixed(fixed)
        added: tuple[ChangedField, ...] = tuple(name for name in fixed if name not in self.changed)
        self.changed = tuple(name for name in ChangedField if name in (*self.changed, *added))
        return added

    def mark_unfixed(self, name: ChangedField) -> None:
        """Поле надо было исправить, а не удалось; уже исправленное или отмеченное не отмечается."""
        if name in self.fixed or name in self.unfixed:
            return
        failed: set[ChangedField] = {*self.unfixed, name}
        self.unfixed = tuple(candidate for candidate in ChangedField if candidate in failed)
