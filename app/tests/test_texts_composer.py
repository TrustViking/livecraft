"""Сборка описания после санации и заголовки блоков (донор: test_heading_resolver.py, description_composer.py)."""
from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from app.resources.loader import TextResource
from app.tests.conftest import LogCollector
from app.texts.composer import HEADINGS_RESOURCE, DescriptionParts, HeadingKind, PublishHeadings

HEADINGS: PublishHeadings = PublishHeadings.load()
# `_HARDCODED_SEED` restreamer `app\resources\heading_resolver.py` (35324e5) — строки без правки.
DONOR_SEED: dict[str, dict[str, str]] = {
    "official_links": {"uk": "🌐 Офіційні ресурси:", "en": "🌐 Official links:", "ru": "🌐 Официальные ссылки:"},
    "recommended_materials": {
        "uk": "Рекомендовані матеріали:",
        "en": "Recommended materials:",
        "ru": "Рекомендуемые материалы:",
    },
}


@pytest.fixture
def texts_log() -> Iterator[LogCollector]:
    collector: LogCollector = LogCollector()
    logger: logging.Logger = logging.getLogger("livecraft.texts")
    logger.addHandler(collector)
    previous: int = logger.level
    logger.setLevel(logging.DEBUG)
    yield collector
    logger.setLevel(previous)
    logger.removeHandler(collector)


# --- заголовки


def test_headings_resource_is_the_donor_seed() -> None:
    assert {kind: dict(values) for kind, values in TextResource(HEADINGS_RESOURCE).data.items()} == DONOR_SEED


@pytest.mark.parametrize(("language", "expected"), [("uk", "🌐 Офіційні ресурси:"), ("en", "🌐 Official links:"),
                                                   ("ru", "🌐 Официальные ссылки:"), (" RU ", "🌐 Официальные ссылки:")])
def test_seeded_languages_have_their_headings(language: str, expected: str) -> None:
    assert HEADINGS.official_links(language) == expected


@pytest.mark.parametrize("language", ["unknown", "other", "", "xx", "und", "none"])
def test_service_language_codes_give_english_silently(language: str, texts_log: LogCollector) -> None:
    assert HEADINGS.official_links(language) == "🌐 Official links:"
    assert HEADINGS.recommended_materials(language) == "Recommended materials:"
    assert texts_log.messages() == []


@pytest.mark.parametrize("language", ["ru-RU", "english", "12"])
def test_malformed_language_codes_give_english_with_a_warning(language: str, texts_log: LogCollector) -> None:
    assert HEADINGS.official_links(language) == "🌐 Official links:"
    assert texts_log.messages(logging.WARNING) == [
        f"heading_cache_invalid_language_format kind=official_links language={language!r}"
    ]


def test_a_language_outside_the_file_gives_english_and_a_log_line(texts_log: LogCollector) -> None:
    assert HEADINGS.resolve(HeadingKind.RECOMMENDED_MATERIALS, "de") == "Recommended materials:"
    assert texts_log.messages() == ["heading_fallback_en kind=recommended_materials language=de"]


# --- раскладка и сборка


def test_layout_names_the_parts_in_donor_order() -> None:
    parts: DescriptionParts = DescriptionParts(
        body="Body.", hashtags_line="#a", recommended_urls=("https://youtu.be/aaaaaaaaaaa",),
        official_urls=("https://example.org",), cta="Join us.",
    )
    assert parts.layout == "body_blank_recommended_materials_blank_official_links_blank_cta_blank_hashtags"
    assert DescriptionParts(body="").layout == "empty"
    assert DescriptionParts(body="", hashtags_line="#a").layout == "blank_hashtags"


def test_compose_joins_the_blocks_with_blank_lines() -> None:
    parts: DescriptionParts = DescriptionParts(
        body=" Body paragraph. ",
        hashtags_line="#nano #micro",
        official_urls=("https://www.example.org/official", " ", "https://t.me/channel/1?utm_source=x"),
    )
    assert parts.compose("en", HEADINGS) == (
        "Body paragraph.\n\n🌐 Official links:\nhttps://example.org\nhttps://t.me/channel/1\n\n#nano #micro"
    )
    assert parts.compose("uk", HEADINGS).count("🌐 Офіційні ресурси:") == 1


def test_recommended_videos_are_drawn_as_links_until_titles_arrive(texts_log: LogCollector) -> None:
    parts: DescriptionParts = DescriptionParts(body="Body.", recommended_urls=("https://youtu.be/aaaaaaaaaaa", " "))
    assert parts.compose("ru", HEADINGS) == "Body.\n\nРекомендуемые материалы:\n\n👉 https://youtu.be/aaaaaaaaaaa"
    assert texts_log.messages() == [
        "recommended_block_rendered_with_titles urls=1 titles_rendered=0 title_fetch_failures=1"
    ]


def test_compose_of_nothing_is_empty() -> None:
    assert DescriptionParts(body="").compose("en", HEADINGS) == ""
