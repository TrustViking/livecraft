"""Блок «Какой должна быть таблица» на вкладке «Таблица плана» (CLAUDE.md §8.2 п.2, §14 решения 26, 27).

Заголовок, текст, образец таблицы (шапка и строка — подписями Tk из текстов каталога, по модели `TableSample`), второй
текст с поясом программы, кнопка «Проверить таблицу» и строка итога. Проверку делает модель `TableCheck`; окно
запускает её в фоновом потоке (`CheckLine`), чтобы не замирать на сети и входе в Google. Своих правил у блока нет.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Final

from app.setup.panels.table_check import TableCheck, TableSample, TableVerdict
from app.setup.tabs.check_line import CheckLine, CheckTexts
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_theme import HEADING_STYLE
from app.ui.messages import msg

SAMPLE_BORDER: Final[int] = 1           # ячейка образца — в рамке, как клетка таблицы
SAMPLE_HEADER_ROW: Final[int] = 0
SAMPLE_VALUE_ROW: Final[int] = 1


class TableBlock:
    """Образец таблицы и её проверка. Поля: модель проверки `check`, образец, подписи и строка проверки `line`."""

    def __init__(self, parent: ttk.Frame, check: TableCheck, timezone: str) -> None:
        self.check: TableCheck = check
        self.sample: TableSample = TableSample(timezone)
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        ttk.Label(self.frame, text=msg.SETUP_TABLE_TITLE, style=HEADING_STYLE).pack(anchor=tk.W)
        self._text(msg.SETUP_TABLE_TEXT_BEFORE)
        self.sample_frame: ttk.Frame = self._sample()
        self.rules: ttk.Label = self._text(self.sample.rules)
        texts: CheckTexts = CheckTexts(
            button=msg.SETUP_TABLE_BUTTON_CHECK,
            checking=msg.SETUP_TABLE_CHECKING,
            login=msg.SETUP_TABLE_LOGIN,
            interrupted=TableVerdict.failed(msg.SETUP_TABLE_INTERRUPTED),
        )
        self.line: CheckLine = CheckLine(self.frame, texts, lambda: self.check.run)

    @property
    def button(self) -> ttk.Button:
        return self.line.button

    @property
    def is_running(self) -> bool:
        return self.line.is_running

    @property
    def result_text(self) -> str:
        return self.line.result_text

    def show_rules(self, timezone: str) -> None:
        """Текст после образца — с поясом программы: пояс сменили на «Дополнительно» — окно говорит новый."""
        self.sample = TableSample(timezone)
        self.rules.configure(text=self.sample.rules)

    def _text(self, text: str) -> ttk.Label:
        label: ttk.Label = ttk.Label(self.frame, text=text, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        label.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        return label

    def _sample(self) -> ttk.Frame:
        """Образец: шапка и строка ячейками в рамке."""
        frame: ttk.Frame = ttk.Frame(self.frame)
        frame.pack(anchor=tk.W, pady=(PAD, 0))
        rows: tuple[tuple[int, tuple[str, ...], str], ...] = (
            (SAMPLE_HEADER_ROW, self.sample.header, HEADING_STYLE),
            (SAMPLE_VALUE_ROW, self.sample.row, ""),
        )
        for row, cells, style in rows:
            for column, text in enumerate(cells):
                cell: ttk.Label = ttk.Label(
                    frame, text=text, style=style, relief=tk.SOLID, borderwidth=SAMPLE_BORDER, padding=PAD
                )
                cell.grid(row=row, column=column, sticky=tk.NSEW)
        return frame
