"""Вид ползунка «да / нет» окна настройщика — без Tk (CLAUDE.md §8.2, §14 решение 37).

Ползунок — как в iPhone: дорожка — скруглённая капсула 34×20 при масштабе 100 % (дальше — по масштабу Tk), бегунок —
белый круг с мягкой тенью. Включён — дорожка зелёная и бегунок справа; выключен — дорожка бледно-белая с тонкой рамкой
и бегунок слева. Пока бегунок едет, положение (`position`, 0 — слева, 1 — справа) дробное, и цвета дорожки и рамки
переходят от выключенных к включённым по тому же положению. Недоступен — те же цвета, смешанные с фоном окна наполовину;
в фокусе — рамка цвета фокуса темы вокруг дорожки. Цвета и размеры — константы темы (app\\setup\\tabs\\tab_theme.py);
холст Tk рисует ровно то, что здесь посчитано (app\\setup\\tabs\\toggle_switch.py).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Final

from app.setup.tabs.tab_theme import (
    SWITCH_FOCUS_RING,
    SWITCH_KNOB,
    SWITCH_KNOB_INSET,
    SWITCH_OFF,
    SWITCH_OFF_BORDER,
    SWITCH_ON,
    SWITCH_RING_WIDTH,
    SWITCH_SHADOW_BASE,
    SWITCH_SHADOW_OFFSET,
    SWITCH_SHADOW_SHARE,
    SWITCH_SLIDE_MS,
    SWITCH_FRAME_MS,
    SWITCH_TRACK_HEIGHT,
    SWITCH_TRACK_WIDTH,
    WINDOW_BACKGROUND,
    RgbColor,
)

SIDES: Final[int] = 2                      # отступ — с обеих сторон
FULL_SCALE: Final[float] = 1.0              # масштаб 100 %
OFF_POSITION: Final[float] = 0.0
ON_POSITION: Final[float] = 1.0
# Шагов анимации на весь путь бегунка: весь путь — за SWITCH_SLIDE_MS.
SLIDE_FRAMES: Final[int] = SWITCH_SLIDE_MS // SWITCH_FRAME_MS


@dataclass(frozen=True)
class SwitchBox:
    """Прямоугольник на холсте ползунка: левый верхний и правый нижний углы в пикселях."""

    left: int
    top: int
    right: int
    bottom: int

    def shifted(self, down: int) -> SwitchBox:
        return SwitchBox(self.left, self.top + down, self.right, self.bottom + down)

    def grown(self, by: int) -> SwitchBox:
        """Прямоугольник, шире на `by` с каждой стороны."""
        return SwitchBox(self.left - by, self.top - by, self.right + by, self.bottom + by)


@dataclass(frozen=True)
class SwitchLook:
    """Вид ползунка: включён ли, положение бегунка, доступен ли, в фокусе ли, масштаб экрана и фон окна (с ним
    смешиваются цвета недоступного ползунка, им же рисуется рамка без фокуса)."""

    is_on: bool
    position: float
    is_enabled: bool = True
    has_focus: bool = False
    scale: float = FULL_SCALE
    background: str = WINDOW_BACKGROUND

    @classmethod
    def of(cls, is_on: bool, scale: float, background: str) -> SwitchLook:
        """Ползунок в покое: бегунок там, где велит состояние."""
        return cls(is_on=is_on, position=ON_POSITION if is_on else OFF_POSITION, scale=scale, background=background)

    def stepped(self) -> SwitchLook:
        """Вид через один шаг анимации: бегунок на шаг (`SLIDE_FRAMES` шагов на весь путь) ближе к своему месту, не
        дальше него; доехал — тот же вид."""
        frame: int = round(self.position * SLIDE_FRAMES)
        if self.is_on:
            return dataclasses.replace(self, position=min(ON_POSITION, (frame + 1) / SLIDE_FRAMES))
        return dataclasses.replace(self, position=max(OFF_POSITION, (frame - 1) / SLIDE_FRAMES))

    @property
    def canvas(self) -> SwitchBox:
        """Холст: дорожка и поле вокруг неё под рамку фокуса."""
        margin: int = self._pixels(SWITCH_RING_WIDTH)
        width: int = self._pixels(SWITCH_TRACK_WIDTH) + SIDES * margin
        return SwitchBox(0, 0, width, self._pixels(SWITCH_TRACK_HEIGHT) + SIDES * margin)

    @property
    def track(self) -> SwitchBox:
        """Дорожка — капсула во весь холст без поля под рамку."""
        return self.canvas.grown(-self._pixels(SWITCH_RING_WIDTH))

    @property
    def knob(self) -> SwitchBox:
        """Бегунок — круг внутри дорожки с отступом; по горизонтали — по положению."""
        inset: int = self._pixels(SWITCH_KNOB_INSET)
        track: SwitchBox = self.track
        size: int = track.bottom - track.top - SIDES * inset
        travel: int = track.right - track.left - SIDES * inset - size
        left: int = track.left + inset + round(travel * self.position)
        return SwitchBox(left, track.top + inset, left + size, track.top + inset + size)

    @property
    def shadow(self) -> SwitchBox:
        """Тень бегунка — тот же круг чуть ниже."""
        return self.knob.shifted(self._pixels(SWITCH_SHADOW_OFFSET))

    @property
    def track_color(self) -> str:
        return self._shown(self._track)

    @property
    def border_color(self) -> str:
        """Рамка дорожки: у выключенной — тонкая серая, у включённой сливается с зелёным."""
        return self._shown(RgbColor.of(SWITCH_OFF_BORDER).mixed(RgbColor.of(SWITCH_ON), self.position))

    @property
    def knob_color(self) -> str:
        return self._shown(RgbColor.of(SWITCH_KNOB))

    @property
    def shadow_color(self) -> str:
        return self._shown(self._track.mixed(RgbColor.of(SWITCH_SHADOW_BASE), SWITCH_SHADOW_SHARE))

    @property
    def ring_color(self) -> str:
        """Рамка фокуса: в фокусе — цвет фокуса темы, иначе — фон окна (рамки не видно)."""
        return SWITCH_FOCUS_RING if self.has_focus else self.background

    @property
    def _track(self) -> RgbColor:
        """Дорожка по положению: от бледно-белой к зелёной."""
        return RgbColor.of(SWITCH_OFF).mixed(RgbColor.of(SWITCH_ON), self.position)

    def _shown(self, color: RgbColor) -> str:
        """Цвет, каким его видно: недоступный ползунок — наполовину с фоном окна."""
        if self.is_enabled:
            return color.text
        return color.dimmed(self.background).text

    def _pixels(self, size: int) -> int:
        """Размер при масштабе 100 % — в пикселях экрана."""
        return round(size * self.scale)
