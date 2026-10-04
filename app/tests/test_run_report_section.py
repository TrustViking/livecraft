"""Часть отчёта запуска и её разделы (app\\run\\report_section.py; CLAUDE.md §3 шаг 12, задача 6.3)."""
from __future__ import annotations

from app.run.report_section import PartReport, ReportSection
from app.ui import messages_ru as msg


def test_a_section_without_items_is_not_printed() -> None:
    assert ReportSection("### Пусто", ()).lines == ()
    assert ReportSection("### Раздел", ("пункт",), "пояснение").lines == ("### Раздел", "пояснение", "- пункт", "")


def test_a_part_is_its_title_its_lines_and_its_sections() -> None:
    part: PartReport = PartReport("Часть", ("строка 1", "строка 2"), (ReportSection("### Раздел", ("пункт",)),))
    assert part.lines == ("## Часть", "", "строка 1", "строка 2", "", "### Раздел", "- пункт", "")
    assert part.lines[0] == msg.REPORT_PART.format(title="Часть")


def test_a_part_with_nothing_to_say_is_not_printed() -> None:
    assert PartReport("Часть", ()).lines == ()
    assert PartReport("Часть", (), (ReportSection("### Пусто", ()),)).lines == ()


def test_a_part_with_sections_only_has_no_empty_body() -> None:
    part: PartReport = PartReport("Часть", (), (ReportSection("### Раздел", ("пункт",)),))
    assert part.lines == ("## Часть", "", "### Раздел", "- пункт", "")
