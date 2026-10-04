"""Точка входа livecraft: ключи (CLAUDE.md §10), коды выхода (§10) и шаги запуска.

`run_cli` — одна свободная функция: консоль, ключи, корень, папки, замок одного экземпляра до логов, лог запуска,
`Launch` и освобождение. `Launch` ведёт начало: шапка сразу после настройки логов (до конфигов и сети); livecraft.json
из поставочного шаблона, если файла нет (в git его нет, §5), или недостающий раздел из шаблона; сейф и оба конфига
(app\\setup\\readiness.py) — независимо друг от друга, до них однократные переносы прежних ключей livecraft.json:
ссылка на папку Диска — в сейф, ключ источника текстов — прочь (app\\setup\\migration.py); фильтр секретов в логах сразу после чтения сейфа (§7.4); готовность и
снимок запуска в лог (§14 решение 38). Обрыв (Ctrl+C) и любое необработанное исключение ловит `Launch.run`: строка в лог и в консоль
(падение — как отказ запуска: у оконного exe окном-сообщением), код 1 — единственный перехват Exception в программе
(§11). Фоновый поток (проверки окна настройщика) своё исключение не ловит: `Launch.run` ставит `threading.excepthook`,
и трассировка уходит в лог запуска, а не в stderr.

Дальше — `LaunchWork` на путях с папками ролей из настроек. Что делает запуск, решают включённые линии работы (§14
решение 37) и их готовность (`ModeReadiness.step`): не работает ни одна линия или не готова основа — окно настройки и
код 2 (§8.2). Вход «Таблица» — свежие yt-dlp и deno и проверка cookies (app\\runtime\\ytdlp_updater.py; cookies не
того вида — код 2) и прогон контура A (app\\intake: всё, что знает таблицу); вход «Пакеты» (таблица выключена) — полка
пакетов (app\\broadcasts\\shelf.py): нет пакетов или будущих слотов — код 3, дальше не идём. Затем от слотов входа с
формой каждого (`RunSlots`, §14 решение 51) — один путь: вывод (app\\publish\\run_output.py: превью слотов пакетов,
пакет, документ объявлений, Telegram) и последними эфиры (app\\broadcasts\\) по слотам для YouTube: сбой YouTube не
задерживает объявления. Пакет из
проводника (`livecraft.exe <файл>.bcast`) копируется в папку пакетов (app\\packages\\package_drop.py; не открылся —
код 2), затем — обычный запуск. --setup открывает окно при любом состоянии; --check, --auth и --status требуют только
своих нужд (`ServiceReadiness`): не хватает — строки нужд и код 2. Код запуска — важнейший из исходов частей (app\\run).
--dry-run снаружи ничего не меняет (§10), из файлов пишет только пакет; полный запуск по линиям в конце чистит старьё по
keep_days (app\\runtime\\retention.py). Отчёт (app\\run\\run_report.py) пишет каждый запуск по линиям, дошедший
до работы, и --status: строки запуска и части по порядку собирает `RunJournal`; последним — подвал путей.
"""
from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from app.broadcasts.run import BroadcastSlots
from app.broadcasts.service import ChannelService
from app.broadcasts.services import BroadcastServices
from app.broadcasts.shelf import ShelfRead
from app.broadcasts.stage import BroadcastPartResult, BroadcastStage
from app.config.channel import ConfiguredChannels
from app.config.files import SettingsFile, ShippedSettings
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.intake.intake import IntakeRequest, IntakeResult, PlanIntake
from app.intake.intake_report import IntakeReport
from app.observability.log_event import MESSAGE_TEMPLATE, LogArea, LogEvent, get_logger
from app.observability.logging_setup import RunLog
from app.packages.package_drop import PackageDrop, PackageDropResult
from app.packages.run_slots import RunSlots
from app.paths import FileName, LivecraftPaths
from app.pipeline.progress import RunProgress
from app.publish.run_output import RunOutput
from app.run.exit_code import ExitCode, RunOutcome
from app.run.line_plan import ModeReadiness
from app.run.mode import ModeStep, RunMode, RunPart
from app.run.progress import StageProgress
from app.run.request import RunRequest
from app.run.run_report import RunJournal
from app.runtime.retention import Retention
from app.runtime.ytdlp_updater import SourceTools, SourceToolsCheck
from app.runtime.single_instance import AnotherInstanceRunning, InstanceLock
from app.secretsafe.vault import Vault
from app.setup.migration import DriveFolderMigration, TextSourceMigration
from app.setup.readiness import ChannelBasis, Readiness, RunBasis, RunSnapshot, ServiceReadiness
from app.ui.console import Console
from app.ui.messages import msg
from app.version import APP_VERSION

