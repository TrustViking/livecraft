"""Где лежат файлы замка: стандарт в пакете, реестр и исключения в данных тестов (REFACTORING_STANDARD.md §6)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.tools.code_standard.check import StandardCheck
from app.tools.code_standard.source import APP_PACKAGE, POSIX_SLASH, TESTS_PACKAGE, SourceKey, SourceTree
from app.tools.code_standard.standard import Standard

REPOSITORY_DEPTH: Final[int] = 3  # app\tools\code_standard\<модуль> → корень репозитория
STANDARD_PARTS: Final[tuple[str, ...]] = (APP_PACKAGE, "tools", "code_standard", "standard.json")
DATA_PARTS: Final[tuple[str, ...]] = (APP_PACKAGE, TESTS_PACKAGE, "data", "code_standard")
LEDGER_FILE: Final[str] = "debt.json"
EXCEPTIONS_FILE: Final[str] = "exceptions.json"


@dataclass(frozen=True)
class LockFiles:
    """Корень репозитория и файлы замка в нём."""

    root: Path

    @classmethod
    def repository(cls) -> LockFiles:
        """Корень репозитория, в котором лежит сам замок."""
        return cls(Path(__file__).resolve().parents[REPOSITORY_DEPTH])

    @property
    def standard(self) -> Path:
        return self.root.joinpath(*STANDARD_PARTS)

    @property
    def ledger(self) -> Path:
        return self.root.joinpath(*DATA_PARTS, LEDGER_FILE)

    @property
    def exceptions(self) -> Path:
        return self.root.joinpath(*DATA_PARTS, EXCEPTIONS_FILE)

    @property
    def ledger_in_git(self) -> str:
        """Путь реестра для `git show <версия>:<путь>`."""
        return POSIX_SLASH.join(DATA_PARTS + (LEDGER_FILE,))

    def check(self) -> StandardCheck:
        """Проверка кода app этого корня по его стандарту."""
        return StandardCheck(SourceTree.from_root(self.root), Standard.load(self.standard))

    def key_of(self, raw: str) -> SourceKey:
        """Путь из командной строки — ключ от корня; абсолютный путь внутри корня тоже годится."""
        path: Path = Path(raw)
        if path.is_absolute() and path.resolve().is_relative_to(self.root.resolve()):
            return SourceKey.of(path.resolve().relative_to(self.root.resolve()).as_posix())
        return SourceKey.of(raw)
