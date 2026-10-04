"""Этап «превью»: копии превью в папке превью и на Google Диске от слотов любого входа (CLAUDE.md §3, §14 решения 27,
37, 51).

Что делает этап, решают две линии работы (`PreviewMode.of`). Копии — `PreviewCopies`: при входе «Таблица» — превью
готовых видео (`of`: имя по `PreviewName` — номер среди видео своей даты и языка в порядке таблицы, строка таблицы);
этап идёт между источниками и записью в таблицу. При входе «Пакеты» — превью слотов пакетов (`of_slots`: имена
`StreamSlot.preview_file_names`, строки таблицы нет). Идёт линия «Превью на диске» — копия в папке превью по шаблону
`image_dir_template`, и в пробном запуске (как пакет). Идёт линия «Превью на Google Диске» и запуск не пробный — копия
ложится и на Диск, в подпапку `drive.preview_path_template` папки материалов (файл с тем же именем и размером не
загружается второй раз). Итог этапа — ссылки на копии на Диске: по строкам таблицы (`PreviewResult.links` — их пишет в
таблицу следующий шаг, `app\\intake\\table_stage.py`) и по ссылкам видео (`covers` — обложки документа объявлений). Не
идёт ни одна линия — этапа нет: превью в памяти для вывода остаются.

Сбой Диска прогон не останавливает: строка для человека и ошибка запуска (код 1), дальше прогон идёт. Сбой записи
копии в папке превью (OSError) — ошибка программы, её ловит запуск, как и сбой записи пакета.

Папка материалов — поле сейфа (§14 решение 39): её id раскрывает одна точка, `DriveTarget` — объект, который отдаёт id
обращениям к Диску (подпапки превью здесь, документ объявлений — app\\publish\\doc_stage.py, проверка папки в окне —
app\\setup\\panels\\folder_check.py); в лог — только ярлык с отпечатком (§7.4).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.folder_template import FolderTemplate
from app.config.settings import LivecraftSettings
from app.google.auth import GoogleLogin
from app.google.drive import DriveCall, DriveClient, DriveError, DriveFile, DriveFolder, DriveReason, DriveUpload
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import AtomicFile, DataDir, LivecraftPaths
from app.run.line_plan import RunScope
from app.run.mode import RunPart
from app.run.progress import SILENT_PROGRESS, StageProgress, StepCount
from app.secretsafe.field import SecretField
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.sheets.preview import OutputCell
from app.slots.preview import Preview
from app.slots.slot import SlotKey, StreamSlot
from app.sources.preview_name import PreviewName
from app.sources.video import SourceVideo
from app.ui.messages import msg

LOGGER = get_logger(LogArea.INTAKE)


@dataclass(frozen=True)
class DriveTarget:
    """Папка материалов на Google Диске из сейфа — секрет, а не строка (§7.4, §14 решение 39). Её id раскрывается
    только в обращении к Диску (`_folder_id`)."""

    folder: SecretValue

    @classmethod
    def from_vault(cls, vault: Vault) -> DriveTarget:
        """Папка из сейфа; нет её — DriveError(NOT_CONFIGURED), к Диску не обращаемся."""
        folder: SecretValue | None = vault.get(SecretField.DRIVE_FOLDER)
        if folder is None:
            raise DriveError(DriveReason.NOT_CONFIGURED, DriveCall.FOLDER)
        return cls(folder=folder)

    def check(self, client: DriveClient) -> DriveFolder:
        """Сама папка: название, папка ли это и можно ли в неё добавлять файлы."""
        return client.folder(self._folder_id)

    def subfolder(self, client: DriveClient, parts: Sequence[str]) -> str:
        """id подпапки по частям пути внутри папки материалов: найти или создать."""
        return client.ensure_path(self._folder_id, parts)

    def create_document(self, client: DriveClient, name: str) -> DriveFile:
        """Пустой документ Google Docs с этим именем в корне папки материалов."""
        return client.create_document(self._folder_id, name)

    @property
    def _folder_id(self) -> str:
        """id папки для обращения к Диску — единственная точка раскрытия этого поля сейфа (§7.4)."""
        return self.folder.reveal()


class PreviewMode(str, Enum):
    """Что делает этап в этом запуске. Значение — идентификатор для лога."""

    FULL = "full"           # копии в папке превью и на Google Диске
    LOCAL = "local"         # линия «Превью на Google Диске» не идёт: только копии в папке превью
    DRIVE = "drive"         # линия «Превью на диске» не идёт: только копии на Google Диске
    DRY_RUN = "dry_run"     # пробный запуск: только копии в папке превью, на Диск — ничего

    @classmethod
    def of(cls, scope: RunScope) -> PreviewMode | None:
        """Режим по линиям превью, которые идут в запуске; этапу нечего делать (ни одна не идёт или идёт только Диск в
        пробном запуске) — None."""
        local: bool = scope.runs(RunPart.LOCAL_PREVIEWS)
        drive: bool = scope.runs(RunPart.DRIVE_PREVIEWS)
        if local:
            return cls.LOCAL if not drive else cls.DRY_RUN if scope.dry_run else cls.FULL
        return cls.DRIVE if drive and not scope.dry_run else None

    @property
    def saves_local(self) -> bool:
        return self is not PreviewMode.DRIVE

    @property
    def uploads(self) -> bool:
        return self in (PreviewMode.FULL, PreviewMode.DRIVE)


class PreviewEvent(str, Enum):
    """События этапа «превью» в логе."""

    COPY = "preview_copy"
    FINISHED = "previews_finished"


@dataclass(frozen=True)
class PreviewCopy:
    """Превью одного видео: ключ его слота (дата и язык), имя файла, сама картинка, ссылка видео (None — чьё это превью,
    не известно) и строка видео в таблице плана (превью из пакета — None)."""

    key: SlotKey
    file_name: str
    preview: Preview
    source: str | None
    row_number: int | None = None

    def local_file(self, image_dir: Path, template: FolderTemplate) -> Path:
        """Куда ложится копия в папке превью: подпапка по шаблону для даты и языка эфира, имя превью."""
        return image_dir.joinpath(*template.parts(self.key.date_text, self.key.language), self.file_name)

    def drive_parts(self, template: FolderTemplate) -> tuple[str, ...]:
        """Подпапка копии внутри папки материалов на Диске — части пути по шаблону."""
        return template.parts(self.key.date_text, self.key.language)

    @property
    def upload(self) -> DriveUpload:
        return DriveUpload(name=self.file_name, data=self.preview.data, mime_type=self.preview.mime_type)

    @property
    def log_place(self) -> int | str:
        """Чьё превью — в строку лога: строка таблицы, иначе имя файла."""
        return self.file_name if self.row_number is None else self.row_number


@dataclass(frozen=True)
class PreviewCopies:
    """Превью запуска в порядке слотов входа."""

    items: tuple[PreviewCopy, ...]

    @classmethod
    def of(cls, videos: Sequence[SourceVideo], zone: ZoneInfo) -> PreviewCopies:
        """Вход «Таблица»: номер видео — место среди готовых видео той же даты и того же языка в порядке таблицы (с 1);
        превью есть не у всех: видео без превью номер занимает, копии не даёт."""
        places: dict[tuple[str, str], int] = {}
        items: list[PreviewCopy] = []
        for video in videos:
            key: SlotKey | None = video.slot_key(zone)
            if key is None:
                continue
            place: int = places.get((key.date_text, key.language), 0) + 1
            places[(key.date_text, key.language)] = place
            if video.preview is not None:
                name: PreviewName = PreviewName(index=place, language=key.language, title=video.text.title)
                items.append(PreviewCopy(key, name.file_name, video.preview, video.watch_url, video.row_number))
        return cls(items=tuple(items))

    @classmethod
    def of_slots(cls, slots: Sequence[StreamSlot]) -> PreviewCopies:
        """Вход «Пакеты»: превью слотов под именами обложек слота. Превью слота — превью его видео в порядке видео, но
        только тех, у кого оно было: чьё оно, известно, лишь когда превью столько же, сколько видео."""
        items: list[PreviewCopy] = []
        for slot in slots:
            owners: tuple[str | None, ...] = (
                slot.sources if len(slot.previews) == len(slot.sources) else (None,) * len(slot.previews)
            )
            items.extend(
                PreviewCopy(slot.key, name, preview, owner)
                for name, preview, owner in zip(slot.preview_file_names, slot.previews, owners, strict=True)
            )
        return cls(items=tuple(items))


@dataclass(frozen=True)
class DriveCopy:
    """Копия превью на Диске: чья она и файл, который лёг (или уже лежал)."""

    copy: PreviewCopy
    file: DriveFile

    @property
    def link(self) -> OutputCell | None:
        """Ссылка на копию — в строку таблицы этого видео; превью из пакета строки нет — None."""
        row: int | None = self.copy.row_number
        return None if row is None else OutputCell(row_number=row, text=self.file.download_url)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(
            PreviewEvent.COPY, row=self.copy.log_place, drive_file=self.file.file_id, uploaded=self.file.is_new
        )


@dataclass(frozen=True)
class DriveCopies:
    """Итог копий на Диске: какие легли и сбой, после которого Диск больше не спрашивали."""

    copies: tuple[DriveCopy, ...] = ()
    error: DriveError | None = None

    @property
    def uploaded(self) -> int:
        return sum(1 for copy in self.copies if copy.file.is_new)

    @property
    def kept(self) -> int:
        return len(self.copies) - self.uploaded

    @property
    def links(self) -> tuple[OutputCell, ...]:
        return tuple(link for copy in self.copies if (link := copy.link) is not None)

    @property
    def covers(self) -> dict[str, str]:
        """Ссылка видео → ссылка на копию его превью на Диске."""
        return {copy.copy.source: copy.file.download_url for copy in self.copies if copy.copy.source is not None}


@dataclass(frozen=True)
class PreviewResult:
    """Итог этапа: режим, сколько копий в папке превью, что на Диске и сбой Диска."""

    mode: PreviewMode
    saved: int
    drive: DriveCopies = field(default_factory=DriveCopies)

    @property
    def links(self) -> tuple[OutputCell, ...]:
        """Ссылки на копии, которые лежат на Диске, — по строкам видео; копий на Диске нет — ни одной."""
        return self.drive.links

    @property
    def covers(self) -> dict[str, str]:
        """Обложки документа объявлений: ссылка видео → копия его превью на Диске этого запуска."""
        return self.drive.covers

    @property
    def has_errors(self) -> bool:
        """Сбой Диска — ошибка запуска (§10)."""
        return self.drive.error is not None

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Строка итога по режиму; сбой Диска — своей строкой после неё."""
        if self.mode is PreviewMode.LOCAL:
            return (msg.PREVIEWS_LOCAL_LINE.format(saved=self.saved),)
        if self.mode is PreviewMode.DRY_RUN:
            return (msg.PREVIEWS_DRY_RUN_LINE.format(saved=self.saved),)
        template: str = msg.PREVIEWS_LINE if self.mode is PreviewMode.FULL else msg.PREVIEWS_DRIVE_LINE
        line: str = template.format(saved=self.saved, uploaded=self.drive.uploaded, kept=self.drive.kept)
        return (line,) if self.drive.error is None else (line, self.drive.error.human)

    @property
    def log_fields(self) -> Mapping[str, object]:
        return dict(
            mode=self.mode, saved=self.saved, uploaded=self.drive.uploaded, kept=self.drive.kept,
            drive_error=None if self.drive.error is None else self.drive.error.reason,
        )


