"""Команда замка: `python -m app.tools.code_standard [--init | --write-debt | --compare ВЕРСИЯ | --files ПУТЬ …]`.

Без флагов — отчёт и код 0. Реестр меняют только `--init` (создать реестр или добавить раздел правила,
которого в нём нет) и `--write-debt` (переписать по коду, если ничего не появилось и не выросло).
`--compare` сравнивает реестр на диске с прежней версией (git-ссылка или файл), `--files` — долги файлов.
"""
from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
from functools import cached_property
from pathlib import Path
from typing import Final, TextIO

from app.tools.code_standard.exemptions import Exceptions
from app.tools.code_standard.json_file import JsonProblem, StandardFileError
from app.tools.code_standard.ledger import Ledger, LedgerChange, LedgerDiff
from app.tools.code_standard.locations import LockFiles
from app.tools.code_standard.measurement import Measurements
from app.tools.code_standard.report import StandardReport
from app.tools.code_standard.rule import Rule
from app.tools.code_standard.source import SourceKey
from app.ui import messages_ru as msg

PROGRAM: Final[str] = "python -m app.tools.code_standard"
STORE_TRUE: Final[str] = "store_true"
ONE_OR_MORE: Final[str] = "+"
GIT: Final[str] = "git"
GIT_SHOW: Final[str] = "show"
GIT_OBJECT: Final[str] = "{ref}:{path}"


class CommandExit(IntEnum):
    """Коды выхода команды."""

    OK = 0          # отчёт напечатан, реестр создан или переписан, реестр не вырос
    REFUSED = 1     # реестр не меняется: долги появились или выросли, реестра нет или он уже есть
    BROKEN = 2      # файл замка или прежняя версия реестра не читаются


class CommandAction(str, Enum):
    """Что делает команда; значение — имя поля разбора argparse."""

    REPORT = "report"
    INIT = "init"
    WRITE_DEBT = "write_debt"
    COMPARE = "compare"
    FILES = "files"


class CliFlag(str, Enum):
    """Флаги командной строки."""

    INIT = "--init"
    WRITE_DEBT = "--write-debt"
    COMPARE = "--compare"
    FILES = "--files"


@dataclass(frozen=True)
class CommandRequest:
    """Разобранная командная строка: действие, версия для сравнения, пути."""

    action: CommandAction
    target: str
    paths: tuple[str, ...]

    @classmethod
    def parse(cls, argv: Sequence[str]) -> CommandRequest:
        parsed: argparse.Namespace = cls.parser().parse_args(list(argv))
        if parsed.compare is not None:
            return cls(CommandAction.COMPARE, parsed.compare, ())
        if parsed.files:
            return cls(CommandAction.FILES, "", tuple(parsed.files))
        flags: tuple[CommandAction, ...] = (CommandAction.INIT, CommandAction.WRITE_DEBT)
        chosen: list[CommandAction] = [action for action in flags if getattr(parsed, action.value)]
        return cls(chosen[0] if chosen else CommandAction.REPORT, "", ())

    @classmethod
    def parser(cls) -> argparse.ArgumentParser:
        parser: argparse.ArgumentParser = argparse.ArgumentParser(prog=PROGRAM, description=msg.CODE_STANDARD_DESCRIPTION)
        group = parser.add_mutually_exclusive_group()
        group.add_argument(CliFlag.INIT.value, dest=CommandAction.INIT.value, action=STORE_TRUE, help=msg.CODE_STANDARD_HELP_INIT)
        group.add_argument(
            CliFlag.WRITE_DEBT.value, dest=CommandAction.WRITE_DEBT.value, action=STORE_TRUE, help=msg.CODE_STANDARD_HELP_WRITE_DEBT
        )
        group.add_argument(
            CliFlag.COMPARE.value, dest=CommandAction.COMPARE.value,
            metavar=msg.CODE_STANDARD_METAVAR_VERSION, help=msg.CODE_STANDARD_HELP_COMPARE,
        )
        group.add_argument(
            CliFlag.FILES.value, dest=CommandAction.FILES.value, nargs=ONE_OR_MORE,
            metavar=msg.CODE_STANDARD_METAVAR_PATH, help=msg.CODE_STANDARD_HELP_FILES,
        )
        return parser


@dataclass(frozen=True)
class PreviousLedger:
    """Прежняя версия реестра: файл по пути или `git show <версия>:<путь реестра>`."""

    files: LockFiles
    target: str

    def load(self) -> Ledger:
        if Path(self.target).is_file():
            return Ledger.load(Path(self.target))
        spec: str = GIT_OBJECT.format(ref=self.target, path=self.files.ledger_in_git)
        try:
            shown = subprocess.run([GIT, GIT_SHOW, spec], cwd=self.files.root, capture_output=True, check=False)
        except OSError as error:
            raise StandardFileError(JsonProblem.GIT_FAILED, self.target) from error
        if shown.returncode:
            raise StandardFileError(JsonProblem.GIT_FAILED, self.target)
        return Ledger.parse(shown.stdout.decode(), self.target)


