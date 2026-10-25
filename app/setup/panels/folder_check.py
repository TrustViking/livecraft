"""Папка Google Диска на вкладке «Превью» или «Google-документ» без окна: проверка (CLAUDE.md §8.2 пп. 4, 5, §14 решения
27, 39, 60).

`FolderCheck` проверяет одну папку — свою (`field`: папка превью или папка документов объявлений, у каждой вкладки своя
проверка): берёт её из сейфа этой установки и спрашивает Диск тем же клиентом и той же точкой раскрытия id, что
и запуск (`DriveTarget.check`): как называется папка, папка ли это и может ли программа добавлять в неё файлы. Итог —
`FolderVerdict`: строка для окна. Проверка идёт в фоновом потоке окна: модель не знает ни потоков, ни Tk; «открылся
браузер» она сообщает тем, кого ей дали (`on_login`). Значений сейфа в строках нет: название папки и причина.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.config.files import SettingsFile
from app.google.auth import GoogleLogin
from app.google.drive import DriveClient, DriveError, DriveFolder
from app.intake.preview_stage import DriveTarget
from app.paths import LivecraftPaths
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.field import SecretField
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
    """Проверка папки Диска `field` этой установки: сейф — с диска, Диск — клиентом `open_drive` (в программе — вход
    оператора и Drive, в тестах — подделка)."""

    paths: LivecraftPaths
    field: SecretField
    open_drive: DriveSource

    @classmethod
    def of(cls, paths: LivecraftPaths, field: SecretField) -> FolderCheck:
        """Боевая проверка папки `field`: вход оператора этой установки (обе папки пишет он, §9) через проект Google из
        настроек, как они на диске в момент проверки (его могли выбрать в этом же окне); браузер — только если входа
        ещё не было."""
        return cls(paths=paths, field=field, open_drive=lambda on_login: DriveClient.open(
            GoogleLogin.operator(SettingsFile.placed(paths)), on_login=on_login
        ))

    def run(self, on_login: Callable[[], None]) -> FolderVerdict:
        """Спросить Диск о папке и сказать, годится ли она; сейф не прочитан, папка не задана или Диск не ответил —
        строка с причиной."""
        try:
            target: DriveTarget = DriveTarget.from_vault(VaultStore.open(self.paths).load().vault, self.field)
            folder: DriveFolder = target.check(self.open_drive(on_login))
        except (VaultFormatError, DriveError) as error:
            return FolderVerdict.failed(error.human)
        return FolderVerdict.of_folder(folder)
