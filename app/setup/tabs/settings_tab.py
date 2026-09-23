"""Вкладка окна «Настройки запуска» поверх модели `SettingsPanel` (CLAUDE.md §8.2 п.3).

Сетка полей по черновику настроек (`SettingsDraft`): текст — поле ввода, флажок — ttk.Checkbutton, уровень
рассуждений и тариф — выбор из перечней модели. «Сохранить» отдаёт черновик модели (`apply`) и, если модель
его приняла, просит её записать livecraft.json; отказ — красная строка с подписью поля. Своих правил нет.
"""
from __future__ import annotations

import dataclasses
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Final

from app.paths import LivecraftPaths
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.panels.settings_panel import SettingsPanel, SettingsPanelEdit
from app.setup.tabs import NOTICE_JOINER, PAD, TEXT_WRAP_PIXELS, ProblemLine
from app.ui import messages_ru as msg

# Поле черновика → путь поля в livecraft.json: по пути модель называет проблему, по нему же ищется подпись.
FIELD_KEYS: Final[dict[str, str]] = {
    "min_lead_minutes": "min_lead_minutes",
    "keep_days": "keep_days",
    "auto_start": "auto_start",
    "set_thumbnail": "set_thumbnail",
    "category_id": "category_id",
    "youtube_pause_seconds": "youtube_pause_seconds",
    "image_dir_template": "image_dir_template",
    "timezone": "timezone",
    "llm_model": "llm.model",
    "llm_fallback_model": "llm.fallback_model",
    "llm_reasoning_effort": "llm.reasoning_effort",
    "llm_service_tier": "llm.service_tier",
    "llm_timeout_sec": "llm.timeout_sec",
    "llm_max_output_tokens": "llm.max_output_tokens",
}
ENTRY_WIDTH_CHARS: Final[int] = 32
READONLY: Final[str] = "readonly"
HINT_FOREGROUND: Final[str] = "#6b6b6b"     # серая подсказка: читается, но не спорит с подписью поля
HINT_WRAP_PIXELS: Final[int] = 420


class SettingsTab:
    """Вкладка «Настройки запуска». `panel` — текущая модель; `variables` — значения полей окна;
    `hints` — серые подсказки у полей, которым они нужны (messages_ru, по тем же ключам, что подписи).
    """

    def __init__(self, notebook: ttk.Notebook, paths: LivecraftPaths, on_saved: Callable[[], None]) -> None:
        self.paths: LivecraftPaths = paths
        self.panel: SettingsPanel = SettingsPanel.from_paths(paths)
        self.frame: ttk.Frame = ttk.Frame(notebook, padding=PAD)
        self.notice: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.notice.pack(fill=tk.X, anchor=tk.W)
        self.variables: dict[str, tk.Variable] = {}
        self.inputs: dict[str, ttk.Widget] = {}
        self.hints: dict[str, ttk.Label] = {}
        self._build_fields()
        self.problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_SETTINGS_FIELD_LABELS)
        self.problem.label.pack(fill=tk.X, anchor=tk.W)
        self.save_button: ttk.Button = ttk.Button(self.frame, text=msg.SETUP_BUTTON_SAVE, command=self.save)
        self.save_button.pack(anchor=tk.E, pady=PAD)
        self._on_saved: Callable[[], None] = on_saved
        self._show()

    @property
    def form_draft(self) -> SettingsDraft:
        """Черновик из полей окна: текст — как введён, флажки — bool."""
        return SettingsDraft(**{name: variable.get() for name, variable in self.variables.items()})

    @property
    def is_dirty(self) -> bool:
        """Несохранённое есть в модели или в полях окна, ещё не отданных модели."""
        return self.panel.is_dirty or self.form_draft != self.panel.draft

    def save(self) -> None:
        """«Сохранить»: черновик — модели; принято — модель пишет файл. Сбой диска — диалог."""
        edit: SettingsPanelEdit = self.panel.apply(self.form_draft)
        if not edit.is_applied:
            self.problem.show_problem(edit.problem)
            return
        self.panel = edit.panel
        self.problem.show_text(None)
        try:
            self.panel = self.panel.save(self.paths)
        except OSError as error:
            messagebox.showerror(
                msg.SETUP_SAVE_FAILED_TITLE, msg.SETUP_SETTINGS_SAVE_FAILED.format(error=error), parent=self.frame
            )
            return
        self._show()
        self._on_saved()

    def _show(self) -> None:
        """Перерисовать оговорки и поля по модели."""
        self.notice.configure(text=NOTICE_JOINER.join(self.panel.notices))
        draft: SettingsDraft = self.panel.draft
        for name, variable in self.variables.items():
            variable.set(getattr(draft, name))

    @property
    def _choices(self) -> dict[str, tuple[str, ...]]:
        """Поля только с выбором и их варианты — из перечней модели."""
        return {
            "llm_reasoning_effort": self.panel.reasoning_effort_options,
            "llm_service_tier": self.panel.service_tier_options,
        }

    def _build_fields(self) -> None:
        """Строка на поле черновика: подпись, виджет по типу значения и серая подсказка, если она есть."""
        grid: ttk.Frame = ttk.Frame(self.frame)
        grid.pack(fill=tk.X, anchor=tk.W, pady=PAD)
        draft: SettingsDraft = self.panel.draft
        choices: dict[str, tuple[str, ...]] = self._choices
        for row, field in enumerate(dataclasses.fields(SettingsDraft)):
            name: str = field.name
            ttk.Label(grid, text=msg.SETUP_SETTINGS_FIELD_LABELS[FIELD_KEYS[name]]).grid(
                row=row, column=0, sticky=tk.W, padx=PAD, pady=(PAD, 0)
            )
            widget: ttk.Widget = self._build_input(grid, name, getattr(draft, name), choices.get(name))
            widget.grid(row=row, column=1, sticky=tk.W, padx=PAD, pady=(PAD, 0))
            self.inputs[name] = widget
            hint: str | None = msg.SETUP_SETTINGS_FIELD_HINTS.get(FIELD_KEYS[name])
            if hint is not None:
                label: ttk.Label = ttk.Label(grid, text=hint, foreground=HINT_FOREGROUND, wraplength=HINT_WRAP_PIXELS)
                label.grid(row=row, column=2, sticky=tk.W, padx=PAD, pady=(PAD, 0))
                self.hints[name] = label

    def _build_input(
        self, parent: ttk.Frame, name: str, value: str | bool, options: tuple[str, ...] | None
    ) -> ttk.Widget:
        """Флажок, выбор из перечня или поле ввода; переменная поля — в `variables`."""
        if isinstance(value, bool):
            flag: tk.BooleanVar = tk.BooleanVar(master=parent, value=value)
            self.variables[name] = flag
            return ttk.Checkbutton(parent, variable=flag)
        text: tk.StringVar = tk.StringVar(master=parent, value=value)
        self.variables[name] = text
        if options is not None:
            return ttk.Combobox(parent, textvariable=text, values=options, state=READONLY)
        return ttk.Entry(parent, textvariable=text, width=ENTRY_WIDTH_CHARS)
