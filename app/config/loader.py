"""Фасад конфигов для модулей, которые ещё берут имена отсюда (CLAUDE.md §11, перенос модуля).

Конфиги живут в `json_node.py` (узел JSON, путь ключа, ошибка), `settings.py` (livecraft.json), `channel.py`
(channels.json) и `files.py` (файлы на диске). Имена разделов livecraft.json выводятся из `SettingKey`.
"""
from __future__ import annotations

from typing import Final

from app.config.json_node import SettingProblem
from app.config.settings import FormSettings, LivecraftSettings, LlmSettings, ReasoningEffort, ServiceTier, SettingKey

LLM_KEY: Final[str] = SettingKey.LLM.leaf
FORM_KEY: Final[str] = SettingKey.FORM.leaf
FORM_URL_KEY: Final[str] = SettingKey.FORM_URL.leaf

__all__ = [
    "FORM_KEY",
    "FORM_URL_KEY",
    "LLM_KEY",
    "FormSettings",
    "LivecraftSettings",
    "LlmSettings",
    "ReasoningEffort",
    "ServiceTier",
    "SettingProblem",
]
