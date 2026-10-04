"""Пакет plan_*.bcast из слотов запуска (CLAUDE.md §4, §14 решение 13).

ZIP: `manifest.json` первым, затем обложки `previews/`. Формат — ровно тот, что читает planers
`app\\package\\reader.py::read_package` (schema_version 1), чтобы пакет годился и для planers на другой машине.
Обложки берутся из памяти (`Preview.data`), а не с диска, и всегда JPEG. Запись атомарна: читатель видит либо
прежний пакет, либо новый целиком. Ссылка на форму ключей уходит в манифест открытым текстом (решение 15): без неё
planers пакет не читает, поэтому без ссылки, как и без слотов, пакет не пишется — причина называется. Пакет — слоты
одной формы (§14 решение 51): запуск пишет по пакету на форму, второй и следующие — с номером в имени файла.
"""
from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

from app.config.loader import FormSettings, LivecraftSettings
from app.packages.package_slot import FormSlots
from app.core.dates import DATETIME_FORMAT, SLOT_TIME_FORMAT, format_date, format_human_date, require_aware
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import AtomicFile
from app.slots.slot import StreamSlot
from app.ui.messages import msg
from app.version import APP_NAME, APP_VERSION

LOGGER = get_logger(LogArea.PACKAGES)

# Формат пакета — единственный источник; читатель — planers _ManifestParser.
SCHEMA_VERSION: Final[int] = 1
MANIFEST_NAME: Final[str] = "manifest.json"
JSON_INDENT: Final[int] = 2
PREVIEWS_DIR: Final[str] = "previews"
PREVIEW_PATH_TEMPLATE: Final[str] = PREVIEWS_DIR + "/{name}"    # имя обложки — StreamSlot.preview_file_names
FILE_NAME_TEMPLATE: Final[str] = "plan_{period_from}_{period_to}_gen{generated_date}-{generated_time}{order}.bcast"
# Номер пакета запуска в имени файла — со второго: «-2», «-3». Внутри части «gen…»: имя остаётся из четырёх частей.
FILE_ORDER_TEMPLATE: Final[str] = "-{number}"
TEMP_PREFIX_TEMPLATE: Final[str] = ".{stem}_"    # точка впереди: недописанный пакет не похож на plan_*.bcast
ARCHIVE_WRITE_MODE: Final[str] = "w"


class ManifestKey(str, Enum):
    """Ключи верхнего уровня манифеста схемы 1 в порядке записи."""

    SCHEMA_VERSION = "schema_version"
    PACKAGE_ID = "package_id"
    GENERATED_AT = "generated_at"
    GENERATOR = "generator"
    TIMEZONE = "timezone"
    PERIOD = "period"
    FORM = "form"
    SLOTS = "slots"


class GeneratorKey(str, Enum):
    """Ключи записи «кто собрал пакет»."""

    PROJECT = "project"
    VERSION = "version"
    RUN_ID = "run_id"


class PeriodKey(str, Enum):
    """Ключи записи периода пакета."""

    FROM = "from"
    TO = "to"


class PackageEvent(str, Enum):
    """События пакета в логе."""

    SKIPPED = "package_skipped"
    WRITTEN = "package_written"


class PackageProblem(str, Enum):
    """Почему пакет не пишется. Текст с точным действием — msg.PACKAGE_PROBLEMS."""

    NO_SLOTS = "no_slots"                        # нечего записывать
    FORM_NOT_CONFIGURED = "form_not_configured"  # без ссылки на форму planers пакет не читает

    @property
    def human(self) -> str:
        return msg.PACKAGE_PROBLEMS[self.value]


