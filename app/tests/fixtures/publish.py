"""Документ объявлений в тестах: итог прогона контура A по готовым видео и часть «документ объявлений» на подделках
Google Диска и Docs. Превью ложатся на свой поддельный Диск тем же этапом превью, что в бою: ссылки на копии — такие,
какие получит часть документа."""
from __future__ import annotations

import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.files import ShippedSettings
from app.config.settings import LivecraftSettings
from app.intake.intake import IntakeResult
from app.intake.preview_stage import PreviewCopies, PreviewMode, PreviewResult, PreviewStage
from app.packages.run_slots import RunSlots
from app.paths import DataFolders, LivecraftPaths
from app.publish.day import PublishDay
from app.publish.doc_day import DocDay
from app.publish.doc_stage import DocStage
from app.publish.doc_texts import DocTexts
from app.slots.preview import Preview
from app.sources.video import PreparedSources, SourceVideo
from app.tests.conftest import FORM_URL
from app.tests.fixtures.docs import FakeDocsService, docs_client
from app.tests.fixtures.drive import ROOT_FOLDER_ID, FakeDriveService, drive_client
from app.tests.fixtures.settings import drive_vault, with_form_url
from app.tests.fixtures.slots import build_slots
from app.tests.fixtures.sources import admitted_row, ready_source

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
CREATED: datetime = datetime(2026, 9, 28, 10, 5, tzinfo=KYIV)
DOC_PREVIEW: Preview = Preview(data=b"\xff\xd8preview\xff\xd9", width=1280, height=720)
UNUSED_ROOT: str = "livecraft-doc-stage-without-root"


def doc_settings() -> LivecraftSettings:
    """Поставочные настройки с формой: часть «документ объявлений» готова (папка материалов — в сейфе `drive_vault`)."""
    return with_form_url(ShippedSettings().settings, FORM_URL)


def doc_video(row: int, link: str, start: datetime, language: str = "uk", title: str = "") -> SourceVideo:
    """Годное видео с превью: название — по строке, если не задано."""
    return ready_source(admitted_row(row, link, start), title or f"Видео {row}", f"Опис відео {row}", language, DOC_PREVIEW)


@dataclass(frozen=True)
class DocRun:
    """Итог прогона таблицы по готовым видео и то, с чем по нему идёт документ: дни слотов (дата и форма настроек) и
    обложки — копии превью на Диске по ссылкам видео. `DocStage.run(*doc_run)` — как у вывода запуска."""

    result: IntakeResult

    @property
    def days(self) -> tuple[PublishDay, ...]:
        return PublishDay.days(RunSlots.of_table(self.result.slots, doc_settings().form).items)

    @property
    def covers(self) -> dict[str, str]:
        return {} if self.result.previews is None else self.result.previews.covers

    def __iter__(self) -> Iterator[object]:
        return iter((self.days, self.covers))

    def doc_days(self, texts: DocTexts) -> tuple[DocDay, ...]:
        """Дни документа со слотами — как их строит часть."""
        return tuple(DocDay.of(day, self.covers, texts) for day in self.days)


def doc_run(tmp_path: Path, videos: Sequence[SourceVideo], on_drive: bool = True) -> DocRun:
    """Итог прогона по готовым видео: превью — на поддельный Диск (или только в image\\), слоты — как у прогона."""
    sources: PreparedSources = PreparedSources(tuple(videos))
    mode: PreviewMode = PreviewMode.FULL if on_drive else PreviewMode.LOCAL
    stage: PreviewStage = PreviewStage(
        tmp_path, doc_settings(), drive_vault(ROOT_FOLDER_ID), mode, lambda: drive_client(FakeDriveService())
    )
    previews: PreviewResult = stage.run(PreviewCopies.of(videos, KYIV))
    return DocRun(IntakeResult(sources=sources, previews=previews, build=build_slots(videos, KYIV)))


def doc_stage(
    drive: FakeDriveService,
    docs: FakeDocsService,
    settings: LivecraftSettings | None = None,
    dry_run: bool = False,
    root: Path | None = None,
    with_copy: bool = True,
    folders: DataFolders | None = None,
) -> DocStage:
    """Часть «документ объявлений» на подделках; время создания — `CREATED`; копии .docx — в docs\\ корня `root`.

    Без `root` часть не запускают: запуск части пишет копии, и тест, который её запускает, даёт свой временный
    корень. `with_copy` — идёт ли линия «Копия документа»; `folders` — папки ролей из настроек."""
    paths: LivecraftPaths = LivecraftPaths(root if root is not None else Path(tempfile.gettempdir()) / UNUSED_ROOT)
    return DocStage(
        settings=settings or doc_settings(),
        vault=drive_vault(ROOT_FOLDER_ID),
        now=CREATED,
        dry_run=dry_run,
        open_drive=lambda: drive_client(drive),
        open_docs=lambda: docs_client(docs),
        paths=paths if folders is None else paths.with_folders(folders),
        with_copy=with_copy,
    )
