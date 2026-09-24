"""Сейф в памяти: что в нём лежит, чего не хватает и что об этом сказать (CLAUDE.md §7.3).

Этот объект — про **содержимое** сейфа, а не про его хранение: ни файлов, ни шифрования, ни DPAPI он не
знает. Читать и писать файлы будет `VaultStore`; с `Vault` работают одинаково и пайплайн, и настройщик
(§8: «Настройщик не знает ни про файлы, ни про шифрование — он работает с `Vault`, `LivecraftConfig`
и `ChannelBook`»).

Сейф сам знает, каких полей ему не хватает для запуска, и сам формирует причину недопуска — так же, как
`planers\\app\\pipeline\\plan.py::PlannedBroadcast.admit` формирует свои `AdmissionReason`, а не отдаёт
сборку причины наружу.

Сейф неизменяемый: `with_field` и `without_field` отдают новый сейф. Настройщик, меняя поле, получает
другой объект — прежний остаётся тем, чем был, и его не надо «откатывать» при отказе от правки.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.secretsafe.value import SecretField, SecretValue
from app.ui import messages_ru as msg

FIELD_JOINER: Final[str] = ", "
LOG_ENTRY_TEMPLATE: Final[str] = "{label}={origin}"
LOG_LINE_JOINER: Final[str] = " "
LOG_LINE_EMPTY: Final[str] = "-"


class VaultOrigin(str, Enum):
    """Откуда взялось значение поля. Значение — английский идентификатор, для человека — `human_label`."""

    SUPPLIED = "supplied"   # пришло со сборкой: поставочный сейф Артура (§7.2)
    OWN = "own"             # вписал сам пользователь: локальный сейф под его Windows-аккаунтом

    @property
    def human_label(self) -> str:
        """Русское название; текст — в messages_ru (§11), здесь только отображение на него."""
        return _ORIGIN_LABELS[self]


_ORIGIN_LABELS: Final[dict[VaultOrigin, str]] = {
    VaultOrigin.SUPPLIED: msg.VAULT_ORIGIN_SUPPLIED,
    VaultOrigin.OWN: msg.VAULT_ORIGIN_OWN,
}


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

    def get(self, field: SecretField) -> SecretValue | None:
        """Значение поля как объект-секрет; поля нет — None."""
        entry: VaultEntry | None = self.entries.get(field)
        return None if entry is None else entry.secret

    def origin_of(self, field: SecretField) -> VaultOrigin | None:
        """Откуда взялось поле: поставка или своё; поля нет — None."""
        entry: VaultEntry | None = self.entries.get(field)
        return None if entry is None else entry.origin

    @property
    def missing(self) -> tuple[SecretField, ...]:
        """Каких полей не хватает для запуска — в порядке объявления SecretField; устаревшие не требуются."""
        return tuple(field for field in SecretField.current() if field not in self.entries)

    @property
    def is_ready(self) -> bool:
        """Все поля на месте: с таким сейфом запуск возможен."""
        return not self.missing

    @property
    def admission_reason(self) -> str | None:
        """Почему с этим сейфом нельзя работать. Готовому сейфу — None.

        Причину строит сам сейф: снаружи её не собирают из `missing` (§0, образец `PlannedBroadcast.admit`).
        """
        absent: tuple[SecretField, ...] = self.missing
        if not absent:
            return None
        return msg.VAULT_NOT_READY.format(
            fields=FIELD_JOINER.join(field.human_label for field in absent)
        )

    def secrets(self) -> tuple[SecretValue, ...]:
        """Объекты-секреты (не значения) для фильтра логов: порядок — как у полей.

        Устаревшие поля тоже: пока значение лежит в сейфе, фильтр логов обязан его вычёркивать (§7.4).
        """
        return tuple(self.entries[field].secret for field in SecretField if field in self.entries)

    def with_field(self, field: SecretField, secret: SecretValue, origin: VaultOrigin) -> Vault:
        """Новый сейф с этим полем; прежний не меняется."""
        entries: dict[SecretField, VaultEntry] = dict(self.entries)
        entries[field] = VaultEntry(secret=secret, origin=origin)
        return Vault(entries=entries)

    def without_field(self, field: SecretField) -> Vault:
        """Новый сейф без этого поля — так настройщик сбрасывает своё значение к поставке (§8.2)."""
        entries: dict[SecretField, VaultEntry] = dict(self.entries)
        entries.pop(field, None)
        return Vault(entries=entries)

    @property
    def log_line(self) -> str:
        """Строка сейфа для лога: по каждому полю ярлык с отпечатком и происхождение, ни одного значения."""
        if not self.entries:
            return LOG_LINE_EMPTY
        return LOG_LINE_JOINER.join(
            LOG_ENTRY_TEMPLATE.format(label=entry.log_label, origin=entry.origin.value)
            for entry in (self.entries[field] for field in SecretField if field in self.entries)
        )
