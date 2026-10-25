"""Правка livecraft.json в тесте — тем же файлом настроек, что пишет настройщик; настройки со своими полями; папки
Google Диска для превью и для документов — в сейфе (§14 решения 39, 60)."""
from __future__ import annotations

import dataclasses

from app.config.docs import DocsSettings
from app.config.files import SettingsFile
from app.config.folders import FolderSettings
from app.config.lines import LineSettings
from app.config.settings import FormSettings, LivecraftSettings
from app.config.telegram import TelegramSettings
from app.paths import LivecraftPaths
from app.run.mode import LINE_ORDER, RunPart
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.fields.secret_input import SecretInput

DRIVE_FOLDER_ID: str = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123-_"
DRIVE_FOLDER_URL: str = f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}?usp=sharing"
# Обе папки Google Диска (§14 решение 60): у установки, где задана «папка Диска», — одна и та же в обоих полях.
DRIVE_FOLDER_FIELDS: tuple[SecretField, ...] = (SecretField.DRIVE_PREVIEWS_FOLDER, SecretField.DRIVE_DOCS_FOLDER)


def with_telegram(settings: LivecraftSettings, telegram: TelegramSettings) -> LivecraftSettings:
    """Те же настройки с другим разделом `telegram` — так его пишут вкладка «Telegram» и перенос чата."""
    return dataclasses.replace(settings, telegram=telegram)


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


def drive_vault(folder_id: str = DRIVE_FOLDER_ID, fields: tuple[SecretField, ...] = DRIVE_FOLDER_FIELDS) -> Vault:
    """Сейф, в котором заданы только папки Google Диска `fields` (по умолчанию обе) с id `folder_id`."""
    vault: Vault = Vault.empty()
    for field in fields:
        vault = vault.with_field(field, SecretValue(field=field, value=folder_id), VaultOrigin.OWN)
    return vault


def set_drive_folder(
    paths: LivecraftPaths, link: str = DRIVE_FOLDER_URL, fields: tuple[SecretField, ...] = DRIVE_FOLDER_FIELDS
) -> None:
    """Папки Диска `fields` (по умолчанию обе) в личном сейфе корня `paths` — тем же правилом поля, что у окна (ссылка →
    id); пустая строка — поля убраны. Остальные свои значения сейфа остаются."""
    store: VaultStore = VaultStore.open(paths)
    own: Vault = store.load_for_setup().own
    for field in fields:
        own = own.without_field(field)
        secret: SecretValue | None = SecretInput(field=field, raw=link).secret
        own = own if secret is None else own.with_field(field, secret, VaultOrigin.OWN)
    store.save_local(own)


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
