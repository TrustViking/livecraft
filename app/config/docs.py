"""Раздел `docs` файла `secrets\\livecraft.json`: документ объявлений в Google Docs (CLAUDE.md §5, §13 задача 4.4,
§14 решения 14, 15).

Документ объявлений программа создаёт сама — на каждую дату эфиров, в папке материалов (раздел `drive`). Здесь — то,
что решает человек: кому документ открыт по ссылке (`access`) и контакты для стримеров в его шапке (`contacts`; пусто —
блока контактов в шапке нет). Обе настройки открытые, секретов в разделе нет. Раздел строит себя сам из узла JSON
(`from_node`) в пару к `to_data`; недопустимый доступ называет разбор (`JsonNode.choice`).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.config.json_node import JsonNode, json_value
from app.config.setting_key import SettingKey


class DocAccess(str, Enum):
    """Доступ к документу объявлений по ссылке. Значение — вариант в файле."""

    PRIVATE = "private"          # только тем, кому документ открыт на Диске
    READER = "reader"            # все, у кого есть ссылка, — читать
    COMMENTER = "commenter"      # все, у кого есть ссылка, — комментировать
    WRITER = "writer"            # все, у кого есть ссылка, — править

    @property
    def link_role(self) -> str | None:
        """Роль «все, у кого есть ссылка» на Google Диске; у закрытого документа её нет — None."""
        return None if self is DocAccess.PRIVATE else self.value


@dataclass(frozen=True)
class DocsSettings:
    """Документ объявлений: доступ по ссылке и контакты для стримеров в шапке (пусто — блока нет)."""

    access: DocAccess
    contacts: str

    @classmethod
    def from_node(cls, node: JsonNode) -> DocsSettings:
        """Раздел `docs` файла."""
        node.mapping(SettingKey.leaves(SettingKey.DOCS))
        return cls(
            access=node.field(SettingKey.DOCS_ACCESS.leaf).choice(DocAccess),
            contacts=node.field(SettingKey.DOCS_CONTACTS.leaf).string(),
        )

    def to_data(self) -> dict[str, Any]:
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.DOCS)}

    @property
    def has_contacts(self) -> bool:
        """Контакты заданы: в шапке документа есть их блок."""
        return bool(self.contacts)
