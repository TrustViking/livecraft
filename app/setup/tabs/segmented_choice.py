"""Выбор из двух названных значений в окне настройщика — две кнопки рядом (CLAUDE.md §8.2, §14 решение 37).

Кнопки — ttk.Radiobutton со стилем на основе Toolbutton (`SEGMENT_STYLE`): выбранная — зелёная с белым текстом.
Значение — переменная Tk `variable`: кнопка варианта стоит нажатой, когда переменная равна её значению. Что за
варианты и как они подписаны и доступен ли выбор (`set_enabled` — весь выбор, `allow` — один вариант), знает модель;
здесь только кнопки. `ChoiceRow` — строка «Главной» с таким выбором и строкой текста под ним (вход, ключи).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from tkinter import ttk

from app.setup.tabs.field_shade import ENABLED_STATE
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_theme import HEADING_STYLE, SEGMENT_STYLE


class ChoiceButton(ttk.Radiobutton):
    """Кнопка варианта. Вариант, который модель не разрешает (`is_allowed`), недоступен при любом состоянии поля:
    бледность полей (`FieldShades`) включает поле целиком последней, и без этого правила кнопка неразрешённого
    варианта стала бы нажимаемой вместе с полем."""

    is_allowed: bool = True

    def state(self, statespec: Iterable[str] | None = None) -> object:
        """Состояние Tk кнопки; неразрешённый вариант на любую смену получает «недоступна»."""
        if statespec is None or self.is_allowed:
            return super().state(statespec)
        return super().state([tk.DISABLED])


class SegmentedChoice:
    """Кнопки вариантов в ряд. Поля: рамка ряда и кнопки по значениям вариантов."""

    def __init__(
        self, parent: tk.Misc, variable: tk.StringVar, labels: Mapping[str, str], command: Callable[[], None]
    ) -> None:
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.buttons: dict[str, ChoiceButton] = {}
        for value, label in labels.items():
            button: ChoiceButton = ChoiceButton(
                self.frame, text=label, value=value, variable=variable, command=command, style=SEGMENT_STYLE
            )
            button.pack(side=tk.LEFT)
            self.buttons[value] = button

    def set_enabled(self, is_enabled: bool) -> None:
        """Кнопки доступны или нет; выбранная остаётся нажатой и недоступной."""
        for button in self.buttons.values():
            button.state([ENABLED_STATE if is_enabled else tk.DISABLED])

    def allow(self, value: str, is_allowed: bool) -> None:
        """Вариант `value` можно выбрать или нет; выбранный неразрешённый остаётся нажатым и недоступным."""
        button: ChoiceButton = self.buttons[value]
        button.is_allowed = is_allowed
        button.state([ENABLED_STATE])


class ChoiceRow:
    """Строка выбора: ряд (`top`) с подписью (если она есть) и кнопками вариантов, под ним — строка текста (`text`).
    Поля: рамка строки, ряд, кнопки и строка текста."""

    def __init__(self, parent: tk.Misc, title: str, choice: ChoiceSpec) -> None:
        self.frame: ttk.Frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        self.top: ttk.Frame = ttk.Frame(self.frame)
        self.top.pack(fill=tk.X, anchor=tk.W)
        if title:
            ttk.Label(self.top, text=title, style=HEADING_STYLE).pack(side=tk.LEFT, padx=(0, PAD))
        self.choice: SegmentedChoice = SegmentedChoice(self.top, choice.variable, choice.labels, choice.command)
        self.choice.frame.pack(side=tk.LEFT)
        self.text: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.text.pack(fill=tk.X, anchor=tk.W)


@dataclass(frozen=True)
class ChoiceSpec:
    """Что выбирать: переменная Tk, подписи вариантов по значениям и что сделать после выбора."""

    variable: tk.StringVar
    labels: Mapping[str, str]
    command: Callable[[], None]
