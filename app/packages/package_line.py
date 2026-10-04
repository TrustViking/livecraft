"""Строки о пакетах bcast\\ для людей: раздел «Пакеты» отчёта, ВНИМАНИЕ консоли и строка прогресса (CLAUDE.md §10,
§14 решение 18).

Строку пакета строит сам пакет (`ReadPackage.line`, `PackageFailure.line` — app\\packages\\package_file.py); здесь —
её вид и одно правило счёта: «Итог», строка прогресса и код выхода берут числа из одних и тех же строк.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.packages.package import SCHEMA_VERSION
from app.ui.messages import msg


class PackageLineStatus(str, Enum):
    """Что с пакетом: принят, повреждён, неизвестная версия схемы, все слоты в прошлом."""

    ACCEPTED = "accepted"
    DAMAGED = "damaged"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    ALL_PAST = "all_past"                # у пакета нет ни одного будущего слота

    @property
    def is_unreadable(self) -> bool:
        return self in UNREADABLE_STATUSES


UNREADABLE_STATUSES: frozenset[PackageLineStatus] = frozenset(
    {PackageLineStatus.DAMAGED, PackageLineStatus.UNSUPPORTED_SCHEMA}
)


@dataclass(frozen=True)
class PackageLine:
    """Строка одного пакета: имя файла, статус, слотов всего и языков каналов, подробность (причина повреждения или
    версия схемы)."""

    file_name: str
    status: PackageLineStatus
    slots_total: int = 0
    slots_mine: int = 0
    detail: str = ""

    @property
    def text(self) -> str:
        return msg.PACKAGE_LINE_TEMPLATES[self.status.value].format(
            file=self.file_name,
            total=self.slots_total,
            mine=self.slots_mine,
            detail=self.detail,
            supported=SCHEMA_VERSION,
        )


@dataclass(frozen=True)
class PackageLines:
    """Строки пакетов одного чтения bcast\\: сначала прочитанные (от старого к новому), затем непрочитанные."""

    lines: tuple[PackageLine, ...] = ()

    @property
    def unreadable(self) -> tuple[PackageLine, ...]:
        """Непрочитанные пакеты: в отчёте — раздел «Пакеты», в консоли — ВНИМАНИЕ, в коде выхода — причина."""
        return tuple(line for line in self.lines if line.status.is_unreadable)

    @property
    def progress_line(self) -> str:
        """Сколько пакетов прочитано и сколько в принятых слотов — всего и языков каналов."""
        accepted: tuple[PackageLine, ...] = tuple(
            line for line in self.lines if line.status is PackageLineStatus.ACCEPTED
        )
        return msg.PROGRESS_PACKAGES_READ.format(
            packages=len(self.lines),
            slots_total=sum(line.slots_total for line in accepted),
            slots_mine=sum(line.slots_mine for line in accepted),
        )
