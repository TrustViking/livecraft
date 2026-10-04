"""Тексты для людей (каталоги app\\ui\\messages_ru.py, messages_uk.py, messages_en.py, §14 решение 24).

Каталоги одинаковы по устройству: те же имена констант, ключи словарей и подстановки в каждой строке — иначе
модуль, который берёт `msg` другого языка, упадёт или покажет не то. Проверяются все строки каталога, которые видит
человек: строковые константы, строки кортежей и строковые значения словарей; ни одна не раскрывает значений сейфа и
его устройства (§7.4, §7.5). Образец таблицы плана каждого каталога узнаёт сам план.
"""
from __future__ import annotations

import re
import string
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest

from app.core.sheet_text import parse_sheet_datetime
from app.sheets.plan import PlanColumn, SheetColumns, SheetPlan
from app.tests.conftest import TOKEN_VALUES
from app.ui import messages_en, messages_ru, messages_uk
from app.ui.messages import CATALOGS

# Слова о внутреннем устройстве программы, которые человеку без знания кода ничего не говорят.
STORAGE_WORDS: tuple[str, ...] = ("сейф", "secrets\\vault")
CYRILLIC: re.Pattern[str] = re.compile("[\u0400-\u04ff]")
RUSSIAN_ONLY_LETTERS: re.Pattern[str] = re.compile("[ыэъё]", re.IGNORECASE)
TRANSLATIONS: tuple[ModuleType, ...] = (messages_uk, messages_en)
ZONE: ZoneInfo = ZoneInfo("Europe/Kyiv")
# Обращение к человеку на «вы» (§14 решение 28) — целым словом, без учёта регистра.
ADDRESS_WORDS: dict[str, re.Pattern[str]] = {
    messages_ru.__name__: re.compile(r"\b(?:вы|вас|вам|вами|ваш\w*)\b", re.IGNORECASE),
    messages_uk.__name__: re.compile(r"\b(?:ви|вас|вам|вами|ваш\w*)\b", re.IGNORECASE),
    messages_en.__name__: re.compile(r"\b(?:you|your|yours|yourself)\b", re.IGNORECASE),
}
# Подстановка — имя поля и формат; строка, которую Formatter не разбирает (шаблон JSON), — одна пометка на всех.
NOT_A_TEMPLATE: tuple[tuple[str, str], ...] = (("", "not a template"),)


def _human_texts(catalog: ModuleType) -> dict[str, str]:
    """Все строки каталога с адресом вида ИМЯ, ИМЯ[индекс] или ИМЯ[ключ]."""
    texts: dict[str, str] = {}
    for name, value in vars(catalog).items():
        if not name.isupper():
            continue
        if isinstance(value, str):
            texts[name] = value
        elif isinstance(value, tuple):
            texts.update({f"{name}[{index}]": item for index, item in enumerate(value) if isinstance(item, str)})
        elif isinstance(value, dict):
            texts.update({f"{name}[{key!r}]": item for key, item in value.items() if isinstance(item, str)})
    return texts


def _names(catalog: ModuleType) -> set[str]:
    return {name for name in vars(catalog) if name.isupper()}


def _placeholders(text: str) -> tuple[tuple[str, str], ...]:
    """Подстановки строки по порядку: имя поля и формат. Скобки примера JSON подстановками не считаются."""
    try:
        fields = [(name, spec or "") for _, name, spec, _ in string.Formatter().parse(text) if name is not None]
    except ValueError:
        return NOT_A_TEMPLATE
    return tuple(sorted(field for field in fields if field[0].isidentifier()))


def test_the_module_texts_are_collected() -> None:
    texts: dict[str, str] = _human_texts(messages_ru)
    assert "VAULT_TOKEN_UNREADABLE" in texts
    assert "CONFIG_CHANNELS_FIELDS[0]" in texts
    assert "SETUP_SETTINGS_FIELD_LABELS['timezone']" in texts


def test_every_language_has_its_catalog() -> None:
    assert set(CATALOGS.values()) == {messages_ru, messages_uk, messages_en}


@pytest.mark.parametrize("catalog", TRANSLATIONS)
def test_a_translation_has_the_same_names_keys_and_placeholders(catalog: ModuleType) -> None:
    assert _names(catalog) == _names(messages_ru)
    for name in _names(messages_ru):
        original: object = getattr(messages_ru, name)
        translated: object = getattr(catalog, name)
        assert type(translated) is type(original), name
        if isinstance(original, dict):
            assert list(translated) == list(original), name
        if isinstance(original, tuple):
            assert len(translated) == len(original), name
    translated_texts: dict[str, str] = _human_texts(catalog)
    for address, text in _human_texts(messages_ru).items():
        assert _placeholders(translated_texts[address]) == _placeholders(text), address


def test_english_values_have_no_cyrillic() -> None:
    for address, text in _human_texts(messages_en).items():
        assert not CYRILLIC.search(text), address


def test_ukrainian_values_have_no_russian_only_letters() -> None:
    for address, text in _human_texts(messages_uk).items():
        assert not RUSSIAN_ONLY_LETTERS.search(text), address


@pytest.mark.parametrize("catalog", TRANSLATIONS)
def test_the_joiners_are_the_same_in_every_catalog(catalog: ModuleType) -> None:
    """LIST_JOINER уходит и в промт merge, а промт от языка окна не зависит."""
    assert catalog.LIST_JOINER == messages_ru.LIST_JOINER
    assert catalog.ITEM_JOINER == messages_ru.ITEM_JOINER


