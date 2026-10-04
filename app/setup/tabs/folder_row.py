"""Строка папки роли на вкладке окна поверх модели `FolderField` (CLAUDE.md §8.2, §14 решение 37).

Папка пакетов — на «Пакете», папка копий документов — на «Google-документе», папка превью — на «Превью». Строка
выглядит как строка поля: подпись и подсказка, статус (где папка на диске), кнопки «Выбрать…» (окно выбора папки
Windows) и «По умолчанию». Выбор пишется сразу; отмена окна выбора ничего не меняет. Своих правил у строки нет: какой
путь писать, решает модель.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk

from app.config.setting_key import SettingKey
from app.setup.fields.field_use import FieldUse
from app.setup.fields.folder_field import FolderField
from app.setup.tabs.key_rows import FieldBlock
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg

# Окно выбора папки: получает родителя, начальную папку и заголовок; отдаёт выбранную папку или пустую строку.
FolderAsk = Callable[..., str]


class FolderRow:
    """Строка папки роли: модель `folder`, каркас строки, кнопки, оболочка вкладки (диалог и перерисовка окна) и окно
    выбора папки `ask` (в программе — окно Windows; в тестах — подделка)."""

    def __init__(self, parent: ttk.Frame, folder: FolderField, shell: TabShell) -> None:
        self.block: FieldBlock = FieldBlock(parent, folder.label, folder.hint)
        self.choose_button: ttk.Button = self.block.button(msg.SETUP_FOLDER_BUTTON_CHOOSE, self.choose)
        self.default_button: ttk.Button = self.block.button(msg.SETUP_FOLDER_BUTTON_DEFAULT, self.reset)
        self.folder: FolderField = folder
        self.shell: TabShell = shell
        self.ask: FolderAsk = filedialog.askdirectory
        self.show()

    @classmethod
    def placed(cls, shell: TabShell, key: SettingKey) -> FolderRow:
        """Строка папки роли `key` на вкладке `shell` — поле окна со своими линиями (`FieldUse`)."""
        row: FolderRow = cls(shell.body, FolderField.from_paths(shell.context.paths, key), shell)
        shell.context.shades.block(FieldUse.of(key), row.frame)
        return row

    @property
    def frame(self) -> ttk.Frame:
        return self.block.frame

    def choose(self) -> None:
        """«Выбрать…»: окно выбора папки с текущей папкой; выбрана — сразу в livecraft.json."""
        picked: str = self.ask(parent=self.frame, initialdir=str(self.folder.place), title=self.folder.label)
        if picked:
            self._write(lambda: self.folder.choose(Path(picked)))

    def reset(self) -> None:
        """«По умолчанию»: имя роли в корне программы — сразу в livecraft.json."""
        self._write(self.folder.reset)

    def show(self) -> None:
        """Где папка на диске."""
        self.block.show_status(self.folder.status, True)

    def _write(self, write: Callable[[], FolderField]) -> None:
        """Модель пишет файл; записано — строка по записанному и перерисовка окна; сбой диска — диалог."""
        written: FolderField | None = self.shell.write_settings(write)
        if written is None:
            return
        self.folder = written
        self.show()
        self.shell.on_saved()
