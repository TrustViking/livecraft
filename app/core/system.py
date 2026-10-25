"""Операционная система, на которой идёт программа, — то, что нужно нескольким слоям (CLAUDE.md §11).

DPAPI сейфа, проверка живости процесса-владельца замка и язык интерфейса по языку Windows есть только на Windows: эти
места спрашивают об этом одним значением. Готовый файл, который человек отправит сам (архив логов, §14 решение 62),
окно показывает в Проводнике Windows выделенным (`FolderOpener`).
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

WINDOWS_PLATFORM: Final[str] = "win32"     # sys.platform на Windows
# Проводник открывает папку файла и выделяет его; путь — в кавычках: в нём бывают пробелы.
EXPLORER_SELECT_COMMAND: Final[str] = 'explorer /select,"{path}"'


@dataclass(frozen=True)
class FolderOpener:
    """Папка файла в Проводнике с выделенным файлом. `launch` — запуск команды (`subprocess.Popen`; в тестах —
    подделка)."""

    launch: Callable[[str], object] = subprocess.Popen

    def show_file(self, path: Path) -> None:
        """Проводник открывает папку файла `path` и выделяет его; программа Проводник не ждёт."""
        self.launch(EXPLORER_SELECT_COMMAND.format(path=path))