@dataclass(frozen=True)
class StandardCommand:
    """Одно действие команды над файлами замка; вывод — в `out`."""

    files: LockFiles
    request: CommandRequest
    out: TextIO

    def run(self) -> CommandExit:
        actions: dict[CommandAction, Callable[[], CommandExit]] = {
            CommandAction.REPORT: self._report,
            CommandAction.INIT: self._init,
            CommandAction.WRITE_DEBT: self._write_debt,
            CommandAction.COMPARE: self._compare,
            CommandAction.FILES: self._files,
        }
        try:
            return actions[self.request.action]()
        except StandardFileError as error:
            self._say((error.human,))
            return CommandExit.BROKEN

    @cached_property
    def _measurements(self) -> Measurements:
        return self.files.check().measure()

    @cached_property
    def _report_of_code(self) -> StandardReport:
        registered: Ledger | None = Ledger.load(self.files.ledger) if self.files.ledger.is_file() else None
        return StandardReport(self._measurements, Exceptions.load(self.files.exceptions), registered)

    def _report(self) -> CommandExit:
        self._say(self._report_of_code.lines())
        return CommandExit.OK

    def _init(self) -> CommandExit:
        debts: Ledger = self._report_of_code.debts
        registered: Ledger | None = self._report_of_code.ledger
        if registered is None:
            debts.save(self.files.ledger)
            self._say((msg.CODE_STANDARD_INIT_CREATED.format(file=self.files.ledger.name, count=debts.count),))
            return CommandExit.OK
        extended: Ledger = registered.with_sections_of(debts)
        added: list[str] = [rule.value for rule in extended.rules if rule not in registered.rules]
        if not added:
            self._say((msg.CODE_STANDARD_INIT_EXISTS.format(file=self.files.ledger.name),))
            return CommandExit.REFUSED
        extended.save(self.files.ledger)
        rules: str = msg.CODE_STANDARD_REPORT_RULE_JOINER.join(added)
        self._say((msg.CODE_STANDARD_INIT_EXTENDED.format(rules=rules, count=extended.count - registered.count),))
        return CommandExit.OK

    def _write_debt(self) -> CommandExit:
        registered: Ledger | None = self._report_of_code.ledger
        if registered is None:
            self._say((msg.CODE_STANDARD_NO_LEDGER,))
            return CommandExit.REFUSED
        diff: LedgerDiff = registered.diff(self._report_of_code.debts)
        if diff.growth:
            self._say((msg.CODE_STANDARD_WRITE_REFUSED,) + self._change_lines(diff.growth))
            return CommandExit.REFUSED
        self._report_of_code.debts.save(self.files.ledger)
        self._say((msg.CODE_STANDARD_WRITE_DONE.format(file=self.files.ledger.name, count=len(diff.reduction)),))
        return CommandExit.OK

    def _compare(self) -> CommandExit:
        diff: LedgerDiff = PreviousLedger(self.files, self.request.target).load().diff(Ledger.load(self.files.ledger))
        if diff.reduction:
            self._say((msg.CODE_STANDARD_COMPARE_REDUCED.format(target=self.request.target),) + self._change_lines(diff.reduction))
        if diff.growth:
            self._say((msg.CODE_STANDARD_COMPARE_GROWN.format(target=self.request.target),) + self._change_lines(diff.growth))
            return CommandExit.REFUSED
        self._say((msg.CODE_STANDARD_COMPARE_SAME.format(target=self.request.target),))
        return CommandExit.OK

    def _files(self) -> CommandExit:
        """Долги реестра в файлах и папках — для раздела «ДОЛГИ К СНЯТИЮ» промта задачи."""
        registered: Ledger | None = self._report_of_code.ledger
        if registered is None:
            self._say((msg.CODE_STANDARD_NO_LEDGER,))
            return CommandExit.REFUSED
        paths: tuple[SourceKey, ...] = tuple(self.files.key_of(raw) for raw in self.request.paths)
        debts: Ledger = registered.under(paths, self._measurements)
        lines: list[str] = [
            msg.CODE_STANDARD_FILES_LINE.format(rule=rule.value, key=key, value=value, signs=self._signs_of(rule, key))
            for rule in debts.rules for key, value in debts.section(rule).items()
        ]
        heading: str = msg.CODE_STANDARD_FILES_TITLE if lines else msg.CODE_STANDARD_FILES_NONE
        shown: str = msg.CODE_STANDARD_REPORT_RULE_JOINER.join(path.text for path in paths)
        self._say((heading.format(paths=shown),) + tuple(lines))
        return CommandExit.OK

    def _signs_of(self, rule: Rule, key: str) -> str:
        """Признаки нарушения после величины; нет признаков — пусто."""
        labels: str = msg.CODE_STANDARD_REPORT_SIGN_JOINER.join(
            sign.label for sign in self._measurements.of(rule).signs_of(key)
        )
        return msg.CODE_STANDARD_FILES_SIGNS.format(signs=labels) if labels else ""

    def _change_lines(self, changes: tuple[LedgerChange, ...]) -> tuple[str, ...]:
        return tuple(change.line for change in changes)

    def _say(self, lines: Sequence[str]) -> None:
        for line in lines:
            print(line, file=self.out)
