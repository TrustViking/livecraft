"""Настройки пакета без диска: поставочные настройки, разобранные боевым загрузчиком, со своей ссылкой на форму."""
from __future__ import annotations

import dataclasses

from app.config.loader import LivecraftSettings, ShippedSettings
from app.ui import messages_ru as msg


def package_settings(form_url: str) -> LivecraftSettings:
    """Поставочные настройки со ссылкой на форму ключей `form_url`; пустая ссылка — форма не настроена."""
    shipped: LivecraftSettings = ShippedSettings(template=msg.CONFIG_SETTINGS_TEMPLATE).settings
    return dataclasses.replace(shipped, form=dataclasses.replace(shipped.form, url=form_url))
