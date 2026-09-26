"""Вид вкладок окна настройщика (CLAUDE.md §8.2; итог смотра окна 23-09-2026).

Вкладки должны быть заметны человеку, который видит окно впервые: отступ внутри вкладки, промежуток между
вкладками, выбранная — жирная и на светлом фоне.
"""
from __future__ import annotations

import tkinter as tk
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
TAB_SELECTED_BACKGROUND: Final[str] = "#ffffff"
TAB_BACKGROUND: Final[str] = "#c9c6bf"      # темнее фона окна clam (#dcdad5): невыбранные не сливаются с ним
SELECTED: Final[str] = "selected"
NOT_SELECTED: Final[str] = "!selected"
DEFAULT_FONT: Final[str] = "TkDefaultFont"


class SetupTheme:
    """Стиль вкладок окна. Поля: стиль ttk, шрифт выбранной вкладки и картинка промежутка — поля объекта,
    иначе их соберёт мусорщик и Tk потеряет их посреди работы окна."""

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
        self.style.map(
            TAB_STYLE,
            background=[(SELECTED, TAB_SELECTED_BACKGROUND), (NOT_SELECTED, TAB_BACKGROUND)],
            font=[(SELECTED, self.selected_tab_font)],
            padding=[(SELECTED, TAB_PADDING)],      # clam сужает отступ выбранной вкладки — возвращаем свой
            expand=[(SELECTED, TAB_SELECTED_EXPAND)],
        )
