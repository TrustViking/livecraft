from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import replace
from unittest.mock import patch

import pytest
from langdetect import DetectorFactory

from app.sources.language import (
    LanguageDecision,
    LanguageProfile,
    LanguageResolver,
    LanguageSignal,
    LanguageSource,
    TextLanguageDetector,
    normalize_language,
)
from app.sources.metadata import SourceMetadata

LINK: str = "https://youtu.be/aaaaaaaaaaa"
UKRAINIAN: str = "Сьогодні ввечері говоримо про новини економіки та політики України"
RUSSIAN: str = "Сегодня вечером говорим о новостях экономики и политики в нашей стране"
ENGLISH: str = "Tonight we talk about the latest news on the economy and politics"
DETECT_TARGET: str = "app.sources.language.detect"


@pytest.fixture(scope="module")
def detector() -> TextLanguageDetector:
    return TextLanguageDetector.from_resources()


@pytest.fixture(scope="module")
def resolver() -> LanguageResolver:
    return LanguageResolver.from_resources()


def metadata(
    *,
    title: str = "",
    description: str = "",
    youtube_language: str | None = None,
    channel_language: str | None = None,
    audio_languages: tuple[str, ...] = (),
    subtitle_languages: tuple[str, ...] = (),
    auto_caption_languages: tuple[str, ...] = (),
) -> SourceMetadata:
    return SourceMetadata(
        url=LINK,
        video_id="aaaaaaaaaaa",
        title=title,
        description=description,
        thumbnail_url="https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg",
        youtube_language=youtube_language,
        channel_language=channel_language,
        duration_seconds=None,
        audio_languages=audio_languages,
        subtitle_languages=subtitle_languages,
        auto_caption_languages=auto_caption_languages,
    )


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self, level: int) -> list[str]:
        return [record.getMessage() for record in self.records if record.levelno == level]


@pytest.fixture
def log() -> Iterator[_Collector]:
    logger: logging.Logger = logging.getLogger("livecraft.sources")
    collector: _Collector = _Collector()
    level: int = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    yield collector
    logger.removeHandler(collector)
    logger.setLevel(level)


# --- normalize_language: набор сверен с донором (restreamer app\core\language.py::normalize_language)


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
def test_normalize_language_follows_the_donor(raw: str | None, expected: str | None) -> None:
    assert normalize_language(raw) == expected


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
    assert replace(detector, min_length=5).detect("Hello there") is not None


def test_langdetect_refusal_is_none() -> None:
    text: str = "12345 67890 12345 67890 12345"             # цифры: langdetect не находит признаков
    assert TextLanguageDetector(service_hints=()).detect(text) is None


# --- LanguageProfile.of


def test_profile_normalizes_and_deduplicates_in_order(detector: TextLanguageDetector) -> None:
    source: SourceMetadata = metadata(
        youtube_language="fr-FR",
        channel_language="en-US",
        audio_languages=("fr", "fr-FR", "", "en", "fr"),
        subtitle_languages=("de-DE", "", "de"),
        auto_caption_languages=("en", "", "fr-FR"),
    )
    profile: LanguageProfile = LanguageProfile.of(source, detector)
    assert profile.video_language == "fr"
    assert profile.channel_language == "en"
    assert profile.audio_languages == ("fr", "en")
    assert profile.subtitle_languages == ("de",)
    assert profile.auto_caption_languages == ("en", "fr")
    assert profile.metadata_candidates == ("fr", "en")


def test_empty_metadata_gives_an_empty_profile(detector: TextLanguageDetector) -> None:
    profile: LanguageProfile = LanguageProfile.of(metadata(), detector)
    assert profile == LanguageProfile(video_language=None, channel_language=None)


def test_original_caption_key_is_the_audio_language(detector: TextLanguageDetector) -> None:
    source: SourceMetadata = metadata(auto_caption_languages=("ab", "aa", "uk-orig", "uk", "uk", "en"))
    profile: LanguageProfile = LanguageProfile.of(source, detector)
    assert profile.auto_caption_orig_language == "uk"
    assert profile.auto_caption_languages == ("ab", "aa", "uk", "en")


@pytest.mark.parametrize("keys", [(), ("ab", "en", "fr", "de")])
def test_no_original_caption_key_is_none(detector: TextLanguageDetector, keys: tuple[str, ...]) -> None:
    assert LanguageProfile.of(metadata(auto_caption_languages=keys), detector).auto_caption_orig_language is None


def test_title_description_and_both_are_detected_separately(detector: TextLanguageDetector) -> None:
    profile: LanguageProfile = LanguageProfile.of(metadata(title=ENGLISH, description=UKRAINIAN), detector)
    assert profile.title_language == "en"
    assert profile.description_language == "uk"
    assert profile.text_language in {"uk", "en"}


