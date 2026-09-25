from __future__ import annotations

import pytest

from app.llm.merges.service_lines import (
    LANGUAGE_HINTS_RESOURCE,
    ServiceLanguage,
    ServiceLineCatalog,
    ServiceLineKey,
)
from app.resources.loader import TextResource
from app.sources.language import TextLanguageDetector

CATALOG: ServiceLineCatalog = ServiceLineCatalog.load()
SERVICE: ServiceLanguage = ServiceLanguage.load()

# Списки донора `quality_service_lines.py` (restreamer 35324e5) — те же значения и порядок.
DONOR_HINTS: dict[str, tuple[str, ...]] = {
    "uk_phrases": ("у цьому стрімі", "офіційні ресурси", "дивіться ефір", "діліться думками"),
    "ru_phrases": ("в этом стриме", "официальные ссылки", "смотрите эфир", "делитесь мнением"),
    "en_phrases": ("in this stream", "official links", "watch the stream", "share your thoughts"),
    "uk_words": (" це ", " про ", " у ", " та ", " ефір", " стрімі"),
    "ru_words": (" это ", " про ", " эфир", " стриме", " этом "),
}


def test_hint_file_keeps_donor_values_and_order() -> None:
    for key, expected in DONOR_HINTS.items():
        assert getattr(SERVICE, key) == expected
    assert "restreamer" in TextResource(LANGUAGE_HINTS_RESOURCE).data["source"]


def test_catalog_is_the_donor_file() -> None:
    assert CATALOG.line("uk", ServiceLineKey.LEAD_IN) == "У цьому стрімі ви побачите:"
    assert CATALOG.line("ru", ServiceLineKey.LINKS_HEADING) == "🌐 Официальные ссылки:"
    assert CATALOG.line("en", ServiceLineKey.CTA) == "Watch the stream and share your thoughts."
    assert set(CATALOG.lines) == {"uk", "en", "ru", "other"}


def test_unknown_language_falls_back_to_other() -> None:
    assert CATALOG.line("de", ServiceLineKey.LINKS_HEADING) == CATALOG.line("other", ServiceLineKey.LINKS_HEADING)


def test_cta_replacement_keeps_hashtags() -> None:
    assert CATALOG.cta_preserving_hashtags("Watch it #one and #two", "uk") == "Дивіться ефір і діліться думками. #one #two"
    assert CATALOG.cta_preserving_hashtags("Watch it", "ru") == "Смотрите эфир и делитесь мнением."


def test_catalog_skips_non_objects_and_rejects_missing_keys() -> None:
    lines: dict[str, str] = {"lead_in": "L", "links_heading": "H", "cta": "C"}
    catalog: ServiceLineCatalog = ServiceLineCatalog.from_data({"other": lines, "comment": "text"})
    assert set(catalog.lines) == {"other"}
    with pytest.raises(ValueError):
        ServiceLineCatalog.from_data({"other": {"lead_in": "L"}})
    with pytest.raises(ValueError):
        ServiceLineCatalog.from_data({"uk": lines})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "none"),
        ("   ", "none"),
        ("In this STREAM you'll see:", "en"),
        ("Офіційні ресурси", "uk"),
        ("Смотрите эфир", "ru"),
        ("Їжа", "uk"),
        ("Объём", "ru"),
        ("Слово про нас", "uk"),
        ("Он сказал это вслух", "ru"),
        ("Hi", "unknown"),
        ("The government announced a new budget for the regions today", "en"),
    ],
)
def test_detect_service(text: str, expected: str) -> None:
    assert SERVICE.detect_service(text) == expected


def test_detect_paragraph_needs_twelve_chars() -> None:
    assert SERVICE.detect_paragraph("Коротко  їх") == "none"
    assert SERVICE.detect_paragraph("Коротко про їжу") == "uk"


def test_langdetect_undecided_is_unknown() -> None:
    silent: ServiceLanguage = ServiceLanguage.load(TextLanguageDetector(service_hints=(), min_length=10_000))
    assert silent.detect_service("The government announced a new budget") == "unknown"


@pytest.mark.parametrize(
    ("detected", "expected", "wrong"),
    [("en", "uk", True), ("uk", "uk", False), ("unknown", "uk", False), ("none", "ru", False),
     ("other", "en", False), ("en", "de", False), ("ru", "en", True)],
)
def test_is_wrong(detected: str, expected: str, wrong: bool) -> None:
    assert ServiceLanguage.is_wrong(detected, expected) is wrong


def test_short_service_line_is_at_most_140_chars() -> None:
    assert ServiceLanguage.is_short_service_line("a" * 140) is True
    assert ServiceLanguage.is_short_service_line("a" * 141) is False
    assert ServiceLanguage.is_short_service_line(" a  b " * 35) is True       # пробелы схлопываются: 139 знаков
    assert ServiceLanguage.is_short_service_line(" a  b " * 36) is False
