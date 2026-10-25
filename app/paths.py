"""Корень livecraft и его папки (CLAUDE.md §5): рядом с exe (frozen) или корень репо (dev).

Одна папка данных на роль (§6, инвариант 10) — `DataDir`: secrets\\ — всё секретное и все конфиги,
image\\ — превью, bcast\\ — пакеты plan_*.bcast, docs\\ — копии документов объявлений в формате Word по датам,
tokens\\ — созданные токены доступа, keystreams\\ — ключи потоков, state\\ — замок, служебные отметки, кэш yt-dlp и
deno, logs\\ — лог и отчёт, tools\\ — внешние бинарники.
Папки превью, пакетов и копий документов человек выбирает сам (§14 решение 37, `DataFolders`). Всё остальное — в app\\.
Ставить программу в папку с правом записи (установщик по умолчанию — %LOCALAPPDATA%\\Programs\\Livecraft), не в
Program Files.
"""
from __future__ import annotations

import dataclasses
import os
import random
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Final

from app.core.dates import FILE_STAMP_FORMAT
from app.core.retry import AttemptFailure, RetryLoop, RetryPolicy, RetryRun

ROOT_ENV_VAR: Final[str] = "LIVECRAFT_ROOT"  # подмена корня — только для тестов и отладки
TEMP_FILE_SUFFIX: Final[str] = ".tmp"
TOKEN_FILE_TEMPLATE: Final[str] = "{stem}.token.json"
REPORT_FILE_TEMPLATE: Final[str] = "{stamp}_report.md"   # штамп — момент начала запуска, как у лога
# Замена занятого файла (`AtomicFile`): до четырёх повторов с паузами 0,1–0,8 с — всего не дольше полутора секунд.
REPLACE_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(base_delay_sec=0.1, max_delay_sec=0.8, jitter_max_sec=0.05)


class ProcessAttr(str, Enum):
    """Признаки процесса в модуле sys, по которым видно, как запущена программа."""

    FROZEN = "frozen"      # PyInstaller ставит sys.frozen в собранном exe


class DataDir(str, Enum):
    """Папки данных в корне (§6, инвариант 10). Значение — имя папки."""

    SECRETS = "secrets"          # всё секретное и все конфиги
    TOOLS = "tools"              # внешние бинарники, обновляются сами
    IMAGE = "image"              # превью по шаблону {date}\{language}
    BCAST = "bcast"              # пакеты plan_*.bcast: пишет режим А, читает режим Б (§14 решения 13, 18)
    DOCS = "docs"                # копии документов объявлений .docx: docs\<DD-MM-YYYY>\ (§14 решение 33)
    TOKENS = "tokens"            # созданные токены доступа: пары «токен + ключ» и токены одним файлом (§14 решение 44)
    KEYSTREAMS = "keystreams"    # ключи потоков для ручной передачи
    STATE = "state"              # замок одного экземпляра, отметки автообновлений, кэш yt-dlp и deno
    LOGS = "logs"                # лог запуска и отчёт


class FileName(str, Enum):
    """Имена файлов и папок в папках данных, которые читает и пишет программа."""

    CONFIG = "livecraft.json"
    CHANNELS = "channels.json"
    CHANNELS_PREVIOUS = "channels.previous.json"
    # Файл проекта Google под прежним именем (до 9.21): его подключает запуск, когда проект не выбран.
    CLIENT_SECRET = "client_secret.json"
    SHEETS_TOKEN = "sheets.token.json"
    COOKIES = "cookies.txt"
    VAULT_LOCAL = "vault.local.dat"
    VAULT_TOKEN = "vault.token.dat"   # значения из загруженного токена доступа (§14 решения 16, 44)
    TOKEN_RECEIVED = "token_received.json"   # файлы secrets, полученные с токеном доступа, и их отпечатки (решение 65)
    YTDLP = "yt-dlp.exe"
    DENO = "deno.exe"
    LOCK = "livecraft.lock"
    YTDLP_CHECK = "ytdlp_last_check.json"     # отметка последней проверки новой версии yt-dlp (app\runtime)
    DENO_CHECK = "deno_last_check.json"       # то же для deno
    STARTUP_LOG = "startup.log"
    RECORDS = "livecraft.sqlite3"     # память программы (§6, инвариант 0)
    PASSPORT = "channels_passport.json"   # паспорт каналов: ник ↔ id YouTube ↔ файл токена (§6, инвариант 5)
    KEYS = "keys.txt"                 # ключи потоков для ручной передачи (§6, инвариант 6)
    YTDLP_CACHE = "yt-dlp-cache"      # папка кэша yt-dlp (§14 решение 56)
    DENO_CACHE = "deno-cache"         # папка кэша deno, которого зовёт yt-dlp (§14 решение 56)

    @property
    def folder(self) -> DataDir:
        """Папка данных, в которой лежит файл с этим именем."""
        return FILE_FOLDERS[self]


