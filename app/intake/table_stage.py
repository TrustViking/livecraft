"""Шаг «запись в таблицу» прогона режима А: язык видео и ссылка на копию превью — в строку видео на листе плана
(CLAUDE.md §3, §6 инвариант 3, §14 решения 27, 29).

Шаг идёт после превью и до merge. Код языка каждого годного видео (`SourceVideo.language_code`) ложится в колонку
языка его строки, ссылка на копию превью на Google Диске (`PreviewResult.links` — есть, только когда копии легли на
Диск; этапа превью нет — ссылок нет) — в колонку превью; какие колонки и какие ячейки, решает `SheetWrite`
(app\\sheets\\preview.py): только там,
где значение другое. Всё — одним обращением values.batchUpdate, «обрезать» — только ячейки превью. Пробный запуск к
таблице не обращается вовсе.

Сбой записи прогон не останавливает: строка для человека и ошибка запуска (код 1), merge и пакет идут дальше. В строках
консоли и лога — счётчики и причина, без значений сейфа.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from app.intake.preview_stage import PreviewResult
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReader, SheetsReadError
from app.sheets.plan import SheetPlan
from app.sheets.preview import OutputCell, SheetOutput, SheetWrite
from app.sources.video import PreparedSources
from app.ui.messages import msg

LOGGER = get_logger(LogArea.INTAKE)


class TableEvent(str, Enum):
    """События шага «запись в таблицу» в логе."""

    FAILED = "sheet_write_failed"
    FINISHED = "sheet_write_finished"


@dataclass(frozen=True)
class TableResult:
    """Итог шага: пробный ли запуск, что записывалось (`write`), сбой записи (`error`) и шли ли в запуске превью на
    Google Диске (`uploads`): не шли — ссылок на превью программа не пишет, и строка о них молчит.

    Пробный запуск — ни записи, ни сбоя. Запись не удалась — ни одно значение не считается записанным.
    """

    dry_run: bool
    write: SheetWrite | None = None
    error: SheetsReadError | None = None
    uploads: bool = False

    def written(self, output: SheetOutput) -> int:
        """Сколько значений вывода записано: записи не было или она не удалась — ни одного."""
        return 0 if self.write is None or self.error is not None else self.write.written(output)

    def kept(self, output: SheetOutput) -> int:
        """Сколько значений вывода уже стояли в таблице."""
        return 0 if self.write is None else self.write.unchanged(output)

    @property
    def has_errors(self) -> bool:
        """Сбой записи в таблицу — ошибка запуска (§10)."""
        return self.error is not None

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Строка итога — о ссылках на превью, только когда превью на Диске шли; сбой записи — своей строкой после
        неё."""
        if self.dry_run:
            return (msg.INTAKE_SHEET_WRITE_DRY_RUN_LINE,)
        template: str = msg.INTAKE_SHEET_WRITE_LINE if self.uploads else msg.INTAKE_SHEET_WRITE_LANGUAGES_LINE
        line: str = template.format(
            languages=self.written(SheetOutput.LANGUAGE), languages_kept=self.kept(SheetOutput.LANGUAGE),
            links=self.written(SheetOutput.PREVIEW), links_kept=self.kept(SheetOutput.PREVIEW),
        )
        return (line,) if self.error is None else (line, self.error.human)

    @property
    def log_fields(self) -> Mapping[str, object]:
        return dict(
            dry_run=self.dry_run,
            languages=self.written(SheetOutput.LANGUAGE), languages_kept=self.kept(SheetOutput.LANGUAGE),
            links=self.written(SheetOutput.PREVIEW), links_kept=self.kept(SheetOutput.PREVIEW),
            error=None if self.error is None else self.error.reason,
        )


@dataclass(frozen=True)
class TableStage:
    """Шаг «запись в таблицу» одного запуска: сейф (id таблицы — у читателя таблицы, в единственной точке раскрытия)
    и пробный ли запуск."""

    vault: Vault
    dry_run: bool

    def run(
        self, plan: SheetPlan, sources: PreparedSources, previews: PreviewResult | None, reader: SheetsReader
    ) -> TableResult:
        """Языки годных видео и ссылки на копии превью — в строки видео; нечего менять — к таблице не обращаемся."""
        if self.dry_run:
            return self._finish(TableResult(dry_run=True))
        values: dict[SheetOutput, tuple[OutputCell, ...]] = {
            SheetOutput.PREVIEW: () if previews is None else previews.links,
            SheetOutput.LANGUAGE: self._languages(sources),
        }
        write: SheetWrite = SheetWrite.of(plan, values)
        error: SheetsReadError | None = None if write.is_empty else self._write(reader, write)
        uploads: bool = previews is not None and previews.mode.uploads
        return self._finish(TableResult(dry_run=False, write=write, error=error, uploads=uploads))

    def _languages(self, sources: PreparedSources) -> tuple[OutputCell, ...]:
        """Код языка по строке каждого видео, у которого он есть: язык определён только у годного видео."""
        return tuple(
            OutputCell(row_number=video.row_number, text=language)
            for video in sources.videos
            if (language := video.language_code) is not None
        )

    def _write(self, reader: SheetsReader, write: SheetWrite) -> SheetsReadError | None:
        """Запись в таблицу; не удалась — ошибка значением (строку лога о самом обращении пишет читатель таблицы)."""
        try:
            reader.write_outputs(self.vault, write)
        except SheetsReadError as error:
            LogEvent.of(TableEvent.FAILED, reason=error.reason, sheet=error.label).emit(LOGGER, logging.ERROR)
            return error
        return None

    def _finish(self, result: TableResult) -> TableResult:
        LogEvent.of(TableEvent.FINISHED, **result.log_fields).emit(LOGGER)
        return result