@pytest.mark.parametrize("catalog", CATALOGS.values())
def test_the_plan_reads_the_table_sample_of_every_catalog(catalog: ModuleType) -> None:
    """Шапку образца из названий колонок каталога план узнаёт, а дату и время строки образца — разбирает."""
    header: list[str] = [catalog.SHEET_PLAN_COLUMN_NAMES[column.value] for column in PlanColumn]
    row: list[str] = [catalog.SETUP_TABLE_SAMPLE_ROW[column.value] for column in PlanColumn]
    plan: SheetPlan = SheetPlan.from_values("plan", 0, [header, row])
    assert plan.columns == SheetColumns(link=0, date=1, time=2)
    [sample] = plan.rows
    assert parse_sheet_datetime(sample.date_raw, sample.time_raw, ZONE).year == 2026


@pytest.mark.parametrize("catalog", CATALOGS.values())
def test_no_text_addresses_the_reader(catalog: ModuleType) -> None:
    """§14 решение 28: тексты безличные — ни одна строка каталога, включая значения словарей, не обращается на «вы»."""
    pattern: re.Pattern[str] = ADDRESS_WORDS[catalog.__name__]
    for address, text in _human_texts(catalog).items():
        assert not pattern.search(text), address


@pytest.mark.parametrize("catalog", CATALOGS.values())
def test_no_text_contains_a_supplied_value(catalog: ModuleType) -> None:
    """Ни пример, ни подсказка не совпадают с поставочным значением — даже с коротким диапазоном."""
    for name, text in _human_texts(catalog).items():
        for value in TOKEN_VALUES.values():
            assert value not in text, name


@pytest.mark.parametrize("catalog", CATALOGS.values())
def test_no_text_names_the_vault_or_its_files_path(catalog: ModuleType) -> None:
    for name, text in _human_texts(catalog).items():
        lowered: str = text.lower()
        for word in STORAGE_WORDS:
            assert word not in lowered, name


# §14 решение 40: картинка видео — «превью», картинка, которую программа ставит эфиру, — «обложка эфира». Слово обложки
# встречается только вместе с эфиром. Исключение — описание ключа потока в Студии YouTube: его хвост «заглушка обложки
# thumb0=…» пишет и planers, по нему следующий запуск узнаёт эфир без обложки (app\platforms\youtube_description.py).
COVER_WORDS: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    messages_ru.__name__: (re.compile(r"облож\w*", re.I), re.compile(r"облож\w* эфир\w*", re.I)),
    messages_uk.__name__: (re.compile(r"обкладин\w*", re.I), re.compile(r"обкладин\w* ефір\w*", re.I)),
    messages_en.__name__: (re.compile(r"thumbnails?", re.I), re.compile(r"broadcast thumbnails?", re.I)),
}
YOUTUBE_TEXTS: frozenset[str] = frozenset({"STREAM_DESCRIPTION_PLACEHOLDER"})


@pytest.mark.parametrize("catalog", CATALOGS.values())
def test_the_cover_is_always_the_broadcast_cover_and_the_video_picture_is_a_preview(catalog: ModuleType) -> None:
    word, broadcast_cover = COVER_WORDS[catalog.__name__]
    for address, text in _human_texts(catalog).items():
        if address in YOUTUBE_TEXTS:
            continue
        assert len(word.findall(text)) == len(broadcast_cover.findall(text)), address


@pytest.mark.parametrize("catalog", CATALOGS.values())
def test_the_changed_texts_of_the_window_review(catalog: ModuleType) -> None:
    """Смотр окна 29-09-2026: у каждой строки проблемы проверки — знак «✗»; пробный запуск не обещает ключей."""
    assert catalog.SETUP_FORM_NO_DATES.startswith(catalog.CHECK_MARK_PROBLEM)
    assert catalog.SETUP_FORM_TABLE_UNREAD.startswith(catalog.CHECK_MARK_PROBLEM)
    assert catalog.READINESS_RESEND_KEYS_DRY_RUN != catalog.READINESS_RESEND_KEYS_ON
    assert "@BotFather" in catalog.SETUP_TELEGRAM_STEP_1_TEXT
    assert catalog.CHECK_OK_LINE.format(line="x") == catalog.CHECK_MARK_OK + " x"
    assert catalog.CHECK_PROBLEM_LINE.format(line="x") == catalog.CHECK_MARK_PROBLEM + " x"


def test_the_russian_texts_of_the_window_review_are_the_agreed_ones() -> None:
    assert messages_ru.SETUP_HOME_HOWTO == (
        "Каждая строка ниже — подключение и настройка функции работы приложения. Знак ✗ обозначает необходимость "
        "настроить определённый функционал работы приложения."
    )
    assert messages_ru.SETUP_TELEGRAM_STEP_1_TEXT == (
        "Нет своего бота в Telegram — создайте его: найдите @BotFather, отправьте ему /newbot и придумайте имя — "
        "BotFather пришлёт токен. Вставьте токен бота сюда и нажмите «Сохранить»."
    )
    assert messages_ru.READINESS_RESEND_KEYS_DRY_RUN == "включена — в пробном запуске ключи не уходят"
    labels: dict[str, str] = messages_ru.SETUP_SETTINGS_FIELD_LABELS
    assert labels["image_dir_template"] == "шаблон подпапок превью"
    assert labels["drive.preview_path_template"] == "шаблон подпапок превью на Google Диске"
