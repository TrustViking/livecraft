"""Номер версии и имя программы — единственный источник: CLI, лог, отчёт, spec и инсталлятор (CLAUDE.md §11).

`APP_NAME` — имя программы: корневой логгер `livecraft`, генератор пакета, имя в справке командной строки.

Сборка (build_release.bat, через него и build_local.bat) перед PyInstaller зовёт `python -m app.version --bump`:
patch +1 прямо в этом файле, новый номер — в stdout. Руками номер меняется только в major/minor.
Файл версии — UTF-8: `bytes.decode()` и `str.encode()` без аргумента пишут и читают именно её.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import ClassVar, Final

APP_VERSION: Final[str] = "0.1.0"
APP_NAME: Final[str] = "livecraft"

BUMP_FLAG: Final[str] = "--bump"
VERSION_FORMAT: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
VERSION_LINE: Final[re.Pattern[str]] = re.compile(r'^APP_VERSION: Final\[str\] = "([^"]*)"$', re.MULTILINE)
VERSION_TEMPLATE: Final[str] = "{major}.{minor}.{patch}"
NUMBER_GROUP: Final[int] = 1        # номер версии в строке APP_VERSION — первая группа шаблона
EXPECTED_LINES: Final[int] = 1      # строка APP_VERSION в файле версии — ровно одна


class VersionError(ValueError):
    """Номер или файл версии не того вида: ошибка сборки, текст — для разработчика."""

    NOT_SEMVER: ClassVar[str] = "version is not MAJOR.MINOR.PATCH: {version!r}"
    LINE_COUNT: ClassVar[str] = "expected exactly one APP_VERSION line in {path}, found {count}"

    def __init__(self, template: str, **values: object) -> None:
        super().__init__(template.format(**values))


def next_patch_version(version: str) -> str:
    """0.1.9 → 0.1.10; номер не вида MAJOR.MINOR.PATCH — VersionError."""
    match: re.Match[str] | None = VERSION_FORMAT.fullmatch(version)
    if match is None:
        raise VersionError(VersionError.NOT_SEMVER, version=version)
    major, minor, patch = (int(part) for part in match.groups())
    return VERSION_TEMPLATE.format(major=major, minor=minor, patch=patch + 1)


def bump_version_file(path: Path) -> str:
    """Переписывает строку APP_VERSION в файле версии; остальное — байт в байт. Возвращает новый номер."""
    text: str = path.read_bytes().decode()
    matches: list[re.Match[str]] = list(VERSION_LINE.finditer(text))
    if len(matches) != EXPECTED_LINES:
        raise VersionError(VersionError.LINE_COUNT, path=path, count=len(matches))
    match: re.Match[str] = matches[0]
    version: str = next_patch_version(match.group(NUMBER_GROUP))
    start, end = match.span(NUMBER_GROUP)
    path.write_bytes((text[:start] + version + text[end:]).encode())
    return version


if __name__ == "__main__":
    if sys.argv[1:] != [BUMP_FLAG]:
        sys.exit(f"usage: python -m app.version {BUMP_FLAG}")
    print(bump_version_file(Path(__file__)))
