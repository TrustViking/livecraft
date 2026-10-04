"""Что запросила командная строка (CLAUDE.md §10): один объект вместо россыпи ключей.

Разбор строит argparse из `CliFlag` и `CliArgument`; разобранные ключи дальше `RunRequest.from_argv` не уходят.
Без ключа служебного запуска — работа по включённым линиям (`RunMode.RUN`, §14 решение 37); служебные запуски
взаимоисключающие — это держит argparse (ошибка разбора — код 2, текст печатает он сам); `--help` и `--version`
argparse печатает и выходит тоже сам. Путь к пакету без ключа (`livecraft.exe <файл>.bcast` — так его передаёт
проводник) — копия в папку пакетов и обычная работа; с ключом служебного запуска — ошибка разбора.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.observability.log_event import Quoted
from app.run.flag import ArgAction, ArgCount, CliArgument, CliFlag
from app.run.mode import RunMode
from app.ui.messages import msg
from app.version import APP_NAME, APP_VERSION

OPTION_FLAGS: Final[tuple[CliFlag, ...]] = (CliFlag.DRY_RUN, CliFlag.DEBUG)


@dataclass(frozen=True)
class RunRequest:
    """Вид запуска, ник для входа (`--auth`), ключи, которые меняют любой прогон, и пакет, открытый из проводника."""

    mode: RunMode
    auth_handle: str | None
    dry_run: bool
    debug: bool
    package_file: Path | None = None

    @classmethod
    def from_argv(cls, argv: Sequence[str] | None) -> RunRequest:
        """Запрос из командной строки; без ключа служебного запуска — работа по линиям, в том числе с пакетом."""
        parser: argparse.ArgumentParser = cls._parser()
        values: Mapping[str, object] = vars(parser.parse_args(argv))
        flagged: RunMode | None = next(
            (mode for mode in RunMode if mode.flag is not None and mode.flag.is_given(values)), None
        )
        package: str | None = CliArgument.PACKAGE.value_in(values)
        if package is not None and flagged is not None:
            parser.error(msg.CLI_PACKAGE_WITH_MODE)
        handle: object = values.get(CliFlag.AUTH.dest)
        return cls(
            mode=RunMode.RUN if flagged is None else flagged,
            auth_handle=handle if isinstance(handle, str) else None,
            dry_run=CliFlag.DRY_RUN.is_given(values),
            debug=CliFlag.DEBUG.is_given(values),
            package_file=None if package is None else Path(package),
        )

    @classmethod
    def _parser(cls) -> argparse.ArgumentParser:
        """Ключи прогона, номер версии, взаимоисключающие ключи служебных запусков и пакет без ключа — в порядке
        справки."""
        parser: argparse.ArgumentParser = argparse.ArgumentParser(prog=APP_NAME, description=msg.CLI_DESCRIPTION)
        for flag in OPTION_FLAGS:
            parser.add_argument(flag.value, action=ArgAction.STORE_TRUE.value, help=flag.help)
        parser.add_argument(
            CliFlag.VERSION.value,
            action=ArgAction.VERSION.value,
            version=msg.VERSION_TEXT.format(version=APP_VERSION),
            help=CliFlag.VERSION.help,
        )
        modes: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group()
        for flag in (mode.flag for mode in RunMode if mode.flag is not None):
            if flag.takes_value:
                modes.add_argument(flag.value, metavar=msg.CLI_METAVAR_HANDLE, help=flag.help)
            else:
                modes.add_argument(flag.value, action=ArgAction.STORE_TRUE.value, help=flag.help)
        package: CliArgument = CliArgument.PACKAGE
        parser.add_argument(package.value, nargs=ArgCount.OPTIONAL.value, metavar=package.metavar, help=package.help)
        return parser

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Поля строки лога о запуске: секретов в ключах нет, ник канала — в кавычках (CLAUDE.md §11)."""
        fields: dict[str, object] = dict(mode=self.mode, auth=Quoted(self.auth_handle), dry_run=self.dry_run)
        return dict(fields, debug=self.debug, package=self.package_file)
