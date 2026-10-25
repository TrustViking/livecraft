"""Выбор раздела `broadcasts` на «Главной» окна: какие ключи передать в форму (CLAUDE.md §8.2, §14 решения 47, 49).

Строка «Ключи в форму» этапа «Эфиры» — две кнопки «новые | все» без ползунка и без «Перейти»: передачу ключей
включают на вкладке «Форма». Нажатие сразу пишет выбор (`LineSwitches.choose_keys` — общий путь записи «Главной»), и
окно перерисовывается. Под кнопками — что делает выбранное, а когда выбор сейчас ничего не решает, кнопки недоступны и
строка называет причину (`KeysRow`). Своих правил у строки нет.
"""
from __future__ import annotations

from tkinter import ttk

from app.run.mode import RunPart
from app.setup.panels.lines_panel import KeysRow
from app.setup.tabs.line_switches import LineSwitches
from app.setup.tabs.segmented_choice import ChoiceRow, ChoiceSpec
from app.setup.tabs.tab_layout import HINT_FOREGROUND, TEXT_KEY
from app.ui.messages import msg


class KeysChoiceRow:
    """Строка «Ключи в форму»: подпись, кнопки «новые | все» и строка под ними (`row`)."""

    def __init__(self, parent: ttk.Frame, switches: LineSwitches) -> None:
        spec: ChoiceSpec = ChoiceSpec(switches.keys, msg.SETUP_KEYS_CHOICES, switches.choose_keys)
        self.row: ChoiceRow = ChoiceRow(parent, RunPart.KEYS.human_label, spec)
        self.row.text.configure(foreground=HINT_FOREGROUND)

    @property
    def frame(self) -> ttk.Frame:
        return self.row.frame

    @property
    def text(self) -> str:
        return str(self.row.text.cget(TEXT_KEY))

    def show(self, keys: KeysRow) -> None:
        """Кнопки доступны, когда выбор что-то решает; строка — что делает выбранное или почему выбор недоступен."""
        self.row.choice.set_enabled(keys.is_active)
        self.row.text.configure(text=keys.text)
