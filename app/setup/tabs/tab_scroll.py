"""Прокручиваемая страница вкладки окна настройщика (CLAUDE.md §8.2; смотр окна 27-09-2026).

Вкладка, которая не помещается в окно, прокручивается: на экране 1080 строка папки Диска (теперь — на «Превью») уходила
за нижний край окна, и задать её было нельзя. `TabScroll` — внешняя рамка (её добавляет и выбирает блокнот), холст с
вертикальной полосой прокрутки и внутренняя рамка `body` в окне холста: в неё вкладка кладёт содержимое.

Правила страницы (`fit`): холст просит у окна размер содержимого — окно открывается таким же, как без прокрутки, а
ограничивает его высоту само окно (`SetupWindow`); ширина `body` — ширина холста; высота `body` — большее из нужной
содержимому и высоты холста: когда всё помещается, растягивающиеся виджеты (список каналов) занимают свободную высоту,
а когда нет — холст прокручивается. Содержимое меняется по ходу работы окна (строки проверок, оговорки, список чатов),
поэтому страница пересчитывается после любого изменения размеров в окне — одним отложенным пересчётом.

Колесо мыши над вкладкой прокручивает её (Windows: `event.delta` 120 на щелчок колеса; тачпад шлёт события помельче, их
delta копится в `wheel_rest`, пока не наберётся щелчок, — в обе стороны одинаково); над списком каналов (Treeview) и
списком чатов (Listbox) — их самих, раскрытый выпадающий список — отдельное окно и прокручивается сам. Закрытое
выпадающее поле колесо не меняет: иначе прокрутка страницы молча меняла бы выбранный язык или видимость канала.
"""
from __future__ import annotations

import tkinter as tk
from enum import StrEnum
from tkinter import ttk
from typing import Final

from app.setup.tabs.tab_layout import PAD

FRAME_STYLE: Final[str] = "TFrame"
BACKGROUND_OPTION: Final[str] = "background"
COMBOBOX_CLASS: Final[str] = "TCombobox"
WHEEL_NOTCH: Final[int] = 120               # Windows: event.delta на один щелчок колеса
SCROLL_UNITS: Final[str] = "units"
# Виджеты, которые колесо прокручивает сами: список каналов и список чатов.
SELF_SCROLLING: Final[tuple[type[tk.Misc], ...]] = (ttk.Treeview, tk.Listbox)


class ScrollEvent(StrEnum):
    """События Tk, на которые страница вешает обработчики."""

    CONFIGURE = "<Configure>"
    MOUSE_WHEEL = "<MouseWheel>"
    DESTROY = "<Destroy>"


class TabScroll:
    """Прокручиваемая страница вкладки. Поля: внешняя рамка `frame` (страница блокнота), холст `canvas`, полоса
    прокрутки `bar`, рамка содержимого `body`, id окна холста `window_id`, id отложенного пересчёта `fit_id` и
    накопленный delta колеса `wheel_rest` — меньше щелчка, со знаком направления."""

    def __init__(self, notebook: ttk.Notebook) -> None:
        self.frame: ttk.Frame = ttk.Frame(notebook)
        background: str = str(ttk.Style(notebook).lookup(FRAME_STYLE, BACKGROUND_OPTION))
        self.canvas: tk.Canvas = tk.Canvas(self.frame, highlightthickness=0, borderwidth=0, background=background)
        self.bar: ttk.Scrollbar = ttk.Scrollbar(self.frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.body: ttk.Frame = ttk.Frame(self.canvas, padding=PAD)
        self.window_id: int = self.canvas.create_window(0, 0, window=self.body, anchor=tk.NW)
        self.fit_id: str | None = None
        self.wheel_rest: int = 0
        window: tk.Misc = notebook.winfo_toplevel()
        window.bind(ScrollEvent.CONFIGURE, lambda _event: self.schedule_fit(), add=True)
        window.bind(ScrollEvent.MOUSE_WHEEL, self.wheel, add=True)
        window.bind_class(COMBOBOX_CLASS, ScrollEvent.MOUSE_WHEEL, lambda _event: None)
        self.frame.bind(ScrollEvent.DESTROY, self._cancel_fit, add=True)

    @property
    def content_height(self) -> int:
        """Высота, которая нужна содержимому вкладки."""
        return self.body.winfo_reqheight()

    def schedule_fit(self) -> None:
        """Пересчёт страницы — один на все изменения размеров до ближайшей паузы окна."""
        if self.fit_id is None:
            self.fit_id = self.frame.after_idle(self.fit)

    def fit(self) -> None:
        """Холст просит размер содержимого; `body` — во всю ширину холста и не ниже него; прокрутка — по `body`."""
        self.fit_id = None
        self.canvas.configure(width=self.body.winfo_reqwidth(), height=self.content_height)
        width: int = self.canvas.winfo_width()
        height: int = max(self.content_height, self.canvas.winfo_height())
        self.canvas.itemconfigure(self.window_id, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def wheel(self, event: tk.Event) -> None:
        """Колесо над показанной вкладкой прокручивает её на целые щелчки накопленного delta (усечение к нулю: вверх и
        вниз одинаково), остаток ждёт следующих событий; над списком — только сам список."""
        if not self.frame.winfo_ismapped() or isinstance(event.widget, SELF_SCROLLING):
            return
        self.wheel_rest += event.delta
        notches: int = int(self.wheel_rest / WHEEL_NOTCH)
        self.wheel_rest -= notches * WHEEL_NOTCH
        self.canvas.yview_scroll(-notches, SCROLL_UNITS)

    def _cancel_fit(self, _event: tk.Event) -> None:
        """Страница уничтожена: отложенный пересчёт снимается, пока его команда ещё зарегистрирована."""
        if self.fit_id is None:
            return
        self.frame.after_cancel(self.fit_id)
        self.fit_id = None