@dataclass(frozen=True)
class PackageResult:
    """Итог записи пакета: где лежит или почему не записан, сколько в нём слотов и обложек и его период (не записан —
    периода нет)."""

    path: Path | None
    problem: PackageProblem | None
    slots: int
    previews: int
    size_bytes: int
    period: PackagePeriod | None = None

    @property
    def is_written(self) -> bool:
        return self.path is not None

    @property
    def has_errors(self) -> bool:
        """Незаписанный пакет — ошибка запуска (§10)."""
        return not self.is_written

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Без текстов слотов и без ссылки на форму: путь, счётчики и размер либо причина."""
        if self.problem is not None:
            return dict(problem=self.problem, slots=self.slots)
        return dict(path=self.path, slots=self.slots, previews=self.previews, size_bytes=self.size_bytes)

    @property
    def console_line(self) -> str:
        """Строка для оператора: куда записан пакет либо что сделать, чтобы он записался."""
        if self.problem is not None:
            return msg.PACKAGE_NOT_WRITTEN.format(reason=self.problem.human)
        return msg.PACKAGE_WRITTEN.format(path=self.path, slots=self.slots, previews=self.previews)


@dataclass(frozen=True)
class PackagePeriod:
    """Период пакета: дата самого раннего и самого позднего старта слотов по местному времени сборки."""

    first: date
    last: date

    @classmethod
    def of(cls, starts: Sequence[datetime]) -> PackagePeriod:
        """Период по моментам старта, уже переведённым в зону момента сборки; моментов — хотя бы один."""
        return cls(first=min(starts).date(), last=max(starts).date())

    @property
    def first_text(self) -> str:
        return format_date(self.first)

    @property
    def last_text(self) -> str:
        return format_date(self.last)

    @property
    def first_human(self) -> str:
        """Первая дата DD.MM.YYYY — для текстов людям (§14 решение 31)."""
        return format_human_date(self.first)

    @property
    def last_human(self) -> str:
        return format_human_date(self.last)

    @property
    def manifest_value(self) -> dict[str, str]:
        return {PeriodKey.FROM.value: self.first_text, PeriodKey.TO.value: self.last_text}


@dataclass(frozen=True)
class SlotPackage:
    """Слоты одной формы, форма ключей и момент сборки — всё, из чего складывается один plan_*.bcast; `order` — место
    пакета среди пакетов запуска (с 0).

    Сам решает, можно ли его писать (`problem`), сам строит манифест, имя файла и имена обложек и сам
    пишет архив атомарно (`write`). Слоты — в порядке (start, language).
    """

    slots: tuple[StreamSlot, ...]
    form: FormSettings
    timezone: str
    generated_at: datetime      # со смещением, в зоне программы
    package_id: str
    order: int = 0

    @classmethod
    def of(cls, group: FormSlots, settings: LivecraftSettings, generated_at: datetime, package_id: str) -> SlotPackage:
        """Пакет из слотов одной формы (slot_id у них разные, проблем нет); момент сборки — в зоне программы."""
        require_aware(generated_at)
        return cls(
            slots=tuple(sorted(group.slots, key=lambda slot: (slot.start, slot.language))),
            form=group.form,
            timezone=settings.timezone,
            generated_at=generated_at.astimezone(settings.zone),
            package_id=package_id,
        )

    @property
    def problem(self) -> PackageProblem | None:
        """Почему пакет не пишется; None — пишется. Сначала слоты, затем форма."""
        if not self.slots:
            return PackageProblem.NO_SLOTS
        if not self.form.is_configured:
            return PackageProblem.FORM_NOT_CONFIGURED
        return None

    def preview_names(self, slot: StreamSlot) -> tuple[str, ...]:
        """Пути обложек слота в архиве: папка previews/ и имя файла обложки по правилу слота."""
        return tuple(PREVIEW_PATH_TEMPLATE.format(name=name) for name in slot.preview_file_names)

    @property
    def period(self) -> PackagePeriod:
        """Период по стартам слотов в зоне момента сборки. У пакета без слотов периода нет — он и не пишется."""
        return PackagePeriod.of(tuple(slot.start.astimezone(self.generated_at.tzinfo) for slot in self.slots))

    @property
    def preview_count(self) -> int:
        return sum(len(slot.previews) for slot in self.slots)

    @property
    def manifest(self) -> dict[str, Any]:
        """Манифест схемы 1: ключи `ManifestKey` в их порядке."""
        values: tuple[object, ...] = (
            SCHEMA_VERSION,
            self.package_id,
            self.generated_at.strftime(DATETIME_FORMAT),
            {GeneratorKey.PROJECT.value: APP_NAME, GeneratorKey.VERSION.value: APP_VERSION,
             GeneratorKey.RUN_ID.value: self.package_id},
            self.timezone,
            self.period.manifest_value,
            self.form.to_data(),
            [slot.to_record(self.preview_names(slot)) for slot in self.slots],
        )
        return {key.value: value for key, value in zip(ManifestKey, values, strict=True)}

    @property
    def file_name(self) -> str:
        """Имя файла — для людей: planers его не разбирает, читает только манифест. У второго и следующих пакетов
        запуска — номер: у пакетов разных форм один период и одна минута сборки бывают."""
        period: PackagePeriod = self.period
        return FILE_NAME_TEMPLATE.format(
            period_from=period.first_text,
            period_to=period.last_text,
            generated_date=format_date(self.generated_at.date()),
            generated_time=self.generated_at.strftime(SLOT_TIME_FORMAT),
            order=FILE_ORDER_TEMPLATE.format(number=self.order + 1) if self.order else "",
        )

    def write(self, bcast_dir: Path) -> PackageResult:
        """Пакет в bcast_dir атомарно: временный файл рядом и os.replace. С проблемой — ничего не пишет.

        Сбой файловой системы — OSError наружу; недописанный временный файл при этом удалён.
        """
        problem: PackageProblem | None = self.problem
        if problem is not None:
            result: PackageResult = PackageResult(
                path=None, problem=problem, slots=len(self.slots), previews=0, size_bytes=0
            )
            LogEvent.of(PackageEvent.SKIPPED, **result.log_fields).emit(LOGGER, logging.WARNING)
            return result
        bcast_dir.mkdir(parents=True, exist_ok=True)
        target: Path = bcast_dir / self.file_name
        self._write_atomically(target)
        result = PackageResult(
            path=target,
            problem=None,
            slots=len(self.slots),
            previews=self.preview_count,
            size_bytes=target.stat().st_size,
            period=self.period,
        )
        LogEvent.of(PackageEvent.WRITTEN, package_id=self.package_id, **result.log_fields).emit(LOGGER)
        return result

    def _write_atomically(self, target: Path) -> None:
        """Читатель видит либо прежний пакет с тем же именем, либо новый целиком — недописанного не бывает."""
        AtomicFile(target=target, prefix=TEMP_PREFIX_TEMPLATE.format(stem=target.stem)).write(self._write_archive)

    def _write_archive(self, archive_path: Path) -> None:
        """manifest.json первым, затем обложки слотов в порядке слотов и обложек."""
        manifest_bytes: bytes = json.dumps(
            self.manifest, ensure_ascii=False, indent=JSON_INDENT
        ).encode(TEXT_ENCODING)
        with zipfile.ZipFile(archive_path, mode=ARCHIVE_WRITE_MODE, compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST_NAME, manifest_bytes)
            for slot in self.slots:
                for name, preview in zip(self.preview_names(slot), slot.previews, strict=True):
                    archive.writestr(name, preview.data)
