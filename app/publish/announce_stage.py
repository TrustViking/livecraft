"""Часть запуска «объявления в Telegram» (CLAUDE.md §3 шаг 6a, §13 задача 4.5, §14 решения 14, 19, 31, 32, 51).

Часть идёт после документа объявлений (без него — тоже: тогда строк документа в шапке нет), когда идёт её линия
(`RunBasis.runs`: включена, токен бота и чат, настройки, форма ключей — у входа «Пакеты» она в пакетах), по слотам
запуска любого входа — со слотами «по номерам» тоже: на YouTube они не идут, а стримерам их тексты нужны (решение 32).
На каждый день (`AnnounceDay`: дата и форма — две формы на одну дату дают два объявления) по порядку: начало дня, шапка
(время первого эфира, срок ключей, форма дня, ссылка на документ дня), по слоту — флаги языка, блок слота, обложки
документами, напоминание о форме; конец дня. После всех дней — пакеты .bcast этого запуска документами с подписью,
если они записаны (линия «Пакет» не идёт — объявления уходят без пакетов).

Чат — `telegram.chat_id` настроек. Группа стала супергруппой — новый id сразу в livecraft.json (`ChatMigration`),
следующие отправления идут в него. Первый отказ бота останавливает часть: даты после него и пакет не отправляются,
ошибка запуска (код 1). Пробный запуск к Telegram не обращается. Итог — `AnnounceResult`; лог — область `publish`: даты,
счётчики и имя файла пакета, без токена и текстов слотов (§7.4). Дата в строках консоли — DD.MM.YYYY (решение 31).
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.config.files import SettingsFile
from app.config.settings import LivecraftSettings
from app.config.telegram import ChatTarget, TelegramSettings
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.packages.package import PackageResult
from app.paths import LivecraftPaths
from app.publish.announce_texts import AnnounceTexts
from app.publish.day import PublishDay
from app.publish.doc_stage import DocResult
from app.publish.telegram_api import ZIP_MIME, BotDelivery, BotDocument, BotFailure
from app.publish.telegram_bot import TelegramBot
from app.publish.telegram_chat import ChatMigration
from app.run.exit_code import RunOutcome
from app.run.mode import RunPart
from app.run.progress import SILENT_PROGRESS, StageProgress, StepCount
from app.run.report_section import PartReport
from app.secretsafe.vault import Vault
from app.ui.messages import msg

LOGGER = get_logger(LogArea.PUBLISH)

# Отправление объявления: текст сообщения (HTML) или файл документом.
AnnouncePost = str | BotDocument


class AnnounceEvent(str, Enum):
    """События части «объявления в Telegram» в логе."""

    DAY_SENT = "announce_day_sent"
    PACKAGE_SENT = "announce_package_sent"
    FAILED = "announce_failed"
    FINISHED = "announce_finished"


@dataclass(frozen=True)
class AnnounceDay:
    """День объявлений и ссылка на документ этого дня (документа нет — None)."""

    day: PublishDay
    doc_url: str | None

    @property
    def previews(self) -> int:
        return sum(len(slot.previews) for slot in self.day.slots)

    def posts(self, texts: AnnounceTexts) -> tuple[AnnouncePost, ...]:
        """Отправления дня по порядку: начало, шапка, по слоту — флаги, блок, обложки, напоминание о форме; конец.
        Форма — форма слотов дня."""
        form_url: str = self.day.form.url
        posts: list[AnnouncePost] = [texts.day_start, texts.header(self.day.times, form_url, self.doc_url)]
        for slot in self.day.slots:
            posts.extend((texts.flags(slot.language), texts.slot(slot)))
            posts.extend(
                BotDocument(name=name, data=preview.data, mime=preview.mime_type)
                for name, preview in zip(slot.preview_file_names, slot.previews, strict=True)
            )
            posts.append(texts.form_reminder(form_url))
        posts.append(texts.day_end)
        return tuple(posts)

    @property
    def console_line(self) -> str:
        return msg.ANNOUNCE_DAY_LINE.format(date=self.day.human_date, slots=len(self.day.slots), previews=self.previews)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(
            AnnounceEvent.DAY_SENT, date=self.day.date, slots=len(self.day.slots), previews=self.previews,
            doc=self.doc_url is not None,
        )


@dataclass(frozen=True)
class AnnounceFailure:
    """Отказ бота: на дне (`day`) или на пакете (`day` — None)."""

    day: PublishDay | None
    failure: BotFailure

    @property
    def console_line(self) -> str:
        if self.day is None:
            return msg.ANNOUNCE_PACKAGE_FAILED_LINE.format(reason=self.failure.human)
        return msg.ANNOUNCE_FAILED_LINE.format(date=self.day.human_date, reason=self.failure.human)

    @property
    def event(self) -> LogEvent:
        """Где отказал бот — дата или пакет — и отказ бота: метод, причина, код, пояснение Telegram."""
        where: LogEvent = LogEvent.of(AnnounceEvent.FAILED, date=None if self.day is None else self.day.date)
        return LogEvent(where.name, where.fields + self.failure.event.fields)


@dataclass(frozen=True)
class AnnounceResult:
    """Итог части: пробный ли запуск, дни слотов запуска, отправленные дни, имена отправленных пакетов, перенос чата и
    отказ."""

    dry_run: bool
    planned: tuple[PublishDay, ...] = ()
    days: tuple[AnnounceDay, ...] = ()
    packages: tuple[str, ...] = ()
    migration: ChatMigration | None = None
    failure: AnnounceFailure | None = None

    @property
    def outcome(self) -> RunOutcome:
        """Отказ бота — ошибка запуска (§10)."""
        return RunOutcome.DONE if self.failure is None else RunOutcome.FAILED

    @property
    def skipped(self) -> int:
        """Сколько дней после отказа остались без объявлений."""
        if self.failure is None or self.failure.day is None:
            return 0
        failed: PublishDay = self.failure.day
        return len(self.planned) - next(place for place, day in enumerate(self.planned) if day.is_same(failed)) - 1

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Перенос чата, по строке на день, по строке на пакет; отказ — строкой и, если остались дни, строкой о них."""
        if self.dry_run:
            return (msg.ANNOUNCE_DRY_RUN_LINE,)
        migration: tuple[str, ...] = () if self.migration is None else (self.migration.line,)
        package: tuple[str, ...] = tuple(msg.ANNOUNCE_PACKAGE_LINE.format(name=name) for name in self.packages)
        failure: tuple[str, ...] = () if self.failure is None else (self.failure.console_line,)
        skipped: tuple[str, ...] = (msg.ANNOUNCE_SKIPPED_LINE.format(count=self.skipped),) if self.skipped else ()
        return (*migration, *(day.console_line for day in self.days), *package, *failure, *skipped)

    @property
    def part_report(self) -> PartReport:
        """Часть «Telegram» отчёта запуска — строки консоли части."""
        return PartReport(RunPart.ANNOUNCE.human_label, self.console_lines)

    @property
    def log_fields(self) -> Mapping[str, object]:
        return dict(
            dry_run=self.dry_run,
            dates=len(self.planned),
            days=len(self.days),
            previews=sum(day.previews for day in self.days),
            packages=self.packages,
            migrated=self.migration is not None,
            failed=self.failure is not None,
        )


