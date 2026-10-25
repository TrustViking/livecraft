"""Язык источника по данным видео (CLAUDE.md §3 шаг 2.3, §14 решение 12).

Колонку языка таблицы программа не читает: язык решается один раз по тому, что yt-dlp сказал о видео,
и дальше переходит в слот. Код языка из сырого значения и язык текста — `app\\texts\\language_detector.py`
(`normalize_language`, `TextLanguageDetector`).

- `LanguageProfile` — все сигналы языка одного видео, коды уже нормализованы;
- `LanguageVoting` — голосование сигналов: консенсус → согласие langdetect с языком видео → арбитраж спора →
  langdetect → язык видео; итог — `LanguageDecision`;
- `LanguageResolver` — точка входа: данные видео → профиль → решение → строка лога.

Не определился язык — решение с `language=None`; такой источник дальше по конвейеру не идёт (§0).
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.sequence import unique_in_order
from app.core.text_format import NEWLINE
from app.observability.log_event import LogArea, LogEvent, LogValue, get_logger
from app.sources.metadata import SourceMetadata
from app.texts.language_detector import TextLanguageDetector, normalize_language

LOGGER = get_logger(LogArea.SOURCES)

CONSENSUS_VOTES: Final[int] = 3
ORIGINAL_CAPTION_SUFFIX: Final[str] = "-orig"   # YouTube так помечает автосубтитры на языке звука
VOTE_TEMPLATE: Final[str] = "{signal}:{code}"   # голос в поле строки лога


class LanguageSource(str, Enum):
    """Каким правилом решён язык."""

    CONSENSUS = "consensus"
    LANGDETECT_METADATA_AGREEMENT = "langdetect_metadata_agreement"
    METADATA_ARBITRATION = "metadata_arbitration"
    LANGDETECT_ARBITRATION = "langdetect_arbitration"
    METADATA_ARBITRATION_FALLBACK = "metadata_arbitration_fallback"
    LANGDETECT = "langdetect"
    METADATA_FALLBACK = "metadata_fallback"
    UNDETECTED = "undetected"


class LanguageSignal(str, Enum):
    """Независимый голос за язык видео. Первые субтитры и первые автосубтитры не голосуют:
    первые — часто перевод, вторые — алфавитный каталог."""

    VIDEO_LANGUAGE = "video_language"
    AUDIO_FIRST = "audio_first"
    AUTO_CAPTION_ORIG = "auto_caption_orig"
    DESCRIPTION_LANGUAGE = "description_language"
    LANGDETECT_TEXT = "langdetect_text"


class LanguageEvent(str, Enum):
    """События решения языка в логе."""

    PROFILE = "language_profile"
    VOTES = "language_votes"
    ARBITRATION = "language_arbitration"
    DECISION = "language_decision"


# Голоса-арбитры спора языка видео и langdetect: звук, `-orig`, описание.
ARBITER_SIGNALS: Final[tuple[LanguageSignal, ...]] = (
    LanguageSignal.AUDIO_FIRST,
    LanguageSignal.AUTO_CAPTION_ORIG,
    LanguageSignal.DESCRIPTION_LANGUAGE,
)


@dataclass(frozen=True)
class RawLanguages:
    """Сырые коды языков из ответа yt-dlp: языки звука или ключи субтитров, как пришли."""

    values: tuple[str, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        """Нормализованные коды в порядке первого появления, без повторов и без нераспознанных."""
        return unique_in_order(code for code in map(normalize_language, self.values) if code is not None)

    @property
    def original_caption(self) -> str | None:
        """Язык первого ключа автосубтитров вида `{язык}-orig` — это язык звука."""
        for value in self.values:
            key: str = value.strip()
            if key.endswith(ORIGINAL_CAPTION_SUFFIX):
                return normalize_language(key[: -len(ORIGINAL_CAPTION_SUFFIX)])
        return None


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
        captions: RawLanguages = RawLanguages(metadata.auto_caption_languages)
        profile: LanguageProfile = cls(
            video_language=normalize_language(metadata.youtube_language),
            channel_language=normalize_language(metadata.channel_language),
            audio_languages=RawLanguages(metadata.audio_languages).codes,
            subtitle_languages=RawLanguages(metadata.subtitle_languages).codes,
            auto_caption_languages=captions.codes,
            auto_caption_orig_language=captions.original_caption,
            title_language=detector.detect(metadata.title),
            description_language=detector.detect(metadata.description),
            text_language=detector.detect(NEWLINE.join((metadata.title, metadata.description)).strip()),
        )
        LogEvent.of(LanguageEvent.PROFILE, url=metadata.url, **profile.log_fields).emit(LOGGER, logging.DEBUG)
        return profile

    @property
    def audio_first(self) -> str | None:
        return self.audio_languages[0] if self.audio_languages else None

    @property
    def metadata_candidates(self) -> tuple[str, ...]:
        """Языки видео и канала без повторов — для строки лога."""
        return unique_in_order(code for code in (self.video_language, self.channel_language) if code)

    @property
    def log_fields(self) -> Mapping[str, object]:
        return dict(
            video=self.video_language,
            channel=self.channel_language,
            audio=self.audio_languages,
            subtitles=self.subtitle_languages,
            auto_caption_orig=self.auto_caption_orig_language,
            title=self.title_language,
            description=self.description_language,
            text=self.text_language,
        )


@dataclass(frozen=True)
class LanguageVoting:
    """Голосование сигналов профиля за язык видео."""

    profile: LanguageProfile

    @property
    def votes(self) -> dict[LanguageSignal, str]:
        """Голоса, которые есть, по порядку: видео, звук, `-orig`, описание, текст."""
        profile: LanguageProfile = self.profile
        signals: dict[LanguageSignal, str | None] = {
            LanguageSignal.VIDEO_LANGUAGE: profile.video_language,
            LanguageSignal.AUDIO_FIRST: profile.audio_first,
            LanguageSignal.AUTO_CAPTION_ORIG: profile.auto_caption_orig_language,
            LanguageSignal.DESCRIPTION_LANGUAGE: profile.description_language,
            LanguageSignal.LANGDETECT_TEXT: profile.text_language,
        }
        return {signal: code for signal, code in signals.items() if code is not None}

    @property
    def arbiter_votes(self) -> dict[LanguageSignal, str]:
        """Голоса-арбитры спора языка видео и langdetect: звук, `-orig`, описание."""
        return {signal: code for signal, code in self.votes.items() if signal in ARBITER_SIGNALS}

    def decide(self) -> LanguageDecision:
        """Язык видео по приоритетам: консенсус → согласие → арбитраж → langdetect → язык видео."""
        LogEvent.of(LanguageEvent.VOTES, votes=self._vote_values(self.votes)).emit(LOGGER, logging.DEBUG)
        profile: LanguageProfile = self.profile
        consensus: str | None = self._consensus()
        if consensus is not None:
            return LanguageDecision(consensus, LanguageSource.CONSENSUS, is_conflict=False, profile=profile)
        if profile.text_language is not None and profile.video_language is not None:
            return self._compare_text_with_video()
        if profile.text_language is not None:
            return LanguageDecision(
                profile.text_language, LanguageSource.LANGDETECT, is_conflict=False, profile=profile
            )
        if profile.video_language is not None:
            return LanguageDecision(
                profile.video_language, LanguageSource.METADATA_FALLBACK, is_conflict=False, profile=profile
            )
        return LanguageDecision(None, LanguageSource.UNDETECTED, is_conflict=False, profile=profile)

    def _consensus(self) -> str | None:
        """Язык, за который не меньше трёх голосов из не меньше трёх; иначе None."""
        votes: dict[LanguageSignal, str] = self.votes
        if len(votes) < CONSENSUS_VOTES:
            return None
        language, count = Counter(votes.values()).most_common(1)[0]
        return language if count >= CONSENSUS_VOTES else None

    def _compare_text_with_video(self) -> LanguageDecision:
        """langdetect и язык видео есть оба: совпали — согласие, нет — арбитраж."""
        profile: LanguageProfile = self.profile
        if profile.text_language == profile.video_language:
            return LanguageDecision(
                profile.text_language, LanguageSource.LANGDETECT_METADATA_AGREEMENT, is_conflict=False, profile=profile
            )
        return self._arbitrate()

    def _arbitrate(self) -> LanguageDecision:
        """Спор: арбитры голосуют за язык видео или за langdetect; ничья или арбитров нет — язык видео."""
        profile: LanguageProfile = self.profile
        arbiters: dict[LanguageSignal, str] = self.arbiter_votes
        counts: Counter[str] = Counter(arbiters.values())
        for_video: int = counts.get(profile.video_language or "", 0)
        for_text: int = counts.get(profile.text_language or "", 0)
        arbitration: LogEvent = LogEvent.of(LanguageEvent.ARBITRATION, video=profile.video_language)
        arbitration = arbitration.extended(for_video=for_video, text=profile.text_language, for_text=for_text)
        arbitration.extended(arbiters=self._vote_values(arbiters)).emit(LOGGER, logging.DEBUG)
        if arbiters and for_video > for_text:
            return LanguageDecision(profile.video_language, LanguageSource.METADATA_ARBITRATION, True, profile)
        if arbiters and for_text > for_video:
            return LanguageDecision(profile.text_language, LanguageSource.LANGDETECT_ARBITRATION, True, profile)
        return LanguageDecision(profile.video_language, LanguageSource.METADATA_ARBITRATION_FALLBACK, True, profile)

    def _vote_values(self, votes: dict[LanguageSignal, str]) -> tuple[str, ...]:
        """Голоса для поля строки лога: «сигнал:код» по порядку."""
        return tuple(VOTE_TEMPLATE.format(signal=signal.value, code=code) for signal, code in votes.items())


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
    def log_fields(self) -> Mapping[str, object]:
        """Решение и сигналы, на которых оно стоит; не определился — `unknown`, нет значения — «-»."""
        profile: LanguageProfile = self.profile
        return dict(
            final_language=self.language or LogValue.UNKNOWN,
            source=self.source,
            conflict=self.is_conflict,
            metadata_candidates=profile.metadata_candidates,
            langdetect=profile.text_language,
            description_lang=profile.description_language,
            title_lang=profile.title_language,
            audio_lang=profile.audio_first,
            auto_caption_orig=profile.auto_caption_orig_language,
        )

    def event(self, url: str) -> LogEvent:
        """Строка лога о решении по видео `url`."""
        return LogEvent.of(LanguageEvent.DECISION, url=url, **self.log_fields)


@dataclass(frozen=True)
class LanguageResolver:
    """Точка входа контура A за языком источника: данные видео → профиль → решение → строка лога."""

    detector: TextLanguageDetector

    @classmethod
    def from_resources(cls) -> LanguageResolver:
        return cls(detector=TextLanguageDetector.from_resources())

    def resolve(self, metadata: SourceMetadata) -> LanguageDecision:
        """Решение по одному видео; не определился — WARNING, иначе INFO."""
        decision: LanguageDecision = LanguageVoting(LanguageProfile.of(metadata, self.detector)).decide()
        decision.event(metadata.url).emit(LOGGER, logging.INFO if decision.is_resolved else logging.WARNING)
        return decision
