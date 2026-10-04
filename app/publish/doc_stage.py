"""Часть запуска «документ объявлений»: Google-документ на каждый день слотов (CLAUDE.md §3 шаг 6a, §13 задача 4.4,
§14 решения 14, 15, 27, 39, 51).

Часть идёт, когда идёт её линия (`RunBasis.runs`, §14 решение 37), по слотам запуска любого входа. На каждый день
(`PublishDay`: дата и форма ключей — две формы на одну дату дают два документа) — новый документ в папке материалов на
Google Диске (поле сейфа, `DriveTarget`), открытый по ссылке по `docs.access`, и в нём по порядку: шапка одним пакетом
правок; по слоту — таблица в конец (перед первой — пустой абзац, перед остальными — разрыв страницы), тексты её ячеек
одним пакетом, обложки — по картинке на пакет. Источники слота — его ссылки; обложка — копия превью на Диске этого
запуска (`PreviewResult.covers`), отказ 400 — следующий адрес (обложка YouTube). Адреса кончились — обложка не встала:
счёт и строка лога, не ошибка.

Когда идёт линия «Копия документа», готовый документ выгружается в формате Word и сохраняется копией в папке копий
<DD-MM-YYYY>\\ (`DocCopy`, §14 решение 33): путь копии — в строке документа. Копия не сохранилась — причина в строке
документа, код 1, а документы следующих дат создаются: отказ копии — не сбой документа.

Прочий отказ Диска или Docs — ошибка запуска (код 1): документы следующих дней не создаются. Пробный запуск к Google
не обращается и копий не пишет. Дни — дни объявлений (`PublishDay.days`, общие с Telegram). Итог — `DocResult`:
документы по дням (`url_of` — ссылка документа дня для объявлений в Telegram), сбой, строки консоли и лога, число
сохранённых копий и отказов. Лог — область `publish`; в
строках — даты, ссылки на документы и счётчики, без значений сейфа. Дата в строках консоли — DD.MM.YYYY (§14 решение
31); ключ документа даты и поле лога — DD-MM-YYYY. Слоты с текстами «по номерам» в документ входят: на YouTube они не
идут, а стримерам их тексты нужны (решение 32).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.google.auth import GoogleLogin
from app.google.docs import DocsClient, DocsError, DocsReason
from app.google.drive import DriveClient, DriveError, DriveFile
from app.intake.preview_stage import DriveTarget
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths
from app.publish.day import PublishDay
from app.publish.doc_copy import DocCopy, DocCopyFailure, DocCopySaved
from app.publish.doc_day import HEADER_START_INDEX, DocDay
from app.publish.doc_request import DocRequest
from app.publish.doc_slot import CoverSpot, DocSlot
from app.publish.doc_texts import DocTexts
from app.run.exit_code import RunOutcome
from app.run.line_plan import RunScope
from app.run.mode import RunPart
from app.run.progress import SILENT_PROGRESS, StageProgress, StepCount
from app.run.report_section import PartReport
from app.secretsafe.vault import Vault
from app.ui.messages import msg

LOGGER = get_logger(LogArea.PUBLISH)


class DocEvent(str, Enum):
    """События части «документ объявлений» в логе."""

    CREATED = "doc_created"
    COVER_MISSED = "doc_cover_missed"
    FAILED = "doc_failed"
    FINISHED = "docs_finished"


@dataclass(frozen=True)
class DocDocument:
    """Готовый документ даты: день, имя, ссылка, сколько обложек встало и сколько нет, копия .docx или её отказ (None —
    линия «Копия документа» не идёт)."""

    day: DocDay
    name: str
    url: str
    covers_placed: int
    covers_missed: int
    copy: DocCopySaved | DocCopyFailure | None

    @property
    def date(self) -> str:
        """Дата DD-MM-YYYY: ключ документа (`DocResult.url_of`) и поле лога."""
        return self.day.date

    @property
    def is_copied(self) -> bool:
        return isinstance(self.copy, DocCopySaved)

    @property
    def is_copy_failed(self) -> bool:
        return isinstance(self.copy, DocCopyFailure)

    @property
    def console_line(self) -> str:
        """Строка для людей — с датой DD.MM.YYYY (§14 решение 31) и путём копии или причиной, почему её нет."""
        total: int = self.covers_placed + self.covers_missed
        line: str = msg.DOC_LINE.format(date=self.day.human_date, url=self.url, placed=self.covers_placed, total=total)
        return line if self.copy is None else line + self.copy.console_part

    @property
    def event(self) -> LogEvent:
        created: LogEvent = LogEvent.of(
            DocEvent.CREATED, date=self.date, url=self.url, covers=self.covers_placed, covers_missed=self.covers_missed
        )
        return created if self.copy is None else self.copy.extend(created)


@dataclass(frozen=True)
class DocFailure:
    """Отказ Диска или Docs на документе даты: после него документы следующих дат не создаются."""

    day: DocDay
    error: DriveError | DocsError

    @property
    def date(self) -> str:
        """Дата DD-MM-YYYY: место сбоя среди дат запуска и поле лога."""
        return self.day.date

    @property
    def console_line(self) -> str:
        return msg.DOC_FAILED_LINE.format(date=self.day.human_date, reason=self.error.human)

    @property
    def event(self) -> LogEvent:
        """Строка лога: дата, причина, обращение и код ответа — без текста ошибки."""
        return LogEvent.of(
            DocEvent.FAILED, date=self.date, reason=self.error.reason, call=self.error.call, status=self.error.status
        )


@dataclass(frozen=True)
class DocResult:
    """Итог части: пробный ли запуск, дни слотов запуска, готовые документы и сбой."""

    dry_run: bool
    days: tuple[PublishDay, ...] = ()
    documents: tuple[DocDocument, ...] = ()
    failure: DocFailure | None = None

    @property
    def outcome(self) -> RunOutcome:
        """Сбой Диска или Docs и копия .docx, которая не сохранилась, — ошибка запуска (§10); обложка — нет."""
        is_done: bool = self.failure is None and not any(document.is_copy_failed for document in self.documents)
        return RunOutcome.DONE if is_done else RunOutcome.FAILED

    @property
    def skipped(self) -> int:
        """Сколько дней после сбоя остались без документа."""
        if self.failure is None:
            return 0
        failed: PublishDay = self.failure.day.day
        return len(self.days) - next(place for place, day in enumerate(self.days) if day.is_same(failed)) - 1

    @property
    def console_lines(self) -> tuple[str, ...]:
        """По строке на документ; сбой — строкой и, если остались даты, строкой о них."""
        if self.dry_run:
            return (msg.DOC_DRY_RUN_LINE,)
        lines: list[str] = [document.console_line for document in self.documents]
        if self.failure is not None:
            lines.append(self.failure.console_line)
        if self.skipped:
            lines.append(msg.DOC_SKIPPED_LINE.format(count=self.skipped))
        return tuple(lines)

    @property
    def part_report(self) -> PartReport:
        """Часть «Google-документ» отчёта запуска — строки консоли части."""
        return PartReport(RunPart.DOC.human_label, self.console_lines)

    @property
    def log_fields(self) -> Mapping[str, object]:
        return dict(
            dry_run=self.dry_run,
            dates=len(self.days),
            documents=len(self.documents),
            covers=sum(document.covers_placed for document in self.documents),
            covers_missed=sum(document.covers_missed for document in self.documents),
            copies=sum(document.is_copied for document in self.documents),
            copies_failed=sum(document.is_copy_failed for document in self.documents),
            failed_date=None if self.failure is None else self.failure.date,
        )

    def url_of(self, day: PublishDay) -> str | None:
        """Ссылка на документ дня; документа нет — None."""
        return next((document.url for document in self.documents if document.day.day.is_same(day)), None)


@dataclass(frozen=True)
class DocWriter:
    """Пишет документы дат в папку материалов `folder` на открытых клиентах Диска и Docs по настройкам запуска; копии
    .docx — в папку копий `paths`, когда идёт их линия (`with_copy`)."""

    folder: DriveTarget
    drive: DriveClient
    docs: DocsClient
    settings: LivecraftSettings
    texts: DocTexts
    paths: LivecraftPaths
    with_copy: bool

    def write(self, day: DocDay, created: datetime) -> DocDocument:
        """Документ даты: создать в папке материалов, открыть по ссылке, шапка, таблицы слотов, затем копия .docx —
        если идёт её линия."""
        name: str = day.name(self.texts, created)
        file: DriveFile = self.folder.create_document(self.drive, name)
        role: str | None = self.settings.docs.access.link_role
        if role is not None:
            self.drive.share(file.file_id, role)
        self._update(file.file_id, day.header(self.texts, self.settings).requests(HEADER_START_INDEX))
        placed: list[bool] = []
        for place, slot in enumerate(day.slots):
            placed.extend(self._slot(file.file_id, slot, is_first=place == 0))
        copy: DocCopySaved | DocCopyFailure | None = None
        if self.with_copy:
            copy = DocCopy(day.date, name).save(self.drive, file.file_id, self.paths)
        document: DocDocument = DocDocument(day, name, file.document_url, sum(placed), placed.count(False), copy)
        document.event.emit(LOGGER)
        return document

    def _slot(self, document_id: str, slot: DocSlot, is_first: bool) -> tuple[bool, ...]:
        """Таблица слота в конец, тексты ячеек, обложки; итог — встала ли обложка каждого источника."""
        self._update(document_id, slot.table_requests(is_first))
        self._update(document_id, slot.cell_requests(self.docs.document(document_id).last_table))
        spots: tuple[CoverSpot, ...] = slot.cover_spots(self.docs.document(document_id).last_table)
        return tuple(self._cover(document_id, slot, spot) for spot in spots)

    def _cover(self, document_id: str, slot: DocSlot, spot: CoverSpot) -> bool:
        """Обложка по адресам по порядку: 400 — следующий адрес; кончились — не встала (строка лога, не ошибка)."""
        for uri in spot.source.covers:
            try:
                self._update(document_id, (spot.image(uri),))
            except DocsError as error:
                if error.reason is not DocsReason.BAD_REQUEST:
                    raise
                continue
            return True
        missed: LogEvent = LogEvent.of(DocEvent.COVER_MISSED, slot=slot.slot.slot_id, source=spot.source.link)
        missed.extended(tried=len(spot.source.covers)).emit(LOGGER, logging.WARNING)
        return False

    def _update(self, document_id: str, requests: Sequence[DocRequest]) -> None:
        self.docs.update(document_id, [request.body for request in requests])


@dataclass(frozen=True)
class DocStage:
    """Часть «документ объявлений» одного запуска: настройки и сейф (папка материалов на Диске), «сейчас» (время
    создания в имени документа), пробный ли запуск, клиенты Диска и Docs — открываются, только когда нужны, — пути
    программы (папка копий) и идёт ли линия «Копия документа» (`with_copy`)."""

    settings: LivecraftSettings
    vault: Vault
    now: datetime
    dry_run: bool
    open_drive: Callable[[], DriveClient]
    open_docs: Callable[[], DocsClient]
    paths: LivecraftPaths
    with_copy: bool = True
    texts: DocTexts = field(default_factory=DocTexts)

    @classmethod
    def of(cls, paths: LivecraftPaths, settings: LivecraftSettings, vault: Vault, scope: RunScope) -> DocStage:
        """Боевая часть: время создания — «сейчас» в зоне программы; клиенты Диска и Docs по входу оператора этой
        установки (тот же вход, что для таблицы)."""
        login: GoogleLogin = GoogleLogin.operator(paths)
        return cls(
            settings, vault, Clock(settings.zone).now(), scope.dry_run, lambda: DriveClient.open(login),
            lambda: DocsClient.open(login), paths, with_copy=scope.runs(RunPart.DOC_COPY),
        )

    def run(
        self, days: Sequence[PublishDay], covers: Mapping[str, str], progress: StageProgress = SILENT_PROGRESS
    ) -> DocResult:
        """Документ на каждый день слотов запуска (обложки — копии превью на Диске по ссылкам видео); перед документом
        — строка хода в консоль; первый сбой Диска или Docs останавливает часть."""
        if self.dry_run:
            return self._finish(DocResult(dry_run=True))
        docs: tuple[DocDay, ...] = tuple(DocDay.of(day, covers, self.texts) for day in days)
        done: list[DocDocument] = []
        day: DocDay = docs[0]
        try:
            writer: DocWriter = DocWriter(
                DriveTarget.from_vault(self.vault), self.open_drive(), self.open_docs(), self.settings, self.texts,
                self.paths, self.with_copy,
            )
            for place, day in enumerate(docs, start=1):
                progress.doc_started(StepCount(place, len(docs)), day.human_date)
                done.append(writer.write(day, self.now))
        except (DriveError, DocsError) as error:
            failure: DocFailure = DocFailure(day, error)
            failure.event.emit(LOGGER, logging.ERROR)
            return self._finish(DocResult(dry_run=False, days=tuple(days), documents=tuple(done), failure=failure))
        return self._finish(DocResult(dry_run=False, days=tuple(days), documents=tuple(done)))

    def _finish(self, result: DocResult) -> DocResult:
        LogEvent.of(DocEvent.FINISHED, **result.log_fields).emit(LOGGER)
        return result
