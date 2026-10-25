"""Раздел `cookies` файла `secrets\\livecraft.json`: срок напоминания о выгрузке cookies YouTube (CLAUDE.md §14
решение 73).

Выгрузка cookies живёт несколько дней: браузер обновляет их, и YouTube перестаёт принимать выгруженное. Поэтому
запуск и вкладка «Cookies YouTube» говорят выгрузить их заново, когда с выгрузки прошло больше `remind_days` суток.
Значение — целое, не меньше одних суток; задаётся на вкладке «Cookies YouTube». Раздел строит себя сам из узла JSON
(`from_node`) в пару к `to_data`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.config.json_node import JsonNode, json_value
from app.config.setting_key import SettingKey

REMIND_DAYS_MINIMUM: Final[int] = 1


@dataclass(frozen=True)
class CookiesSettings:
    """Через сколько суток после выгрузки напоминать выгрузить cookies заново."""

    remind_days: int

    @classmethod
    def from_node(cls, node: JsonNode) -> CookiesSettings:
        """Раздел `cookies` файла."""
        node.mapping(SettingKey.leaves(SettingKey.COOKIES))
        return cls(remind_days=node.field(SettingKey.COOKIES_REMIND_DAYS.leaf).integer(REMIND_DAYS_MINIMUM))

    def to_data(self) -> dict[str, Any]:
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.COOKIES)}
