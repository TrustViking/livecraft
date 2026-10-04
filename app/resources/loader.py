"""Текстовые ресурсы программы: тексты промтов, лексиконы, пороги-данные (CLAUDE.md §5, §14 решение 23).

`TextResource` — один файл из папки текстовых ресурсов. Папки ресурсов называет `ResourceBundle`: в dev-режиме
они лежат рядом с этим модулем, в собранном exe — внутри распакованной поставки PyInstaller
(`sys._MEIPASS\\app\\resources\\<папка>`); тем же правилом он находит иконку программы (`icon_file`, §14 решение 53).
Прочитанное кешируется на ресурс до конца процесса: `lines` — строки
без краёв, пустых и комментариев `#…`; `data` — объект JSON; `body` — весь текст без строки-источника.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Final

from app.core.text_format import NEWLINE, TEXT_ENCODING

COMMENT_PREFIX: Final[str] = "#"         # строка-комментарий ресурса; первая такая строка — откуда взят текст
TEXT_DIR_NAME: Final[str] = "text"
ICON_DIR_NAME: Final[str] = "icon"
ICON_FILE_NAME: Final[str] = "livecraft.ico"    # иконка программы: exe и ярлыки (livecraft.spec), окно настройки
FROZEN_RESOURCE_PARTS: Final[tuple[str, ...]] = ("app", "resources")
FROZEN_ATTR: Final[str] = "frozen"
BUNDLE_DIR_ATTR: Final[str] = "_MEIPASS"


class ResourceError(ValueError):
    """Ресурс не того вида: ошибка поставки, текст — для разработчика."""

    NOT_AN_OBJECT: ClassVar[str] = "resource {name} must contain a JSON object"

    def __init__(self, name: str) -> None:
        super().__init__(self.NOT_AN_OBJECT.format(name=name))


@dataclass(frozen=True)
class ResourceBundle:
    """Как запущена программа: из исходников или собранным exe, и где PyInstaller распаковал поставку."""

    frozen: bool
    bundle_dir: str | None

    @classmethod
    def of_process(cls) -> ResourceBundle:
        """Признаки текущего процесса: PyInstaller ставит `sys.frozen` и `sys._MEIPASS`."""
        return cls(frozen=bool(getattr(sys, FROZEN_ATTR, False)), bundle_dir=getattr(sys, BUNDLE_DIR_ATTR, None))

    @property
    def text_dir(self) -> Path:
        """Папка текстовых ресурсов."""
        return self._folder(TEXT_DIR_NAME)

    @property
    def icon_file(self) -> Path:
        """Иконка программы — .ico со всеми размерами."""
        return self._folder(ICON_DIR_NAME) / ICON_FILE_NAME

    def _folder(self, name: str) -> Path:
        """Папка ресурсов `name`: в собранном exe — из поставки PyInstaller, иначе рядом с модулем."""
        if self.frozen and self.bundle_dir is not None:
            return Path(self.bundle_dir).joinpath(*FROZEN_RESOURCE_PARTS, name)
        return Path(__file__).resolve().parent / name


@dataclass(frozen=True)
class TextResource:
    """Текстовый файл ресурсов по имени в папке ресурсов; прочитанное кешируется на ресурс до конца процесса."""

    name: str
    text_dir: Path = field(default_factory=lambda: ResourceBundle.of_process().text_dir)

    @property
    def path(self) -> Path:
        return self.text_dir / self.name.strip()

    @property
    @lru_cache(maxsize=None)
    def lines(self) -> tuple[str, ...]:
        """Строки файла без краёв, без пустых и без комментариев `#…` — в порядке файла."""
        stripped: list[str] = [line.strip() for line in self.path.read_text(encoding=TEXT_ENCODING).splitlines()]
        return tuple(line for line in stripped if line and not line.startswith(COMMENT_PREFIX))

    @property
    @lru_cache(maxsize=None)
    def body(self) -> str:
        """Весь текст файла; первая строка-комментарий (откуда взят текст) в него не входит."""
        raw: str = self.path.read_text(encoding=TEXT_ENCODING)
        first, _, rest = raw.partition(NEWLINE)
        return rest if first.startswith(COMMENT_PREFIX) else raw

    @property
    @lru_cache(maxsize=None)
    def data(self) -> Mapping[str, Any]:
        """Объект JSON файла (ключи — строки), только для чтения; в корне не объект — `ResourceError`."""
        parsed: Any = json.loads(self.path.read_text(encoding=TEXT_ENCODING))
        if not isinstance(parsed, dict):
            raise ResourceError(self.name)
        return MappingProxyType({str(key): value for key, value in parsed.items()})
