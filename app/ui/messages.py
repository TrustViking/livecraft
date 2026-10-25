"""Каталог текстов для людей на языке этого процесса (CLAUDE.md §11, §14 решение 24).

Модули продукта берут тексты отсюда: `from app.ui.messages import msg`. Язык выбирается один раз, при первом
импорте (`UiLanguage.current`), и один на весь запуск — окно настройщика и консоль говорят на одном языке.
Каталоги подключены явными импортами, чтобы сборка взяла все три. Модуль ничего не печатает и в лог не пишет.
"""
from __future__ import annotations

from types import ModuleType
from typing import Final

from app.ui import messages_en, messages_ru, messages_uk
from app.ui.language import UiLanguage

CATALOGS: Final[dict[UiLanguage, ModuleType]] = {
    UiLanguage.RU: messages_ru,
    UiLanguage.UK: messages_uk,
    UiLanguage.EN: messages_en,
}
UI_LANGUAGE: Final[UiLanguage] = UiLanguage.current()
msg: Final[ModuleType] = CATALOGS[UI_LANGUAGE]