# Папка каждого имени — одно правило для всех файлов данных (§6, инвариант 10).
FILE_FOLDERS: Final[dict[FileName, DataDir]] = {
    FileName.CONFIG: DataDir.SECRETS,
    FileName.CHANNELS: DataDir.SECRETS,
    FileName.CHANNELS_PREVIOUS: DataDir.SECRETS,
    FileName.CLIENT_SECRET: DataDir.SECRETS,
    FileName.SHEETS_TOKEN: DataDir.SECRETS,
    FileName.COOKIES: DataDir.SECRETS,
    FileName.VAULT_LOCAL: DataDir.SECRETS,
    FileName.VAULT_TOKEN: DataDir.SECRETS,
    FileName.TOKEN_RECEIVED: DataDir.SECRETS,
    FileName.YTDLP: DataDir.TOOLS,
    FileName.DENO: DataDir.TOOLS,
    FileName.LOCK: DataDir.STATE,
    FileName.YTDLP_CHECK: DataDir.STATE,
    FileName.DENO_CHECK: DataDir.STATE,
    FileName.STARTUP_LOG: DataDir.LOGS,
    FileName.RECORDS: DataDir.SECRETS,
    FileName.PASSPORT: DataDir.SECRETS,
    FileName.KEYS: DataDir.KEYSTREAMS,
    FileName.YTDLP_CACHE: DataDir.STATE,
    FileName.DENO_CACHE: DataDir.STATE,
}


class ProjectFileMark(str, Enum):
    """Части имени файла проекта Google, который программа кладёт в secrets\\ сама: google_project_<ID>.json — клиент
    из токена доступа (§14 решение 66). `.previous` — прежний проект сборок 9.21: при подключении не берётся."""

    PREFIX = "google_project_"
    PREVIOUS = ".previous"
    SUFFIX = ".json"


PROJECT_FILE_GLOB: Final[str] = f"{ProjectFileMark.PREFIX.value}*{ProjectFileMark.SUFFIX.value}"
PREVIOUS_PROJECT_ENDING: Final[str] = ProjectFileMark.PREVIOUS.value + ProjectFileMark.SUFFIX.value


@dataclass(frozen=True)
class DataFolders:
    """Папки ролей, которые выбирает человек (§14 решение 37): превью, пакеты, копии документов. Путь относительный —
    от корня программы, абсолютный — как есть; по умолчанию — имя папки роли в корне. У остальных ролей папка не
    выбирается."""

    images: Path = Path(DataDir.IMAGE.value)
    packages: Path = Path(DataDir.BCAST.value)
    docs: Path = Path(DataDir.DOCS.value)

    def place(self, folder: DataDir) -> Path:
        """Папка роли относительно корня программы (абсолютная — как есть)."""
        chosen: dict[DataDir, Path] = {
            DataDir.IMAGE: self.images, DataDir.BCAST: self.packages, DataDir.DOCS: self.docs
        }
        return chosen.get(folder, Path(folder.value))


@dataclass(frozen=True)
class LivecraftPaths:
    """Где что лежит — знает только этот объект; модули получают готовый путь, а не собирают его сами.

    `folders` — папки ролей из настроек (`with_folders`); до чтения настроек и без них — имена ролей в корне.
    `google_project` — файл проекта Google из настроек (`with_google_project`, §14 решение 66): путь как в настройке —
    относительный от корня, абсолютный как есть; проект не выбран или настройки не прочитаны — None."""

    root: Path
    folders: DataFolders = DataFolders()
    google_project: Path | None = None

    @classmethod
    def locate(cls) -> LivecraftPaths:
        """LIVECRAFT_ROOT, если задан; иначе папка exe (frozen) или корень репо (родитель app\\)."""
        override: str = os.environ.get(ROOT_ENV_VAR, "").strip()
        if override:
            return cls(Path(override).resolve())
        if getattr(sys, ProcessAttr.FROZEN.value, False):
            return cls(Path(sys.executable).resolve().parent)
        return cls(Path(__file__).resolve().parents[1])

    def with_folders(self, folders: DataFolders) -> LivecraftPaths:
        """Те же пути с папками ролей из настроек."""
        return dataclasses.replace(self, folders=folders)

    def dir(self, folder: DataDir) -> Path:
        """Папка роли: выбранная в настройках или имя роли в корне; `/` с абсолютным путём даёт его самого."""
        return self.root / self.folders.place(folder)

    def ensure_dirs(self) -> None:
        """Все папки данных, в том числе выбранные в настройках; файлы в них программа сама не создаёт: конфиги и сейф
        пишет настройщик (§8)."""
        for folder in DataDir:
            self.dir(folder).mkdir(parents=True, exist_ok=True)

    def file(self, name: FileName) -> Path:
        """Файл данных с этим именем в его папке — единственное правило «файл в папке данных»."""
        return self.dir(name.folder) / name.value

    def token_file(self, stem: str) -> Path:
        """secrets\\<stem>.token.json — токен входа владельца канала (§9); `stem` — имя файла без расширения."""
        return self.dir(DataDir.SECRETS) / TOKEN_FILE_TEMPLATE.format(stem=stem)

    def with_google_project(self, project: Path | None) -> LivecraftPaths:
        """Те же пути с файлом проекта Google из настроек."""
        return dataclasses.replace(self, google_project=project)

    @property
    def project_file(self) -> Path | None:
        """Файл проекта Google — тем же правилом, что папки ролей: относительный путь — от корня; не выбран — None."""
        return None if self.google_project is None else self.root / self.google_project

    def received_project_file(self, project: str) -> Path:
        """secrets\\google_project_<project>.json — куда ложится проект Google из токена доступа."""
        name: str = "".join((ProjectFileMark.PREFIX.value, project, ProjectFileMark.SUFFIX.value))
        return self.dir(DataDir.SECRETS) / name

    @property
    def found_project_files(self) -> tuple[Path, ...]:
        """Файлы google_project_*.json в secrets\\, кроме прежних (.previous.json), по имени."""
        found: list[Path] = sorted(self.dir(DataDir.SECRETS).glob(PROJECT_FILE_GLOB))
        return tuple(path for path in found if not path.name.endswith(PREVIOUS_PROJECT_ENDING))

    @property
    def logs_dir(self) -> Path:
        return self.dir(DataDir.LOGS)

    @property
    def bcast_dir(self) -> Path:
        return self.dir(DataDir.BCAST)

    def doc_copy_file(self, date: str, file_name: str) -> Path:
        """docs\\<DD-MM-YYYY>\\<имя файла> — копия документа объявлений на дату (§14 решение 33)."""
        return self.dir(DataDir.DOCS) / date / file_name

    def report_file(self, started: datetime) -> Path:
        """logs\\<DD-MM-YYYY>_<HHMMSS>_report.md — отчёт запуска; штамп — момент начала запуска, тот же, что у лога."""
        return self.logs_dir / REPORT_FILE_TEMPLATE.format(stamp=started.strftime(FILE_STAMP_FORMAT))

    def shown(self, path: Path) -> str:
        """Путь для людей — от корня программы, как человек видит папки рядом с ней; путь вне корня (папка, выбранная в
        настройках) — целиком."""
        return str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path)


