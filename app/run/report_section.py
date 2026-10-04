"""Часть отчёта запуска и её разделы (CLAUDE.md §3 шаг 12, §13 задача 6.3).

Отчёт logs\\<DD-MM-YYYY>_<HHMMSS>_report.md складывается из частей в порядке работы: «Запуск», «Таблица плана и
тексты», «Google-документ», «Telegram», «Пакеты», «Эфиры YouTube». `PartReport` — часть: заголовок уровнем «##», строки,
которые часть сказала в консоли, и разделы уровнем «###» (`ReportSection`). Пустой раздел не печатается; часть без
строк и без непустых разделов — тоже. Часть, которая писала keys.txt, несёт путь к нему (`keys_file`): его называет
подвал путей запуска.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.ui.messages import msg


@dataclass(frozen=True)
class ReportSection:
    """Раздел отчёта: заголовок, пояснение под ним (не пункт списка) и пункты; пунктов нет — раздела нет."""

    header: str
    items: Sequence[str]
    lead: str | None = None

    @property
    def lines(self) -> tuple[str, ...]:
        if not self.items:
            return ()
        lead: tuple[str, ...] = () if self.lead is None else (self.lead,)
        items: tuple[str, ...] = tuple(msg.REPORT_ITEM.format(text=text) for text in self.items)
        return (self.header, *lead, *items, "")


@dataclass(frozen=True)
class PartReport:
    """Часть отчёта: заголовок, строки части (те же, что она сказала в консоли), разделы и путь keys.txt для людей,
    если часть его писала."""

    title: str
    body: tuple[str, ...]
    sections: tuple[ReportSection, ...] = ()
    keys_file: str | None = None

    @property
    def lines(self) -> tuple[str, ...]:
        """«## <заголовок>», строки части, разделы; нечего сказать — части нет."""
        sections: tuple[str, ...] = tuple(line for section in self.sections for line in section.lines)
        if not self.body and not sections:
            return ()
        body: tuple[str, ...] = (*self.body, "") if self.body else ()
        return (msg.REPORT_PART.format(title=self.title), "", *body, *sections)