def test_detector_gets_title_description_and_joined_text(detector: TextLanguageDetector) -> None:
    seen: list[str] = []

    def fake_detect(text: str) -> str:
        seen.append(text)
        return "de"

    with patch(DETECT_TARGET, side_effect=fake_detect):
        profile: LanguageProfile = LanguageProfile.of(metadata(title=ENGLISH, description=RUSSIAN), detector)
    assert seen == [ENGLISH, RUSSIAN, f"{ENGLISH}\n{RUSSIAN}"]
    assert (profile.title_language, profile.description_language, profile.text_language) == ("de", "de", "de")


# --- LanguageProfile.decide: каждая ветка правила донора


def profile(**fields: object) -> LanguageProfile:
    base: dict[str, object] = {"video_language": None, "channel_language": None}
    return LanguageProfile(**(base | fields))   # type: ignore[arg-type]


def test_votes_are_the_five_signals_in_donor_order() -> None:
    subject: LanguageProfile = profile(
        video_language="uk", audio_languages=("ru", "en"), auto_caption_orig_language="uk",
        description_language="en", text_language="ru", title_language="de", subtitle_languages=("fr",),
    )
    assert subject.votes == {
        LanguageSignal.VIDEO_LANGUAGE: "uk",
        LanguageSignal.AUDIO_FIRST: "ru",
        LanguageSignal.AUTO_CAPTION_ORIG: "uk",
        LanguageSignal.DESCRIPTION_LANGUAGE: "en",
        LanguageSignal.LANGDETECT_TEXT: "ru",
    }
    assert list(subject.arbiter_votes) == [
        LanguageSignal.AUDIO_FIRST, LanguageSignal.AUTO_CAPTION_ORIG, LanguageSignal.DESCRIPTION_LANGUAGE
    ]


def test_consensus_of_three_signals() -> None:
    decision: LanguageDecision = profile(
        video_language="fr", audio_languages=("fr",), auto_caption_orig_language="fr", text_language="en"
    ).decide()
    assert (decision.language, decision.source, decision.is_conflict) == ("fr", LanguageSource.CONSENSUS, False)


def test_consensus_can_outvote_the_video_language() -> None:
    decision: LanguageDecision = profile(
        video_language="de", audio_languages=("en",), auto_caption_orig_language="en", text_language="en"
    ).decide()
    assert (decision.language, decision.source) == ("en", LanguageSource.CONSENSUS)


def test_three_votes_without_three_alike_are_not_a_consensus() -> None:
    decision: LanguageDecision = profile(video_language="uk", audio_languages=("uk",), text_language="ru").decide()
    assert decision.source is not LanguageSource.CONSENSUS


def test_langdetect_agrees_with_the_video_language() -> None:
    decision: LanguageDecision = profile(video_language="en", channel_language="en", text_language="en").decide()
    assert (decision.language, decision.source, decision.is_conflict) == (
        "en", LanguageSource.LANGDETECT_METADATA_AGREEMENT, False
    )


def test_arbiters_side_with_the_video_language() -> None:
    decision: LanguageDecision = profile(video_language="de", audio_languages=("de",), text_language="en").decide()
    assert (decision.language, decision.source, decision.is_conflict) == (
        "de", LanguageSource.METADATA_ARBITRATION, True
    )


def test_arbiters_side_with_langdetect() -> None:
    decision: LanguageDecision = profile(
        video_language="de", auto_caption_orig_language="en", text_language="en"
    ).decide()
    assert (decision.language, decision.source, decision.is_conflict) == (
        "en", LanguageSource.LANGDETECT_ARBITRATION, True
    )


def test_tie_of_arbiters_falls_back_to_the_video_language() -> None:
    decision: LanguageDecision = profile(
        video_language="uk", audio_languages=("uk",), description_language="ru", text_language="ru"
    ).decide()
    assert (decision.language, decision.source, decision.is_conflict) == (
        "uk", LanguageSource.METADATA_ARBITRATION_FALLBACK, True
    )


def test_arbiters_for_a_third_language_are_a_tie() -> None:
    decision: LanguageDecision = profile(video_language="uk", audio_languages=("en",), text_language="ru").decide()
    assert (decision.language, decision.source) == ("uk", LanguageSource.METADATA_ARBITRATION_FALLBACK)


def test_no_arbiters_falls_back_to_the_video_language() -> None:
    decision: LanguageDecision = profile(video_language="en", text_language="uk").decide()
    assert (decision.language, decision.source, decision.is_conflict) == (
        "en", LanguageSource.METADATA_ARBITRATION_FALLBACK, True
    )


def test_only_langdetect() -> None:
    decision: LanguageDecision = profile(channel_language="ru", text_language="de").decide()
    assert (decision.language, decision.source, decision.is_conflict) == ("de", LanguageSource.LANGDETECT, False)


def test_only_the_video_language() -> None:
    decision: LanguageDecision = profile(video_language="ru", description_language="en").decide()
    assert (decision.language, decision.source, decision.is_conflict) == (
        "ru", LanguageSource.METADATA_FALLBACK, False
    )