@dataclass
class AnnounceSender:
    """Отправитель части: бот, чат, куда уходит следующее отправление, и перенос чата, если он был. Перенос сразу
    пишется в livecraft.json поверх файла, как он на диске: прежний id уже мёртв."""

    bot: TelegramBot
    chat_id: str
    file: SettingsFile
    target: ChatTarget
    migration: ChatMigration | None = None

    def send(self, post: AnnouncePost) -> BotFailure | None:
        """Одно отправление в текущий чат; отказ — итогом, иначе None."""
        sent: BotDelivery | BotFailure
        if isinstance(post, str):
            sent = self.bot.send_text(self.chat_id, post)
        else:
            sent = self.bot.send_document(self.chat_id, post)
        if isinstance(sent, BotFailure):
            return sent
        if sent.migrated_from is not None:
            self._migrate(ChatMigration(old_chat_id=sent.migrated_from, new_chat_id=sent.chat.chat_id))
        return None

    def send_all(self, posts: tuple[AnnouncePost, ...]) -> BotFailure | None:
        """Отправления по порядку; первый отказ останавливает."""
        for post in posts:
            failure: BotFailure | None = self.send(post)
            if failure is not None:
                return failure
        return None

    def _migrate(self, migration: ChatMigration) -> None:
        migration.event.emit(LOGGER)
        self.file.save(migration.written(self.file.latest, self.target))
        self.chat_id = migration.new_chat_id
        self.migration = migration


