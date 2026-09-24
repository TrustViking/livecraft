"""Вкладки окна настройщика: Tk поверх моделей app\\setup\\panels (CLAUDE.md §8.2).

Вкладка только рисует ответы своей модели и передаёт ей ввод: правил проверки, записи файлов и шифрования
здесь нет. Здесь же — общее для трёх вкладок: отступы, строка проблемы правки (`ProblemLine`) и сочетания
правки полей ввода в любой раскладке (`EditShortcuts`).
Значение сейфа в виджет не попадает никогда: вкладка «Ключи и ссылки» показывает только маску (§7.4).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Mapping
from dataclasses import dataclass
from tkinter import ttk
from typing import Final

from app.config.loader import SettingProblem
from app.ui import messages_ru as msg

PAD: Final[int] = 6
TEXT_WRAP_PIXELS: Final[int] = 760
PROBLEM_FOREGROUND: Final[str] = "#b00020"
NOTICE_JOINER: Final[str] = "\n\n"
TEXT_KEY: Final[str] = "text"
BREAK: Final[str] = "break"                 # ответ обработчика Tk: дальше событие не идёт
CONTROL_KEY_PRESS: Final[str] = "<Control-KeyPress>"
PASTE_EVENT: Final[str] = "<<Paste>>"
SELECT_ALL_EVENT: Final[str] = "<<SelectAll>>"
CUT_EVENT: Final[str] = "<<Cut>>"
COPY_EVENT: Final[str] = "<<Copy>>"
# Коды клавиш Windows (virtual-key) — одни и те же в любой раскладке, в отличие от keysym.
KEYCODE_V: Final[int] = 86
KEYCODE_A: Final[int] = 65
KEYCODE_X: Final[int] = 88
KEYCODE_C: Final[int] = 67
# Классы полей ввода окна: ttk.Entry, tk.Entry и ttk.Combobox.
EDITABLE_CLASSES: Final[frozenset[str]] = frozenset({"TEntry", "Entry", "TCombobox"})


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


@dataclass(frozen=True)
class EditShortcut:
    """Одно сочетание правки: код клавиши, её латинская буква и событие Tk, которое оно означает.

    Штатно Tk связывает событие с keysym латинской буквы (`<Control-Key-v>` → `<<Paste>>`). В другой
    раскладке та же клавиша даёт другой keysym (`Cyrillic_em`), и штатная связь молчит.
    """

    keycode: int
    letter: str
    virtual_event: str

    def matches(self, event: tk.Event) -> bool:
        """Нажата эта клавиша, а штатная связь Tk не сработала: keysym — не латинская буква клавиши.

        Латинская буква (в любом регистре — Caps Lock) уже отдана штатной связью: второе событие дало бы
        вторую вставку.
        """
        return event.keycode == self.keycode and event.keysym.lower() != self.letter


class EditShortcuts:
    """Ctrl+V, Ctrl+A, Ctrl+X и Ctrl+C в полях ввода окна — в любой раскладке клавиатуры.

    Обработчик вешается на тег `all` — его Tk проверяет последним, после привязок самого виджета и его
    класса. Поэтому запрет на виджете (поля ключей не копируются) действует и здесь: сгенерированное
    событие попадает сначала в привязку виджета. Сам буфер обмена объект не читает и не пишет — только
    отдаёт полю штатное событие Tk, как это сделала бы латинская раскладка.
    """

    def __init__(self, root: tk.Misc, shortcuts: tuple[EditShortcut, ...]) -> None:
        self.root: tk.Misc = root
        self.shortcuts: tuple[EditShortcut, ...] = shortcuts

    @classmethod
    def install(cls, root: tk.Misc) -> EditShortcuts:
        """Четыре сочетания правки на корне окна."""
        shortcuts: EditShortcuts = cls(
            root,
            (
                EditShortcut(KEYCODE_V, "v", PASTE_EVENT),
                EditShortcut(KEYCODE_A, "a", SELECT_ALL_EVENT),
                EditShortcut(KEYCODE_X, "x", CUT_EVENT),
                EditShortcut(KEYCODE_C, "c", COPY_EVENT),
            ),
        )
        root.bind_all(CONTROL_KEY_PRESS, shortcuts.handle, add=True)
        return shortcuts

    def handle(self, event: tk.Event) -> str | None:
        """Поле ввода и нелатинская раскладка — отдать полю событие правки; иначе не вмешиваться."""
        widget: object = event.widget
        if not isinstance(widget, tk.Misc) or widget.winfo_class() not in EDITABLE_CLASSES:
            return None
        for shortcut in self.shortcuts:
            if shortcut.matches(event):
                widget.event_generate(shortcut.virtual_event)
                return BREAK
        return None
