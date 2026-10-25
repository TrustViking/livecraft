"""Чтение пакета plan_*.bcast — режим Б (CLAUDE.md §4, §14 решения 13, 18).

Правила — planers `app\\package\\reader.py` (schema_version 1): ZIP с manifest.json; версия схемы — ровно 1; в
манифесте — id пакета, момент сборки, кто собрал, пояс, период и форма ключей; слоты — список записей, slot_id не
повторяется, обложки каждой записи лежат в архиве. Формат — тот, что пишет `SlotPackage` (app\\packages\\package.py):
константы формата объявлены там один раз. Форма пакета разбирается тем же правилом, что раздел form настроек
(`FormSettings.from_node`), запись слота — самим слотом (`SlotEntry.of_record`).

Итог чтения — значение: прочитанный пакет (`ReadPackage`) или отказ (`PackageFailure`: причина и подробность — путь
поля манифеста, версия схемы или текст ошибки архива); исключение наружу не выходит. Будущие слоты (старт позже
«сейчас» программы) получают обложки из архива и форму своего пакета (`PackageSlot`); прошедшим они не нужны.
"""
from __future__ import annotations

import logging
import zipfile
import zlib
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from enum import Enum
from pathlib import Path
from typing import Final

from app.config.json_node import ConfigError, ConfigProblem, JsonNode, KeyPath
from app.config.setting_key import SettingKey
from app.config.settings import FormSettings
from app.core.dates import DATE_FORMAT, parse_datetime_text
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.packages.package import MANIFEST_NAME, SCHEMA_VERSION, ManifestKey, PeriodKey
from app.packages.package_line import PackageLine, PackageLineStatus
from app.packages.package_slot import PackageSlot
from app.slots.preview import Preview
from app.slots.slot import RecordFault, SlotEntry, SlotRecordError
from app.ui.messages import msg

LOGGER = get_logger(LogArea.PACKAGES)

# Архив не открылся или не распаковался: не ZIP, битый поток, файл исчез.
ARCHIVE_ERRORS: Final[tuple[type[Exception], ...]] = (zipfile.BadZipFile, zlib.error, OSError)
DETAIL_VALUE_TEMPLATE: Final[str] = "{path}={value!r}"         # негодное значение: путь поля и значение
DETAIL_PREVIEW_TEMPLATE: Final[str] = "{path}: {name}"          # обложка записи слота: путь записи и файл в архиве
MANIFEST_NOT_OBJECT: Final[str] = "manifest root is not an object"


class PackageFault(str, Enum):
    """Почему пакет не прочитан; значения — ключи PACKAGE_REASON_TEXT."""

    NOT_ZIP = "not_zip"
    NO_MANIFEST = "no_manifest"
    BAD_JSON = "bad_json"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    MISSING_KEY = "missing_key"
    BAD_VALUE = "bad_value"
    DUPLICATE_SLOT = "duplicate_slot"
    PREVIEW_MISSING = "preview_missing"
    PREVIEW_NOT_IMAGE = "preview_not_image"     # файл обложки в архиве есть, но это не картинка


class PackageReadEvent(str, Enum):
    """События чтения пакетов в логе."""

    READ = "package_read"
    REJECTED = "package_rejected"


class ManifestError(Exception):
    """Манифест не годится: причина и подробность. Наружу не выходит — `PackageFile.read` делает из неё отказ."""

    def __init__(self, fault: PackageFault, detail: str) -> None:
        self.fault: PackageFault = fault
        self.detail: str = detail
        super().__init__(detail)


@dataclass(frozen=True)
class PackageFailure:
    """Пакет не прочитан: файл, причина и подробность. Файл не трогается."""

    file: Path
    fault: PackageFault
    detail: str

    @property
    def line(self) -> PackageLine:
        """Строка пакета: неизвестная версия — своей строкой, прочее — «повреждён» с причиной и подробностью."""
        if self.fault is PackageFault.UNSUPPORTED_SCHEMA:
            return PackageLine(self.file.name, PackageLineStatus.UNSUPPORTED_SCHEMA, detail=self.detail)
        reason: str = msg.PACKAGE_REASON_WITH_DETAIL.format(
            reason=msg.PACKAGE_REASON_TEXT[self.fault.value], detail=self.detail
        )
        return PackageLine(self.file.name, PackageLineStatus.DAMAGED, detail=reason)

    @property
    def event(self) -> LogEvent:
        rejected: LogEvent = LogEvent.of(PackageReadEvent.REJECTED, file=self.file.name, reason=self.fault)
        return rejected.extended(detail=Quoted(self.detail))


