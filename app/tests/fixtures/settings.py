"""Правка livecraft.json в тесте — тем же файлом настроек, что пишет настройщик; настройки со своими полями."""
from __future__ import annotations

import dataclasses

from app.config.files import SettingsFile
from app.config.settings import FormSettings, LivecraftSettings
from app.paths import LivecraftPaths


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
