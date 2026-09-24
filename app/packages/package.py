"""Пакет plan_*.bcast из слотов запуска (CLAUDE.md §4, §14 решение 13).

ZIP: `manifest.json` первым, затем обложки `previews/`. Формат — ровно тот, что читает planers
`app\\package\\reader.py::read_package` (schema_version 1), чтобы пакет годился и для planers на другой машине.
Правила записи — донор restreamer `publish\\planer_package_exporter.py` (`_build_manifest_payload`, `_build_period`,
`_build_file_name`, `_write_archive_atomically`); обложки берутся из памяти (`Preview.data`), а не с диска, и
всегда JPEG. Ссылка на форму ключей уходит в манифест открытым текстом (решение 15): без неё planers пакет не читает,
поэтому без ссылки, как и без слотов, пакет не пишется — причина называется.
"""
from __future__ import annotations

import json
import os
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

from app.config.loader import FormSettings, LivecraftSettings
from app.core.dates import DATE_FORMAT, DATETIME_FORMAT, SLOT_TIME_FORMAT
from app.observability.logging_setup import get_logger
from app.paths import TEMP_FILE_SUFFIX
from app.slots.slot import StreamSlot
from app.ui import messages_ru as msg
from app.version import APP_VERSION

LOGGER_NAME: Final[str] = "packages"
LOGGER = get_logger(LOGGER_NAME)

# Формат пакета — единственный источник (донор PlanerPackageFormat); читатель — planers _ManifestParser.
SCHEMA_VERSION: Final[int] = 1
MANIFEST_NAME: Final[str] = "manifest.json"
MANIFEST_ENCODING: Final[str] = "utf-8"
JSON_INDENT: Final[int] = 2
PREVIEWS_DIR: Final[str] = "previews"
PREVIEW_NAME_TEMPLATE: Final[str] = PREVIEWS_DIR + "/{slot_id}_{index}.jpg"   # обложки всегда JPEG (Preview)
FILE_NAME_TEMPLATE: Final[str] = "plan_{period_from}_{period_to}_gen{generated_date}-{generated_time}.bcast"
GENERATOR_PROJECT: Final[str] = "livecraft"
TEMP_SUFFIX: Final[str] = TEMP_FILE_SUFFIX
TEMP_PREFIX_TEMPLATE: Final[str] = ".{stem}_"    # точка впереди: недописанный пакет не похож на plan_*.bcast
PREVIEW_INDEX_START: Final[int] = 1


class PackageProblem(str, Enum):
    """Почему пакет не пишется. Текст с точным действием — msg.PACKAGE_PROBLEMS."""

    NO_SLOTS = "no_slots"                        # нечего записывать
    FORM_NOT_CONFIGURED = "form_not_configured"  # без ссылки на форму planers пакет не читает

    @property
    def human(self) -> str:
        return msg.PACKAGE_PROBLEMS[self.value]


@dataclass(frozen=True)
class PackageResult:
    """Итог записи пакета: где лежит или почему не записан, и сколько в нём слотов и обложек."""

    path: Path | None
    problem: PackageProblem | None
    slots: int
    previews: int
    size_bytes: int

    @property
    def is_written(self) -> bool:
        return self.path is not None

    @property
    def log_line(self) -> str:
        """Без текстов слотов и без ссылки на форму: путь, счётчики и размер либо причина."""
        if self.problem is not None:
            return f"problem={self.problem.value} slots={self.slots}"
        return f"path={self.path} slots={self.slots} previews={self.previews} size_bytes={self.size_bytes}"

    @property
    def console_line(self) -> str:
        """Строка для оператора: куда записан пакет либо что сделать, чтобы он записался."""
        if self.problem is not None:
            return msg.PACKAGE_NOT_WRITTEN.format(reason=self.problem.human)
        return msg.PACKAGE_WRITTEN.format(path=self.path, slots=self.slots, previews=self.previews)


