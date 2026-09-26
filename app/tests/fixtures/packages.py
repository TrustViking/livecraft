"""Настройки пакета без диска: поставочные настройки, разобранные боевым разбором, со своей ссылкой на форму."""
from __future__ import annotations

from app.config.files import ShippedSettings
from app.config.settings import LivecraftSettings
from app.tests.fixtures.settings import with_form_url


def package_settings(form_url: str) -> LivecraftSettings:
    """Поставочные настройки со ссылкой на форму ключей `form_url`; пустая ссылка — форма не настроена."""
    return with_form_url(ShippedSettings().settings, form_url)
