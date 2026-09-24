"""Тексты для человека (app\\ui\\messages_ru.py) не раскрывают значений сейфа и его устройства (§7.4, §7.5).

Проверяются все строки модуля, которые видит человек: строковые константы, строки кортежей и строковые
значения словарей. Консольных строк «только для разработчика» в модуле нет — поэтому и исключений нет.
"""
from __future__ import annotations

from app.tests.conftest import SUPPLIED_VALUES
from app.ui import messages_ru as msg

# Слова о внутреннем устройстве программы, которые человеку без знания кода ничего не говорят.
STORAGE_WORDS: tuple[str, ...] = ("сейф", "secrets\\vault")


def _human_texts() -> dict[str, str]:
    """Все строки модуля с адресом вида ИМЯ, ИМЯ[индекс] или ИМЯ[ключ]."""
    texts: dict[str, str] = {}
    for name, value in vars(msg).items():
        if not name.isupper():
            continue
        if isinstance(value, str):
            texts[name] = value
        elif isinstance(value, tuple):
            texts.update({f"{name}[{index}]": item for index, item in enumerate(value) if isinstance(item, str)})
        elif isinstance(value, dict):
            texts.update({f"{name}[{key!r}]": item for key, item in value.items() if isinstance(item, str)})
    return texts


def test_the_module_texts_are_collected() -> None:
    texts: dict[str, str] = _human_texts()
    assert "VAULT_NOT_READY" in texts
    assert "CONFIG_CHANNELS_FIELDS[0]" in texts
    assert "SETUP_SETTINGS_FIELD_LABELS['timezone']" in texts


def test_no_text_contains_a_supplied_value() -> None:
    """Ни пример, ни подсказка не совпадают с поставочным значением — даже с коротким диапазоном."""
    for name, text in _human_texts().items():
        for value in SUPPLIED_VALUES.values():
            assert value not in text, name


def test_no_text_names_the_vault_or_its_files_path() -> None:
    for name, text in _human_texts().items():
        lowered: str = text.lower()
        for word in STORAGE_WORDS:
            assert word not in lowered, name