@dataclass(frozen=True)
class SlotPackage:
    """Слоты запуска, форма ключей и момент сборки — всё, из чего складывается один plan_*.bcast.

    Сам решает, можно ли его писать (`problem`), сам строит манифест, имя файла и имена обложек и сам
    пишет архив атомарно (`write`). Слоты — в порядке (start, language), как у донора.
    """

    slots: tuple[StreamSlot, ...]
    form: FormSettings
    timezone: str
    generated_at: datetime      # со смещением, в зоне программы
    package_id: str

    @classmethod
    def of(
        cls,
        slots: Sequence[StreamSlot],
        settings: LivecraftSettings,
        generated_at: datetime,
        package_id: str,
    ) -> SlotPackage:
        """Пакет запуска: момент сборки — в зоне программы; слот с проблемой в пакет не идёт (planers его
        не прочтёт), повтор slot_id — побеждает более поздний (донор). Оба случая — WARNING в лог.
        """
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        by_id: dict[str, StreamSlot] = {}
        for slot in slots:
            if slot.problem is not None:
                LOGGER.warning("package_slot_refused %s problem=%r", slot.log_line, slot.problem)
                continue
            if slot.slot_id in by_id:
                LOGGER.warning("package_slot_duplicate slot=%s resolution=later_wins", slot.slot_id)
            by_id[slot.slot_id] = slot
        return cls(
            slots=tuple(sorted(by_id.values(), key=lambda item: (item.start, item.language))),
            form=settings.form,
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
        """Имена обложек слота в архиве — по одному на обложку, номера с 1 в порядке обложек."""
        return tuple(
            PREVIEW_NAME_TEMPLATE.format(slot_id=slot.slot_id, index=index)
            for index, _ in enumerate(slot.previews, start=PREVIEW_INDEX_START)
        )

    @property
    def period_from(self) -> str | None:
        """Дата самого раннего старта DD-MM-YYYY в зоне момента сборки; слотов нет — None."""
        if not self.slots:
            return None
        return min(self._local_starts).strftime(DATE_FORMAT)

    @property
    def period_to(self) -> str | None:
        """Дата самого позднего старта DD-MM-YYYY в зоне момента сборки; слотов нет — None."""
        if not self.slots:
            return None
        return max(self._local_starts).strftime(DATE_FORMAT)

    @property
    def _local_starts(self) -> tuple[datetime, ...]:
        return tuple(slot.start.astimezone(self.generated_at.tzinfo) for slot in self.slots)

    @property
    def preview_count(self) -> int:
        return sum(len(slot.previews) for slot in self.slots)

    @property
    def manifest(self) -> dict[str, Any]:
        """Манифест схемы 1 — ключи и порядок донора `_build_manifest_payload`."""
        return {
            "schema_version": SCHEMA_VERSION,
            "package_id": self.package_id,
            "generated_at": self.generated_at.strftime(DATETIME_FORMAT),
            "generator": {"project": GENERATOR_PROJECT, "version": APP_VERSION, "run_id": self.package_id},
            "timezone": self.timezone,
            "period": {"from": self.period_from, "to": self.period_to},
            "form": self.form.to_data(),
            "slots": [slot.to_record(self.preview_names(slot)) for slot in self.slots],
        }

    @property
    def file_name(self) -> str:
        """Имя файла — для людей: planers его не разбирает, читает только манифест."""
        return FILE_NAME_TEMPLATE.format(
            period_from=self.period_from,
            period_to=self.period_to,
            generated_date=self.generated_at.strftime(DATE_FORMAT),
            generated_time=self.generated_at.strftime(SLOT_TIME_FORMAT),
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
            LOGGER.warning("package_skipped %s", result.log_line)
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
        )
        LOGGER.info("package_written package_id=%s %s", self.package_id, result.log_line)
        return result

    def _write_atomically(self, target: Path) -> None:
        """Читатель видит либо прежний пакет с тем же именем, либо новый целиком — недописанного не бывает."""
        handle, temp_name = tempfile.mkstemp(
            prefix=TEMP_PREFIX_TEMPLATE.format(stem=target.stem), suffix=TEMP_SUFFIX, dir=target.parent
        )
        os.close(handle)
        temp_path: Path = Path(temp_name)
        try:
            self._write_archive(temp_path)
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)       # после os.replace файла уже нет — ничего не делает

    def _write_archive(self, archive_path: Path) -> None:
        """manifest.json первым, затем обложки слотов в порядке слотов и обложек."""
        manifest_bytes: bytes = json.dumps(
            self.manifest, ensure_ascii=False, indent=JSON_INDENT
        ).encode(MANIFEST_ENCODING)
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST_NAME, manifest_bytes)
            for slot in self.slots:
                for name, preview in zip(self.preview_names(slot), slot.previews, strict=True):
                    archive.writestr(name, preview.data)
