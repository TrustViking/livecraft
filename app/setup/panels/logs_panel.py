"""Вкладка «Логи» без окна: «Отправить логи» (CLAUDE.md §8.2 п.11, §13 задача 7.2, §14 решения 20, 43, 46, 58).

Одно действие — `run`: архив папки логов (`LogArchive`: новые файлы первыми, до 45 МБ, без прежних архивов) с
`diagnostics.txt` (`Diagnostics`, значений сейфа нет) под именем `livecraft_logs_<DD-MM-YYYY_HHMMSS>.zip` по поясу
программы всегда ложится в саму папку logs\\ — там его найти, как и остальные логи (старые архивы чистит срок хранения,
как весь logs\\). Есть бот поддержки и чат поддержки — затем архив уходит документом в чат поддержки с подписью (версия,
момент, число файлов; начинается со знака «🛠», как подпись пакета — со своего); группа стала супергруппой — новый id сразу в
livecraft.json (`ChatMigration`, как у объявлений). Бот отказал — итог называет причину, архив уже лежит в logs\\:
человеку не нужно ничего делать второй раз (CLAUDE.md §1, «Поведение программы»). Бота поддержки нет — архив
остаётся в logs\\, и строка говорит об этом: бот объявлений логи не носит никогда (§14 решение 58); бот есть, а
чата поддержки нет — так же, строкой о чате. Архив не записался — строка с причиной ОС, отправки нет. Что будет по кнопке — надпись кнопки,
строка вкладки над ней и куда уйдёт архив — решает одно правило (`route` → `LogsRoute`) и для окна, и для отправки:
вкладка не обещает отправку, которой не будет. Итог — строками со знаками для строки проверки окна (`LogsVerdict`); лог — область `setup`, без
значений: сколько файлов и байтов, путь архива, причина отказа.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from app.config.files import SettingsFile
from app.config.settings import LivecraftSettings
from app.config.telegram import ChatRole, TelegramSettings
from app.core.clock import Clock
from app.core.dates import FILE_STAMP_FORMAT, format_human_datetime
from app.core.errors import os_error_reason
from app.core.text_format import NEWLINE
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.paths import AtomicFile, DataDir, LivecraftPaths
from app.publish.telegram_api import ZIP_MIME, BotDelivery, BotDocument, BotFailure
from app.publish.telegram_bot import TelegramBot
from app.publish.telegram_chat import ChatMigration
from app.runtime.log_archive import LOG_ARCHIVE_LIMIT_BYTES, LOG_ARCHIVE_LIMIT_MEGABYTES, LogArchive, PackedLogs
from app.setup.diagnostics import Diagnostics
from app.setup.panels.publish_panel import ChatConnection
from app.setup.readiness import Readiness
from app.ui.messages import msg
from app.version import APP_VERSION

LOGGER = get_logger(LogArea.SETUP)


class LogsEvent(str, Enum):
    """События вкладки «Логи» в логе."""

    SENT = "logs_sent"
    SAVED = "logs_saved"
    NOT_SENT = "logs_not_sent"
    NOT_SAVED = "logs_not_saved"


@dataclass(frozen=True)
class LogsVerdict:
    """Итог «Отправить логи»: удалось ли и строки для окна."""

    is_ok: bool
    lines: tuple[str, ...]

    @classmethod
    def problem(cls, text: str) -> LogsVerdict:
        """Не удалось: причина словами — строкой со знаком «✗»."""
        return cls(is_ok=False, lines=(msg.CHECK_PROBLEM_LINE.format(line=text),))

    @property
    def text(self) -> str:
        return NEWLINE.join(self.lines)


@dataclass(frozen=True)
class LogsRoute:
    """Что будет по кнопке «Логов»: надпись кнопки, строка вкладки над ней и id чата поддержки, куда архив уходит после
    записи в logs\\ (пусто — не уходит никуда)."""

    button: str
    line: str
    chat_id: str = ""


@dataclass(frozen=True)
class LogsPanel:
    """Вкладка «Логи»: установка `paths` и часы `clock` (момент архива — по поясу программы из livecraft.json)."""

    paths: LivecraftPaths
    clock: Clock

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> LogsPanel:
        return cls(paths=paths, clock=Clock.utc())

    def route(self, bot: TelegramBot | None, telegram: TelegramSettings) -> LogsRoute:
        """Куда ляжет архив — одно правило для кнопки, строки вкладки и отправки: есть бот поддержки `bot` и чат
        поддержки — архив уходит ботом в чат; бота поддержки нет — остаётся в logs\\ (бот объявлений логи не носит,
        §14 решение 58); бот есть, а чата нет — тоже остаётся."""
        if bot is None:
            return LogsRoute(button=msg.SETUP_LOGS_BUTTON_SAVE, line=msg.SETUP_LOGS_NO_SUPPORT_BOT)
        chat_id: str = ChatRole.SUPPORT.chat_of(telegram)
        if not chat_id:
            return LogsRoute(button=msg.SETUP_LOGS_BUTTON_SAVE, line=msg.SETUP_LOGS_CHAT_NOT_CONNECTED)
        return LogsRoute(button=msg.SETUP_LOGS_BUTTON_SEND, line=msg.SETUP_LOGS_ROUTE_SEND, chat_id=chat_id)

    def run(self, bot: TelegramBot | None) -> LogsVerdict:
        """Архив логов — в logs\\, затем — куда велит правило `route`: ботом поддержки `bot` в чат поддержки либо
        никуда, со строкой, почему. OSError чтения логов — наружу."""
        settings: LivecraftSettings = SettingsFile.of(self.paths).latest
        route: LogsRoute = self.route(bot, settings.telegram)
        moment: datetime = self.clock.now().astimezone(settings.zone)
        diagnostics: str = Diagnostics(Readiness.check(self.paths), moment).text
        folder: Path = self.paths.dir(DataDir.LOGS)
        packed: PackedLogs = LogArchive(folder, LOG_ARCHIVE_LIMIT_BYTES).pack(
            diagnostics, moment.strftime(FILE_STAMP_FORMAT)
        )
        saved: LogsVerdict = self._saved(packed, folder / packed.name)
        if not saved.is_ok:
            return saved
        if bot is None or not route.chat_id:
            return LogsVerdict(is_ok=True, lines=(*saved.lines, route.line))
        caption: str = msg.SETUP_LOGS_CAPTION.format(
            version=APP_VERSION, moment=format_human_datetime(moment), files=packed.files
        )
        document: BotDocument = BotDocument(name=packed.name, data=packed.data, mime=ZIP_MIME, caption=caption)
        return self._sent(bot.send_document(route.chat_id, document), packed, saved)

    def _sent(self, sent: BotDelivery | BotFailure, packed: PackedLogs, saved: LogsVerdict) -> LogsVerdict:
        """Итог отправки после строк записи архива: отказ бота — причина в лог и строкой окна; ушло — строка и перенос
        чата в супергруппу, если он был."""
        if isinstance(sent, BotFailure):
            sent.event.emit(LOGGER, logging.WARNING)
            LogEvent.of(LogsEvent.NOT_SENT, reason=sent.reason).emit(LOGGER, logging.WARNING)
            refused: str = msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_LOGS_NOT_SENT.format(reason=sent.human))
            return LogsVerdict(is_ok=False, lines=(*saved.lines, refused))
        LogEvent.of(LogsEvent.SENT, files=packed.files, skipped=packed.skipped, bytes=packed.size).emit(LOGGER)
        sent_line: str = msg.SETUP_LOGS_SENT.format(files=packed.files, megabytes=packed.megabytes)
        sent_lines: tuple[str, ...] = (msg.CHECK_OK_LINE.format(line=sent_line), *self._moved(sent))
        return LogsVerdict(is_ok=True, lines=(*saved.lines, *sent_lines))

    def _saved(self, packed: PackedLogs, target: Path) -> LogsVerdict:
        """Архив — в logs\\ целиком или никак; не записался — строка с причиной ОС."""
        try:
            AtomicFile.at(target).write(lambda path: path.write_bytes(packed.data))
        except OSError as error:
            LogEvent.of(LogsEvent.NOT_SAVED, path=Quoted(str(target)), error=Quoted(str(error))).emit(
                LOGGER, logging.WARNING
            )
            return LogsVerdict.problem(msg.SETUP_LOGS_NOT_SAVED.format(reason=os_error_reason(error)))
        LogEvent.of(LogsEvent.SAVED, path=Quoted(str(target)), files=packed.files, bytes=packed.size).emit(LOGGER)
        saved_line: str = msg.SETUP_LOGS_SAVED.format(
            path=self.paths.shown(target), files=packed.files, megabytes=packed.megabytes
        )
        return LogsVerdict(is_ok=True, lines=(msg.CHECK_OK_LINE.format(line=saved_line), *self._skipped(packed)))

    def _skipped(self, packed: PackedLogs) -> tuple[str, ...]:
        """Старые файлы за пределом архива — строкой справки; все вошли — ничего."""
        if not packed.skipped:
            return ()
        return (msg.SETUP_LOGS_SKIPPED.format(count=packed.skipped, limit=LOG_ARCHIVE_LIMIT_MEGABYTES),)

    def _moved(self, sent: BotDelivery) -> tuple[str, ...]:
        """Чат поддержки стал супергруппой: новый id — сразу в livecraft.json поверх файла, как он на диске."""
        if sent.migrated_from is None:
            return ()
        migration: ChatMigration = ChatMigration(old_chat_id=sent.migrated_from, new_chat_id=sent.chat.chat_id)
        migration.event.emit(LOGGER)
        file: SettingsFile = SettingsFile.of(self.paths)
        file.save(ChatConnection(sent.chat, ChatRole.SUPPORT).moved(file.latest, migration))
        return (migration.line,)
