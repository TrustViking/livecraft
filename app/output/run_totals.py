"""Счётчики запуска — единственный подсчёт для «Итога», заголовков разделов, консоли и кода выхода (CLAUDE.md §10)."""
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from app.output.result import CREATED_KINDS, ERROR_KINDS, BroadcastResult, KeyState, OutcomeKind


@dataclass(frozen=True)
class RunTotals:
    """`broadcasts` — эфиры (слот × канал) = created + fixed + matched + not_admitted + errors; `failures` — сбои без
    слота (каналы, файлы программы): в «Итог по эфирам» не входят; `undelivered` — ключи, которые должны были дойти до
    стримера и не дошли; `unreadable_packages` — непрочитанные пакеты bcast\\ (режим Б)."""

    created: int          # создано и поток привязан: и там, и там новый ключ
    fixed: int
    matched: int          # в --status — эфиры программы на каналах
    not_admitted: int     # не допущены: не ошибки, код выхода не меняют
    errors: int
    broadcasts: int
    failures: int
    orphans: int
    skipped: int
    undelivered: int
    unreadable_packages: int = 0

    @classmethod
    def count(cls, results: Sequence[BroadcastResult], failures: int, orphans: int, skipped: int) -> RunTotals:
        kinds: list[OutcomeKind] = [result.kind for result in results]
        return cls(
            created=sum(1 for kind in kinds if kind in CREATED_KINDS),
            fixed=kinds.count(OutcomeKind.FIXED),
            matched=kinds.count(OutcomeKind.MATCHED),
            not_admitted=kinds.count(OutcomeKind.NOT_ADMITTED),
            errors=sum(1 for kind in kinds if kind in ERROR_KINDS),
            broadcasts=len(kinds),
            failures=failures,
            orphans=orphans,
            skipped=skipped,
            undelivered=sum(1 for result in results if result.key_state is KeyState.FAILED),
        )

    def with_packages(self, unreadable: int) -> RunTotals:
        """Те же счётчики и число непрочитанных пакетов: их считают строки пакетов, а не итоги эфиров."""
        return dataclasses.replace(self, unreadable_packages=unreadable)
