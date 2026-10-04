"""Вкладка окна «Эфиры YouTube» — линия BROADCAST — поверх модели `ChannelsPanel` (CLAUDE.md §8.2 п.4, §14 решения 25,
37).

Вверху — ползунок линии, ниже — зачем вкладка. Таблица каналов — строки модели (`drafts`), под ней сетка полей черновика канала
(`ChannelDraft.FIELDS`: подпись, поле и серая подсказка с примером справа) и кнопки. Названия канала в окне нет:
его даёт ник, а потом YouTube. Видимость — словами (`DraftField.labels`). Выбор строки заполняет поля; «добавить» и «изменить выбранный» отдают черновик модели, и ответ модели
заменяет вкладку либо называет проблему красной строкой с подписью поля. Своих правил у вкладки нет:
годность канала решает загрузчик внутри модели. Набранное в полях, но не принятое моделью, —
несохранённое вкладки: окно спросит перед закрытием.

У канала один язык (§14 решение 21): он выбирается полем выбора с поиском (`LanguageBox`) из всех языков по
названию. Языки Google-формы — первыми и с пометкой; их вкладке даёт модель настроек при открытии и после
сохранения вкладки «Дополнительно», а не прочитались настройки — список полный, но без пометок. В таблице
каналов язык показан названием, видимость — словами. Ряд кнопок — по центру окна.

Под кнопками — «Проверить все каналы» и «Войти в выбранный канал» со строкой итога (`CheckLine` поверх `ChannelsCheck`):
тот же код, что у .\\livecraft.bat --check и --auth "<ник>", в фоновом потоке; строки по ходу проверки и итогом — те
же, что печатает консоль служебного запуска. Только по кнопке: вход открывает браузер. Проверка идёт по сохранённому
channels.json; после неё вкладка перечитывает каналы, если в ней нет несохранённого: ник и название канала могли
выровняться по YouTube (§14 решение 25).

Таблица, поля и кнопки каналов — одно поле окна (`channels_frame`, нужда «каналы»): эфиры не работают — оно бледное.
Под ним — настройки эфира (раздел настроек `SettingsSection` со своей кнопкой «Сохранить»): категория видео, автостарт,
обложка, запас до старта и пауза между обращениями к YouTube.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Iterable
from dataclasses import dataclass
from tkinter import ttk
from typing import Final

from app.config.json_node import SettingProblem
from app.config.setting_key import SettingKey
from app.paths import LivecraftPaths
from app.run.mode import Need
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.fields.draft_field import DraftField, DraftKind
from app.setup.fields.field_use import FieldUse
from app.setup.fields.language_choice import LanguageDirectory, LanguagePicker
from app.setup.page import SetupPage
from app.setup.panels.channels_check import ChannelsCheck, ChannelsVerdict
from app.setup.panels.channels_panel import ChannelsPanel
from app.setup.panels.panel_edit import PanelEdit
from app.setup.tabs.check_line import CheckLine, CheckMail, CheckTexts
from app.setup.tabs.language_box import LanguageBox
from app.setup.tabs.settings_section import SettingsSection
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_event import TkEvent
from app.setup.tabs.tab_grid import DraftVariables, FormGrid
from app.setup.tabs.tab_layout import PAD, ProblemLine
from app.setup.tabs.tab_shell import TabAction, TabShell
from app.ui.messages import msg

DRAFT_FIELDS: Final[tuple[str, ...]] = tuple(field.name for field in ChannelDraft.FIELDS)
TREE_HEIGHT_ROWS: Final[int] = 6    # наименьшая высота списка; есть место — список тянется на него
TREE_SHOW: Final[str] = "headings"
LANGUAGE_FIELD: Final[DraftField] = next(field for field in ChannelDraft.FIELDS if field.kind is DraftKind.LANGUAGE)
# Настройки эфира под таблицей каналов — в этом порядке.
BROADCAST_KEYS: Final[tuple[SettingKey, ...]] = (
    SettingKey.CATEGORY_ID,
    SettingKey.AUTO_START,
    SettingKey.SET_THUMBNAIL,
    SettingKey.MIN_LEAD_MINUTES,
    SettingKey.YOUTUBE_PAUSE_SECONDS,
)


@dataclass(frozen=True)
class ChannelsJob:
    """Проверка для фонового потока без Tk: вход в канал с ником `handle` или, без ника, проверка всех каналов моделью
    `check`; всё сказанное по ходу — строками почты."""

    check: ChannelsCheck
    handle: str | None = None

    def __call__(self, mail: CheckMail) -> ChannelsVerdict:
        if self.handle is None:
            return self.check.check_all(mail.tell)
        return self.check.log_in(self.handle, mail.tell)


@dataclass(frozen=True)
class ChannelsModels:
    """Модели вкладки «Эфиры YouTube»: каналы, языки Google-формы (пометки в выборе языка) и вход в канал и проверка
    каналов."""

    channels: ChannelsPanel
    form_languages: tuple[str, ...]
    check: ChannelsCheck

    @classmethod
    def from_paths(cls, paths: LivecraftPaths, form_languages: Iterable[str]) -> ChannelsModels:
        """Модели на channels.json этой установки; вход и проверка — на YouTube, как у служебных запусков."""
        return cls(ChannelsPanel.from_paths(paths), tuple(form_languages), ChannelsCheck.of(paths))


class ChannelsTab:
    """Вкладка «Эфиры YouTube» в оболочке `shell`: модель каналов `panel`, рамка поля каналов (`body`): таблица,
    поля черновика (`variables`, `grid`), поле выбора языка (`language`), кнопки, строки проблем, вход и проверка
    каналов (модель `check`, строка `check_line`); под ней — настройки эфира (`settings`)."""

    def __init__(self, context: SetupContext, models: ChannelsModels) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.BROADCASTS, msg.SETUP_CHANNELS_INTRO)
        self.panel: ChannelsPanel = models.channels
        self.frame: ttk.Frame = self.shell.frame
        self.body: ttk.Frame = ttk.Frame(self.shell.body)
        self.body.pack(fill=tk.BOTH, expand=True, anchor=tk.W)
        self.list_problem: ProblemLine = ProblemLine(self.body, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.list_problem.label.pack(fill=tk.X, anchor=tk.W)
        self.tree: ttk.Treeview = self._build_tree()
        self.variables: DraftVariables[ChannelDraft] = DraftVariables(self.body, ChannelDraft.blank())
        self.grid: FormGrid = FormGrid(self.body, msg.SETUP_CHANNEL_FIELD_LABELS, msg.SETUP_CHANNEL_FIELD_HINTS)
        self.inputs: dict[str, tk.Widget] = self.grid.inputs
        self.language: LanguageBox = self._build_form(LanguagePicker.of(models.form_languages))
        self.buttons: dict[TabAction, ttk.Button] = self.shell.button_row(
            self.body,
            {
                TabAction.ADD: self.add,
                TabAction.UPDATE: self.update,
                TabAction.REMOVE: self.remove,
                TabAction.SAVE: self.save,
            }
        )
        self.edit_problem: ProblemLine = ProblemLine(self.body, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.edit_problem.label.pack(fill=tk.X, anchor=tk.W)
        self.check: ChannelsCheck = models.check
        self.check_line: CheckLine = self._build_check_line()
        self.settings: SettingsSection = SettingsSection(self.shell.body, context, BROADCAST_KEYS)
        context.shades.block(FieldUse.of(Need.CHANNELS), self.body)
        self._show()

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — в модели, в полях канала или в поле языка набрана строка поиска."""
        return self.panel.is_dirty or self.variables.has_typed or self.language.picker.is_search

    @property
    def form_draft(self) -> ChannelDraft:
        """Черновик канала из полей окна — текстом, как введено; язык — кодом выбранного."""
        return self.variables.typed

    @property
    def selected_index(self) -> int | None:
        """Номер выбранного канала в модели; ничего не выбрано — None."""
        selection: tuple[str, ...] = self.tree.selection()
        return int(selection[0]) if selection else None

    def fill_from_selection(self) -> None:
        """Выбор строки таблицы заполняет поля черновиком этого канала; язык — первым из записанных."""
        index: int | None = self.selected_index
        if index is None:
            return
        draft: ChannelDraft = self.panel.drafts[index]
        self.variables.show(draft)
        self.language.choose(draft.languages)
        self.variables.accept()

    def refresh_form_languages(self, form_languages: Iterable[str]) -> None:
        """Настройки сохранены: пометки и предупреждение о языке — по новой форме, выбор тот же."""
        known: list[str] = [code for draft in self.panel.drafts for code in draft.languages]
        self.language.with_form(form_languages, known)

    def add(self) -> None:
        """«Добавить»: черновик нового канала — модели, в конец списка; текст языка не из списка — проблема поля."""
        if not self._refuses_language_text():
            self._apply(self.panel.add(self.form_draft.as_new()))

    def update(self) -> None:
        """«Изменить выбранный»: черновик заменяет выбранный канал."""
        index: int | None = self.selected_index
        if index is None:
            self.edit_problem.show_text(msg.SETUP_CHANNELS_NOTHING_SELECTED)
        elif not self._refuses_language_text():
            self._apply(self.panel.update(index, self.form_draft))

    def remove(self) -> None:
        """«Удалить выбранный»: пустой список модель покажет своей проблемой над таблицей."""
        index: int | None = self.selected_index
        if index is None:
            self.edit_problem.show_text(msg.SETUP_CHANNELS_NOTHING_SELECTED)
            return
        self.panel = self.panel.remove(index)
        self.edit_problem.show_text(None)
        self._show()

    def save(self) -> None:
        """«Сохранить»: модель пишет channels.json через загрузчик. Сбой диска — диалог."""
        try:
            edit: PanelEdit[ChannelsPanel] = self.panel.save()
        except OSError as error:
            self.shell.refuse_save(msg.SETUP_CHANNELS_SAVE_FAILED.format(error=error))
            return
        if self._apply(edit):
            self.shell.on_saved()

    def log_in(self) -> None:
        """«Войти в выбранный канал» — как .\\livecraft.bat --auth "<ник>"; ничего не выбрано — строка проблемы."""
        index: int | None = self.selected_index
        if index is None:
            self.edit_problem.show_text(msg.SETUP_CHANNELS_NOTHING_SELECTED)
            return
        self.edit_problem.show_text(None)
        handle: str = self.panel.channels[index].handle
        self.check_line.start_run(ChannelsJob(self.check, handle))

    def channels_checked(self) -> None:
        """Вход или проверка закончились: ник и название могли выровняться (§14 решение 25) — каналы из файла, если на
        вкладке нет несохранённого."""
        if not self.panel.is_dirty:
            self.panel = ChannelsPanel.from_file(self.panel.file)
            self._show()

    def _apply(self, edit: PanelEdit[ChannelsPanel]) -> bool:
        """Ответ модели: принято — новая вкладка, набранное принято, True; нет — проблема с подписью поля, False."""
        self.edit_problem.show_problem(edit.problem)
        if not edit.is_applied:
            return False
        self.panel = edit.panel
        self.variables.accept()
        self._show()
        return True

    def _refuses_language_text(self) -> bool:
        """Набранный текст — не язык из списка: проблема поля, черновик модели не отдаётся."""
        problem: SettingProblem | None = self.language.problem
        if problem is not None:
            self.edit_problem.show_problem(problem)
        return problem is not None

    def _show(self) -> None:
        """Перерисовать оговорки, проблему списка и таблицу по модели; языки — названиями, видимость — словами."""
        self.shell.show_notices(self.panel.notices)
        self.list_problem.show_problem(self.panel.problem)
        self.tree.delete(*self.tree.get_children())
        drafts: tuple[ChannelDraft, ...] = self.panel.drafts
        self.language.including(code for draft in drafts for code in draft.languages)
        directory: LanguageDirectory = self.language.picker.directory
        for index, draft in enumerate(drafts):
            values: tuple[str, ...] = tuple(
                directory.names(draft.languages) if field is LANGUAGE_FIELD
                else str(field.shown(getattr(draft, field.name)))
                for field in ChannelDraft.FIELDS
            )
            self.tree.insert("", tk.END, iid=str(index), values=values)

    def _build_tree(self) -> ttk.Treeview:
        tree: ttk.Treeview = ttk.Treeview(
            self.body, columns=DRAFT_FIELDS, show=TREE_SHOW, height=TREE_HEIGHT_ROWS, selectmode=tk.BROWSE
        )
        for name in DRAFT_FIELDS:
            tree.heading(name, text=msg.SETUP_CHANNEL_COLUMNS[name])
        tree.bind(TkEvent.TREE_SELECT, lambda _event: self.fill_from_selection())
        tree.pack(fill=tk.BOTH, expand=True, pady=PAD)
        return tree

    def _build_check_line(self) -> CheckLine:
        """«Проверить все каналы» (главная кнопка строки) и «Войти в выбранный канал» со строкой итога."""
        texts: CheckTexts = CheckTexts(
            button=msg.SETUP_CHANNELS_BUTTON_CHECK,
            checking=msg.SETUP_CHANNELS_CHECKING,
            interrupted=ChannelsVerdict(is_ok=False, text=msg.SETUP_TABLE_INTERRUPTED),
        )
        line: CheckLine = CheckLine(self.body, texts, lambda: ChannelsJob(self.check), self.channels_checked)
        line.add_button(msg.SETUP_CHANNELS_BUTTON_LOGIN, self.log_in)
        return line

    def _build_form(self, picker: LanguagePicker) -> LanguageBox:
        """Строки полей черновика; в ячейку языка — поле выбора языка, которое пишет коды в черновик."""
        for field in ChannelDraft.FIELDS:
            self.grid.add(field, self.variables.variables[field.name])
        codes: tk.Variable = self.variables.variables[LANGUAGE_FIELD.name]
        return LanguageBox(self.grid.inputs[LANGUAGE_FIELD.name], LANGUAGE_FIELD, picker, codes)