@dataclass(frozen=True)
class ReadPackage:
    """Прочитанный пакет: файл, id, момент сборки (для порядка пакетов), будущие слоты с формой пакета и обложками и
    прошедшие записи слотов."""

    path: Path
    package_id: str
    generated_at: datetime
    future: tuple[PackageSlot, ...]
    past: tuple[SlotEntry, ...]

    @property
    def slot_ids(self) -> tuple[str, ...]:
        """slot_id всех слотов пакета: будущих и прошедших."""
        return (*(item.slot.slot_id for item in self.future), *(entry.slot_id for entry in self.past))

    @property
    def languages(self) -> tuple[str, ...]:
        """Языки всех слотов пакета — по слоту на язык."""
        return (*(item.slot.language for item in self.future), *(entry.language for entry in self.past))

    def line(self, languages: Collection[str]) -> PackageLine:
        """Строка пакета: все слоты в прошлом — «ничего не планируется»; иначе слотов всего и языков каналов."""
        if not self.future:
            return PackageLine(self.path.name, PackageLineStatus.ALL_PAST)
        mine: int = sum(1 for language in self.languages if language in languages)
        return PackageLine(self.path.name, PackageLineStatus.ACCEPTED, len(self.languages), mine)

    @property
    def event(self) -> LogEvent:
        read: LogEvent = LogEvent.of(PackageReadEvent.READ, file=self.path.name, package_id=self.package_id)
        return read.extended(future=len(self.future), past=len(self.past))


@dataclass(frozen=True)
class ManifestValue:
    """Значение манифеста и его путь (`slots[2].start`): значение одного вида читается одним правилом, негодное —
    ManifestError с путём."""

    value: object
    path: KeyPath

    def field(self, key: str) -> ManifestValue:
        """Поле объекта; нет поля — MISSING_KEY с его путём, не объект — BAD_VALUE."""
        if not isinstance(self.value, dict):
            raise self.bad()
        if key not in self.value:
            raise ManifestError(PackageFault.MISSING_KEY, self.path.child(key).text)
        return ManifestValue(self.value[key], self.path.child(key))

    def text(self) -> str:
        """Непустая строка."""
        if not isinstance(self.value, str) or not self.value.strip():
            raise self.bad()
        return self.value

    def mapping(self) -> ManifestValue:
        """Объект JSON."""
        if not isinstance(self.value, dict):
            raise self.bad()
        return self

    def fields(self) -> dict[str, object]:
        """Поля объекта JSON как есть — их разбирает владелец правила (запись слота)."""
        if not isinstance(self.value, dict):
            raise self.bad()
        return {str(key): value for key, value in self.value.items()}

    def items(self) -> tuple[ManifestValue, ...]:
        """Список; пустой годен."""
        if not isinstance(self.value, list):
            raise self.bad()
        return tuple(ManifestValue(item, self.path.item(index)) for index, item in enumerate(self.value))

    def date(self) -> date:
        """Дата DD-MM-YYYY."""
        text: str = self.text()
        try:
            return datetime.strptime(text, DATE_FORMAT).date()
        except ValueError as error:
            raise self.bad() from error

    def moment(self, zone: tzinfo) -> datetime:
        """Момент `DD-MM-YYYY HH:MM` по поясу программы."""
        text: str = self.text()
        try:
            return parse_datetime_text(text, zone)
        except ValueError as error:
            raise self.bad() from error

    def bad(self) -> ManifestError:
        detail: str = DETAIL_VALUE_TEMPLATE.format(path=self.path.text, value=self.value)
        return ManifestError(PackageFault.BAD_VALUE, detail)