class ReplaceFailure(str, Enum):
    """Почему готовый файл не встал на место цели."""

    TARGET_BUSY = "target_busy"     # Windows не меняет файл, открытый другим потоком или процессом


@dataclass(frozen=True)
class AtomicFile:
    """Файл, который пишется целиком или никак: временный файл рядом с целью, затем `os.replace`.

    Читатель видит либо прежний файл, либо новый целиком — недописанного не бывает. `prefix` — начало имени
    временного файла: по нему недописанное легко отличить от готового. На Windows замена цели, которую в этот миг
    читает другой поток или процесс (фоновая проверка окна читает сейф), — PermissionError: замена повторяется по
    короткой политике `REPLACE_RETRY_POLICY`, всего не дольше полутора секунд. Прочий сбой записи и занятость дольше
    этого — OSError; временный файл при любом исходе убирается. `rng` и `sleep` — паузы повторов, в тестах свои.
    """

    target: Path
    prefix: str
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def at(cls, target: Path) -> AtomicFile:
        """Временный файл называется от имени цели."""
        return cls(target=target, prefix=target.name)

    def write(self, fill: Callable[[Path], None]) -> None:
        """`fill` пишет содержимое во временный файл; готовый файл встаёт на место цели одним `os.replace`."""
        handle, temp_name = tempfile.mkstemp(prefix=self.prefix, suffix=TEMP_FILE_SUFFIX, dir=self.target.parent)
        os.close(handle)
        temp_path: Path = Path(temp_name)
        try:
            fill(temp_path)
            self._replace(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)       # после os.replace файла уже нет — ничего не делает

    def _replace(self, temp_path: Path) -> None:
        """Готовый файл — на место цели; цель занята дольше политики повторов — последняя PermissionError."""
        run: RetryRun[Path] = RetryLoop(REPLACE_RETRY_POLICY, self.rng, self.sleep).run(
            lambda: self._replaced(temp_path), lambda _step: None
        )
        if run.failure is not None and run.failure.cause is not None:
            raise run.failure.cause

    def _replaced(self, temp_path: Path) -> Path | AttemptFailure:
        """Одна замена: занятая цель — повторяемая неудача, прочий OSError уходит вызывающему как есть."""
        try:
            os.replace(temp_path, self.target)
        except PermissionError as busy:
            return AttemptFailure(ReplaceFailure.TARGET_BUSY, is_retryable=True, error_name=type(busy).__name__, cause=busy)
        return self.target

    def write_text(self, text: str, encoding: str) -> None:
        """Текст как есть: переводы строк не переводятся."""
        self.write(lambda path: path.write_text(text, encoding=encoding, newline=""))


def write_text_atomically(path: Path, text: str, encoding: str) -> None:
    """Текст файла целиком или никак (`AtomicFile`). Сбой — OSError."""
    AtomicFile.at(path).write_text(text, encoding)