LOGGER = get_logger(LogArea.MAIN)
SHIPPED_SETTINGS: ShippedSettings = ShippedSettings()


class LaunchEvent(str, Enum):
    """События запуска в логе."""

    STARTED = "run_started"
    FINISHED = "run_finished"
    INTERRUPTED = "run_interrupted"
    CRASHED = "run_crashed"
    THREAD_CRASHED = "thread_crashed"
    SETTINGS_FILE_CREATED = "settings_file_created"
    SETTINGS_SECTIONS_ADDED = "settings_sections_added"
    SETUP_WINDOW_FAILED = "setup_window_failed"


@dataclass(frozen=True)
class Launch:
    """Начало одного запуска: что запрошено, где корень, куда писать оператору и в какой лог."""

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
        previous_hook: Callable[[threading.ExceptHookArgs], object] = threading.excepthook
        threading.excepthook = self.log_thread_crash
        try:
            code = self._run(started)
        except KeyboardInterrupt:
            LogEvent.of(LaunchEvent.INTERRUPTED).emit(LOGGER, logging.WARNING)
            self.console.say(msg.RUN_INTERRUPTED)
        # Единственный перехват Exception в livecraft (CLAUDE.md §11): всё, что не обработано ниже, — ошибка
        # программы. Без него трассировка ушла бы только в окно консоли, которое оператор закроет, а лог остался бы
        # оборванным на последней строке.
        except Exception:
            LOGGER.exception(MESSAGE_TEMPLATE, LogEvent.of(LaunchEvent.CRASHED, log=self.log.path).text)
            self.console.say_error(msg.RUN_CRASHED.format(log=self.log.path))     # и в оконном exe — окном
        finally:
            threading.excepthook = previous_hook
        LogEvent.of(LaunchEvent.FINISHED, exit_code=code).emit(LOGGER)
        return code

    def log_thread_crash(self, crash: threading.ExceptHookArgs) -> None:
        """Исключение, которым упал фоновый поток, — строкой с трассировкой в лог запуска.

        Это не перехват: исключение уже оборвало поток и пришло туда, где иначе threading напечатал бы его сам.
        """
        event: LogEvent = LogEvent.of(LaunchEvent.THREAD_CRASHED, error=crash.exc_type.__name__, log=self.log.path)
        LOGGER.error(MESSAGE_TEMPLATE, event.text, exc_info=(crash.exc_type, crash.exc_value, crash.exc_traceback))

    def _run(self, started: datetime) -> ExitCode:
        """Настройки, готовность и снимок запуска в лог; дальше — работа на путях с папками ролей из настроек. Строки
        запуска — в консоль и в часть «Запуск» отчёта (`RunJournal`)."""
        journal: RunJournal = RunJournal(self.console, self.request.dry_run)
        self._install_settings(journal)
        moved: tuple[str, ...] = DriveFolderMigration.apply(self.paths)     # до разбора: прежний ключ файл ломает
        TextSourceMigration.apply(self.paths)
        readiness: Readiness = Readiness.check(self.paths)
        vault: Vault | None = readiness.vault.vault
        if vault is not None:
            self.log.protect(vault.log_filter())     # сразу после чтения сейфа, до любых строк лога (§7.4)
        journal.say(moved)
        readiness.log(LOGGER)
        for event in RunSnapshot(readiness).events:
            event.emit(LOGGER)
        journal.say(readiness.warnings)
        readiness.paths.ensure_dirs()
        work: LaunchWork = LaunchWork(self.request, readiness, journal, self.log.path)
        return work.run(started)

    def _install_settings(self, journal: RunJournal) -> None:
        """livecraft.json в git нет (§5): нет файла — программа кладёт поставочный вид сама; нет раздела, который
        добавила новая версия, — дописывает его из шаблона. Человеку делать нечего: только строка консоли."""
        file: SettingsFile = SettingsFile.of(self.paths)
        config: Path = self.paths.file(FileName.CONFIG)
        if file.install_shipped():
            LogEvent.of(LaunchEvent.SETTINGS_FILE_CREATED, path=config).emit(LOGGER)
            journal.say((msg.SETTINGS_FILE_CREATED.format(path=config),))
            return
        added: tuple[str, ...] = file.complete_sections()
        if not added:
            return
        LogEvent.of(LaunchEvent.SETTINGS_SECTIONS_ADDED, path=config, sections=added).emit(LOGGER)
        journal.say((msg.SETTINGS_SECTIONS_ADDED.format(sections=msg.LIST_JOINER.join(added)),))


