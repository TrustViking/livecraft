"""Что изменила запись livecraft.json — для лога (CLAUDE.md §14 решение 38).

`SettingsChange.between` сравнивает прежние и новые настройки по их данным файла (`LivecraftSettings.to_data`) поле за
полем: ключ — путь «раздел.поле» (вложенные словари — дальше через точку), значение — как в JSON. Строка лога
`settings_saved` называет файл и каждое изменённое поле с прежним и новым значением. Значения пишутся как есть: в
livecraft.json значений сейфа нет (§5, §7.5). Поля, которого с одной стороны нет, — «-».
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.config.json_node import KEY_SEPARATOR
from app.config.settings import LivecraftSettings
from app.observability.log_event import LogEvent, LogValue

CHANGE_TEMPLATE: Final[str] = "{key}: {before} -> {after}"


class SettingsChangeEvent(str, Enum):
    """События записи настроек в логе."""

    SAVED = "settings_saved"


class ChangeMark(str, Enum):
    """Разделитель изменённых полей в одной строке лога."""

    JOINER = "; "


@dataclass(frozen=True)
class SettingChange:
    """Одно изменённое поле: путь ключа, прежнее и новое значение текстом JSON (поля нет — «-»)."""

    key: str
    before: str
    after: str

    @property
    def text(self) -> str:
        return CHANGE_TEMPLATE.format(key=self.key, before=self.before, after=self.after)


@dataclass(frozen=True)
class SettingsChange:
    """Изменённые поля livecraft.json по порядку ключей файла."""

    changes: tuple[SettingChange, ...]

    @classmethod
    def between(cls, before: LivecraftSettings, after: LivecraftSettings) -> SettingsChange:
        old: dict[str, str] = cls._leaves(before.to_data(), "")
        new: dict[str, str] = cls._leaves(after.to_data(), "")
        absent: str = LogValue.EMPTY.value
        keys: list[str] = [*old, *(key for key in new if key not in old)]
        return cls(changes=tuple(
            SettingChange(key=key, before=old.get(key, absent), after=new.get(key, absent))
            for key in keys if old.get(key) != new.get(key)
        ))

    @property
    def is_empty(self) -> bool:
        return not self.changes

    def event(self, path: Path) -> LogEvent:
        """Строка `settings_saved path=<файл> changed=<ключ: прежнее -> новое; …>`."""
        changed: str = ChangeMark.JOINER.value.join(change.text for change in self.changes)
        return LogEvent.of(SettingsChangeEvent.SAVED, path=path, changed=changed)

    @classmethod
    def _leaves(cls, data: Mapping[str, object], prefix: str) -> dict[str, str]:
        """Поля данных файла по путям «раздел.поле»; значение — текстом JSON."""
        leaves: dict[str, str] = {}
        for name, value in data.items():
            key: str = prefix + name
            if isinstance(value, Mapping):
                leaves.update(cls._leaves(value, key + KEY_SEPARATOR))
            else:
                leaves[key] = json.dumps(value, ensure_ascii=False)
        return leaves