@dataclass(frozen=True)
class PackageFile:
    """Файл пакета, пояс программы и «сейчас»: что из пакета будущее, а что уже прошло."""

    path: Path
    zone: tzinfo
    now: datetime

    def read(self) -> ReadPackage | PackageFailure:
        """Пакет целиком или отказ с причиной; отказ — строкой лога."""
        try:
            with zipfile.ZipFile(self.path) as archive:
                package: ReadPackage = self._parse(archive)
        except ManifestError as error:
            return self._failed(error.fault, error.detail)
        except ARCHIVE_ERRORS as error:
            return self._failed(PackageFault.NOT_ZIP, str(error))
        package.event.emit(LOGGER)
        return package

    def _failed(self, fault: PackageFault, detail: str) -> PackageFailure:
        failure: PackageFailure = PackageFailure(self.path, fault, detail)
        failure.event.emit(LOGGER, logging.WARNING)
        return failure

    def _parse(self, archive: zipfile.ZipFile) -> ReadPackage:
        """Версия схемы → форма → прочие поля манифеста → слоты; обложки — у будущих слотов."""
        root: ManifestValue = self._manifest(archive)
        self._check_schema(root)
        form: FormSettings = self._form(root.field(ManifestKey.FORM.value))
        generated_at: datetime = self._check_head(root)
        names: frozenset[str] = frozenset(archive.namelist())
        entries: tuple[SlotEntry, ...] = self._entries(root.field(ManifestKey.SLOTS.value), names)
        future: tuple[PackageSlot, ...] = tuple(
            PackageSlot(entry.slot(self._previews(archive, entry)), form) for entry in entries if entry.start > self.now
        )
        return ReadPackage(
            path=self.path,
            package_id=root.field(ManifestKey.PACKAGE_ID.value).text(),
            generated_at=generated_at,
            future=future,
            past=tuple(entry for entry in entries if entry.start <= self.now),
        )

    def _manifest(self, archive: zipfile.ZipFile) -> ManifestValue:
        """manifest.json архива: нет — NO_MANIFEST; не текст, не JSON или не объект — BAD_JSON."""
        try:
            raw: bytes = archive.read(MANIFEST_NAME)
        except KeyError as error:
            raise ManifestError(PackageFault.NO_MANIFEST, MANIFEST_NAME) from error
        try:
            node: JsonNode = JsonNode.parse(raw.decode(TEXT_ENCODING), self.path)
        except UnicodeDecodeError as error:
            raise ManifestError(PackageFault.BAD_JSON, str(error)) from error
        except ConfigError as error:
            raise ManifestError(PackageFault.BAD_JSON, error.problem) from error
        if not isinstance(node.value, dict):
            raise ManifestError(PackageFault.BAD_JSON, MANIFEST_NOT_OBJECT)
        return ManifestValue(node.value, KeyPath())

    def _check_schema(self, root: ManifestValue) -> None:
        """Версия схемы — целое ровно SCHEMA_VERSION (bool целым не считается)."""
        version: object = root.field(ManifestKey.SCHEMA_VERSION.value).value
        if type(version) is not int or version != SCHEMA_VERSION:
            raise ManifestError(PackageFault.UNSUPPORTED_SCHEMA, str(version))

    def _form(self, form: ManifestValue) -> FormSettings:
        """Форма пакета — правилом раздела form настроек; ссылка обязательна: без неё ключ отправлять некуда."""
        node: JsonNode = JsonNode(value=form.value, source=self.path, path=form.path)
        try:
            settings: FormSettings = FormSettings.from_node(node)
            node.check(settings.problem)
        except ConfigError as error:
            fault: PackageFault = (
                PackageFault.MISSING_KEY if error.reason is ConfigProblem.FIELD_MISSING else PackageFault.BAD_VALUE
            )
            raise ManifestError(fault, error.key_path) from error
        if not settings.is_configured:
            raise ManifestValue(settings.url, form.path.child(SettingKey.FORM_URL.leaf)).bad()
        return settings

    def _check_head(self, root: ManifestValue) -> datetime:
        """id пакета и пояс — строки, «кто собрал» — объект, период — две даты; итог — момент сборки."""
        for key in (ManifestKey.PACKAGE_ID, ManifestKey.TIMEZONE):
            root.field(key.value).text()
        root.field(ManifestKey.GENERATOR.value).mapping()
        period: ManifestValue = root.field(ManifestKey.PERIOD.value).mapping()
        for period_key in PeriodKey:
            period.field(period_key.value).date()
        return root.field(ManifestKey.GENERATED_AT.value).moment(self.zone)

    def _entries(self, slots: ManifestValue, names: frozenset[str]) -> tuple[SlotEntry, ...]:
        """Записи слотов по порядку манифеста: slot_id не повторяется, обложки каждой записи лежат в архиве."""
        entries: dict[str, SlotEntry] = {}
        for item in slots.items():
            entry: SlotEntry = self._entry(item)
            if entry.slot_id in entries:
                raise ManifestError(PackageFault.DUPLICATE_SLOT, entry.slot_id)
            missing: list[str] = [name for name in entry.preview_names if name not in names]
            if missing:
                detail: str = DETAIL_PREVIEW_TEMPLATE.format(path=item.path.text, name=missing[0])
                raise ManifestError(PackageFault.PREVIEW_MISSING, detail)
            entries[entry.slot_id] = entry
        return tuple(entries.values())

    def _entry(self, item: ManifestValue) -> SlotEntry:
        """Запись слота разбирает сам слот; путь негодного поля — от корня манифеста."""
        try:
            return SlotEntry.of_record(item.fields(), self.zone)
        except SlotRecordError as error:
            path: KeyPath = item.path.child(error.key.value)
            if error.fault is RecordFault.MISSING:
                raise ManifestError(PackageFault.MISSING_KEY, path.text) from error
            raise ManifestValue(error.value, path).bad() from error

    def _previews(self, archive: zipfile.ZipFile, entry: SlotEntry) -> tuple[Preview, ...]:
        """Обложки будущего слота в порядке записи; файл — не картинка: PREVIEW_NOT_IMAGE."""
        previews: list[Preview] = []
        for name in entry.preview_names:
            preview: Preview | None = Preview.of_image(archive.read(name))
            if preview is None:
                raise ManifestError(PackageFault.PREVIEW_NOT_IMAGE, name)
            previews.append(preview)
        return tuple(previews)
