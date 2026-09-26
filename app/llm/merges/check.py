"""Проверка ответа модели на merge: диагностика стиля, проверка покрытия и восстановление форматирования.

- `MergeCheck.of` — описание ответа нормализуется (качество с названием и числом источников) и получает диагностику
  стиля (`MergeDiagnostics`, строки `merge_style_coverage` и `merge_semantic_gate`);
- `MergeCheck.run` — проверки строго по порядку, первая сработавшая даёт отказ-значение `MergeReject`; эхо тезиса
  чинится на месте (строка лога `hook_echo_repair_applied=yes`). Восстановление форматирования после отказа — шаг
  попытки (`attempt.py::FormattingRecovery`).

Строки лога попытки начинаются полями `MergeAttemptLabel`: слот, язык, модель, номер попытки. Текста описания и
названия в строках лога нет. Поле `official_links_fill_applied` всегда `no`: блок ссылок в описание не вставляется.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.core.sequence import unique_in_order
from app.core.text_format import NEWLINE
from app.llm.merges.contract import MergeContract
from app.llm.merges.description import MergedDescription
from app.llm.merges.emoji import EmojiUsage
from app.llm.merges.hook_echo import HookEcho
from app.llm.merges.links import OfficialLinkSelection
from app.llm.merges.merge_rules import MergeLexicons
from app.llm.merges.opening import DescriptionOpening
from app.llm.merges.quality import QualityDiagnostics, QualityGateStatus, QualityNormalization, QualityRequest
from app.llm.merges.reject import MergeReject, MergeRejectCode
from app.llm.merges.rules import (
    AGENDA_MIN_BULLETS,
    COMPACT_BULLET_MAX,
    COMPACT_MAX_SOURCES,
    EMOJI_MAX,
    HOOK_MARKS,
    HOOK_MIN_CHARS,
    MIN_BULLETS_MIN_SOURCES,
    OVERLOADED_BULLETS_MIN_LIST,
    OVERLOADED_BULLETS_REJECT,
    STYLE_CONTRACT_VERSION,
)
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.sources.video import SourceVideo
from app.texts.description_marks import ALLOWED_BULLET_MARKERS, BulletLine, extract_named_entities
from app.texts.paragraphs import normalize_newlines

LOGGER: logging.Logger = get_logger(LogArea.LLM)

# Название-перечень: «1) », «2) » — пункт под номером прямо в названии.
NUMBERED_DUMP_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\d\)\s")
OVERLOADED_DETAIL: Final[str] = "count={count}"
NAMED_ENTITIES_METRIC: Final[str] = "informational"
REQUEST_LABEL: Final[str] = "merge_{language}_primary_{attempt}"


class CheckEvent(str, Enum):
    """События проверки ответа в логе."""

    STYLE = "merge_style_coverage"
    GATE = "merge_semantic_gate"
    HOOK_ECHO_REPAIRED = "hook_echo_repair_applied=yes"


@dataclass(frozen=True)
class MergeAttemptLabel:
    """Какая попытка merge проверяется: слот, язык блока, модель, номер попытки — начало строк лога."""

    slot_id: str
    language: str
    model: str
    attempt: int

    def event(self, name: Enum) -> LogEvent:
        """Строка лога о попытке: имя события, слот, язык, модель, номер попытки."""
        return LogEvent.of(name, slot=self.slot_id, language=self.language, model=self.model, attempt=self.attempt)

    @property
    def request_label(self) -> str:
        """Ярлык запроса попытки у нейросети: `merge_<язык>_primary_<номер>`."""
        return REQUEST_LABEL.format(language=self.language, attempt=self.attempt)


@dataclass(frozen=True)
class MergeCheckRequest:
    """Что о попытке не меняется между проверкой и восстановлением: метка, название ответа, источники слота
    и сколько ссылок было в разобранном ответе (они считаются до починок текста)."""

    label: MergeAttemptLabel
    title: str = field(repr=False)
    sources: tuple[SourceVideo, ...] = field(repr=False)
    links_in_answer: int

    @classmethod
    def of(
        cls, label: MergeAttemptLabel, title: str, answer: MergedDescription, sources: Sequence[SourceVideo]
    ) -> MergeCheckRequest:
        """Запрос по разобранному ответу: ссылки ответа считаются по его тексту."""
        return cls(label=label, title=title, sources=tuple(sources), links_in_answer=answer.official_link_count)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def quality(self) -> QualityRequest:
        """Нормализация качества описания попытки: язык блока, название, число источников."""
        return QualityRequest(language=self.label.language, title=self.title, source_count=self.source_count)

    @property
    def source_entities(self) -> set[str]:
        """Имена собственные источников — по названию и описанию видео до чистки."""
        entities: set[str] = set()
        for source in self.sources:
            entities.update(extract_named_entities(NEWLINE.join((source.text.title.strip(), source.text.description.strip()))))
        return entities


@dataclass(frozen=True)
class BulletMarkers:
    """Маркеры пунктов описания по порядку строк: эмодзи из разрешённых и простые («-», «1)»)."""

    markers: tuple[str, ...]

    @classmethod
    def of(cls, description: MergedDescription) -> BulletMarkers:
        lines: list[str] = normalize_newlines(description.text).split(NEWLINE)
        return cls(tuple(marker for marker in (BulletLine.of(line).marker for line in lines) if marker))

    @property
    def semantic(self) -> int:
        return sum(1 for marker in self.markers if marker in ALLOWED_BULLET_MARKERS)


@dataclass(frozen=True)
class MergeDiagnostics:
    """Диагностика стиля описания; `quality` — диагностика качества."""

    hook_present: bool
    agenda_block_present: bool
    bullet_points_count: int
    semantic_bullets_count: int
    bullets_with_emoji_count: int
    bullets_with_plain_marker_count: int
    bullet_marker_types: tuple[str, ...]
    named_entities_preserved: int
    source_named_entities_total: int
    emoji_count: int
    links: OfficialLinkSelection
    official_links_in_output: int
    quality: QualityDiagnostics

    @classmethod
    def of(
        cls, request: MergeCheckRequest, description: MergedDescription, quality: QualityDiagnostics, lexicons: MergeLexicons
    ) -> MergeDiagnostics:
        """Диагностика описания; ссылки источников отбираются по их описаниям, имена — по названию и описанию."""
        trimmed: MergedDescription = MergedDescription(description.text.strip())
        markers: BulletMarkers = BulletMarkers.of(trimmed)
        paragraphs: list[str] = trimmed.paragraphs
        first: str = paragraphs[0] if paragraphs else ""
        answer_entities: set[str] = extract_named_entities(NEWLINE.join((request.title.strip(), trimmed.text)))
        return cls(
            hook_present=len(first) >= HOOK_MIN_CHARS and any(mark in first for mark in HOOK_MARKS),
            agenda_block_present=len(markers.markers) >= AGENDA_MIN_BULLETS or lexicons.agenda.matches(trimmed.text),
            bullet_points_count=len(markers.markers),
            semantic_bullets_count=markers.semantic,
            bullets_with_emoji_count=markers.semantic,
            bullets_with_plain_marker_count=len(markers.markers) - markers.semantic,
            bullet_marker_types=unique_in_order(markers.markers),
            named_entities_preserved=len(request.source_entities & answer_entities),
            source_named_entities_total=len(request.source_entities),
            emoji_count=EmojiUsage(trimmed).count,
            links=OfficialLinkSelection.for_sources(request.sources, lexicons.link_hints),
            official_links_in_output=request.links_in_answer,
            quality=quality,
        )

    def events(self, label: MergeAttemptLabel) -> tuple[LogEvent, ...]:
        """Строки `merge_style_coverage` и `merge_semantic_gate` без текста описания."""
        return self._style_event(label), self._gate_event(label)

    def _style_event(self, label: MergeAttemptLabel) -> LogEvent:
        quality: QualityDiagnostics = self.quality
        bullets: LogEvent = label.event(CheckEvent.STYLE).extended(
            style_contract_version=STYLE_CONTRACT_VERSION,
            hook_present=self.hook_present,
            agenda_block_present=self.agenda_block_present,
            bullet_points_count=self.bullet_points_count,
            semantic_bullets_count=self.semantic_bullets_count,
            bullets_with_emoji_count=self.bullets_with_emoji_count,
            bullets_with_plain_marker_count=self.bullets_with_plain_marker_count,
            bullet_marker_types=self.bullet_marker_types,
        )
        accents: LogEvent = bullets.extended(
            neutral_bullets_count=quality.neutral_bullets_count,
            accent_bullets_count=quality.accent_bullets_count,
            accent_marker_types=quality.accent_marker_types,
            accent_overflow=quality.accent_overflow,
            block_spacing_ok=quality.block_spacing_ok,
        )
        return accents.extended(
            named_entities_preserved=self.named_entities_preserved,
            source_named_entities_total=self.source_named_entities_total,
            named_entities_metric=NAMED_ENTITIES_METRIC,
            emoji_count=self.emoji_count,
            official_links_found_in_sources=self.links.found_in_sources,
            official_links_kept=len(self.links.kept_links),
            official_links_in_output=self.official_links_in_output,
            official_links_fill_applied=False,
        )

    def _gate_event(self, label: MergeAttemptLabel) -> LogEvent:
        quality: QualityDiagnostics = self.quality
        languages: LogEvent = label.event(CheckEvent.GATE).extended(
            block_language_expected=quality.block_language_expected,
            hook_language_detected=quality.hook_language_detected,
            lead_in_language_detected=quality.lead_in_language_detected,
            links_heading_language_detected=quality.links_heading_language_detected,
            cta_language_detected=quality.cta_language_detected,
            language_consistency_ok=quality.language_consistency_ok,
        )
        return languages.extended(
            wrong_language_heading_detected=quality.wrong_language_heading_detected,
            script_mix_detected=quality.script_mix_detected,
            script_mix_suspects=quality.script_mix_suspects,
            semantic_gate_status=quality.semantic_gate_status,
            semantic_gate_reason_codes=quality.semantic_gate_reason_codes,
        )


@dataclass(frozen=True)
class MergeCheckPassed:
    """Ответ прошёл проверку: описание (эхо тезиса, если было, починено) и диагностика до починки."""

    description: MergedDescription
    diagnostics: MergeDiagnostics


@dataclass(frozen=True)
class MergeCheck:
    """Проверка покрытия одного описания: запрос попытки, описание после нормализации качества, её диагностика
    и диагностика стиля."""

    request: MergeCheckRequest
    description: MergedDescription
    quality: QualityDiagnostics
    diagnostics: MergeDiagnostics
    lexicons: MergeLexicons = field(repr=False)

    @classmethod
    def of(cls, request: MergeCheckRequest, description: MergedDescription, lexicons: MergeLexicons) -> MergeCheck:
        """Проверка описания попытки: качество нормализуется с названием и числом источников."""
        return cls.normalized(request, QualityNormalization.of(description, request.quality, lexicons), lexicons)

    @classmethod
    def normalized(
        cls, request: MergeCheckRequest, normalization: QualityNormalization, lexicons: MergeLexicons
    ) -> MergeCheck:
        """Проверка уже нормализованного описания; диагностика стиля строится по нему."""
        diagnostics: MergeDiagnostics = MergeDiagnostics.of(
            request, normalization.description, normalization.diagnostics, lexicons
        )
        return cls(request, normalization.description, normalization.diagnostics, diagnostics, lexicons)

    def run(self) -> MergeCheckPassed | MergeReject:
        """Проверки по порядку; первая сработавшая — отказ."""
        description: MergedDescription | MergeReject = self._repetition_checked()
        if isinstance(description, MergeReject):
            return description
        reject: MergeReject | None = self._opening_reject(description) or self._structure_reject(description)
        if reject is not None:
            return reject
        if self.quality.semantic_gate_status == QualityGateStatus.HARD_REJECT:
            return MergeReject.semantic_gate([code.value for code in self.quality.semantic_gate_reason_codes])
        return MergeCheckPassed(description=description, diagnostics=self.diagnostics)

    def _repetition_checked(self) -> MergedDescription | MergeReject:
        """Пересказ по источникам, повтор абзацев, эхо тезиса (чинится), повтор соседних строк."""
        description: MergedDescription = self.description
        if description.looks_like_per_source_dump:
            return MergeReject(MergeRejectCode.PER_SOURCE_ENUMERATION)
        if description.has_duplicate_paragraphs:
            return MergeReject(MergeRejectCode.DUPLICATE_PARAGRAPH)
        if HookEcho(description).found:
            repaired: MergedDescription | None = HookEcho(description).repaired()
            if repaired is None:
                return MergeReject(MergeRejectCode.HOOK_ECHO_IN_BODY)
            description = repaired
            self.request.label.event(CheckEvent.HOOK_ECHO_REPAIRED).emit(LOGGER)
        if description.has_adjacent_duplicate_lines:
            return MergeReject(MergeRejectCode.DUPLICATE_PARAGRAPH)
        return description

    def _opening_reject(self, description: MergedDescription) -> MergeReject | None:
        """Призыв в начальных строках раньше тезиса и пунктов; служебная строка или негодный тезис в первом абзаце."""
        lexicons: MergeLexicons = self.lexicons
        opening: DescriptionOpening = DescriptionOpening(description)
        if opening.cta_before_content(lexicons.cta, lexicons.bad_hooks, lexicons.service_hints):
            return MergeReject(MergeRejectCode.CTA_AS_FIRST_PARAGRAPH)
        if opening.hook_is_service_line(lexicons.bad_hooks, lexicons.service_hints):
            return MergeReject(MergeRejectCode.CTA_IN_HOOK)
        return None

    def _structure_reject(self, description: MergedDescription) -> MergeReject | None:
        """Число пунктов, эмодзи, перегруженные пункты, название-перечень, похожие начала абзацев."""
        bullets: int = self.diagnostics.bullet_points_count
        source_count: int = self.request.source_count
        if source_count >= MIN_BULLETS_MIN_SOURCES and bullets < MergeContract.min_bullets(source_count):
            return MergeReject(MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE)
        if source_count <= COMPACT_MAX_SOURCES and bullets > COMPACT_BULLET_MAX:
            return MergeReject(MergeRejectCode.COMPACT_BULLET_OVERFLOW)
        if self.diagnostics.emoji_count > EMOJI_MAX:
            return MergeReject(MergeRejectCode.EXCESSIVE_EMOJI_USAGE)
        overloaded: int = description.overloaded_bullet_count
        if overloaded >= OVERLOADED_BULLETS_REJECT and bullets >= OVERLOADED_BULLETS_MIN_LIST:
            return MergeReject(MergeRejectCode.OVERLOADED_BULLET, OVERLOADED_DETAIL.format(count=overloaded))
        if NUMBERED_DUMP_PATTERN.search(self.request.title):
            return MergeReject(MergeRejectCode.NUMBERED_TITLE_DUMP)
        if description.has_similar_paragraph_prefixes:
            return MergeReject(MergeRejectCode.DUPLICATE_PARAGRAPH)
        return None
