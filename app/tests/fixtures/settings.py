"""Правка livecraft.json в тесте — тем же файлом настроек, что пишет настройщик; настройки со своими полями; папка
материалов на Google Диске — в сейфе (§14 решение 39)."""
from __future__ import annotations

import dataclasses

from app.config.docs import DocsSettings
from app.config.files import SettingsFile
from app.config.folders import FolderSettings
from app.config.lines import LineSettings
from app.config.settings import FormSettings, LivecraftSettings
from app.paths import LivecraftPaths
from app.run.mode import LINE_ORDER, RunPart
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.fields.secret_input import SecretInput

DRIVE_FOLDER_ID: str = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123-_"
DRIVE_FOLDER_URL: str = f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}?usp=sharing"


def with_form_url(settings: LivecraftSettings, url: str) -> LivecraftSettings:
    """Те же настройки со ссылкой на форму `url`."""
    return dataclasses.replace(settings, form=dataclasses.replace(settings.form, url=url))


def with_form(settings: LivecraftSettings, form: FormSettings) -> LivecraftSettings:
    """Те же настройки с другим разделом формы."""
    return dataclasses.replace(settings, form=form)


def set_form_url(paths: LivecraftPaths, url: str) -> None:
    """Ссылка на форму в livecraft.json корня `paths`."""
    file: SettingsFile = SettingsFile.of(paths)
    file.save(with_form_url(file.load(), url))


def drive_vault(folder_id: str = DRIVE_FOLDER_ID) -> Vault:
    """Сейф, в котором задана только папка материалов на Google Диске (§14 решение 39)."""
    return Vault.empty().with_field(
        SecretField.DRIVE_FOLDER, SecretValue(field=SecretField.DRIVE_FOLDER, value=folder_id), VaultOrigin.OWN
    )


def set_drive_folder(paths: LivecraftPaths, link: str = DRIVE_FOLDER_URL) -> None:
    """Папка материалов в личном сейфе корня `paths` — тем же правилом поля, что у окна (ссылка → id); пустая строка —
    поле убрано. Остальные свои значения сейфа остаются."""
    store: VaultStore = VaultStore.open(paths)
    own: Vault = store.load_for_setup().own.without_field(SecretField.DRIVE_FOLDER)
    secret: SecretValue | None = SecretInput(field=SecretField.DRIVE_FOLDER, raw=link).secret
    store.save_local(own if secret is None else own.with_field(SecretField.DRIVE_FOLDER, secret, VaultOrigin.OWN))


def with_docs(settings: LivecraftSettings, docs: DocsSettings) -> LivecraftSettings:
    """Те же настройки с другим разделом документа объявлений."""
    return dataclasses.replace(settings, docs=docs)


def set_contacts(paths: LivecraftPaths, contacts: str) -> None:
    """Контакты для стримеров в документе объявлений — в livecraft.json корня `paths`."""
    file: SettingsFile = SettingsFile.of(paths)
    settings: LivecraftSettings = file.load()
    file.save(with_docs(settings, dataclasses.replace(settings.docs, contacts=contacts)))


def lines_on(*parts: RunPart) -> LineSettings:
    """Раздел lines, в котором включены только линии `parts`."""
    return LineSettings(**{part.value: part in parts for part in LINE_ORDER})


def lines_without(*parts: RunPart) -> LineSettings:
    """Раздел lines, в котором выключены только линии `parts`."""
    return lines_on(*(part for part in LINE_ORDER if part not in parts))


def set_lines(paths: LivecraftPaths, lines: LineSettings) -> None:
    """Раздел lines в livecraft.json корня `paths`."""
    file: SettingsFile = SettingsFile.of(paths)
    file.save(dataclasses.replace(file.load(), lines=lines))


def set_folders(paths: LivecraftPaths, folders: FolderSettings) -> None:
    """Раздел folders в livecraft.json корня `paths`."""
    file: SettingsFile = SettingsFile.of(paths)
    file.save(dataclasses.replace(file.load(), folders=folders))
