"""Фасад прежних имён ссылок (CLAUDE.md §11, перенос модуля): ссылка — объект `app\\core\\web_link.py::WebLink`.

Остаются только имена, которые ещё берут отсюда модули вне `app\\core` и `app\\texts`.
"""
from __future__ import annotations

from app.core.web_link import HTTPS_SCHEME, split_url

__all__ = ["HTTPS_SCHEME", "split_url"]