@dataclass(frozen=True)
class PreviewStage:
    """Этап «превью» одного запуска: папка превью, настройки (шаблоны папок, пояс), сейф (папка материалов на Диске),
    режим и клиент Диска — открывается, только когда он нужен (`open_drive`)."""

    image_dir: Path
    settings: LivecraftSettings
    vault: Vault
    mode: PreviewMode
    open_drive: Callable[[], DriveClient]

    @classmethod
    def of(cls, paths: LivecraftPaths, settings: LivecraftSettings, vault: Vault, mode: PreviewMode) -> PreviewStage:
        """Боевой этап: клиент Диска по входу оператора этой установки (браузер тот же, что для таблицы)."""
        login: GoogleLogin = GoogleLogin.operator(paths)
        return cls(paths.dir(DataDir.IMAGE), settings, vault, mode, lambda: DriveClient.open(login))

    def run(self, copies: PreviewCopies, progress: StageProgress = SILENT_PROGRESS) -> PreviewResult:
        """Копии в папке превью и на Диске — по режиму; перед каждой загрузкой на Диск — строка хода в консоль."""
        local: tuple[PreviewCopy, ...] = copies.items if self.mode.saves_local else ()
        for copy in local:
            self._save(copy)
        if not self.mode.uploads:
            return self._finish(PreviewResult(mode=self.mode, saved=len(local)))
        return self._finish(PreviewResult(mode=self.mode, saved=len(local), drive=self._upload(copies, progress)))

    def _save(self, copy: PreviewCopy) -> None:
        """Копия в папке превью — атомарно: на месте файла либо прежняя копия, либо новая целиком."""
        target: Path = copy.local_file(self.image_dir, FolderTemplate(self.settings.image_dir_template))
        target.parent.mkdir(parents=True, exist_ok=True)
        AtomicFile.at(target).write(lambda path: path.write_bytes(copy.preview.data))
        LogEvent.of(PreviewEvent.COPY, row=copy.log_place, file=target).emit(LOGGER)

    def _upload(self, copies: PreviewCopies, progress: StageProgress) -> DriveCopies:
        """Копии на Диск по порядку; первый сбой Диска останавливает загрузку: следующие упали бы так же."""
        done: list[DriveCopy] = []
        template: FolderTemplate = self.settings.drive.preview_folder
        total: int = len(copies.items)
        try:
            target: DriveTarget = DriveTarget.from_vault(self.vault)
            client: DriveClient = self.open_drive()
            for place, copy in enumerate(copies.items, start=1):
                progress.drive_copy_started(StepCount(place, total))
                folder_id: str = target.subfolder(client, copy.drive_parts(template))
                placed: DriveCopy = DriveCopy(copy=copy, file=client.upload(folder_id, copy.upload))
                placed.event.emit(LOGGER)
                done.append(placed)
        except DriveError as error:
            error.event.emit(LOGGER, logging.ERROR)
            return DriveCopies(copies=tuple(done), error=error)
        return DriveCopies(copies=tuple(done))

    def _finish(self, result: PreviewResult) -> PreviewResult:
        LogEvent.of(PreviewEvent.FINISHED, **result.log_fields).emit(LOGGER)
        return result
