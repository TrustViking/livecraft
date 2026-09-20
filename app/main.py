"""Точка входа livecraft: флаги (CLAUDE.md §10), коды выхода (§10).

Только разбор флагов, построение зависимостей и печать; оркестрация — app\\pipeline\\runner.py (этап 4).
Вывод в консоль — только отсюда и только текстами из messages_ru: шапка сразу после настройки логов
(до конфигов и сети), строки прогресса по ходу работы, пустая строка, итоговые блоки.
Обрыв (Ctrl+C) и любое необработанное исключение ловятся в run_cli: строка в лог и в консоль, код 1 —
это единственный перехват Exception во всей программе (§11).

Пока нет сейфа (§7) и загрузчика конфига (§5), обычный запуск не начинается: любой режим, кроме
--version, печатает SETUP_REQUIRED и возвращает код 2. Ветка получит настоящую проверку сейфа и конфига
в задаче про загрузчик; поведение программы без настройки от этого не изменится (§8).
"""
from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path

from app.core.dates import format_datetime_text
from app.observability.logging_setup import close_logging, get_logger, setup_logging
from app.paths import LivecraftPaths, build_paths, ensure_dirs, resolve_root
from app.ui import messages_ru as msg
from app.version import APP_VERSION

LOGGER = get_logger("main")

PROGRAM_NAME: str = "livecraft"
AUTH_ALL: str = "all"
EXPORT_SLOTS_METAVAR: str = "ПУТЬ"
AUTH_METAVAR: str = "HANDLE"


class ExitCode(IntEnum):
    """Коды выхода (CLAUDE.md §10). Появится runner.decide_exit → RunExit — переедут туда, как в planers."""

    OK = 0                 # сделано всё, что можно
    ERRORS = 1             # есть ошибки
    CONFIG = 2             # ошибка конфигурации, сейфа или авторизации — ничего не делалось
    NO_FUTURE_SLOTS = 3    # в таблице нет будущих слотов — к каналам не обращались


@dataclass(frozen=True)
class RunRequest:
    """Что запросила командная строка: один объект вместо россыпи флагов по параметрам (CLAUDE.md §0).

    Режимы setup / check / auth / status взаимоисключающие — это держит argparse; объект знает только,
    что именно запрошено, и сам отвечает на вопросы о себе.
    """

    setup: bool
    check: bool
    auth: str | None
    status: bool
    dry_run: bool
    no_llm: bool
    export_slots: Path | None
    debug: bool

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> RunRequest:
        """Namespace argparse дальше главной функции не уходит: ниже работают только с этим объектом."""
        export: str | None = args.export_slots
        return cls(
            setup=args.setup,
            check=args.check,
            auth=args.auth,
            status=args.status,
            dry_run=args.dry_run,
            no_llm=args.no_llm,
            export_slots=None if export is None else Path(export),
            debug=args.debug,
        )

    @property
    def log_line(self) -> str:
        """Строка запуска для лога: секретов в флагах нет, ник канала — в кавычках (CLAUDE.md §11)."""
        return (
            f"setup={self.setup} check={self.check} auth={_quoted(self.auth)} status={self.status} "
            f"dry_run={self.dry_run} no_llm={self.no_llm} export_slots={self.export_slots}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog=PROGRAM_NAME, description=msg.CLI_DESCRIPTION
    )
    parser.add_argument("--dry-run", action="store_true", help=msg.HELP_DRY_RUN)
    parser.add_argument("--no-llm", action="store_true", help=msg.HELP_NO_LLM)
    parser.add_argument("--export-slots", metavar=EXPORT_SLOTS_METAVAR, help=msg.HELP_EXPORT_SLOTS)
    parser.add_argument("--debug", action="store_true", help=msg.HELP_DEBUG)
    parser.add_argument(
        "--version",
        action="version",
        version=msg.VERSION_TEXT.format(version=APP_VERSION),
        help=msg.HELP_VERSION,
    )
    modes: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group()
    modes.add_argument("--setup", action="store_true", help=msg.HELP_SETUP)
    modes.add_argument("--check", action="store_true", help=msg.HELP_CHECK)
    modes.add_argument("--auth", metavar=AUTH_METAVAR, help=msg.HELP_AUTH)
    modes.add_argument("--status", action="store_true", help=msg.HELP_STATUS)
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    # Консоль настраивается до разбора флагов: --help, --version и ошибку разбора печатает сам argparse,
    # и в консоли с кодировкой cp1251 «→» из CLI_DESCRIPTION иначе роняет запуск вместо вывода справки.
    _configure_console()
    # Здесь берётся файл-замок state\livecraft.lock — до настройки логов (CLAUDE.md §6, инвариант 12).
    request: RunRequest = RunRequest.from_args(build_parser().parse_args(argv))
    paths: LivecraftPaths = build_paths(resolve_root())
    ensure_dirs(paths)
    log_path: Path = setup_logging(paths.logs_dir, debug=request.debug)
    LOGGER.info(
        "run_started version=%s root=%s %s log=%s",
        APP_VERSION,
        paths.root,
        request.log_line,
        log_path,
    )
    now_utc: datetime = datetime.now(timezone.utc)
    _say_title(now_utc)
    try:
        exit_code: int = _run_guarded(request, paths, log_path)
        LOGGER.info("run_finished exit_code=%d", exit_code)
        return exit_code
    finally:
        close_logging()


def _run_guarded(request: RunRequest, paths: LivecraftPaths, log_path: Path) -> int:
    """Обрыв и падение не пропадают без следа: причина — в лог, короткая строка — в консоль, код 1."""
    try:
        return _run(request, paths)
    except KeyboardInterrupt:
        LOGGER.warning("run_interrupted")
        _say(msg.RUN_INTERRUPTED)
    # Единственный перехват Exception в livecraft (CLAUDE.md §11): всё, что не обработано ниже, —
    # ошибка программы. Без него трассировка ушла бы только в окно консоли, которое оператор закроет,
    # а лог остался бы оборванным на последней строке.
    except Exception:
        LOGGER.exception("run_crashed log=%s", log_path)
        _say(msg.RUN_CRASHED.format(log=log_path))
    return int(ExitCode.ERRORS)


def _run(request: RunRequest, paths: LivecraftPaths) -> int:
    """Сейфа и конфига ещё нет — значит настроенной программы нет: код 2 и строка про --setup (§8)."""
    LOGGER.error("setup_required vault=%s config=%s", paths.vault_local_file, paths.config_file)
    _say(msg.SETUP_REQUIRED)
    return int(ExitCode.CONFIG)


def _configure_console() -> None:
    """Символы, которых нет в кодировке консоли, — заменой, а не падением."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def _say(text: str) -> None:
    """flush — чтобы строка была видна сразу и в собранном exe, а не в конце запуска."""
    print(text, flush=True)


def _say_title(now_utc: datetime) -> None:
    """Шапка — первая строка любого запуска; время — то же, что в отчёте этого запуска."""
    _say(
        msg.CONSOLE_TITLE.format(
            version=APP_VERSION, generated_at=format_datetime_text(now_utc.astimezone())
        )
    )


def _quoted(value: str | None) -> str:
    """Ник канала в логе — в кавычках (CLAUDE.md §11); не задан — прочерк без кавычек."""
    return "-" if value is None else f'"{value}"'


if __name__ == "__main__":
    sys.exit(run_cli())
