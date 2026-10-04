"""Папка материалов на Google Диске на вкладках «Превью» и «Google-документ» без окна: проверка (CLAUDE.md §8.2 п.2,
§14 решения 27, 39).

`FolderCheck` берёт папку из сейфа этой установки и спрашивает Диск тем же клиентом и той же точкой раскрытия id, что
и запуск (`DriveTarget.check`): как называется папка, папка ли это и может ли программа добавлять в неё файлы. Итог —
`FolderVerdict`: строка для окна. Проверка идёт в фоновом потоке окна: модель не знает ни потоков, ни Tk; «открылся
браузер» она сообщает тем, кого ей дали (`on_login`). Значений сейфа в строках нет: название папки и причина.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.google.auth import GoogleLogin
from app.google.drive import DriveClient, DriveError, DriveFolder
from app.intake.preview_stage import DriveTarget
from app.paths import LivecraftPaths
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultStore
from app.ui.messages import msg

# Клиент Диска по входу оператора; аргумент — что сделать, когда для входа открывается браузер.
DriveSource = Callable[[Callable[[], None]], DriveClient]


@dataclass(frozen=True)
class FolderVerdict:
    """Итог проверки папки: годится ли она и строка для окна."""

    is_ok: bool
    text: str

    @classmethod
    def failed(cls, problem: str) -> FolderVerdict:
        return cls(is_ok=False, text=msg.SETUP_FOLDER_FAILED.format(problem=problem))

    @classmethod
    def of_folder(cls, folder: DriveFolder) -> FolderVerdict:
        """Не папка или добавлять в неё нельзя — отказ с названием; иначе — годится."""
        if not folder.is_folder:
            return cls.failed(msg.SETUP_FOLDER_NOT_FOLDER.format(name=folder.name))
        if not folder.can_add_files:
            return cls.failed(msg.SETUP_FOLDER_READ_ONLY.format(name=folder.name))
        return cls(is_ok=True, text=msg.SETUP_FOLDER_OK.format(name=folder.name))


@dataclass(frozen=True)
class FolderCheck:
    """Проверка папки материалов этой установки: сейф — с диска, Диск — клиентом `open_drive` (в программе — вход
    оператора и Drive, в тестах — подделка)."""

    paths: LivecraftPaths
    open_drive: DriveSource

    @classmethod
    def of(cls, paths: LivecraftPaths) -> FolderCheck:
        """Боевая проверка: вход оператора этой установки; браузер — только если входа ещё не было."""
        login: GoogleLogin = GoogleLogin.operator(paths)
        return cls(paths=paths, open_drive=lambda on_login: DriveClient.open(login, on_login=on_login))

    def run(self, on_login: Callable[[], None]) -> FolderVerdict:
        """Спросить Диск о папке и сказать, годится ли она; сейф не прочитан, папка не задана или Диск не ответил —
        строка с причиной."""
        try:
            target: DriveTarget = DriveTarget.from_vault(VaultStore.open(self.paths).load().vault)
            folder: DriveFolder = target.check(self.open_drive(on_login))
        except (VaultFormatError, DriveError) as error:
            return FolderVerdict.failed(error.human)
        return FolderVerdict.of_folder(folder)
