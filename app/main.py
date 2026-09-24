"""Точка входа livecraft: флаги (CLAUDE.md §10), коды выхода (§10).

Только разбор флагов, построение зависимостей и печать; оркестрация — app\\pipeline\\runner.py (этап 4).
Вывод в консоль — только отсюда и только текстами из messages_ru: шапка сразу после настройки логов
(до конфигов и сети), строки прогресса по ходу работы, пустая строка, итоговые блоки.
Обрыв (Ctrl+C) и любое необработанное исключение ловятся в run_cli: строка в лог и в консоль, код 1 —
это единственный перехват Exception во всей программе (§11).

Каждый запуск, кроме --version, сначала кладёт livecraft.json из поставочного шаблона, если файла нет
(в git его нет, §5), затем читает сейф и оба конфига (app\\setup\\readiness.py) — независимо друг от друга.
Фильтр секретов в логах встаёт сразу после чтения сейфа (§7.4). Ссылка на форму, оставшаяся в сейфе, один раз
сама переносится в livecraft.json (app\\setup\\migration.py).

Режим задаёт ярлык (§10, §14 решения 17, 18): --announce, --broadcast, --from-package, без флага — «всё».
Готовность считается по частям режима (app\\setup\\run_mode.py): не готова часть — одна строка с точным
действием и код 1; не готово ничего — программа сама открывает окно настройки и после него отдаёт код 2 (§8.2).
Шаблоны файлов в консоль не печатаются: файлы правит настройщик. --setup открывает окно при любом состоянии
(app\\setup\\app.py); --check, --auth и --status пока требуют полной настройки. Сам прогон частей — задача 3.9.
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
from typing import Final

from app.config.loader import ShippedSettings
from app.core.dates import format_datetime_text
from app.observability.logging_setup import close_logging, get_logger, install_secret_filter, setup_logging
from app.paths import LivecraftPaths, build_paths, ensure_dirs, resolve_root
from app.runtime.single_instance import AnotherInstanceRunning, InstanceLock, LockOwner
from app.setup.migration import FormUrlMigration, FormUrlMigrationResult
from app.setup.readiness import ModeReadiness, Readiness
from app.setup.run_mode import RunMode
from app.ui import messages_ru as msg
from app.version import APP_VERSION

LOGGER = get_logger("main")

PROGRAM_NAME: Final[str] = "livecraft"


class ExitCode(IntEnum):
    """Коды выхода (CLAUDE.md §10). Появится runner.decide_exit → RunExit — переедут туда, как в planers."""

    OK = 0                 # сделано всё, что можно
    ERRORS = 1             # есть ошибки
    CONFIG = 2             # ошибка конфигурации, сейфа или авторизации — ничего не делалось
    NO_FUTURE_SLOTS = 3    # в таблице нет будущих слотов — к каналам не обращались


@dataclass(frozen=True)
class RunRequest:
    """Что запросила командная строка: один объект вместо россыпи флагов по параметрам (CLAUDE.md §0).

    Режимы работы (announce / broadcast / from-package / без флага) и служебные запуски (setup / check /
    auth / status) взаимоисключающие — это держит argparse; объект знает только, что именно запрошено,
    и сам отвечает на вопросы о себе.
    """

    mode: RunMode
    setup: bool
    check: bool
    auth: str | None
    status: bool
    dry_run: bool
    no_llm: bool
    debug: bool

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> RunRequest:
        """Namespace argparse дальше главной функции не уходит: ниже работают только с этим объектом."""
        return cls(
            mode=RunMode.of(announce=args.announce, broadcast=args.broadcast, from_package=args.from_package),
            setup=args.setup,
            check=args.check,
            auth=args.auth,
            status=args.status,
            dry_run=args.dry_run,
            no_llm=args.no_llm,
            debug=args.debug,
        )

    @property
    def is_service_run(self) -> bool:
        """Служебный запуск (--setup, --check, --auth, --status), а не работа режима."""
        return self.setup or self.check or self.auth is not None or self.status

    @property
    def log_line(self) -> str:
        """Строка запуска для лога: секретов в флагах нет, ник канала — в кавычках (CLAUDE.md §11)."""
        return (
            f"mode={self.mode.value} setup={self.setup} check={self.check} auth={_quoted(self.auth)} status={self.status} "
            f"dry_run={self.dry_run} no_llm={self.no_llm}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog=PROGRAM_NAME, description=msg.CLI_DESCRIPTION
    )
    parser.add_argument("--dry-run", action="store_true", help=msg.HELP_DRY_RUN)
    parser.add_argument("--no-llm", action="store_true", help=msg.HELP_NO_LLM)
    parser.add_argument("--debug", action="store_true", help=msg.HELP_DEBUG)
    parser.add_argument(
        "--version",
        action="version",
        version=msg.VERSION_TEXT.format(version=APP_VERSION),
        help=msg.HELP_VERSION,
    )
    modes: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group()
    modes.add_argument("--announce", action="store_true", help=msg.HELP_ANNOUNCE)
    modes.add_argument("--broadcast", action="store_true", help=msg.HELP_BROADCAST)
    modes.add_argument("--from-package", action="store_true", help=msg.HELP_FROM_PACKAGE)
    modes.add_argument("--setup", action="store_true", help=msg.HELP_SETUP)
    modes.add_argument("--check", action="store_true", help=msg.HELP_CHECK)
    modes.add_argument("--auth", metavar=msg.CLI_METAVAR_HANDLE, help=msg.HELP_AUTH)
    modes.add_argument("--status", action="store_true", help=msg.HELP_STATUS)
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    # Консоль настраивается до разбора флагов: --help, --version и ошибку разбора печатает сам argparse,
    # и в консоли с кодировкой cp1251 «→» из CLI_DESCRIPTION иначе роняет запуск вместо вывода справки.
    _configure_console()
    request: RunRequest = RunRequest.from_args(build_parser().parse_args(argv))
    paths: LivecraftPaths = build_paths(resolve_root())
    ensure_dirs(paths)
    # Замок — до настройки логов и после ensure_dirs: без state\ и logs\ ему некуда лечь
    # (CLAUDE.md §6, инвариант 12). Сбой файловой системы здесь не перехватывается: лога,
    # в который пишется причина падения, ещё нет.
    lock: InstanceLock = InstanceLock(path=paths.lock_file, startup_log=paths.startup_log_file)
    try:
        lock.acquire()
    except AnotherInstanceRunning as conflict:
        _say_lock_rejected(conflict.owner)
        return int(ExitCode.ERRORS)
    try:
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
        exit_code: int = _run_guarded(request, paths, log_path)
        LOGGER.info("run_finished exit_code=%d", exit_code)
        return exit_code
    finally:
        close_logging()
        lock.release()


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
    """Готовность решает Readiness; здесь — только печать и выбор кода (§8.2, §10)."""
    _install_settings(paths)
    readiness: Readiness = Readiness.check(paths)
    if readiness.vault is not None:
        install_secret_filter(readiness.vault)      # сразу после чтения сейфа, до любых строк лога (§7.4)
    readiness = _migrate_form_url(paths, readiness)
    _log_readiness(readiness)
    _say_lines(readiness.warnings)
    if request.setup:
        return _run_setup(paths)
    if request.is_service_run:
        return _run_service(readiness)
    return _run_mode(request, paths, readiness)


def _run_service(readiness: Readiness) -> int:
    """--check, --auth, --status: нужны и каналы, и все ключи — без полной настройки не начинаются."""
    if not readiness.is_ready:
        _say_lines(readiness.problems)
        _say(msg.SETUP_REQUIRED)
        return int(ExitCode.CONFIG)
    _say_lines(readiness.summary_lines)
    return int(ExitCode.OK)


def _run_mode(request: RunRequest, paths: LivecraftPaths, readiness: Readiness) -> int:
    """Режим по частям (§10): не готово ничего — окно настройки и код 2; не готова часть — строка и код 1.

    Файл ключей и ссылок повреждён — окно его не починит (правка там выключена): только строки и код 2.
    Прогона частей пока нет (задача 3.9): после проверки программа ничего не делает.
    """
    mode: ModeReadiness = readiness.for_mode(request.mode, no_llm=request.no_llm)
    LOGGER.info("mode_readiness %s", mode.log_line)
    if mode.is_nothing_ready and not mode.is_fixable_in_setup:
        _say_lines(readiness.problems)
        return int(ExitCode.CONFIG)
    if mode.is_nothing_ready:
        _say_lines(mode.lines)
        _say(msg.SETUP_OPENING)
        _run_setup(paths)
        return int(ExitCode.CONFIG)
    _say_lines(readiness.summary_lines)
    _say_lines(mode.lines)
    return int(ExitCode.ERRORS) if mode.blocked else int(ExitCode.OK)


def _install_settings(paths: LivecraftPaths) -> None:
    """livecraft.json в git нет (§5): нет файла — программа кладёт поставочный вид сама, человеку делать нечего."""
    if not ShippedSettings(template=msg.CONFIG_SETTINGS_TEMPLATE).install(paths.config_file):
        return
    LOGGER.info("settings_file_created path=%s", paths.config_file)
    _say(msg.SETTINGS_FILE_CREATED.format(path=paths.config_file))


def _migrate_form_url(paths: LivecraftPaths, readiness: Readiness) -> Readiness:
    """Ссылка на форму из сейфа — один раз в livecraft.json (§14 решение 15); перенесено — готовность заново.

    Фильтр секретов уже стоит на всех значениях сейфа и повторно не ставится: перечитанный сейф — подмножество.
    """
    migration: FormUrlMigration | None = FormUrlMigration.plan(paths, readiness)
    if migration is None:
        return readiness
    result: FormUrlMigrationResult = migration.run()
    _say(result.console_line)
    if not result.moved:
        LOGGER.warning("form_url_not_migrated %s", result.log_line)
        return readiness
    LOGGER.info("form_url_migrated %s", result.log_line)
    return Readiness.check(paths)


def _run_setup(paths: LivecraftPaths) -> int:
    """Окно настройщика (§8). tkinter тянется только сюда: обычный запуск окна не знает.

    TclError при создании окна — нет Tk или рабочего стола: строка в консоль и в лог, код 1.
    """
    from tkinter import TclError

    from app.setup.app import SetupApp

    try:
        SetupApp(paths).run()
    except TclError as error:
        LOGGER.error("setup_window_failed error=%s", error)
        _say(msg.SETUP_WINDOW_FAILED.format(error=error))
        return int(ExitCode.ERRORS)
    return int(ExitCode.OK)


def _log_readiness(readiness: Readiness) -> None:
    """Строка готовности и причины отказа — в лог; значений сейфа здесь нет ни в одной строке."""
    LOGGER.info("readiness %s ready=%s", readiness.log_line, readiness.is_ready)
    for error in readiness.config_errors:
        LOGGER.error(
            "config_error path=%s key=%s kind=%s problem=%s",
            error.config_path,
            error.key_path,
            error.kind.value,
            error.problem,
        )
    for line in readiness.template_lines:          # шаблон сломанного файла — только в лог, в консоль не идёт
        LOGGER.debug("config_template %s", line)
    if readiness.vault_error is not None:
        LOGGER.error("vault_error error=%s", readiness.vault_error)
    if readiness.vault_load is not None and readiness.vault_load.is_local_unreadable:
        LOGGER.warning("vault_local_unreadable working_on=supplied")


def _configure_console() -> None:
    """Символы, которых нет в кодировке консоли, — заменой, а не падением."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def _say(text: str) -> None:
    """flush — чтобы строка была видна сразу и в собранном exe, а не в конце запуска."""
    print(text, flush=True)


def _say_lines(lines: tuple[str, ...]) -> None:
    for line in lines:
        _say(line)


def _say_error(text: str) -> None:
    """Отказ запуска — в stderr: в stdout идут только тексты работающего запуска."""
    print(text, file=sys.stderr, flush=True)


def _say_lock_rejected(owner: LockOwner) -> None:
    """Замок занят: называем владельца, если его удалось опознать (инвариант 12)."""
    if owner.is_known:
        _say_error(msg.LOCK_REJECTED.format(pid=owner.pid, started_at=owner.started_at))
        return
    _say_error(msg.LOCK_REJECTED_UNKNOWN_OWNER)


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
