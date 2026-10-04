"""Вид вкладок окна настройщика (CLAUDE.md §8.2; итоги смотра окна 23-09-2026 и 27-09-2026).

Вкладки должны быть заметны человеку, который видит окно впервые: отступ внутри вкладки, промежуток между
вкладками, выбранная — жирная и на светлом фоне. Подписи полей и заголовки шагов — жирные (`HEADING_STYLE`); задано
поле или нет — видно цветом статуса (`STATUS_SET_FOREGROUND`, `STATUS_UNSET_FOREGROUND`).

Поле «да / нет» — ползунок как в iPhone (§14 решение 37, app\\setup\\tabs\\toggle_switch.py): его цвета и размеры
при масштабе 100 % — константы `SWITCH_*` ниже. Выбор из двух названных значений — две кнопки рядом
(`SEGMENT_STYLE`): выбранная — зелёная с белым текстом, тем же зелёным, что включённый ползунок; недоступный выбор
бледнеет так же, как недоступный ползунок (`RgbColor.dimmed`). Поле, которое не нужно ни одной работающей линии, —
бледное (`DIM_FOREGROUND`).
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from enum import Enum
from tkinter import font, ttk
from typing import Final

THEME: Final[str] = "clam"                  # vista и xpnative фон вкладки не берут: рисуют её картинкой
TAB_STYLE: Final[str] = "TNotebook.Tab"
TAB_GAP_ELEMENT: Final[str] = "Livecraft.tabgap"
IMAGE_ELEMENT_KIND: Final[str] = "image"    # вид элемента ttk: картинка с отступами
LAYOUT_STICKY: Final[str] = "sticky"        # ключи узла раскладки стиля ttk
LAYOUT_CHILDREN: Final[str] = "children"
TAB_PADDING: Final[tuple[int, int]] = (16, 6)                    # внутри вкладки: по горизонтали, по вертикали
TAB_GAP_PADDING: Final[tuple[int, int, int, int]] = (3, 0, 3, 0)  # с каждого бока: между вкладками — 6
TAB_SELECTED_EXPAND: Final[tuple[int, int, int, int]] = (0, 2, 0, 0)  # выбранная чуть выше, промежуток не съедает
WHITE: Final[str] = "#ffffff"
TAB_SELECTED_BACKGROUND: Final[str] = WHITE
TAB_BACKGROUND: Final[str] = "#c9c6bf"      # темнее фона окна clam (#dcdad5): невыбранные не сливаются с ним
SELECTED: Final[str] = "selected"
NOT_SELECTED: Final[str] = "!selected"
DEFAULT_FONT: Final[str] = "TkDefaultFont"
HEADING_STYLE: Final[str] = "Livecraft.Heading.TLabel"   # подпись поля и заголовок шага
STATUS_SET_FOREGROUND: Final[str] = "#2e7d32"     # зелёный: задано, нужда закрыта
STATUS_UNSET_FOREGROUND: Final[str] = "#c62828"   # красный: не задано, нужда не закрыта
WINDOW_BACKGROUND: Final[str] = "#dcdad5"         # фон окна темы clam: с ним смешиваются цвета недоступного ползунка
DIM_FOREGROUND: Final[str] = "#999999"            # бледная подпись поля, которое не нужно ни одной работающей линии
# Ползунок (как в iPhone) при масштабе 100 %: дорожка 34×20 (две трети прежних 51×31: тот был слишком
# крупным), бегунок — белый круг с отступом 2 и тенью ниже на 1, рамка фокуса — 2 вокруг дорожки.
SWITCH_ON: Final[str] = "#34c759"                 # включён: зелёная дорожка
SWITCH_OFF: Final[str] = "#e9e9eb"                # выключен: бледно-белая дорожка
SWITCH_OFF_BORDER: Final[str] = "#d1d1d6"         # тонкая рамка выключенной дорожки
SWITCH_KNOB: Final[str] = WHITE
SWITCH_SHADOW_BASE: Final[str] = "#000000"        # тень бегунка — цвет дорожки, чуть затемнённый
SWITCH_SHADOW_SHARE: Final[float] = 0.18
SWITCH_DIM_SHARE: Final[float] = 0.5              # недоступен: цвета смешаны с фоном окна наполовину
SWITCH_FOCUS_RING: Final[str] = "#6f9dc6"         # рамка фокуса — цвет фокуса полей темы clam
SWITCH_TRACK_WIDTH: Final[int] = 34
SWITCH_TRACK_HEIGHT: Final[int] = 20
SWITCH_KNOB_INSET: Final[int] = 2
SWITCH_SHADOW_OFFSET: Final[int] = 1
SWITCH_RING_WIDTH: Final[int] = 2                 # толщина рамки фокуса вокруг дорожки
SWITCH_SLIDE_MS: Final[int] = 150                 # бегунок едет плавно около 150 мс
SWITCH_FRAME_MS: Final[int] = 15                  # шаг анимации бегунка
SEGMENT_STYLE: Final[str] = "Livecraft.Toolbutton"    # две кнопки рядом: ttk.Radiobutton на основе Toolbutton
SEGMENT_PADDING: Final[tuple[int, int]] = (12, 4)


class ColorText(str, Enum):
    """Запись цвета Tk «#rrggbb»."""

    MARK = "#"


