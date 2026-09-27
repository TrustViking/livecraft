"""Точка входа livecraft: ключи (CLAUDE.md §10), коды выхода (§10) и шаги запуска.

`run_cli` — одна свободная функция: консоль, ключи, корень, папки, замок одного экземпляра до логов, лог запуска,
`Launch` и освобождение. `Launch` ведёт шаги запуска: шапка сразу после настройки логов (до конфигов и сети),
строки по ходу работы, итоговые строки. Обрыв (Ctrl+C) и любое необработанное исключение ловит `Launch.run`:
строка в лог и в консоль, код 1 — это единственный перехват Exception во всей программе (§11).

Каждый запуск, кроме --version, сначала кладёт livecraft.json из поставочного шаблона, если файла нет
(в git его нет, §5), затем читает сейф и оба конфига (app\\setup\\readiness.py) — независимо друг от друга.
Фильтр секретов в логах встаёт сразу после чтения сейфа (§7.4). Ссылка на форму, оставшаяся в сейфе, один раз
сама переносится в livecraft.json (app\\setup\\migration.py).

Режим задаёт ярлык (§10, §14 решения 17, 18). Что делает запуск режима, решает его готовность
(`ModeReadiness.step`): не готово ничего — окно настройки и код 2 (§8.2); готова таблица плана — прогон контура A
(app\\intake): таблица → источники → merge → слоты → пакет в bcast\\; merge — когда его часть готова (нет --no-llm,
ключ OpenAI в сейфе), иначе тексты слотов — из видео. --setup открывает окно при любом состоянии;
--check, --auth и --status пока требуют полной настройки. Код запуска — самый важный из исходов частей (app\\run).
--dry-run прогон не меняет: контур A ничего снаружи не создаёт, пакет пишется всегда (§10).
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import uuid4

from app.config.files import SettingsFile, ShippedSettings
from app.core.clock import Clock
from app.intake.intake import IntakeRequest, IntakeResult, PlanIntake
from app.observability.log_event import MESSAGE_TEMPLATE, LogArea, LogEvent, get_logger
from app.observability.logging_setup import RunLog
from app.paths import LivecraftPaths
from app.run.exit_code import ExitCode, RunOutcome
from app.run.mode import ModeReadiness, ModeStep, RunMode
from app.run.request import RunRequest
from app.runtime.single_instance import AnotherInstanceRunning, InstanceLock
from app.secretsafe.vault import Vault
from app.setup.migration import FormUrlMigration, FormUrlMigrationResult
from app.setup.readiness import PlanBasis, Readiness
from app.ui import messages_ru as msg
from app.ui.console import Console
from app.version import APP_VERSION

LOGGER = get_logger(LogArea.MAIN)
SHIPPED_SETTINGS: ShippedSettings = ShippedSettings()


class LaunchEvent(str, Enum):
    """События запуска в логе."""

    STARTED = "run_started"
    FINISHED = "run_finished"
    INTERRUPTED = "run_interrupted"
    CRASHED = "run_crashed"
    SETTINGS_FILE_CREATED = "settings_file_created"
    SETUP_WINDOW_FAILED = "setup_window_failed"


@dataclass(frozen=True)
class Launch:
    """Шаги одного запуска: что запрошено, где корень, куда писать оператору и в какой лог."""

    request: RunRequest
    paths: LivecraftPaths
    console: Console
    log: RunLog

    def run(self, started: datetime) -> ExitCode:
        """Строка запуска и шапка, шаги запуска, строка итога. Обрыв и падение не пропадают без следа."""
        started_event: LogEvent = LogEvent.of(LaunchEvent.STARTED, version=APP_VERSION, root=self.paths.root)
        started_event.extended(**self.request.log_fields, log=self.log.path).emit(LOGGER)
        self.console.title(started)
        code: ExitCode = ExitCode.ERRORS
        try:
            code = self._run()
        except KeyboardInterrupt:
            LogEvent.of(LaunchEvent.INTERRUPTED).emit(LOGGER, logging.WARNING)
            self.console.say(msg.RUN_INTERRUPTED)
        # Единственный перехват Exception в livecraft (CLAUDE.md §11): всё, что не обработано ниже, — ошибка
        # программы. Без него трассировка ушла бы только в окно консоли, которое оператор закроет, а лог остался бы
        # оборванным на последней строке.
        except Exception:
            LOGGER.exception(MESSAGE_TEMPLATE, LogEvent.of(LaunchEvent.CRASHED, log=self.log.path).text)
            self.console.say(msg.RUN_CRASHED.format(log=self.log.path))
        LogEvent.of(LaunchEvent.FINISHED, exit_code=code).emit(LOGGER)
        return code

    def _run(self) -> ExitCode:
        """Готовность решает Readiness; здесь — только порядок шагов и печать (§8.2, §10)."""
        self._install_settings()
        readiness: Readiness = Readiness.check(self.paths)
        vault: Vault | None = readiness.vault.vault
        if vault is not None:
            self.log.protect(vault.log_filter())     # сразу после чтения сейфа, до любых строк лога (§7.4)
        readiness = self._migrate_form_url(readiness)
        readiness.log(LOGGER)
        self.console.say_lines(readiness.warnings)
        if self.request.mode.is_service:
            return self._service(readiness).exit_code
        return self._mode(readiness)

    def _service(self, readiness: Readiness) -> RunOutcome:
        """--setup — окно при любом состоянии; --check, --auth, --status — только при полной настройке."""
        if self.request.mode is RunMode.SETUP:
            return self._setup()
        if not readiness.is_ready:
            self.console.say_lines(readiness.problems)
            self.console.say(msg.SETUP_REQUIRED)
            return RunOutcome.NOT_CONFIGURED
        self.console.say_lines(readiness.summary_lines)
        return RunOutcome.DONE

    def _mode(self, readiness: Readiness) -> ExitCode:
        """Режим по частям (§10): что делать, решает `ModeReadiness.step`; код — важнейший из исходов частей."""
        mode: ModeReadiness = readiness.for_mode(self.request.mode, no_llm=self.request.no_llm)
        mode.event.emit(LOGGER)
        step: ModeStep = mode.step
        if step is ModeStep.REFUSE:
            self.console.say_lines(readiness.problems)
            return RunOutcome.NOT_CONFIGURED.exit_code
        if step is ModeStep.OPEN_SETUP:
            self.console.say_lines(mode.lines)
            self.console.say(msg.SETUP_OPENING)
            self._setup()
            return RunOutcome.NOT_CONFIGURED.exit_code
        self.console.say_lines(readiness.summary_lines)
        self.console.say_lines(mode.lines)
        code: ExitCode = mode.outcome.exit_code
        basis: PlanBasis | None = readiness.plan_basis(mode)
        if basis is None:           # таблица плана этому режиму не нужна или не готова
            return code
        result: IntakeResult = self._intake(basis)
        self.console.say_lines(result.console_lines)
        return code.combined(result.outcome.exit_code)

    def _intake(self, basis: PlanBasis) -> IntakeResult:
        """Прогон контура A: «сейчас» — в зоне программы, id пакета — новый на каждый запуск.

        Первый вход оператора открывает браузер — перед этим строка в консоль.
        """
        now: datetime = Clock(basis.settings.zone).now()
        request: IntakeRequest = IntakeRequest(
            paths=self.paths,
            settings=basis.settings,
            vault=basis.vault,
            now=now,
            package_id=uuid4().hex,
            with_merge=basis.with_merge,
        )
        return PlanIntake.of(request, on_login=lambda: self.console.say(msg.SHEETS_LOGIN_BROWSER)).run()

    def _install_settings(self) -> None:
        """livecraft.json в git нет (§5): нет файла — программа кладёт поставочный вид сама, человеку делать нечего."""
        if not SettingsFile.of(self.paths).install_shipped():
            return
        LogEvent.of(LaunchEvent.SETTINGS_FILE_CREATED, path=self.paths.config_file).emit(LOGGER)
        self.console.say(msg.SETTINGS_FILE_CREATED.format(path=self.paths.config_file))

    def _migrate_form_url(self, readiness: Readiness) -> Readiness:
        """Ссылка на форму из сейфа — один раз в livecraft.json (§14 решение 15); перенесено — готовность заново.

        Фильтр секретов уже стоит на всех значениях сейфа и повторно не ставится: перечитанный сейф — подмножество.
        """
        migration: FormUrlMigration | None = FormUrlMigration.plan(self.paths, readiness)
        if migration is None:
            return readiness
        result: FormUrlMigrationResult = migration.run()
        self.console.say(result.console_line)
        result.event.emit(LOGGER, result.log_level)
        return Readiness.check(self.paths) if result.moved else readiness

    def _setup(self) -> RunOutcome:
        """Окно настройщика (§8). tkinter тянется только сюда: обычный запуск окна не знает.

        TclError при создании окна — нет Tk или рабочего стола: строка в консоль и в лог, ошибка.
        """
        from tkinter import TclError

        from app.setup.app import SetupApp

        try:
            SetupApp(self.paths).run()
        except TclError as error:
            LogEvent.of(LaunchEvent.SETUP_WINDOW_FAILED, error=error).emit(LOGGER, logging.ERROR)
            self.console.say(msg.SETUP_WINDOW_FAILED.format(error=error))
            return RunOutcome.FAILED
        return RunOutcome.DONE


def run_cli(argv: Sequence[str] | None = None) -> int:
    """Консоль, ключи, корень и папки, замок до логов, лог запуска, шаги запуска; замок и лог — снимаются всегда.

    Консоль настраивается до разбора ключей: справку и ошибку разбора печатает сам argparse. Настройки ещё не
    прочитаны: часы замка, startup.log, лога и шапки идут в поясе поставочного шаблона. Замок — после папок и до
    лога (CLAUDE.md §6, инвариант 12); сбой файловой системы здесь не перехватывается: лога для причины ещё нет.
    """
    console: Console = Console.system()
    console.configure()
    request: RunRequest = RunRequest.from_argv(argv)
    paths: LivecraftPaths = LivecraftPaths.locate()
    paths.ensure_dirs()
    clock: Clock = SHIPPED_SETTINGS.clock
    lock: InstanceLock = InstanceLock(path=paths.lock_file, startup_log=paths.startup_log_file, clock=clock)
    try:
        lock.acquire()
    except AnotherInstanceRunning as conflict:
        console.say_error(conflict.human)
        return int(ExitCode.ERRORS)
    try:
        started: datetime = clock.now()
        log: RunLog = RunLog.open(paths.logs_dir, debug=request.debug, started=started)
        try:
            return int(Launch(request, paths, console, log).run(started))
        finally:
            log.close()
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(run_cli())
