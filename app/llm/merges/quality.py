"""Качество описания merge: нормализация пунктов и служебных строк, диагностика с кодами причин и статусом.

Перенесено из restreamer, поведение как есть (CLAUDE.md §14 решение 23):
- `quality_normalizer.py`: `_normalize_bullets` → `BulletNormalization`, `_split_bullet_marker` → её правило,
  `_trim_compact_bullet_overflow` → `CompactTrim`, замена служебных строк не того языка → `ServiceLineFix`;
  сама нормализация — `MergedDescription.quality_normalized` (`description.py`);
- `quality_diagnostics.py`: `MergeQualityDiagnostics` и `build_diagnostics` → `QualityDiagnostics.of`,
  `MergeQualityNormalizationResult` → `QualityNormalization`.

Одно отличие от донора — исправление его ошибки: простой маркер пункта («- », «1) ») донор снимал шаблоном
распознавания, который захватывал и первое слово («- first point» → «🔹 point»); здесь снимается только маркер.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Final

from app.llm.merges.blocks import DescriptionBlocks
from app.llm.merges.rules import ACCENT_MARKER_CAP, COMPACT_BULLET_MAX, COMPACT_MAX_SOURCES
from app.llm.merges.service_lines import (
    CORE_LANGUAGES,
    LANGUAGE_NONE,
    LANGUAGE_OTHER,
    ServiceLanguage,
    ServiceLineCatalog,
    ServiceLineKey,
)
from app.resources.loader import TextResource
from app.sources.language import TextLanguageDetector
from app.texts.description_marks import (
    ACCENT_BULLET_MARKERS,
    ALLOWED_BULLET_MARKERS,
    NEUTRAL_BULLET_MARKER,
    CtaLexicon,
    is_bullet_line,
)

if TYPE_CHECKING:
    from app.llm.merges.description import MergedDescription

ALLOWED_LATIN_TOKENS_RESOURCE: Final[str] = "merge_allowed_latin_tokens.txt"
# Простой маркер пункта с пробелами после него («- », «• », «1) », «2. »).
PLAIN_BULLET_MARKER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:[-*\u2022\u25aa\u25e6\u2023\u2013\u2014]|(?:\d+[.)]))\s+", flags=re.UNICODE
)
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")


class QualityReasonCode(str, Enum):
    """Причины диагностики — коды донора в донорском порядке проверки."""

    ACCENT_MARKER_OVERFLOW = "accent_marker_overflow"
    # Историческое имя донора: код значит «нормализация изменила текст», а не «нет пустой строки между блоками».
    MISSING_BLOCK_SPACING = "missing_block_spacing"
    WRONG_LANGUAGE_HEADING_DETECTED = "wrong_language_heading_detected"
    OFFICIAL_LINKS_HEADING_MISMATCH = "official_links_heading_mismatch"
    SCRIPT_MIX_CONTAMINATION = "script_mix_contamination"
    INCONSISTENT_BLOCK_LANGUAGE = "inconsistent_block_language"


class QualityGateStatus(str, Enum):
    OK = "ok"
    NEEDS_NORMALIZATION = "needs_normalization"
    HARD_REJECT = "hard_reject"


HARD_REJECT_CODES: Final[frozenset[QualityReasonCode]] = frozenset(
    {QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE, QualityReasonCode.SCRIPT_MIX_CONTAMINATION}
)


@dataclass(frozen=True)
class QualityRules:
    """Всё, чем пользуются нормализация и диагностика: призывы, канонические строки, язык служебных строк,
    латинские слова, допустимые в тексте кириллицей."""

    cta: CtaLexicon
    catalog: ServiceLineCatalog
    service: ServiceLanguage
    allowed_latin_tokens: frozenset[str]

    @classmethod
    def load(cls, detector: TextLanguageDetector | None = None) -> QualityRules:
        return cls(
            cta=CtaLexicon.load(),
            catalog=ServiceLineCatalog.load(),
            service=ServiceLanguage.load(detector),
            allowed_latin_tokens=frozenset(TextResource(ALLOWED_LATIN_TOKENS_RESOURCE).lines),
        )


@dataclass(frozen=True)
class QualityRequest:
    """Что нужно знать о слоте: язык блока, название, число источников (0 — неизвестно, пункты не режутся)."""

    language: str
    title: str = field(default="", repr=False)
    source_count: int = 0


@dataclass(frozen=True)
class BulletNormalization:
    """Пункты после нормализации маркеров: чужой маркер → 🔹, акцентных не больше трёх (лишние → 🔹).

    Первая строка, если она не пункт, — вводная: в ней только схлопываются пробелы.
    """

    lines: tuple[str, ...] = field(repr=False)
    accent_overflow: bool = False
    accent_marker_types: tuple[str, ...] = ()
    neutral_bullets_count: int = 0
    accent_bullets_count: int = 0

    @classmethod
    def of(cls, theses_lines: tuple[str, ...]) -> BulletNormalization:
        lines: list[str] = []
        accent_types: list[str] = []
        accent_count: int = 0
        neutral_count: int = 0
        overflow: bool = False
        for index, line in enumerate(theses_lines):
            if index == 0 and not is_bullet_line(line):
                lines.append(WHITESPACE_RUN_PATTERN.sub(" ", str(line or "")).strip())
                continue
            marker, content = cls._split_marker(line)
            if marker not in ALLOWED_BULLET_MARKERS:
                marker = NEUTRAL_BULLET_MARKER
            if marker in ACCENT_BULLET_MARKERS:
                if accent_count >= ACCENT_MARKER_CAP:
                    marker, overflow = NEUTRAL_BULLET_MARKER, True
                else:
                    accent_count += 1
                    if marker not in accent_types:
                        accent_types.append(marker)
            if marker == NEUTRAL_BULLET_MARKER:
                neutral_count += 1
            lines.append(f"{marker} {content}".strip())
        return cls(tuple(lines), overflow, tuple(accent_types), neutral_count, accent_count)

    @staticmethod
    def _split_marker(line: str) -> tuple[str, str]:
        """Маркер и текст пункта; строка без маркера-эмодзи получает маркер `plain` (дальше он станет 🔹)."""
        stripped: str = str(line or "").strip()
        for marker in ALLOWED_BULLET_MARKERS:
            if stripped.startswith(f"{marker} "):
                return marker, stripped[len(marker) :].strip()
        content: str = PLAIN_BULLET_MARKER_PATTERN.sub("", stripped, count=1).strip()
        if content:
            return "plain", content
        return NEUTRAL_BULLET_MARKER, stripped


@dataclass(frozen=True)
class CompactTrim:
    """Компактный контракт (1–2 источника): пунктов больше семи — лишние с конца отброшены, прочие строки на месте."""

    lines: tuple[str, ...] = field(repr=False)
    applied: bool
    bullets_before: int
    bullets_after: int
    source_count: int

    @classmethod
    def of(cls, theses_lines: tuple[str, ...], source_count: int) -> CompactTrim:
        bullet_count: int = sum(1 for line in theses_lines if is_bullet_line(line))
        if source_count <= 0 or source_count > COMPACT_MAX_SOURCES or bullet_count <= COMPACT_BULLET_MAX:
            return cls(theses_lines, False, bullet_count, bullet_count, source_count)
        kept_lines: list[str] = []
        kept_bullets: int = 0
        for line in theses_lines:
            if not is_bullet_line(line):
                kept_lines.append(line)
            elif kept_bullets < COMPACT_BULLET_MAX:
                kept_lines.append(line)
                kept_bullets += 1
        return cls(tuple(kept_lines), True, bullet_count, kept_bullets, source_count)

    @property
    def log_line(self) -> str:
        return (
            f"source_count={self.source_count} bullets_before={self.bullets_before} "
            f"bullets_after={self.bullets_after} cap={COMPACT_BULLET_MAX}"
        )


@dataclass(frozen=True)
class ServiceLineFix:
    """Блоки после снятия повторов тезиса и замены служебных строк не того языка каноническими."""

    blocks: DescriptionBlocks
    wrong_language_heading_detected: bool
    official_links_heading_mismatch: bool

    @classmethod
    def of(cls, blocks: DescriptionBlocks, language: str, rules: QualityRules) -> ServiceLineFix:
        """Правила донора: повторы снимаются по исходным блокам, замены смотрят на исходные служебные строки —
        поэтому призыв, снятый как повтор тезиса, может вернуться каноническим."""
        fixed: DescriptionBlocks = blocks
        if blocks.is_single_echo_cta:
            fixed = replace(fixed, cta="")
        if blocks.is_single_echo_thesis:
            fixed = replace(fixed, hook="")
        wrong_heading: bool = False
        mismatch: bool = False
        service: ServiceLanguage = rules.service
        if blocks.lead_in and service.is_wrong(service.detect_service(blocks.lead_in), language):
            lead_in: str = rules.catalog.line(language, ServiceLineKey.LEAD_IN)
            fixed = replace(fixed, theses_lines=(lead_in, *fixed.theses_lines[1:]))
            wrong_heading = True
        if blocks.links_heading:
            expected: str = rules.catalog.line(language, ServiceLineKey.LINKS_HEADING)
            mismatch = blocks.links_heading != expected
            if mismatch or service.is_wrong(service.detect_service(blocks.links_heading), language):
                fixed = replace(fixed, links_heading=expected)
                wrong_heading = True
        if (
            blocks.cta
            and service.is_short_service_line(blocks.cta)
            and service.is_wrong(service.detect_service(blocks.cta), language)
        ):
            fixed = replace(fixed, cta=rules.catalog.cta_preserving_hashtags(blocks.cta, language))
        return cls(fixed, wrong_heading, mismatch)


@dataclass(frozen=True)
class QualityFindings:
    """Вход диагностики: итоговый текст и то, что нормализация о нём узнала."""

    description_text: str = field(repr=False)
    request: QualityRequest
    block_spacing_ok: bool
    wrong_language_heading_detected: bool
    official_links_heading_mismatch: bool
    bullets: BulletNormalization


@dataclass(frozen=True)
class QualityDiagnostics:
    """Диагностика качества описания — поля донора; `semantic_gate_*` — статус и причины."""

    neutral_bullets_count: int
    accent_bullets_count: int
    accent_marker_types: tuple[str, ...]
    accent_overflow: bool
    block_spacing_ok: bool
    block_language_expected: str
    hook_language_detected: str
    lead_in_language_detected: str
    links_heading_language_detected: str
    cta_language_detected: str
    language_consistency_ok: bool
    wrong_language_heading_detected: bool
    script_mix_detected: bool
    script_mix_suspects: tuple[str, ...]
    semantic_gate_status: QualityGateStatus
    semantic_gate_reason_codes: tuple[QualityReasonCode, ...]

    @classmethod
    def of(cls, findings: QualityFindings, rules: QualityRules) -> QualityDiagnostics:
        language: str = findings.request.language
        blocks: DescriptionBlocks = DescriptionBlocks.of(findings.description_text, rules.cta)
        service: ServiceLanguage = rules.service
        hook_language: str = service.detect_paragraph(blocks.hook)
        suspects: tuple[str, ...] = blocks.script_mix_suspects(
            findings.request.title, language, rules.allowed_latin_tokens
        )
        codes: tuple[QualityReasonCode, ...] = cls._reason_codes(findings, suspects, hook_language)
        return cls(
            neutral_bullets_count=findings.bullets.neutral_bullets_count,
            accent_bullets_count=findings.bullets.accent_bullets_count,
            accent_marker_types=findings.bullets.accent_marker_types,
            accent_overflow=findings.bullets.accent_overflow,
            block_spacing_ok=findings.block_spacing_ok,
            block_language_expected=language,
            hook_language_detected=hook_language,
            lead_in_language_detected=service.detect_service(blocks.lead_in),
            links_heading_language_detected=service.detect_service(blocks.links_heading),
            cta_language_detected=service.detect_service(blocks.cta),
            language_consistency_ok=QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE not in codes,
            wrong_language_heading_detected=findings.wrong_language_heading_detected,
            script_mix_detected=bool(suspects),
            script_mix_suspects=suspects,
            semantic_gate_status=cls._status(codes),
            semantic_gate_reason_codes=codes,
        )

    @staticmethod
    def _reason_codes(
        findings: QualityFindings, suspects: tuple[str, ...], hook_language: str
    ) -> tuple[QualityReasonCode, ...]:
        checks: tuple[tuple[bool, QualityReasonCode], ...] = (
            (findings.bullets.accent_overflow, QualityReasonCode.ACCENT_MARKER_OVERFLOW),
            (not findings.block_spacing_ok, QualityReasonCode.MISSING_BLOCK_SPACING),
            (findings.wrong_language_heading_detected, QualityReasonCode.WRONG_LANGUAGE_HEADING_DETECTED),
            (findings.official_links_heading_mismatch, QualityReasonCode.OFFICIAL_LINKS_HEADING_MISMATCH),
            (bool(suspects), QualityReasonCode.SCRIPT_MIX_CONTAMINATION),
            (_core_language_mismatch(hook_language, findings.request.language), QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE),
        )
        return tuple(code for is_found, code in checks if is_found)

    @staticmethod
    def _status(codes: tuple[QualityReasonCode, ...]) -> QualityGateStatus:
        if any(code in HARD_REJECT_CODES for code in codes):
            return QualityGateStatus.HARD_REJECT
        if codes:
            return QualityGateStatus.NEEDS_NORMALIZATION
        return QualityGateStatus.OK


def _core_language_mismatch(detected: str, expected: str) -> bool:
    """Язык тезиса явно не язык блока: определён (в том числе `unknown` — как у донора) и блок uk, en или ru."""
    if detected in {LANGUAGE_NONE, LANGUAGE_OTHER} or expected not in CORE_LANGUAGES:
        return False
    return detected != expected


@dataclass(frozen=True)
class QualityNormalization:
    """Итог нормализации: описание после неё и диагностика итогового текста."""

    description: MergedDescription
    diagnostics: QualityDiagnostics
