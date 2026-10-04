"""Ключи командной строки livecraft (CLAUDE.md §10) и действия argparse, которыми они разбираются.

Значение члена `CliFlag` — сам ключ; справка к нему — текст из каталога msg. Имя поля, под которым argparse кладёт
значение ключа, — имя члена строчными буквами: `--dry-run` → `dry_run`, как считает сам argparse.
"""
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Final

from app.ui.messages import msg


class ArgAction(str, Enum):
    """Действия argparse, которыми разбираются ключи livecraft и пробников."""

    STORE_TRUE = "store_true"     # ключ без значения: есть — да
    VERSION = "version"           # напечатать номер версии и выйти


class ArgCount(str, Enum):
    """Сколько значений берёт аргумент argparse."""

    OPTIONAL = "?"                # позиционный аргумент, которого может и не быть


class CliArgument(str, Enum):
    """Позиционный аргумент командной строки; значение — имя поля, под которым argparse кладёт его значение."""

    PACKAGE = "package"           # пакет .bcast, открытый из проводника (§14 решения 18, 37)

    @property
    def help(self) -> str:
        return msg.HELP_PACKAGE_FILE

    @property
    def metavar(self) -> str:
        return msg.CLI_METAVAR_PACKAGE

    def value_in(self, values: Mapping[str, object]) -> str | None:
        """Значение аргумента в разобранных ключах; не дан — None."""
        value: object = values.get(self.value)
        return value if isinstance(value, str) else None


class CliFlag(str, Enum):
    """Ключ командной строки."""

    DRY_RUN = "--dry-run"
    DEBUG = "--debug"
    VERSION = "--version"
    SETUP = "--setup"
    CHECK = "--check"
    AUTH = "--auth"
    STATUS = "--status"

    @property
    def help(self) -> str:
        return CLI_FLAG_HELP[self]

    @property
    def dest(self) -> str:
        """Имя поля разобранных ключей, под которым argparse кладёт значение этого ключа."""
        return self.name.lower()

    @property
    def takes_value(self) -> bool:
        """Ключ со значением: `--auth <ник>`; остальные — без значения."""
        return self is CliFlag.AUTH

    def is_given(self, values: Mapping[str, object]) -> bool:
        """Ключ есть в командной строке: у ключа со значением — строка, у прочих — истина."""
        value: object = values.get(self.dest)
        return isinstance(value, str) if self.takes_value else value is True


CLI_FLAG_HELP: Final[dict[CliFlag, str]] = {
    CliFlag.DRY_RUN: msg.HELP_DRY_RUN,
    CliFlag.DEBUG: msg.HELP_DEBUG,
    CliFlag.VERSION: msg.HELP_VERSION,
    CliFlag.SETUP: msg.HELP_SETUP,
    CliFlag.CHECK: msg.HELP_CHECK,
    CliFlag.AUTH: msg.HELP_AUTH,
    CliFlag.STATUS: msg.HELP_STATUS,
}
