"""Правка livecraft.json в тесте — тем же загрузчиком, что пишет настройщик."""
from __future__ import annotations

import dataclasses

from app.config.loader import LivecraftSettings, load_settings, save_settings_file
from app.paths import LivecraftPaths


def set_form_url(paths: LivecraftPaths, url: str) -> None:
    """Ссылка на форму в livecraft.json корня `paths`."""
    settings: LivecraftSettings = load_settings(paths.config_file)
    save_settings_file(paths.config_file, dataclasses.replace(settings, form=dataclasses.replace(settings.form, url=url)))
