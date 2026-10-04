"""Общий вид вкладок настройщика: отступы, ширина текста, цвета строк и строка проблемы (CLAUDE.md §8.2).

`ProblemLine` — красная строка под полями: что не так с правкой. Подпись поля она берёт по ключу проблемы из
словаря подписей вкладки (каталог msg).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Mapping
from tkinter import ttk
from typing import Final

from app.config.json_node import SettingProblem
from app.ui.messages import msg

PAD: Final[int] = 6
TEXT_WRAP_PIXELS: Final[int] = 760
PROBLEM_FOREGROUND: Final[str] = "#b00020"
HINT_FOREGROUND: Final[str] = "#6b6b6b"     # серая подсказка: читается, но не спорит с подписью поля
HINT_WRAP_PIXELS: Final[int] = 420
TEXT_KEY: Final[str] = "text"               # параметр виджета Tk с его текстом
READONLY: Final[str] = "readonly"           # состояние ttk.Combobox: только выбор из списка


class ProblemLine:
    """Красная строка под полями: что не так с правкой. Пустая — проблемы нет.

    Подпись поля берётся по ключу проблемы из словаря подписей вкладки (каталог msg); незнакомый ключ
    показывается как есть — так путь поля из загрузчика не теряется.
    """

    def __init__(self, parent: ttk.Frame, labels: Mapping[str, str]) -> None:
        self.label: ttk.Label = ttk.Label(parent, foreground=PROBLEM_FOREGROUND, wraplength=TEXT_WRAP_PIXELS)
        self._labels: Mapping[str, str] = labels

    @property
    def text(self) -> str:
        """Что сейчас написано в строке."""
        return str(self.label.cget(TEXT_KEY))

    def show_text(self, text: str | None) -> None:
        """Показать готовый текст; None — очистить строку."""
        self.label.configure(text="" if text is None else text)

    def show_problem(self, problem: SettingProblem | None) -> None:
        """Показать проблему модели с подписью поля на языке окна; None — очистить строку."""
        if problem is None:
            self.show_text(None)
            return
        label: str = self._labels.get(problem.key, problem.key)
        self.show_text(msg.SETUP_PROBLEM_LINE.format(label=label, text=problem.text))
