"""Ползунок «да / нет» окна настройщика на tk.Canvas (CLAUDE.md §8.2, §14 решение 37).

Как в iPhone: включён — зелёная дорожка и бегунок справа, выключен — бледно-белая дорожка и бегунок слева; что именно
рисовать, считает `SwitchLook` (app\\setup\\fields\\switch_look.py), холст только рисует. Значение — переменная Tk
`variable`: ползунок следит за ней, поэтому два ползунка одной переменной (ползунок линии на «Главной» и на её вкладке)
всегда показывают одно. Переключают щелчок, пробел и Enter; после переключения зовётся `command`. Бегунок едет плавно
около 150 мс. Недоступный ползунок (`set_enabled`) бледный, не переключается и фокус не берёт; в фокусе — рамка цвета
фокуса темы. Ползунок растёт с масштабом экрана: его размеры при 100 % умножаются на масштаб Tk.
"""
from __future__ import annotations

import dataclasses
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Final

from app.setup.fields.switch_look import SwitchBox, SwitchLook
from app.setup.tabs.language_box import VARIABLE_WRITE
from app.setup.tabs.tab_event import BREAK, TkEvent
from app.setup.tabs.tab_scroll import BACKGROUND_OPTION, FRAME_STYLE
from app.setup.tabs.tab_theme import SWITCH_FRAME_MS

HAND_CURSOR: Final[str] = "hand2"
TK_SCALING: Final[tuple[str, ...]] = ("tk", "scaling")   # команда Tcl: масштаб экрана в пикселях на пункт
TK_SCALING_AT_100: Final[float] = 96 / 72   # «tk scaling» на экране 100 %: пикселей в пункте
RADIUS_DIVISOR: Final[int] = 2              # радиус конца капсулы — половина её высоты


class ToggleSwitch(tk.Canvas):
    """Ползунок. Поля: переменная значения, что сделать после переключения, вид (`look`), имя слежки за переменной и id
    следующего шага анимации (None — бегунок стоит)."""

    def __init__(self, parent: tk.Misc, variable: tk.BooleanVar, command: Callable[[], None] | None = None) -> None:
        background: str = str(ttk.Style(parent).lookup(FRAME_STYLE, BACKGROUND_OPTION))
        scale: float = float(parent.tk.call(*TK_SCALING)) / TK_SCALING_AT_100
        self.look: SwitchLook = SwitchLook.of(variable.get(), scale, background)
        canvas: SwitchBox = self.look.canvas
        super().__init__(
            parent, width=canvas.right, height=canvas.bottom, highlightthickness=0, borderwidth=0,
            background=background, takefocus=True, cursor=HAND_CURSOR,
        )
        self.variable: tk.BooleanVar = variable
        self.command: Callable[[], None] | None = command
        self.slide_id: str | None = None
        self.trace_name: str = variable.trace_add(VARIABLE_WRITE, lambda *_args: self.follow())
        for event in (TkEvent.BUTTON_PRESS, TkEvent.SPACE, TkEvent.RETURN):
            self.bind(event, self.flip)
        self.bind(TkEvent.FOCUS_IN, lambda _event: self._focus(True))
        self.bind(TkEvent.FOCUS_OUT, lambda _event: self._focus(False))
        self.bind(TkEvent.DESTROY, self._forget, add=True)
        self.draw()

    @property
    def is_enabled(self) -> bool:
        return self.look.is_enabled

    def flip(self, _event: tk.Event | None = None) -> str:
        """Щелчок, пробел или Enter: доступный ползунок меняет значение и зовёт `command`."""
        if self.look.is_enabled:
            self.focus_set()
            self.variable.set(not self.variable.get())
            if self.command is not None:
                self.command()
        return BREAK

    def set_enabled(self, is_enabled: bool) -> None:
        """Доступен ли ползунок: недоступный бледный, не переключается и фокус не берёт."""
        self.look = dataclasses.replace(self.look, is_enabled=is_enabled)
        self.configure(takefocus=is_enabled)
        self.draw()

    def follow(self) -> None:
        """Переменная сменилась: бегунок едет к своему месту."""
        self.look = dataclasses.replace(self.look, is_on=self.variable.get())
        if self.slide_id is None:
            self._slide()

    def draw(self) -> None:
        """Холст заново по виду: рамка фокуса, рамка дорожки, дорожка, тень и бегунок."""
        look: SwitchLook = self.look
        self.delete(tk.ALL)
        self._capsule(look.canvas, look.ring_color)
        self._capsule(look.track, look.border_color)
        self._capsule(look.track.grown(-1), look.track_color)
        self.create_oval(*self._corners(look.shadow), fill=look.shadow_color, outline="")
        self.create_oval(*self._corners(look.knob), fill=look.knob_color, outline="")

    def _slide(self) -> None:
        """Шаг анимации; бегунок не доехал — следующий шаг через SWITCH_FRAME_MS."""
        stepped: SwitchLook = self.look.stepped()
        if stepped == self.look:
            self.slide_id = None
            return
        self.look = stepped
        self.draw()
        self.slide_id = self.after(SWITCH_FRAME_MS, self._slide)

    def _capsule(self, box: SwitchBox, color: str) -> None:
        """Скруглённая капсула в прямоугольнике `box`: два круга по краям и прямоугольник между ними."""
        side: int = box.bottom - box.top
        radius: int = side // RADIUS_DIVISOR
        self.create_oval(box.left, box.top, box.left + side, box.bottom, fill=color, outline="")
        self.create_oval(box.right - side, box.top, box.right, box.bottom, fill=color, outline="")
        self.create_rectangle(box.left + radius, box.top, box.right - radius, box.bottom, fill=color, outline="")

    def _corners(self, box: SwitchBox) -> tuple[int, ...]:
        return (box.left, box.top, box.right, box.bottom)

    def _focus(self, has_focus: bool) -> None:
        self.look = dataclasses.replace(self.look, has_focus=has_focus)
        self.draw()

    def _forget(self, _event: tk.Event) -> None:
        """Ползунок уничтожен: слежка за переменной и шаг анимации снимаются — иначе Tcl позвал бы удалённую
        команду."""
        self.variable.trace_remove(VARIABLE_WRITE, self.trace_name)
        if self.slide_id is not None:
            self.after_cancel(self.slide_id)
            self.slide_id = None
