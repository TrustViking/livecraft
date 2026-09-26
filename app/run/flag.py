"""Ключи командной строки livecraft (CLAUDE.md §10) и действия argparse, которыми они разбираются.

Значение члена `CliFlag` — сам ключ; справка к нему — текст из messages_ru. Имя поля, под которым argparse кладёт
значение ключа, — имя члена строчными буквами: `--dry-run` → `dry_run`, как считает сам argparse.
"""
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Final

from app.ui import messages_ru as msg


class ArgAction(str, Enum):
    """Действия argparse, которыми разбираются ключи livecraft и пробников."""

    STORE_TRUE = "store_true"     # ключ без значения: есть — да
    VERSION = "version"           # напечатать номер версии и выйти


class CliFlag(str, Enum):
    """Ключ командной строки."""

    DRY_RUN = "--dry-run"
    NO_LLM = "--no-llm"
    DEBUG = "--debug"
    VERSION = "--version"
    ANNOUNCE = "--announce"
    BROADCAST = "--broadcast"
    FROM_PACKAGE = "--from-package"
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
    CliFlag.NO_LLM: msg.HELP_NO_LLM,
    CliFlag.DEBUG: msg.HELP_DEBUG,
    CliFlag.VERSION: msg.HELP_VERSION,
    CliFlag.ANNOUNCE: msg.HELP_ANNOUNCE,
    CliFlag.BROADCAST: msg.HELP_BROADCAST,
    CliFlag.FROM_PACKAGE: msg.HELP_FROM_PACKAGE,
    CliFlag.SETUP: msg.HELP_SETUP,
    CliFlag.CHECK: msg.HELP_CHECK,
    CliFlag.AUTH: msg.HELP_AUTH,
    CliFlag.STATUS: msg.HELP_STATUS,
}
