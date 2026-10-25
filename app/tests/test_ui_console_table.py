"""Таблица консоли и ширина окна консоли (app\\ui\\console_table.py, CLAUDE.md §14 решение 78)."""
from __future__ import annotations

import io

import pytest

from app.ui.console_table import MAX_WIDTH, PLAIN_WIDTH, ConsoleTable, ConsoleWidth

WIDTH: int = 24


def test_a_table_has_a_titled_rule_its_entries_with_separators_and_a_closing_rule() -> None:
    table: ConsoleTable = ConsoleTable("ВНИМАНИЕ", (("  первое",), ("  второе", "    подробно")), is_separated=True)
    assert table.lines(WIDTH) == (
        "======= ВНИМАНИЕ =======",
        "  первое",
        "-" * WIDTH,
        "  второе",
        "    подробно",
        "=" * WIDTH,
    )


def test_entries_of_one_part_go_without_separators() -> None:
    table: ConsoleTable = ConsoleTable("Запуск", (("а",), ("б",)))
    assert table.lines(WIDTH) == ("======== Запуск ========", "а", "б", "=" * WIDTH)


def test_one_line_of_content_is_printed_as_is_without_a_frame() -> None:
    assert ConsoleTable("Запуск", (("  одно",),)).lines(WIDTH) == ("  одно",)
    assert ConsoleTable("ВНИМАНИЕ", (("  одно",),), is_separated=True).lines(WIDTH) == ("  одно",)
    assert ConsoleTable("ВНИМАНИЕ", ()).lines(WIDTH) == ()


def test_one_line_of_a_titled_table_goes_after_its_title() -> None:
    """Блок итога эфиров из одной строки — одной строкой с названием блока впереди (§14 решение 78)."""
    assert ConsoleTable("ВНИМАНИЕ", (("  одно",),), is_titled_line=True).lines(WIDTH) == ("ВНИМАНИЕ — одно",)
    assert ConsoleTable("ВНИМАНИЕ", ((), ("  одно",)), is_titled_line=True).lines(WIDTH) == ("ВНИМАНИЕ — одно",)
    assert ConsoleTable("ВНИМАНИЕ", (), is_titled_line=True).lines(WIDTH) == ()
    table: ConsoleTable = ConsoleTable("ВНИМАНИЕ", (("  первое",), ("  второе",)), is_separated=True, is_titled_line=True)
    assert table.lines(WIDTH) == ("======= ВНИМАНИЕ =======", "  первое", "-" * WIDTH, "  второе", "=" * WIDTH)


def test_lines_of_a_part_lose_their_blank_edges() -> None:
    """Края рисует таблица: пустая строка перед «Итогом» части ей не нужна; пустые строки внутри остаются."""
    table: ConsoleTable = ConsoleTable.of_lines("Эфиры YouTube", ("", "Итог", "", "строка", ""))
    assert table.entries == (("Итог", "", "строка"),)
    assert ConsoleTable.of_lines("Эфиры YouTube", ("", "Итог")).lines(WIDTH) == ("Итог",)


def test_an_empty_entry_gives_no_separator() -> None:
    table: ConsoleTable = ConsoleTable("Блок", ((), ("а",), (), ("б",)), is_separated=True)
    assert table.lines(WIDTH)[1:-1] == ("а", "-" * WIDTH, "б")


class TerminalStream(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_the_width_follows_the_terminal_window_up_to_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "90")
    assert ConsoleWidth.of(TerminalStream()).columns == 90
    monkeypatch.setenv("COLUMNS", str(MAX_WIDTH + 40))
    assert ConsoleWidth.of(TerminalStream()).columns == MAX_WIDTH


def test_outside_a_terminal_the_width_is_fixed() -> None:
    assert ConsoleWidth.of(io.StringIO()).columns == PLAIN_WIDTH
    assert ConsoleWidth.of(None).columns == PLAIN_WIDTH
