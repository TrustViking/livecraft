"""Текстовые ресурсы контура A (CLAUDE.md §2: `resources\\resource_loader.py` restreamer).

`TextResource` — один файл из `app\\resources\\text`: в dev-режиме папка лежит рядом с этим модулем,
в собранном exe — внутри распакованной поставки PyInstaller (`sys._MEIPASS\\app\\resources\\text`).
Файлы переносятся из restreamer побайтно; правило чтения строк — `load_lines_resource` донора.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

RESOURCE_ENCODING: Final[str] = "utf-8"
COMMENT_PREFIX: Final[str] = "#"
TEXT_DIR_NAME: Final[str] = "text"
FROZEN_TEXT_PARTS: Final[tuple[str, ...]] = ("app", "resources", TEXT_DIR_NAME)
FROZEN_ATTR: Final[str] = "frozen"
BUNDLE_DIR_ATTR: Final[str] = "_MEIPASS"


@dataclass(frozen=True)
class TextResource:
    """Текстовый файл ресурсов по имени; прочитанное кешируется на имя до конца процесса."""

    name: str

    @staticmethod
    def text_dir() -> Path:
        """Папка текстовых ресурсов: в собранном exe — из поставки PyInstaller, иначе рядом с модулем."""
        if getattr(sys, FROZEN_ATTR, False):
            return Path(getattr(sys, BUNDLE_DIR_ATTR)).joinpath(*FROZEN_TEXT_PARTS)
        return Path(__file__).resolve().parent / TEXT_DIR_NAME

    @property
    def path(self) -> Path:
        return self.text_dir() / self.name.strip()

    @property
    def lines(self) -> tuple[str, ...]:
        """Строки файла без краёв, без пустых и без комментариев `#…` — в порядке файла."""
        return self._read_lines()

    @lru_cache(maxsize=None)
    def _read_lines(self) -> tuple[str, ...]:
        stripped: list[str] = [line.strip() for line in self.path.read_text(encoding=RESOURCE_ENCODING).splitlines()]
        return tuple(line for line in stripped if line and not line.startswith(COMMENT_PREFIX))
