from __future__ import annotations

import pytest
from langdetect import DetectorFactory

from app.texts.language_detector import LanguageSpellings, TextLanguageDetector, normalize_language
from app.texts.phrase_lexicon import PhraseLexicon, ServiceHints

UKRAINIAN: str = "Сьогодні ввечері говоримо про новини економіки та політики України"
RUSSIAN: str = "Сегодня вечером говорим о новостях экономики и политики в нашей стране"
ENGLISH: str = "Tonight we talk about the latest news on the economy and politics"


@pytest.fixture(scope="module")
def detector() -> TextLanguageDetector:
    return TextLanguageDetector.from_resources()


# --- normalize_language: известное написание, вид «xx» / «xx-yy», известное начало


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None), (None, None), ("   ", None),
        ("ua", "uk"), ("UK", "uk"), ("ukr", "uk"), ("uk-UA", "uk"), ("ukrainian", "uk"),
        ("en_US", "en"), ("eng", "en"), (" En ", "en"), ("english", "en"),
        ("rus", "ru"), ("ru-RU", "ru"), ("Russian", "ru"),
        ("fr", "fr"), ("de-DE", "de"), ("pt-BR", "pt"), ("iw", "iw"), ("uk-orig", "uk"),
        ("zh-Hans", None), ("es-419", None), ("a", None), ("abcd", None), ("x1", None),
    ],
)
def test_normalize_language_gives_the_iso_code_or_none(raw: str | None, expected: str | None) -> None:
    assert normalize_language(raw) == expected


def test_spellings_and_prefixes_are_data_of_the_resources() -> None:
    """Написания и начала кода — ресурсы программы, а не код: «ua» → «uk», начало «ua…» → «uk»."""
    spellings: LanguageSpellings = LanguageSpellings.load()
    assert spellings.aliases == {"ua": "uk", "uk": "uk", "ukr": "uk", "en": "en", "eng": "en", "ru": "ru", "rus": "ru"}
    assert spellings.prefixes == (("uk", "uk"), ("ua", "uk"), ("en", "en"), ("ru", "ru"))
    assert spellings.prefixed("ukrainian") == "uk" and spellings.prefixed("french") is None
    assert LanguageSpellings.load() is spellings                       # файлы читаются один раз за процесс


# --- TextLanguageDetector: настоящий langdetect


@pytest.mark.parametrize(("text", "expected"), [(UKRAINIAN, "uk"), (RUSSIAN, "ru"), (ENGLISH, "en")])
def test_detector_names_the_language_of_a_long_text(
    detector: TextLanguageDetector, text: str, expected: str
) -> None:
    assert detector.detect(text) == expected


def test_detector_answers_the_same_every_time(detector: TextLanguageDetector) -> None:
    assert {detector.detect(UKRAINIAN) for _ in range(5)} == {"uk"}
    assert DetectorFactory.seed == 0


@pytest.mark.parametrize("text", ["", "Коротко о главном", "https://a.example/x #тег #tag https://b.example"])
def test_short_or_empty_after_cleaning_is_none(detector: TextLanguageDetector, text: str) -> None:
    assert detector.detect(text) is None


def test_links_and_hashtags_do_not_count_toward_the_length(detector: TextLanguageDetector) -> None:
    assert detector.detect("Новини дня https://example.org/very/long/path/to/page #новини #economy") is None


def test_threshold_is_a_field(detector: TextLanguageDetector) -> None:
    assert detector.min_length == 20
    assert TextLanguageDetector(service_hints=detector.service_hints, min_length=5).detect("Hello there") is not None


def test_langdetect_refusal_is_none() -> None:
    text: str = "12345 67890 12345 67890 12345"             # цифры: langdetect не находит признаков
    assert TextLanguageDetector(service_hints=ServiceHints(PhraseLexicon(()))).detect(text) is None