@dataclass(frozen=True)
class LaunchWork:
    """Работа запуска после чтения настроек: запрос, готовность (её пути — с папками ролей из настроек), журнал
    запуска (консоль и части отчёта) и файл лога запуска."""

    request: RunRequest
    readiness: Readiness
    journal: RunJournal
    log: Path

    @property
    def paths(self) -> LivecraftPaths:
        return self.readiness.paths

    @property
    def log_file(self) -> str:
        """Путь лога для людей — от корня программы (подвал запуска)."""
        return self.paths.shown(self.log)

    @property
    def console(self) -> Console:
        return self.journal.console

    def run(self, started: datetime) -> ExitCode:
        """Пакет из проводника — в папку пакетов; затем служебный запуск или работа по линиям."""
        placed: RunOutcome | None = self._place_package()
        if placed is not None:
            return placed.exit_code
        if self.request.mode.is_service:
            return self._service(started).exit_code
        return self._mode(started)

    def _place_package(self) -> RunOutcome | None:
        """Пакет, открытый из проводника, — в папку пакетов из настроек; не открылся — код 2. Настройки не прочитаны —
        папка неизвестна: строка, и запуск идёт дальше (основе не хватает настроек — код 2). Пакета нет — None."""
        package: Path | None = self.request.package_file
        if package is None:
            return None
        if self.readiness.settings.value is None:
            self.journal.say((msg.PACKAGE_DROP_NO_SETTINGS.format(file=package.name),))
            return None
        result: PackageDropResult = PackageDrop(package).place(self.paths)
        self.journal.say((result.console_line,))
        return None if result.is_placed else RunOutcome.NOT_CONFIGURED

    def _service(self, started: datetime) -> RunOutcome:
        """--setup — окно при любом состоянии; --check, --auth, --status — по своим нуждам: не хватает — строки нужд
        и код 2, окно не открывается. --status пишет отчёт запуска."""
        mode: RunMode = self.request.mode
        if mode is RunMode.SETUP:
            return self._setup()
        service: ServiceReadiness = ServiceReadiness(self.readiness, mode)
        basis: ChannelBasis | None = service.basis
        if basis is None:
            self.console.say_lines(service.lines)
            return RunOutcome.NOT_CONFIGURED
        stage: BroadcastStage = self._stage(basis.settings, basis.channels, started)
        if mode is RunMode.STATUS:
            part: BroadcastPartResult = stage.status()
            self.journal.part(part.console_lines, part.part_report)
            self.journal.finish(self.paths, started, self.log_file)
            return part.outcome
        return ChannelService(stage.services, basis.channels, self.console).run(self.request.auth_handle)

    def _mode(self, started: datetime) -> ExitCode:
        """Работа по линиям (§10, §14 решение 37): что делать, решает `ModeReadiness.step`; код — важнейший из исходов
        частей. Запуск, дошедший до работы, пишет отчёт, а полный ещё и чистит старьё (§3 шаг 12; работа идёт на
        прочитанных настройках — проверка на None только для типа)."""
        readiness: Readiness = self.readiness
        mode: ModeReadiness = readiness.for_run()
        mode.event.emit(LOGGER)
        step: ModeStep = mode.step
        if step is ModeStep.OPEN_SETUP:
            self.console.say_lines(mode.lines)
            self.console.say(msg.SETUP_OPENING)
            self._setup()
            return RunOutcome.NOT_CONFIGURED.exit_code
        self.journal.say(readiness.summary_lines(mode.scope(self.request.dry_run)))
        self.journal.say(mode.lines)
        code: ExitCode = mode.outcome.exit_code.combined(self._work(mode, started))
        settings: LivecraftSettings | None = readiness.settings.value
        if settings is not None and not self.request.dry_run:
            sweep: Retention = Retention(
                self.paths, settings.keep_days, settings.image_dir_template, Clock(settings.zone)
            )
            self.journal.say(sweep.sweep().console_lines)
        self.journal.finish(self.paths, started, self.log_file)
        return code

    def _work(self, mode: ModeReadiness, started: datetime) -> ExitCode:
        """Вход «Пакеты» — полка пакетов; вход «Таблица» — yt-dlp к чтению видео и прогон таблицы; затем от слотов
        входа — вывод и эфиры. `started` — начало запуска: штамп итога эфиров тот же, что у лога."""
        basis: RunBasis | None = self.readiness.run_basis(mode, self.request.dry_run)
        if basis is None:
            return RunOutcome.DONE.exit_code
        if mode.step is ModeStep.RUN_PACKAGES:
            return self._packages(basis, started)
        tools: SourceToolsCheck = SourceTools.of(self.paths, Clock(basis.settings.zone)).refresh()
        self.journal.say(tools.console_lines)
        if tools.stops:
            return RunOutcome.NOT_CONFIGURED.exit_code
        result: IntakeResult = self._intake(basis)
        self.journal.part(result.console_lines, IntakeReport(result).part_report)
        if not result.slots:
            return result.outcome.exit_code
        slots: RunSlots = RunSlots.of_table(result.slots, basis.settings.form)
        code: ExitCode = result.outcome.exit_code.combined(self._output(basis).run(slots, result.previews))
        folder: Path = self.paths.bcast_dir
        return code.combined(
            self._broadcast(basis, lambda: BroadcastSlots.of_table(slots, basis.settings, folder), started)
        )

    def _packages(self, basis: RunBasis, started: datetime) -> ExitCode:
        """Вход «Пакеты»: полка → нет пакетов или будущих слотов — код 3, дальше не идём; иначе вывод и эфиры от
        будущих слотов полки с формой своего пакета."""
        shelf: ShelfRead = ShelfRead.read(self.paths, basis.settings, basis.channels, RunProgress(self.console))
        self.journal.part(shelf.console_lines, shelf.part_report)
        if not shelf.has_slots:
            return shelf.outcome.exit_code
        code: ExitCode = self._output(basis).run(RunSlots.of_shelf(shelf.shelf), None)
        return code.combined(self._broadcast(basis, lambda: shelf.slots, started))

    def _output(self, basis: RunBasis) -> RunOutput:
        """Вывод запуска (превью, пакет, документ, Telegram) на прочитанных настройках и сейфе."""
        return RunOutput(self.paths, basis.settings, basis.vault, basis.scope, self.journal)

    def _stage(self, settings: LivecraftSettings, channels: ConfiguredChannels, started: datetime) -> BroadcastStage:
        """Часть «эфиры» запуска: боевые зависимости, каналы, запрос и начало запуска."""
        return BroadcastStage(
            services=BroadcastServices.open(self.paths, settings, self.console),
            channels=channels,
            request=self.request,
            started=started,
        )

    def _broadcast(self, basis: RunBasis, slots: Callable[[], BroadcastSlots], started: datetime) -> ExitCode:
        """Эфиры, когда они идут (прочитаны каналы): входы, сверка, действия, ключи в форму (если идёт их линия),
        keys.txt и часть отчёта. Слоты эфиров строятся, только когда эфиры идут: у таблицы для этого читается полка."""
        if basis.channels is None:
            return RunOutcome.DONE.exit_code
        stage: BroadcastStage = self._stage(basis.settings, basis.channels, started)
        part: BroadcastPartResult = stage.run(slots(), basis.runs(RunPart.KEYS))
        self.journal.part(part.console_lines, part.part_report)
        return part.outcome.exit_code

    def _intake(self, basis: RunBasis) -> IntakeResult:
        """Прогон контура A: «сейчас» — в зоне программы; строки хода долгих шагов, повторов чтения таблицы и входа
        оператора в Google (каким аккаунтом входить и каким вошли) — на консоль запуска."""
        now: datetime = Clock(basis.settings.zone).now()
        request: IntakeRequest = IntakeRequest(
            paths=self.paths, settings=basis.settings, vault=basis.vault, now=now, scope=basis.scope,
            progress=StageProgress(self.console),
        )
        return PlanIntake.of(request).run()

    def _setup(self) -> RunOutcome:
        """Окно настройщика (§8). tkinter тянется только сюда: обычный запуск окна не знает. Ошибки действий окна
        окно пишет в лог этого запуска.

        TclError при создании окна — нет Tk или рабочего стола: строка в консоль и в лог, ошибка.
        """
        from tkinter import TclError

        from app.setup.app import SetupApp

        try:
            SetupApp(self.paths, self.log).run()
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
    lock: InstanceLock = InstanceLock(
        path=paths.file(FileName.LOCK), startup_log=paths.file(FileName.STARTUP_LOG), clock=clock
    )
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
