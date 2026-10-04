"""Паспорт каналов secrets\\channels_passport.json: ник ↔ id YouTube ↔ файл токена (CLAUDE.md §6 инвариант 5).

Паспорт — не вход для решений об эфирах: по нему программа узнаёт, что канал с другим ником — тот же (id YouTube не
меняется никогда), и находит токен после ручной смены ника в channels.json. Пишет его только программа; формат — тот
же, что у planers, файл годен обоим. Записи каналов, которых уже нет в channels.json, не удаляются. Нет файла — пустой
паспорт; файл не читается или не той формы — пустой паспорт с проблемой (`problem`), его перепишет ближайшее
сохранение. Сохраняется паспорт, только когда в нём что-то изменилось.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Final

from app.config.channel import ChannelConfig, ChannelHandle
from app.core.text_format import NEWLINE, TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, LogValue, get_logger
from app.paths import write_text_atomically
from app.platforms.channel_event import ChannelEvent
from app.platforms.channel_info import ChannelInfo, ChannelLink

LOGGER = get_logger(LogArea.PLATFORMS)
PASSPORT_INDENT: Final[int] = 2
LIST_FIELDS: Final[frozenset[str]] = frozenset({"previous_handles", "previous_titles"})
OPTIONAL_FIELDS: Final[frozenset[str]] = frozenset({"youtube_handle_raw"})


class PassportKey(str, Enum):
    """Поле корня файла паспорта."""

    CHANNELS = "channels"


class PassportDetail(str, Enum):
    """Что не так с файлом паспорта — английская подробность только для лога."""

    NOT_ROOT = 'expected {{"channels": [...]}}'
    NOT_ENTRY = "channels[{index}]: expected exactly the fields {fields}"
    NOT_LIST = "channels[{index}].{name}: expected a list of strings"
    NOT_TEXT = "channels[{index}].{name}: expected a non-empty string"

    def text(self, **values: object) -> str:
        return self.value.format(**values)


class PassportFormatError(ValueError):
    """Файл паспорта не той формы: текст — подробность для лога."""


@dataclass(frozen=True)
class PassportEntry:
    handle: str                     # ник как в channels.json после выравнивания
    account_name: str               # название как в channels.json после выравнивания
    youtube_channel_id: str
    youtube_title: str
    youtube_handle_raw: str | None  # snippet.customUrl как пришёл
    google_account: str
    token_file: str                 # имя файла токена в secrets\
    channel_url: str
    handle_url: str
    first_verified_at: str          # DD-MM-YYYY HH:MM по часам программы
    last_verified_at: str
    previous_handles: tuple[str, ...] = ()
    previous_titles: tuple[str, ...] = ()

    @classmethod
    def of_json(cls, raw: object, index: int) -> PassportEntry:
        """Запись из объекта файла: ровно поля записи, каждое своего вида; иначе — PassportFormatError."""
        if not isinstance(raw, dict) or set(raw) != set(ENTRY_FIELDS):
            names: str = LogValue.LIST_SEPARATOR.value.join(ENTRY_FIELDS)
            raise PassportFormatError(PassportDetail.NOT_ENTRY.text(index=index, fields=names))
        return cls(**{name: cls._field_value(raw[name], name, index) for name in ENTRY_FIELDS})

    @property
    def key(self) -> str:
        return ChannelHandle.of(self.handle).key

    @property
    def data(self) -> dict[str, object]:
        """Запись как объект файла, поля в порядке записи; кортежи JSON пишет списками."""
        return dataclasses.asdict(self)

    def channel_for(self, channel: ChannelConfig) -> ChannelConfig:
        """Канал с ником, названием и почтой этой записи, остальное — от `channel`: так спрашивают токен, который
        лежит под прежним ником."""
        return dataclasses.replace(
            channel, account_name=self.account_name, handle=self.handle, google_account=self.google_account
        )

    @classmethod
    def _field_value(cls, value: object, name: str, index: int) -> object:
        if name in LIST_FIELDS:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise PassportFormatError(PassportDetail.NOT_LIST.text(index=index, name=name))
            return tuple(value)
        if value is None and name in OPTIONAL_FIELDS:
            return None
        if not isinstance(value, str) or not value:
            raise PassportFormatError(PassportDetail.NOT_TEXT.text(index=index, name=name))
        return value


ENTRY_FIELDS: Final[tuple[str, ...]] = tuple(item.name for item in fields(PassportEntry))


@dataclass(frozen=True)
class ChannelVerification:
    """Канал подтверждён: значения channels.json до выравнивания и после, что прислал YouTube, имя файла токена в
    secrets\\ и момент проверки (DD-MM-YYYY HH:MM по часам программы)."""

    before: ChannelConfig
    after: ChannelConfig
    info: ChannelInfo
    token_file: str
    verified_at: str

    def entry(self, old: PassportEntry | None) -> PassportEntry:
        """Запись паспорта; `old` — прежняя запись того же id: от неё — первое подтверждение и прежние ники и названия."""
        return PassportEntry(
            handle=self.after.handle,
            account_name=self.after.account_name,
            youtube_channel_id=self.info.youtube_channel_id,
            youtube_title=self.info.title,
            youtube_handle_raw=self.info.handle_raw,
            google_account=self.after.google_account,
            token_file=self.token_file,
            channel_url=self.info.channel_url,
            handle_url=ChannelLink.HANDLE.url(handle=self.after.handle),
            first_verified_at=self.verified_at if old is None else old.first_verified_at,
            last_verified_at=self.verified_at,
            previous_handles=self.previous_handles(old),
            previous_titles=self.previous_titles(old),
        )

    def previous_handles(self, old: PassportEntry | None) -> tuple[str, ...]:
        """Прежние ники канала без повторов по ключу, кроме нынешнего; написание — первое встреченное."""
        earlier: tuple[str, ...] = () if old is None else (*old.previous_handles, old.handle)
        kept: dict[str, str] = {}
        for handle in (*earlier, self.before.handle):
            key: str = ChannelHandle.of(handle).key
            if key != self.after.key:
                kept.setdefault(key, handle)
        return tuple(kept.values())

    def previous_titles(self, old: PassportEntry | None) -> tuple[str, ...]:
        """Прежние названия канала без повторов, кроме нынешнего."""
        earlier: tuple[str, ...] = () if old is None else (*old.previous_titles, old.account_name)
        candidates: tuple[str, ...] = (*earlier, self.before.account_name)
        return tuple(dict.fromkeys(title for title in candidates if title != self.after.account_name))


class ChannelPassport:
    """Записи в памяти; `save` пишет файл целиком и атомарно — только когда записи изменились."""

    def __init__(self, path: Path, entries: Iterable[PassportEntry] = (), problem: str | None = None) -> None:
        self._path: Path = path
        self._entries: list[PassportEntry] = list(entries)
        self._problem: str | None = problem
        self._is_changed: bool = problem is not None   # не читался — перезаписать ближайшим сохранением

    @classmethod
    def load(cls, path: Path) -> ChannelPassport:
        """Паспорт файла; нет файла — пустой; не читается или не той формы — пустой с проблемой."""
        if not path.is_file():
            return cls(path)
        try:
            raw: object = json.loads(path.read_text(encoding=TEXT_ENCODING))
            return cls(path, cls._entries_of(raw))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            LogEvent.of(ChannelEvent.PASSPORT_UNREADABLE, path=path, error=error).emit(LOGGER, logging.WARNING)
            return cls(path, problem=str(error))

    @property
    def path(self) -> Path:
        return self._path

    @property
    def problem(self) -> str | None:
        """Почему файл не прочитался; None — прочитан или его нет."""
        return self._problem

    @property
    def entries(self) -> tuple[PassportEntry, ...]:
        return tuple(self._entries)

    def find_by_key(self, key: str) -> PassportEntry | None:
        return next((entry for entry in self._entries if entry.key == key), None)

    def find_by_channel_id(self, youtube_channel_id: str) -> PassportEntry | None:
        return next((entry for entry in self._entries if entry.youtube_channel_id == youtube_channel_id), None)

    def record(self, entry: PassportEntry) -> None:
        """Одна запись на канал: прежняя запись того же id или того же ника заменяется."""
        self._entries = [
            item for item in self._entries if item.youtube_channel_id != entry.youtube_channel_id and item.key != entry.key
        ]
        self._entries.append(entry)
        self._is_changed = True

    def record_verified(self, verification: ChannelVerification) -> PassportEntry:
        """Канал подтверждён: запись по прежней записи того же id."""
        entry: PassportEntry = verification.entry(self.find_by_channel_id(verification.info.youtube_channel_id))
        self.record(entry)
        return entry

    def render(self) -> str:
        """Текст файла: записи по названию, затем по нику."""
        ordered: list[PassportEntry] = sorted(self._entries, key=lambda entry: (entry.account_name, entry.handle))
        payload: dict[str, object] = {PassportKey.CHANNELS.value: [entry.data for entry in ordered]}
        return json.dumps(payload, ensure_ascii=False, indent=PASSPORT_INDENT) + NEWLINE

    def save(self) -> str | None:
        """Записать, если записи изменились. None — записан или писать нечего; иначе текст ошибки (запуск идёт дальше)."""
        if not self._is_changed:
            return None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomically(self._path, self.render(), TEXT_ENCODING)
        except OSError as error:
            LogEvent.of(ChannelEvent.PASSPORT_WRITE_FAILED, path=self._path, error=error).emit(LOGGER, logging.WARNING)
            return str(error)
        self._is_changed = False
        LogEvent.of(ChannelEvent.PASSPORT_SAVED, path=self._path, channels=len(self._entries)).emit(LOGGER)
        return None

    @classmethod
    def _entries_of(cls, raw: object) -> list[PassportEntry]:
        """Записи корня файла `{"channels": [...]}`; иначе — PassportFormatError."""
        key: str = PassportKey.CHANNELS.value
        if not isinstance(raw, dict) or set(raw) != {key} or not isinstance(raw[key], list):
            raise PassportFormatError(PassportDetail.NOT_ROOT.text())
        return [PassportEntry.of_json(item, index) for index, item in enumerate(raw[key])]
