"""Язык источника по данным видео (CLAUDE.md §3 шаг 2.3, §14 решение 12; §2: `core\\language*.py` restreamer).

Колонку языка таблицы программа не читает: язык решается один раз по тому, что yt-dlp сказал о видео,
и дальше переходит в слот. Правила перенесены из restreamer без изменений:

- `normalize_language` — код языка из сырого значения (`ua` → `uk`, `en-US` → `en`);
- `TextLanguageDetector` — langdetect по тексту, очищенному от ссылок, хештегов и служебного хвоста;
- `LanguageProfile` — все сигналы языка одного видео; `decide` — голосование донора `resolve_language`
  с тем же порядком приоритетов;
- `LanguageResolver` — точка входа: данные видео → решение и строка лога.

Не определился язык — решение с `language=None`; такой источник дальше по конвейеру не идёт (§0).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Final

from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

from app.observability.logging_setup import get_logger
from app.resources.loader import TextResource
from app.sources.metadata import SourceMetadata
from app.texts.analysis_text import clean_text_for_analysis

LOGGER_NAME: Final[str] = "sources"
LOGGER = get_logger(LOGGER_NAME)

SERVICE_HINTS_RESOURCE: Final[str] = "merge_service_hints.txt"
DETECTOR_SEED: Final[int] = 0              # langdetect без сида отвечает по-разному на один текст
MIN_DETECT_LENGTH: Final[int] = 20         # короче — langdetect гадает (порог донора)
CONSENSUS_VOTES: Final[int] = 3
ORIGINAL_CAPTION_SUFFIX: Final[str] = "-orig"   # YouTube так помечает автосубтитры на языке звука
LANGUAGE_ALIASES: Final[dict[str, str]] = {
    "ua": "uk",
    "uk": "uk",
    "ukr": "uk",
    "en": "en",
    "eng": "en",
    "ru": "ru",
    "rus": "ru",
}
LANGUAGE_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"([a-z]{2,3})(?:-[a-z]{2,3})?")
LANGUAGE_PREFIXES: Final[tuple[tuple[str, str], ...]] = (("uk", "uk"), ("ua", "uk"), ("en", "en"), ("ru", "ru"))
NO_VALUE: Final[str] = "none"
UNDETECTED_LANGUAGE: Final[str] = "unknown"     # так строку лога писал донор — для сверки логов
LIST_JOINER: Final[str] = ","


def normalize_language(raw: str | None) -> str | None:
    """Код языка из сырого значения yt-dlp или langdetect; не похоже на язык — None (правило донора)."""
    text: str = str(raw or "").strip().lower().replace("_", "-")
    if not text:
        return None
    if text in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[text]
    code: re.Match[str] | None = LANGUAGE_CODE_PATTERN.fullmatch(text)
    if code is not None:
        return code.group(1)
    for prefix, canonical in LANGUAGE_PREFIXES:
        if text.startswith(prefix):
            return canonical
    return None


class LanguageSource(str, Enum):
    """Каким правилом решён язык; значения — как у донора, чтобы логи сверялись."""

    CONSENSUS = "consensus"
    LANGDETECT_METADATA_AGREEMENT = "langdetect_metadata_agreement"
    METADATA_ARBITRATION = "metadata_arbitration"
    LANGDETECT_ARBITRATION = "langdetect_arbitration"
    METADATA_ARBITRATION_FALLBACK = "metadata_arbitration_fallback"
    LANGDETECT = "langdetect"
    METADATA_FALLBACK = "metadata_fallback"
    UNDETECTED = "undetected"


class LanguageSignal(str, Enum):
    """Независимый голос за язык видео. Первые субтитры и первые автосубтитры не голосуют (донор):
    первые — часто перевод, вторые — алфавитный каталог."""

    VIDEO_LANGUAGE = "video_language"
    AUDIO_FIRST = "audio_first"
    AUTO_CAPTION_ORIG = "auto_caption_orig"
    DESCRIPTION_LANGUAGE = "description_language"
    LANGDETECT_TEXT = "langdetect_text"


@dataclass(frozen=True)
class TextLanguageDetector:
    """langdetect по тексту видео: сначала чистка, короткий текст — без ответа."""

    service_hints: tuple[str, ...]
    min_length: int = MIN_DETECT_LENGTH

    def __post_init__(self) -> None:
        DetectorFactory.seed = DETECTOR_SEED

    @classmethod
    def from_resources(cls) -> TextLanguageDetector:
        return cls(service_hints=TextResource(SERVICE_HINTS_RESOURCE).lines)

    def detect(self, text: str) -> str | None:
        """Код языка текста; текст после чистки короче `min_length` или langdetect не решил — None."""
        cleaned: str = clean_text_for_analysis(text, self.service_hints)
        if len(cleaned) < self.min_length:
            return None
        try:
            detected: str = str(detect(cleaned) or "").strip().lower()
        except LangDetectException:
            return None
        return normalize_language(detected)


@dataclass(frozen=True)
class LanguageProfile:
    """Все сигналы языка одного видео, коды уже нормализованы; нет сигнала — None или пустой кортеж."""

    video_language: str | None
    channel_language: str | None
    audio_languages: tuple[str, ...] = ()
    subtitle_languages: tuple[str, ...] = ()
    auto_caption_languages: tuple[str, ...] = ()
    auto_caption_orig_language: str | None = None
    title_language: str | None = None
    description_language: str | None = None
    text_language: str | None = None             # langdetect по «название\nописание»

    @classmethod
    def of(cls, metadata: SourceMetadata, detector: TextLanguageDetector) -> LanguageProfile:
        """Профиль из данных видео: коды нормализуются, повторы убираются, langdetect — три раза."""
        profile: LanguageProfile = cls(
            video_language=normalize_language(metadata.youtube_language),
            channel_language=normalize_language(metadata.channel_language),
            audio_languages=cls._unique(metadata.audio_languages),
            subtitle_languages=cls._unique(metadata.subtitle_languages),
            auto_caption_languages=cls._unique(metadata.auto_caption_languages),
            auto_caption_orig_language=cls._original_caption(metadata.auto_caption_languages),
            title_language=detector.detect(metadata.title),
            description_language=detector.detect(metadata.description),
            text_language=detector.detect(f"{metadata.title}\n{metadata.description}".strip()),
        )
        LOGGER.debug("language_profile url=%s %s", metadata.url, profile.log_line)
        return profile

    @staticmethod
    def _unique(raw_values: tuple[str, ...]) -> tuple[str, ...]:
        """Нормализованные коды в порядке первого появления, без повторов и без нераспознанных."""
        codes: list[str] = []
        for raw in raw_values:
            code: str | None = normalize_language(raw)
            if code is not None and code not in codes:
                codes.append(code)
        return tuple(codes)

    @staticmethod
    def _original_caption(raw_keys: tuple[str, ...]) -> str | None:
        """Язык первого сырого ключа автосубтитров вида `{язык}-orig` — это язык звука."""
        for raw_key in raw_keys:
            key: str = str(raw_key or "").strip()
            if key.endswith(ORIGINAL_CAPTION_SUFFIX):
                return normalize_language(key[: -len(ORIGINAL_CAPTION_SUFFIX)])
        return None

    @property
    def audio_first(self) -> str | None:
        return self.audio_languages[0] if self.audio_languages else None

    @property
    def metadata_candidates(self) -> tuple[str, ...]:
        """Языки видео и канала без повторов — для строки лога, как у донора."""
        return tuple(dict.fromkeys(code for code in (self.video_language, self.channel_language) if code))

    @property
    def votes(self) -> dict[LanguageSignal, str]:
        """Голоса, которые есть, в порядке донора: видео, звук, `-orig`, описание, текст."""
        signals: tuple[tuple[LanguageSignal, str | None], ...] = (
            (LanguageSignal.VIDEO_LANGUAGE, self.video_language),
            (LanguageSignal.AUDIO_FIRST, self.audio_first),
            (LanguageSignal.AUTO_CAPTION_ORIG, self.auto_caption_orig_language),
            (LanguageSignal.DESCRIPTION_LANGUAGE, self.description_language),
            (LanguageSignal.LANGDETECT_TEXT, self.text_language),
        )
        return {signal: code for signal, code in signals if code is not None}

    @property
    def arbiter_votes(self) -> dict[LanguageSignal, str]:
        """Голоса-арбитры спора языка видео и langdetect: звук, `-orig`, описание."""
        arbiters: tuple[LanguageSignal, ...] = (
            LanguageSignal.AUDIO_FIRST,
            LanguageSignal.AUTO_CAPTION_ORIG,
            LanguageSignal.DESCRIPTION_LANGUAGE,
        )
        return {signal: code for signal, code in self.votes.items() if signal in arbiters}

    def decide(self) -> LanguageDecision:
        """Язык видео по приоритетам донора: консенсус → согласие → арбитраж → langdetect → метаданные."""
        LOGGER.debug("language_votes %s", self._votes_line(self.votes))
        consensus: str | None = self._consensus()
        if consensus is not None:
            return LanguageDecision(consensus, LanguageSource.CONSENSUS, is_conflict=False, profile=self)
        if self.text_language is not None and self.video_language is not None:
            return self._compare_text_with_video()
        if self.text_language is not None:
            return LanguageDecision(self.text_language, LanguageSource.LANGDETECT, is_conflict=False, profile=self)
        if self.video_language is not None:
            return LanguageDecision(
                self.video_language, LanguageSource.METADATA_FALLBACK, is_conflict=False, profile=self
            )
        return LanguageDecision(None, LanguageSource.UNDETECTED, is_conflict=False, profile=self)

    def _consensus(self) -> str | None:
        """Язык, за который не меньше трёх голосов из не меньше трёх; иначе None."""
        votes: dict[LanguageSignal, str] = self.votes
        if len(votes) < CONSENSUS_VOTES:
            return None
        language, count = Counter(votes.values()).most_common(1)[0]
        return language if count >= CONSENSUS_VOTES else None

    def _compare_text_with_video(self) -> LanguageDecision:
        """langdetect и язык видео есть оба: совпали — согласие, нет — арбитраж."""
        if self.text_language == self.video_language:
            return LanguageDecision(
                self.text_language, LanguageSource.LANGDETECT_METADATA_AGREEMENT, is_conflict=False, profile=self
            )
        return self._arbitrate()

    def _arbitrate(self) -> LanguageDecision:
        """Спор: арбитры голосуют за язык видео или за langdetect; ничья или арбитров нет — язык видео."""
        arbiters: dict[LanguageSignal, str] = self.arbiter_votes
        counts: Counter[str] = Counter(arbiters.values())
        for_video: int = counts.get(self.video_language or "", 0)
        for_text: int = counts.get(self.text_language or "", 0)
        LOGGER.debug(
            "language_arbitration video=%s:%d text=%s:%d arbiters=%s",
            self.video_language, for_video, self.text_language, for_text, self._votes_line(arbiters),
        )
        if arbiters and for_video > for_text:
            return LanguageDecision(self.video_language, LanguageSource.METADATA_ARBITRATION, True, self)
        if arbiters and for_text > for_video:
            return LanguageDecision(self.text_language, LanguageSource.LANGDETECT_ARBITRATION, True, self)
        return LanguageDecision(self.video_language, LanguageSource.METADATA_ARBITRATION_FALLBACK, True, self)

    @staticmethod
    def _votes_line(votes: dict[LanguageSignal, str]) -> str:
        return LIST_JOINER.join(f"{signal.value}:{code}" for signal, code in votes.items()) or NO_VALUE

    @property
    def log_line(self) -> str:
        return (
            f"video={self.video_language or NO_VALUE} channel={self.channel_language or NO_VALUE} "
            f"audio={LIST_JOINER.join(self.audio_languages) or NO_VALUE} "
            f"subtitles={LIST_JOINER.join(self.subtitle_languages) or NO_VALUE} "
            f"auto_caption_orig={self.auto_caption_orig_language or NO_VALUE} "
            f"title={self.title_language or NO_VALUE} description={self.description_language or NO_VALUE} "
            f"text={self.text_language or NO_VALUE}"
        )


@dataclass(frozen=True)
class LanguageDecision:
    """Решённый язык видео: код (None — не определился), каким правилом, был ли спор, из какого профиля."""

    language: str | None
    source: LanguageSource
    is_conflict: bool
    profile: LanguageProfile

    @property
    def is_resolved(self) -> bool:
        return self.language is not None

    @property
    def log_line(self) -> str:
        """key=value по образцу `log_language_decision` донора; нет значения — `none`."""
        profile: LanguageProfile = self.profile
        return (
            f"final_language={self.language or UNDETECTED_LANGUAGE} source={self.source.value} "
            f"conflict={'yes' if self.is_conflict else 'no'} "
            f"metadata_candidates={LIST_JOINER.join(profile.metadata_candidates) or NO_VALUE} "
            f"langdetect={profile.text_language or NO_VALUE} "
            f"description_lang={profile.description_language or NO_VALUE} "
            f"title_lang={profile.title_language or NO_VALUE} "
            f"audio_lang={profile.audio_first or NO_VALUE} "
            f"auto_caption_orig={profile.auto_caption_orig_language or NO_VALUE}"
        )


@dataclass(frozen=True)
class LanguageResolver:
    """Точка входа контура A за языком источника: данные видео → профиль → решение → строка лога."""

    detector: TextLanguageDetector

    @classmethod
    def from_resources(cls) -> LanguageResolver:
        return cls(detector=TextLanguageDetector.from_resources())

    def resolve(self, metadata: SourceMetadata) -> LanguageDecision:
        """Решение по одному видео; не определился — WARNING, иначе INFO."""
        decision: LanguageDecision = LanguageProfile.of(metadata, self.detector).decide()
        if decision.is_resolved:
            LOGGER.info("language_decision url=%s %s", metadata.url, decision.log_line)
        else:
            LOGGER.warning("language_decision url=%s %s", metadata.url, decision.log_line)
        return decision
