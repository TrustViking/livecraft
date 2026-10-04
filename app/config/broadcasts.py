"""Раздел `broadcasts` файла `secrets\\livecraft.json`: какие ключи эфиров передать в форму (CLAUDE.md §8.2, §14 решения
36, 47, 49).

`resend_keys` — «все»: передать ключи всех эфиров запуска, и новых, и уже запланированных; выключен — «новые» (ключи
эфиров, поставленных этим запуском, и один повтор неподтверждённого ключа). После полного запуска, в котором форма
подтвердила все ключи, программа возвращает его на «новые» сама (app\\broadcasts\\key_resend.py). Настройка открытая,
секретов в разделе нет. Раздел строит себя сам из узла JSON (`from_node`) в пару к `to_data`. Прежний переключатель
источника текстов (`text_source`) ушёл (§14 решение 50): его ключ из файла убирает `TextSourceMigration`
(app\\setup\\migration.py).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from app.config.json_node import JsonNode, json_value
from app.config.setting_key import SettingKey


@dataclass(frozen=True)
class BroadcastSettings:
    """Эфиры: передать ли ключи всех эфиров запуска («все»)."""

    resend_keys: bool

    @classmethod
    def from_node(cls, node: JsonNode) -> BroadcastSettings:
        """Раздел `broadcasts` файла."""
        node.mapping(SettingKey.leaves(SettingKey.BROADCASTS))
        return cls(node.field(SettingKey.BROADCASTS_RESEND_KEYS.leaf).boolean())

    def to_data(self) -> dict[str, Any]:
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.BROADCASTS)}

    def with_resend(self, resend_keys: bool) -> BroadcastSettings:
        return dataclasses.replace(self, resend_keys=resend_keys)
