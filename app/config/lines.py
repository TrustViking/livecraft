"""Раздел `lines` файла `secrets\\livecraft.json`: переключатели линий работы (CLAUDE.md §14 решение 37).

Что делает запуск, решают включённые линии, а не ключ режима: что включено, то программа делает и то настраивается;
выключенное не делается. Поле раздела — значение члена `RunPart` своей линии, поэтому раздел сам отвечает, какие линии
включены (`switched_on`). Работает ли включённая линия — работает ли линия, на которую она опирается, — решает
`LinePlan` (app\\run\\line_plan.py). В поставке включены все. Раздел строит себя сам из узла JSON (`from_node`) в пару
к `to_data`; вид каждого поля (да / нет) проверяет разбор.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config.json_node import JsonNode, json_value
from app.config.setting_key import SettingKey
from app.run.line_plan import LinePlan
from app.run.mode import LINE_ORDER, RunPart


@dataclass(frozen=True)
class LineSettings:
    """Включена ли каждая линия работы; имя поля — значение члена `RunPart` линии."""

    plan: bool
    merge: bool
    local_previews: bool
    drive_previews: bool
    doc: bool
    doc_copy: bool
    package: bool
    announce: bool
    broadcast: bool
    keys: bool

    @classmethod
    def from_node(cls, node: JsonNode) -> LineSettings:
        """Раздел `lines` файла: ровно поле на линию, каждое — да или нет."""
        leaves: tuple[str, ...] = SettingKey.leaves(SettingKey.LINES)
        node.mapping(leaves)
        return cls(**{leaf: node.field(leaf).boolean() for leaf in leaves})

    def to_data(self) -> dict[str, Any]:
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.LINES)}

    @property
    def switched_on(self) -> frozenset[RunPart]:
        """Включённые линии."""
        return frozenset(part for part in LINE_ORDER if getattr(self, part.value))

    def is_on(self, part: RunPart) -> bool:
        """Линия включена; часть, которая не линия (чтение пакетов), не включается никогда."""
        return part in self.switched_on

    @property
    def line_plan(self) -> LinePlan:
        """Линии запуска: какие работают, а каким не хватает опоры."""
        return LinePlan(self.switched_on)
