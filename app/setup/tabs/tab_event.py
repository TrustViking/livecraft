"""События Tk окна настройщика и правка полей ввода в любой раскладке (CLAUDE.md §8.2).

`TkEvent` — имена событий Tk, на которые окно вешает обработчики или которые оно порождает. `EditShortcuts` —
вставка, выделение, вырезание и копирование в полях ввода в любой раскладке клавиатуры.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

BREAK: Final[str] = "break"                 # ответ обработчика Tk: дальше событие не идёт
# Коды клавиш Windows (virtual-key) — одни и те же в любой раскладке, в отличие от keysym.
KEYCODE_V: Final[int] = 86
KEYCODE_A: Final[int] = 65
KEYCODE_X: Final[int] = 88
KEYCODE_C: Final[int] = 67
# Классы полей ввода окна: ttk.Entry, tk.Entry и ttk.Combobox.
EDITABLE_CLASSES: Final[frozenset[str]] = frozenset({"TEntry", "Entry", "TCombobox"})


class TkEvent(StrEnum):
    """Имена событий Tk. StrEnum: Tk и строки шаблонов получают само имя события."""

    CONTROL_KEY_PRESS = "<Control-KeyPress>"
    KEY_PRESS = "<KeyPress>"
    ESCAPE = "<Escape>"
    PASTE = "<<Paste>>"
    SELECT_ALL = "<<SelectAll>>"
    CUT = "<<Cut>>"
    COPY = "<<Copy>>"
    TAB_CHANGED = "<<NotebookTabChanged>>"
    TREE_SELECT = "<<TreeviewSelect>>"
    COMBOBOX_SELECTED = "<<ComboboxSelected>>"


@dataclass(frozen=True)
class EditShortcut:
    """Одно сочетание правки: код клавиши, её латинская буква и событие Tk, которое оно означает.

    Штатно Tk связывает событие с keysym латинской буквы (`<Control-Key-v>` → `<<Paste>>`). В другой
    раскладке та же клавиша даёт другой keysym (`Cyrillic_em`), и штатная связь молчит.
    """

    keycode: int
    letter: str
    virtual_event: TkEvent

    def matches(self, event: tk.Event) -> bool:
        """Нажата эта клавиша, а штатная связь Tk не сработала: keysym — не латинская буква клавиши.

        Латинская буква (в любом регистре — Caps Lock) уже отдана штатной связью: второе событие дало бы
        вторую вставку.
        """
        return event.keycode == self.keycode and event.keysym.lower() != self.letter


EDIT_SHORTCUTS: Final[tuple[EditShortcut, ...]] = (
    EditShortcut(KEYCODE_V, "v", TkEvent.PASTE),
    EditShortcut(KEYCODE_A, "a", TkEvent.SELECT_ALL),
    EditShortcut(KEYCODE_X, "x", TkEvent.CUT),
    EditShortcut(KEYCODE_C, "c", TkEvent.COPY),
)


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
        shortcuts: EditShortcuts = cls(root, EDIT_SHORTCUTS)
        root.bind_all(TkEvent.CONTROL_KEY_PRESS, shortcuts.handle, add=True)
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