@dataclass(frozen=True)
class RgbColor:
    """Цвет тремя каналами 0..255."""

    red: int
    green: int
    blue: int

    @classmethod
    def of(cls, text: str) -> RgbColor:
        """Цвет из записи Tk «#rrggbb»."""
        red, green, blue = bytes.fromhex(text.removeprefix(ColorText.MARK))
        return cls(red, green, blue)

    @property
    def channels(self) -> tuple[int, ...]:
        return (self.red, self.green, self.blue)

    @property
    def text(self) -> str:
        """Запись Tk «#rrggbb»."""
        return ColorText.MARK + bytes(self.channels).hex()

    def mixed(self, other: RgbColor, share: float) -> RgbColor:
        """Цвет на доле `share` пути к `other`: 0 — свой, 1 — `other`."""
        red, green, blue = (round(own + (theirs - own) * share) for own, theirs in zip(self.channels, other.channels))
        return RgbColor(red, green, blue)

    def dimmed(self, background: str) -> RgbColor:
        """Цвет недоступного поля выбора (ползунка, кнопки выбора): наполовину с фоном `background`."""
        return self.mixed(RgbColor.of(background), SWITCH_DIM_SHARE)


def status_foreground(is_set: bool) -> str:
    """Цвет статуса: задано — зелёный, нет — красный."""
    return STATUS_SET_FOREGROUND if is_set else STATUS_UNSET_FOREGROUND


class SetupTheme:
    """Стиль вкладок окна. Поля: стиль ttk, жирный шрифт (выбранная вкладка, подписи полей и заголовки шагов) и
    картинка промежутка — поля объекта, иначе их соберёт мусорщик и Tk потеряет их посреди работы окна."""

    def __init__(self, root: tk.Tk) -> None:
        self.style: ttk.Style = ttk.Style(root)
        self.selected_tab_font: font.Font = font.nametofont(DEFAULT_FONT, root=root).copy()
        self.tab_gap_image: tk.PhotoImage = tk.PhotoImage(master=root, width=1, height=1)

    @classmethod
    def applied_to(cls, root: tk.Tk) -> SetupTheme:
        """Стиль, уже поставленный окну `root`."""
        theme: SetupTheme = cls(root)
        theme.apply()
        return theme

    def apply(self) -> None:
        """Заметные вкладки: отступ внутри, промежуток между вкладками, выбранная — жирная и на светлом фоне.

        Тема Windows по умолчанию (vista) рисует вкладки картинками и фон вкладки не берёт — поэтому тема окна
        clam. Промежутка между вкладками в ttk нет: вкладка обёрнута прозрачным элементом с отступами по
        бокам, сквозь который видно фон ряда вкладок.
        """
        self.style.theme_use(THEME)
        self.selected_tab_font.configure(weight=font.BOLD)
        self.style.element_create(
            TAB_GAP_ELEMENT, IMAGE_ELEMENT_KIND, self.tab_gap_image, padding=TAB_GAP_PADDING, sticky=tk.NSEW
        )
        tab_layout: list[tuple[str, dict[str, object]]] = self.style.layout(TAB_STYLE)
        gap_node: dict[str, object] = {LAYOUT_STICKY: tk.NSEW, LAYOUT_CHILDREN: tab_layout}
        self.style.layout(TAB_STYLE, [(TAB_GAP_ELEMENT, gap_node)])
        self.style.configure(TAB_STYLE, padding=TAB_PADDING, font=DEFAULT_FONT)
        self.style.configure(HEADING_STYLE, font=self.selected_tab_font)
        self.style.map(
            TAB_STYLE,
            background=[(SELECTED, TAB_SELECTED_BACKGROUND), (NOT_SELECTED, TAB_BACKGROUND)],
            font=[(SELECTED, self.selected_tab_font)],
            padding=[(SELECTED, TAB_PADDING)],      # clam сужает отступ выбранной вкладки — возвращаем свой
            expand=[(SELECTED, TAB_SELECTED_EXPAND)],
        )
        self._apply_segments()

    def _apply_segments(self) -> None:
        """Две кнопки рядом: выбранная — зелёная с белым текстом, другая — бледно-белая в тонкой рамке. Недоступный
        выбор — те же цвета, смешанные с фоном окна, как у недоступного ползунка; состояния ttk проверяются по порядку,
        поэтому недоступные — первыми."""
        self.style.configure(
            SEGMENT_STYLE, padding=SEGMENT_PADDING, anchor=tk.CENTER, relief=tk.SOLID, borderwidth=1,
            bordercolor=SWITCH_OFF_BORDER,
        )
        self.style.map(
            SEGMENT_STYLE,
            background=[
                (tk.DISABLED, SELECTED, self._dimmed(SWITCH_ON)), (tk.DISABLED, NOT_SELECTED, self._dimmed(SWITCH_OFF)),
                (SELECTED, SWITCH_ON), (NOT_SELECTED, SWITCH_OFF),
            ],
            foreground=[(tk.DISABLED, SELECTED, self._dimmed(WHITE)), (SELECTED, WHITE)],
            bordercolor=[
                (tk.DISABLED, SELECTED, self._dimmed(SWITCH_ON)),
                (tk.DISABLED, NOT_SELECTED, self._dimmed(SWITCH_OFF_BORDER)),
                (SELECTED, SWITCH_ON),
            ],
        )

    def _dimmed(self, color: str) -> str:
        """Цвет `color` недоступной кнопки выбора — на фоне окна."""
        return RgbColor.of(color).dimmed(WINDOW_BACKGROUND).text
