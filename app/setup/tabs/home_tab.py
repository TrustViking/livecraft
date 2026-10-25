"""Вкладка окна «Главная»: линии работы по этапам (CLAUDE.md §8.2, §14 решения 37, 47, 48).

Сверху — что делает Livecraft, сразу под этим — проект Google (`ClientBlock`, §14 решение 66): работа начинается с
него, без проекта не работает ничего, что ходит в Google; затем — как пользоваться строками. Дальше — этапы работы (`LineStage`), каждый под чертой с
подписью, в нём — его линии в порядке «Главной» (`LINE_ORDER`). «Вход» — одно из двух: кнопки «Таблица плана |
Пакеты», под ними — что делает выбранный вход и его готовность, рядом «Перейти» на его вкладку (`InputChoiceRow`).
«Обработка», «Вывод» и эфиры — строки линий (`LineHeader`: ползунок, название, что делает, готовность, «Перейти»;
ползунок — та же переменная, что вверху вкладки линии); линия без опоры — с недоступным ползунком и причиной. Последняя
строка этапа «Эфиры» — какие ключи передать в форму, «новые | все» (`KeysChoiceRow`). Внизу — что сделает запуск.
Строки перерисовываются по свежей модели после каждого переключения, выбора и записи (`show`). «Перейти» к нужде
проекта Google открывает «Главную» с её начала (`to_top`). Своих правил у вкладки нет.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Final

from app.run.mode import LINE_ORDER, LineStage, RunPart
from app.setup.page import SetupPage
from app.setup.panels.client_check import ClientCheck
from app.setup.panels.lines_panel import LineRow, LinesPanel
from app.setup.readiness import Readiness
from app.setup.tabs.broadcast_choices import KeysChoiceRow
from app.setup.tabs.client_block import ClientBlock
from app.setup.tabs.line_switches import TONE_FOREGROUNDS, LineHeader, LineSwitches
from app.setup.tabs.segmented_choice import ChoiceRow, ChoiceSpec
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_scroll import TabScroll
from app.setup.tabs.tab_theme import HEADING_STYLE
from app.ui.messages import msg

# Линии, у которых на «Главной» не ползунок, а выбор: таблица плана — вход, передача ключей — «новые | все».
CHOICE_PARTS: Final[frozenset[RunPart]] = frozenset({RunPart.PLAN, RunPart.KEYS})


class InputChoiceRow:
    """Строка входа: кнопки «Таблица плана | Пакеты» и «Перейти» в ряд, под ними — что делает вход и его готовность.
    Поля: строка выбора (`row`), кнопка «Перейти», строка готовности и вкладка входа, куда ведёт «Перейти»."""

    def __init__(self, parent: ttk.Frame, switches: LineSwitches, go_to: Callable[[SetupPage], None]) -> None:
        spec: ChoiceSpec = ChoiceSpec(switches.source, msg.SETUP_HOME_INPUTS, switches.choose_input)
        self.row: ChoiceRow = ChoiceRow(parent, "", spec)
        self.row.text.configure(foreground=HINT_FOREGROUND)
        self.page: SetupPage = SetupPage.PLAN
        self.go_button: ttk.Button = ttk.Button(self.row.top, text=msg.SETUP_HOME_GO, command=lambda: go_to(self.page))
        self.go_button.pack(side=tk.RIGHT)
        self.state: ttk.Label = ttk.Label(self.row.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.state.pack(fill=tk.X, anchor=tk.W)

    def show(self, row: LineRow) -> None:
        """Что делает выбранный вход, его готовность и вкладка для «Перейти» — по строке модели."""
        self.page = row.page
        self.row.text.configure(text=row.does)
        self.state.configure(text=row.state, foreground=TONE_FOREGROUNDS[row.tone])


class HomeTab:
    """Вкладка «Главная»: прокручиваемая страница, проект Google (`client`), строка входа (`input`), строки линий
    (`lines`), строка ключей (`keys`) и строка «Запуск сделает: …»."""

    def __init__(self, context: SetupContext, go_to: Callable[[SetupPage], None], client: ClientCheck) -> None:
        switches: LineSwitches = context.switches
        self.scroll: TabScroll = TabScroll(context.notebook)
        self._paragraph(msg.SETUP_HOME_INTRO)
        self.client: ClientBlock = ClientBlock(self.body, client, context.on_saved)
        self._paragraph(msg.SETUP_HOME_HOWTO)
        stages: dict[LineStage, ttk.Frame] = {stage: self._stage(stage) for stage in LineStage}
        self.input: InputChoiceRow = InputChoiceRow(stages[LineStage.INPUT], switches, go_to)
        self.lines: dict[RunPart, LineHeader] = {
            part: switches.header(stages[part.stage], part, go_to) for part in LINE_ORDER if part not in CHOICE_PARTS
        }
        self.keys: KeysChoiceRow = KeysChoiceRow(stages[LineStage.BROADCASTS], switches)
        self.run_line: ttk.Label = ttk.Label(
            self.body, style=HEADING_STYLE, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT
        )
        self.run_line.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))

    @property
    def frame(self) -> ttk.Frame:
        """Страница блокнота."""
        return self.scroll.frame

    @property
    def body(self) -> ttk.Frame:
        """Рамка содержимого вкладки."""
        return self.scroll.body

    @property
    def page(self) -> SetupPage:
        return SetupPage.HOME

    def show(self, panel: LinesPanel, readiness: Readiness, rows: tuple[LineRow, ...]) -> None:
        """Вход, ключи и «Запуск сделает: …» — по свежей модели линий и проверке; строки линий перерисовывают ползунки
        окна."""
        self.input.show(panel.input_row(readiness))
        self.keys.show(panel.keys_row(rows))
        self.run_line.configure(text=panel.run_line)

    def to_top(self) -> None:
        """Страница — с начала: там проект Google."""
        self.scroll.canvas.yview_moveto(0)

    def _paragraph(self, text: str) -> None:
        """Абзац текста во всю ширину страницы."""
        label: ttk.Label = ttk.Label(self.body, text=text, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        label.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))

    def _stage(self, stage: LineStage) -> ttk.Frame:
        """Этап: черта, подпись этапа и рамка для его строк."""
        ttk.Separator(self.body, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(PAD, 0))
        title: ttk.Label = ttk.Label(self.body, text=stage.human_label, style=HEADING_STYLE, foreground=HINT_FOREGROUND)
        title.pack(anchor=tk.W, pady=(PAD, 0))
        frame: ttk.Frame = ttk.Frame(self.body)
        frame.pack(fill=tk.X, anchor=tk.W)
        return frame
