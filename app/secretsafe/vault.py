"""Сейф в памяти: что в нём лежит, откуда и чего не хватает (CLAUDE.md §7.3).

Этот объект — про **содержимое** сейфа, а не про его хранение: ни файлов, ни шифрования, ни DPAPI он не
знает. Читает и пишет файлы `VaultStore`; с `Vault` работают одинаково и пайплайн, и настройщик
(§8: «Настройщик не знает ни про файлы, ни про шифрование — он работает с `Vault`, `LivecraftConfig`
и `ChannelBook`»).

Каких полей не хватает нужде работающей линии, сейф отвечает сам (`missing_of`); какие поля нужны какой нужде, знает
готовность запуска (app\\setup\\readiness.py::VAULT_NEEDS).

Сейф неизменяемый: `with_field` и `without_field` отдают новый сейф. Настройщик, меняя поле, получает
другой объект — прежний остаётся тем, чем был, и его не надо «откатывать» при отказе от правки.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

from app.core.text_format import SPACE
from app.observability.log_event import LogValue
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.log_filter import SecretScrubber
from app.secretsafe.value import SecretValue

LOG_ENTRY_TEMPLATE: Final[str] = "{label}={origin}"


@dataclass(frozen=True)
class VaultEntry:
    """Одно заполненное поле сейфа: сам секрет и то, откуда он взялся."""

    secret: SecretValue
    origin: VaultOrigin

    @property
    def masked(self) -> str:
        """Что показать человеку: маска значения по правилу своего поля."""
        return self.secret.masked

    @property
    def log_label(self) -> str:
        """Что писать в лог: ярлык поля с отпечатком, без значения (§7.4)."""
        return self.secret.log_label


@dataclass(frozen=True)
class Vault:
    """Сейф в памяти: только заполненные поля. Нет ключа в `entries` — значит поля нет.

    `entries` считается неизменяемым: менять сейф — значит построить новый через `with_field`
    или `without_field`.
    """

    entries: dict[SecretField, VaultEntry]

    @classmethod
    def empty(cls) -> Vault:
        """Сейф, в котором ещё ничего нет: так выглядит чистая установка до настройщика (§8)."""
        return cls(entries={})

    def entry(self, field: SecretField) -> VaultEntry | None:
        """Заполненное поле целиком — секрет и его происхождение; поля нет — None. Единственный поиск поля."""
        return self.entries.get(field)

    def get(self, field: SecretField) -> SecretValue | None:
        """Значение поля как объект-секрет; поля нет — None."""
        entry: VaultEntry | None = self.entry(field)
        return None if entry is None else entry.secret

    def origin_of(self, field: SecretField) -> VaultOrigin | None:
        """Откуда взялось поле: из токена или своё; поля нет — None."""
        entry: VaultEntry | None = self.entry(field)
        return None if entry is None else entry.origin

    def missing_of(self, fields: tuple[SecretField, ...]) -> tuple[SecretField, ...]:
        """Каких из названных полей нет — в порядке `fields`."""
        return tuple(field for field in fields if self.entry(field) is None)

    def overlaid_by(self, other: Vault) -> Vault:
        """Этот сейф, поверх которого лёг `other`: поле `other` перекрывает своё (§7.3).

        Единственное место правила «своё перекрывает значение из токена»: личный слой кладётся поверх слоя токена.
        """
        return Vault(entries={**self.entries, **other.entries})

    def only(self, origin: VaultOrigin) -> Vault:
        """Слой одного происхождения: только поля, пришедшие оттуда, — так из сейфа выделяется личный слой."""
        return Vault(entries={field: entry for field, entry in self.entries.items() if entry.origin is origin})

    def secrets(self) -> tuple[SecretValue, ...]:
        """Объекты-секреты (не значения) для фильтра логов: порядок — как у полей.

        Фильтр логов обязан вычёркивать каждое значение, которое лежит в сейфе (§7.4).
        """
        return tuple(self.entries[field].secret for field in SecretField if field in self.entries)

    def log_filter(self) -> logging.Filter:
        """Фильтр лога, который вычёркивает значения этого сейфа из готовых строк записи (§7.4)."""
        return SecretScrubber(self.secrets())

    def with_field(self, field: SecretField, secret: SecretValue, origin: VaultOrigin) -> Vault:
        """Новый сейф с этим полем; прежний не меняется."""
        entries: dict[SecretField, VaultEntry] = dict(self.entries)
        entries[field] = VaultEntry(secret=secret, origin=origin)
        return Vault(entries=entries)

    def without_field(self, field: SecretField) -> Vault:
        """Новый сейф без этого поля — так настройщик сбрасывает своё значение к значению из токена (§8.2)."""
        entries: dict[SecretField, VaultEntry] = dict(self.entries)
        entries.pop(field, None)
        return Vault(entries=entries)

    @property
    def log_line(self) -> str:
        """Строка сейфа для лога: по каждому полю ярлык с отпечатком и происхождение, ни одного значения."""
        if not self.entries:
            return LogValue.EMPTY.value
        return SPACE.join(
            LOG_ENTRY_TEMPLATE.format(label=entry.log_label, origin=entry.origin.value)
            for entry in (self.entries[field] for field in SecretField if field in self.entries)
        )
