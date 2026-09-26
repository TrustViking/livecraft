"""Что запросила командная строка (CLAUDE.md §10): один объект вместо россыпи ключей.

Разбор строит argparse из `CliFlag`; разобранные ключи дальше `RunRequest.from_argv` не уходят. Режимы и служебные
запуски взаимоисключающие — это держит argparse (ошибка разбора — код 2, текст печатает он сам); `--help`
и `--version` argparse печатает и выходит тоже сам.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.run.flag import ArgAction, CliFlag
from app.run.mode import RunMode
from app.ui import messages_ru as msg
from app.version import APP_NAME, APP_VERSION

HANDLE_LOG_TEMPLATE: Final[str] = '"{handle}"'     # ник канала в логе — в кавычках (CLAUDE.md §11)
OPTION_FLAGS: Final[tuple[CliFlag, ...]] = (CliFlag.DRY_RUN, CliFlag.NO_LLM, CliFlag.DEBUG)


@dataclass(frozen=True)
class RunRequest:
    """Режим запуска, ник для входа (`--auth`) и ключи, которые меняют прогон любого режима."""

    mode: RunMode
    auth_handle: str | None
    dry_run: bool
    no_llm: bool
    debug: bool

    @classmethod
    def from_argv(cls, argv: Sequence[str] | None) -> RunRequest:
        """Запрос из командной строки; без ключа режима — «всё»."""
        values: Mapping[str, object] = vars(cls._parser().parse_args(argv))
        mode: RunMode = next(
            (mode for mode in RunMode if mode.flag is not None and mode.flag.is_given(values)), RunMode.ALL
        )
        handle: object = values.get(CliFlag.AUTH.dest)
        return cls(
            mode=mode,
            auth_handle=handle if isinstance(handle, str) else None,
            dry_run=CliFlag.DRY_RUN.is_given(values),
            no_llm=CliFlag.NO_LLM.is_given(values),
            debug=CliFlag.DEBUG.is_given(values),
        )

    @classmethod
    def _parser(cls) -> argparse.ArgumentParser:
        """Ключи прогона, номер версии и взаимоисключающие ключи режимов — в порядке справки."""
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
        return parser

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Поля строки лога о запуске: секретов в ключах нет, ник канала — в кавычках (CLAUDE.md §11)."""
        handle: str | None = None if self.auth_handle is None else HANDLE_LOG_TEMPLATE.format(handle=self.auth_handle)
        return dict(mode=self.mode, auth=handle, dry_run=self.dry_run, no_llm=self.no_llm, debug=self.debug)