def test_channel_language_alone_does_not_decide() -> None:
    decision: LanguageDecision = profile(channel_language="uk", title_language="uk", subtitle_languages=("uk",)).decide()
    assert (decision.language, decision.source, decision.is_resolved) == (None, LanguageSource.UNDETECTED, False)


def test_nothing_is_undetected() -> None:
    decision: LanguageDecision = profile().decide()
    assert decision.language is None
    assert decision.source is LanguageSource.UNDETECTED
    assert not decision.is_conflict and not decision.is_resolved


def test_source_values_are_the_donor_values() -> None:
    assert {source.value for source in LanguageSource} == {
        "langdetect", "langdetect_metadata_agreement", "metadata_fallback", "undetected",
        "consensus", "metadata_arbitration", "langdetect_arbitration", "metadata_arbitration_fallback",
    }


# --- случаи донора (restreamer tests\test_language_policy.py) через весь путь с подменённым langdetect


def resolve_with(resolver: LanguageResolver, detected: str, source: SourceMetadata) -> LanguageDecision:
    with patch(DETECT_TARGET, return_value=detected):
        return resolver.resolve(source)


def test_donor_german_video_with_english_text_stays_german(resolver: LanguageResolver) -> None:
    source: SourceMetadata = metadata(
        title="Learn German with this easy lesson for beginners",
        description="In this video we practice everyday German conversations.",
        youtube_language="de",
        audio_languages=("de",),
        subtitle_languages=("en", "de"),
        auto_caption_languages=("ab", "aa", "de-orig", "de", "en"),
    )
    decision: LanguageDecision = resolve_with(resolver, "en", source)
    # видео, звук и «de-orig» — три голоса за de: консенсус; первые субтитры (en) не голосуют
    assert (decision.language, decision.source, decision.is_conflict) == ("de", LanguageSource.CONSENSUS, False)


def test_donor_conflict_without_arbiters_returns_metadata(resolver: LanguageResolver) -> None:
    source: SourceMetadata = metadata(title="English evidence review", youtube_language="ru", channel_language="ru")
    decision: LanguageDecision = resolve_with(resolver, "en", source)
    assert (decision.language, decision.source) == ("ru", LanguageSource.METADATA_ARBITRATION_FALLBACK)


def test_donor_dynamic_language_from_langdetect(resolver: LanguageResolver) -> None:
    source: SourceMetadata = metadata(
        title="Deutscher Titel", description="Deutscher Beschreibungstext fuer die Sendung"
    )
    decision: LanguageDecision = resolve_with(resolver, "de", source)
    assert (decision.language, decision.source) == ("de", LanguageSource.LANGDETECT)


def test_donor_metadata_fallback_with_empty_texts(resolver: LanguageResolver) -> None:
    decision: LanguageDecision = resolver.resolve(metadata(youtube_language="uk"))
    assert (decision.language, decision.source) == ("uk", LanguageSource.METADATA_FALLBACK)


def test_russian_text_with_a_ukrainian_word_is_russian(resolver: LanguageResolver) -> None:
    source: SourceMetadata = metadata(
        title="Обсуждение новостей",
        description=(
            "Сегодня обсуждаем экономику, политику и ситуацию вокруг слова Україна "
            "в контексте русскоязычного обсуждения в одном выпуске."
        ),
    )
    assert resolver.resolve(source).language == "ru"


# --- LanguageDecision.log_line и LanguageResolver: лог


def test_log_line_follows_the_donor_keys() -> None:
    decision: LanguageDecision = profile(
        video_language="uk", channel_language="ru", audio_languages=("uk", "en"), title_language="uk",
        text_language="ru",
    ).decide()
    assert decision.log_line == (
        "final_language=uk source=metadata_arbitration conflict=yes metadata_candidates=uk,ru "
        "langdetect=ru description_lang=none title_lang=uk audio_lang=uk auto_caption_orig=none"
    )


def test_undetected_log_line_says_unknown_and_none() -> None:
    assert profile().decide().log_line == (
        "final_language=unknown source=undetected conflict=no metadata_candidates=none "
        "langdetect=none description_lang=none title_lang=none audio_lang=none auto_caption_orig=none"
    )


def test_resolver_logs_info_for_a_decision(resolver: LanguageResolver, log: _Collector) -> None:
    decision: LanguageDecision = resolver.resolve(metadata(title=UKRAINIAN, youtube_language="uk"))
    assert decision.language == "uk"
    assert f"language_decision url={LINK} {decision.log_line}" in log.messages(logging.INFO)
    assert not log.messages(logging.WARNING)


def test_resolver_warns_when_undetected(resolver: LanguageResolver, log: _Collector) -> None:
    decision: LanguageDecision = resolver.resolve(metadata(title="Коротко"))
    assert not decision.is_resolved
    assert f"language_decision url={LINK} {decision.log_line}" in log.messages(logging.WARNING)