@dataclass(frozen=True)
class AnnounceStage:
    """Часть «объявления в Telegram» одного запуска: настройки, пробный ли запуск, бот и файл настроек (для переноса
    чата)."""

    settings: LivecraftSettings
    dry_run: bool
    bot: TelegramBot
    file: SettingsFile
    texts: AnnounceTexts = field(default_factory=AnnounceTexts)

    @classmethod
    def of(cls, paths: LivecraftPaths, settings: LivecraftSettings, vault: Vault, dry_run: bool) -> AnnounceStage:
        """Боевая часть: бот на токене сейфа — часть готова, значит токен есть (`Need.TELEGRAM`)."""
        return cls(settings, dry_run, TelegramBot.from_vault(vault), SettingsFile.of(paths))

    def run(
        self, days: Sequence[PublishDay], docs: DocResult | None, packages: Sequence[PackageResult],
        progress: StageProgress = SILENT_PROGRESS,
    ) -> AnnounceResult:
        """Объявления на каждый день слотов запуска, затем записанные пакеты; перед днём и перед пакетом — строка хода
        в консоль; первый отказ бота останавливает часть."""
        if self.dry_run:
            return self._finish(AnnounceResult(dry_run=True))
        planned: tuple[AnnounceDay, ...] = tuple(
            AnnounceDay(day, None if docs is None else docs.url_of(day)) for day in days
        )
        telegram: TelegramSettings = self.settings.telegram
        sender: AnnounceSender = AnnounceSender(self.bot, telegram.chat_id, self.file, telegram.target)
        result: AnnounceResult = AnnounceResult(dry_run=False, planned=tuple(days))
        for place, day in enumerate(planned, start=1):
            progress.announce_started(StepCount(place, len(planned)), day.day.human_date)
            failure: BotFailure | None = sender.send_all(day.posts(self.texts))
            if failure is not None:
                return self._failed(result, sender, AnnounceFailure(day.day, failure))
            day.event.emit(LOGGER)
            result = AnnounceResult(False, result.planned, (*result.days, day), migration=sender.migration)
        for package in packages:
            if package.is_written:
                progress.package_send_started(package.path.name)
                result = self._package(result, sender, package)
                if result.failure is not None:
                    return result
        return self._finish(result)

    def _package(self, result: AnnounceResult, sender: AnnounceSender, package: PackageResult) -> AnnounceResult:
        """Записанный пакет документом с подписью; отказ бота — итог с отказом."""
        path: Path = package.path
        caption: str = self.texts.package_caption(package.period, package.slots, package.previews)
        document: BotDocument = BotDocument(name=path.name, data=path.read_bytes(), mime=ZIP_MIME, caption=caption)
        failure: BotFailure | None = sender.send(document)
        if failure is not None:
            return self._failed(result, sender, AnnounceFailure(None, failure))
        LogEvent.of(AnnounceEvent.PACKAGE_SENT, file=path.name).emit(LOGGER)
        sent: tuple[str, ...] = (*result.packages, path.name)
        return AnnounceResult(False, result.planned, result.days, sent, sender.migration)

    def _failed(self, result: AnnounceResult, sender: AnnounceSender, failure: AnnounceFailure) -> AnnounceResult:
        failure.event.emit(LOGGER, logging.ERROR)
        return self._finish(
            AnnounceResult(False, result.planned, result.days, result.packages, sender.migration, failure)
        )

    def _finish(self, result: AnnounceResult) -> AnnounceResult:
        LogEvent.of(AnnounceEvent.FINISHED, **result.log_fields).emit(LOGGER)
        return result
