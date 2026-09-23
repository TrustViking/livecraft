"""Вкладки окна настройщика: Tk поверх моделей app\\setup\\panels (CLAUDE.md §8.2).

Вкладка только рисует ответы своей модели и передаёт ей ввод: правил проверки, записи файлов и шифрования
здесь нет. Здесь же — общее для трёх вкладок: отступы и строка проблемы правки (`ProblemLine`).
Значение сейфа в виджет не попадает никогда: вкладка «Ключи и ссылки» показывает только маску (§7.4).
"""
from __future__ import annotations

from collections.abc import Mapping
from tkinter import ttk
from typing import Final

from app.config.loader import SettingProblem
from app.ui import messages_ru as msg

PAD: Final[int] = 6
TEXT_WRAP_PIXELS: Final[int] = 760
PROBLEM_FOREGROUND: Final[str] = "#b00020"
NOTICE_JOINER: Final[str] = "\n\n"
TEXT_KEY: Final[str] = "text"


class ProblemLine:
    """Красная строка под полями: что не так с правкой. Пустая — проблемы нет.

    Подпись поля берётся по ключу проблемы из словаря подписей вкладки (messages_ru); незнакомый ключ
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
        """Показать проблему модели с русской подписью поля; None — очистить строку."""
        if problem is None:
            self.show_text(None)
            return
        label: str = self._labels.get(problem.key, problem.key)
        self.show_text(msg.SETUP_PROBLEM_LINE.format(label=label, text=problem.text))
