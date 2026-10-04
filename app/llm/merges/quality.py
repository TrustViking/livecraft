"""Качество описания merge: нормализация пунктов и служебных строк, диагностика с кодами причин и статусом.

`QualityNormalization.of` — описание в нормальном виде и диагностика итогового текста. Шаги по порядку: разбор на
блоки → снятие повторов тезиса → служебные строки не того языка — канонические (`ServiceLineFix`) → маркеры пунктов
(`BulletNormalization`) → лишние пункты компактного контракта (`CompactTrim`) → сборка текста. Любая правка текста —
причина `missing_block_spacing` (историческое имя: «нормализация изменила текст»).

`QualityDiagnostics` — коды причин и статус semantic gate: смесь алфавитов и тезис явно не на языке блока — жёсткий
отказ. Язык тезиса, который не определился, — не отказ: правило «язык явно не тот» одно для тезиса и служебных строк
(`service_lines.py::LanguageMatch`).

Маркеры по ролям (§14 решение 34): каждый пункт — 🔹, заголовок (после маркера текст кончается двоеточием) — 📌.
Маркер модели снимается один — эмодзи или простой («- », «1) »), без первого слова пункта («- first point» →
«🔹 first point»).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Final

from app.llm.merges import rules
from app.llm.merges.blocks import DescriptionBlocks
from app.llm.merges.description import MergedDescription
from app.llm.merges.merge_rules import MergeLexicons
from app.llm.merges.service_lines import LanguageMatch, ServiceLanguage, ServiceLineKey
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.texts.description_marks import BulletLine, MarkRole
from app.texts.paragraphs import collapse_spaces

LOGGER: logging.Logger = get_logger(LogArea.LLM)


class QualityEvent(str, Enum):
    """События нормализации качества в логе."""

    COMPACT_BULLET_TRIMMED = "merge_compact_bullet_trimmed"


class QualityReasonCode(str, Enum):
    """Причины диагностики в порядке проверки."""

    # Историческое имя: код значит «нормализация изменила текст», а не «нет пустой строки между блоками».
    MISSING_BLOCK_SPACING = "missing_block_spacing"
    WRONG_LANGUAGE_HEADING_DETECTED = "wrong_language_heading_detected"
    OFFICIAL_LINKS_HEADING_MISMATCH = "official_links_heading_mismatch"
    SCRIPT_MIX_CONTAMINATION = "script_mix_contamination"
    INCONSISTENT_BLOCK_LANGUAGE = "inconsistent_block_language"

    @property
    def is_hard_reject(self) -> bool:
        """Причина, которую нормализация не исправляет: ответ отвергается."""
        return self in HARD_REJECT_CODES


HARD_REJECT_CODES: Final[frozenset[QualityReasonCode]] = frozenset(
    {QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE, QualityReasonCode.SCRIPT_MIX_CONTAMINATION}
)


class QualityGateStatus(str, Enum):
    OK = "ok"
    NEEDS_NORMALIZATION = "needs_normalization"
    HARD_REJECT = "hard_reject"

    @classmethod
    def of(cls, codes: tuple[QualityReasonCode, ...]) -> QualityGateStatus:
        """Есть неисправимая причина — отказ; есть любая — нужна нормализация; нет причин — всё в порядке."""
        if any(code.is_hard_reject for code in codes):
            return cls.HARD_REJECT
        return cls.NEEDS_NORMALIZATION if codes else cls.OK


@dataclass(frozen=True)
class QualityRequest:
    """Что нужно знать о слоте: язык блока, название, число источников (0 — неизвестно, пункты не режутся)."""

    language: str
    title: str = field(default="", repr=False)
    source_count: int = 0


@dataclass(frozen=True)
class BulletNormalization:
    """Пункты и заголовки после нормализации маркеров: заголовок — 📌, любой другой пункт — 🔹, какой бы маркер ни
    поставила модель.

    Первая строка без маркера — вводная: в ней только схлопываются пробелы.
    """

    lines: tuple[str, ...] = field(repr=False)
    neutral_bullets_count: int = 0
    headings_count: int = 0

    @classmethod
    def of(cls, theses_lines: tuple[str, ...]) -> BulletNormalization:
        lines: list[str] = []
        for index, line in enumerate(theses_lines):
            bullet: BulletLine = BulletLine.of(line)
            if index == 0 and not bullet.is_marked:
                lines.append(collapse_spaces(line))
                continue
            role: MarkRole = MarkRole.HEADING if bullet.is_heading else MarkRole.BULLET
            lines.append((role.prefix + bullet.content).strip())
        roles: tuple[MarkRole | None, ...] = tuple(BulletLine.of(line).role for line in lines)
        return cls(tuple(lines), roles.count(MarkRole.BULLET), roles.count(MarkRole.HEADING))


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
        bullet_count: int = sum(1 for line in theses_lines if BulletLine.of(line).is_list_item)
        if source_count <= 0 or source_count > rules.COMPACT_MAX_SOURCES or bullet_count <= rules.COMPACT_BULLET_MAX:
            return cls(theses_lines, False, bullet_count, bullet_count, source_count)
        kept_lines: list[str] = []
        kept_bullets: int = 0
        for line in theses_lines:
            if not BulletLine.of(line).is_list_item:
                kept_lines.append(line)
            elif kept_bullets < rules.COMPACT_BULLET_MAX:
                kept_lines.append(line)
                kept_bullets += 1
        return cls(tuple(kept_lines), True, bullet_count, kept_bullets, source_count)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(
            QualityEvent.COMPACT_BULLET_TRIMMED,
            source_count=self.source_count,
            bullets_before=self.bullets_before,
            bullets_after=self.bullets_after,
            cap=rules.COMPACT_BULLET_MAX,
        )


@dataclass(frozen=True)
class ServiceLineFix:
    """Блоки после снятия повторов тезиса и замены служебных строк не того языка каноническими."""

    blocks: DescriptionBlocks
    wrong_language_heading_detected: bool
    official_links_heading_mismatch: bool

    @classmethod
    def of(cls, blocks: DescriptionBlocks, language: str, lexicons: MergeLexicons) -> ServiceLineFix:
        """Повторы снимаются по исходным блокам, замены смотрят на исходные служебные строки — поэтому призыв,
        снятый как повтор тезиса, может вернуться каноническим."""
        fixed: DescriptionBlocks = blocks
        if blocks.is_single_echo_cta:
            fixed = replace(fixed, cta="")
        if blocks.is_single_echo_thesis:
            fixed = replace(fixed, hook="")
        wrong_heading: bool = False
        mismatch: bool = False
        service: ServiceLanguage = lexicons.service
        if blocks.lead_in and LanguageMatch(service.detect_service(blocks.lead_in), language).is_wrong:
            lead_in: str = lexicons.catalog.line(language, ServiceLineKey.LEAD_IN)
            fixed = replace(fixed, theses_lines=(lead_in, *fixed.theses_lines[1:]))
            wrong_heading = True
        if blocks.links_heading:
            expected: str = lexicons.catalog.line(language, ServiceLineKey.LINKS_HEADING)
            mismatch = blocks.links_heading != expected
            if mismatch or LanguageMatch(service.detect_service(blocks.links_heading), language).is_wrong:
                fixed = replace(fixed, links_heading=expected)
                wrong_heading = True
        if blocks.has_short_cta and LanguageMatch(service.detect_service(blocks.cta), language).is_wrong:
            fixed = replace(fixed, cta=lexicons.catalog.cta_preserving_hashtags(blocks.cta, language))
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

    def reason_codes(self, suspects: tuple[str, ...], hook_language: str) -> tuple[QualityReasonCode, ...]:
        """Причины в порядке проверки; тезис на языке, который не определился, — не причина."""
        checks: tuple[tuple[bool, QualityReasonCode], ...] = (
            (not self.block_spacing_ok, QualityReasonCode.MISSING_BLOCK_SPACING),
            (self.wrong_language_heading_detected, QualityReasonCode.WRONG_LANGUAGE_HEADING_DETECTED),
            (self.official_links_heading_mismatch, QualityReasonCode.OFFICIAL_LINKS_HEADING_MISMATCH),
            (bool(suspects), QualityReasonCode.SCRIPT_MIX_CONTAMINATION),
            (LanguageMatch(hook_language, self.request.language).is_wrong, QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE),
        )
        return tuple(code for is_found, code in checks if is_found)


@dataclass(frozen=True)
class QualityDiagnostics:
    """Диагностика качества описания; `semantic_gate_*` — статус и причины."""

    neutral_bullets_count: int
    headings_count: int
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
    def of(cls, findings: QualityFindings, lexicons: MergeLexicons) -> QualityDiagnostics:
        request: QualityRequest = findings.request
        blocks: DescriptionBlocks = DescriptionBlocks.of(findings.description_text, lexicons.cta)
        service: ServiceLanguage = lexicons.service
        hook_language: str = service.detect_paragraph(blocks.hook)
        suspects: tuple[str, ...] = lexicons.script_mix.suspects(
            (request.title, blocks.hook, *blocks.theses_lines), request.language
        )
        codes: tuple[QualityReasonCode, ...] = findings.reason_codes(suspects, hook_language)
        return cls(
            neutral_bullets_count=findings.bullets.neutral_bullets_count,
            headings_count=findings.bullets.headings_count,
            block_spacing_ok=findings.block_spacing_ok,
            block_language_expected=request.language,
            hook_language_detected=hook_language,
            lead_in_language_detected=service.detect_service(blocks.lead_in),
            links_heading_language_detected=service.detect_service(blocks.links_heading),
            cta_language_detected=service.detect_service(blocks.cta),
            language_consistency_ok=QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE not in codes,
            wrong_language_heading_detected=findings.wrong_language_heading_detected,
            script_mix_detected=bool(suspects),
            script_mix_suspects=suspects,
            semantic_gate_status=QualityGateStatus.of(codes),
            semantic_gate_reason_codes=codes,
        )


@dataclass(frozen=True)
class QualityNormalization:
    """Итог нормализации: описание после неё и диагностика итогового текста."""

    description: MergedDescription
    diagnostics: QualityDiagnostics

    @classmethod
    def of(cls, description: MergedDescription, request: QualityRequest, lexicons: MergeLexicons) -> QualityNormalization:
        """Описание в нормальном виде и диагностика итогового текста; пустое описание — пустое, без правок."""
        source_text: str = description.trimmed_lines_text
        if not source_text:
            empty: QualityFindings = QualityFindings("", request, True, False, False, BulletNormalization(lines=()))
            return cls(MergedDescription(""), QualityDiagnostics.of(empty, lexicons))
        fix: ServiceLineFix = ServiceLineFix.of(DescriptionBlocks.of(source_text, lexicons.cta), request.language, lexicons)
        bullets: BulletNormalization = BulletNormalization.of(fix.blocks.theses_lines)
        trim: CompactTrim = CompactTrim.of(bullets.lines, request.source_count)
        if trim.applied:
            trim.event.emit(LOGGER)
        rendered: str = replace(fix.blocks, theses_lines=trim.lines).render()
        findings: QualityFindings = QualityFindings(
            rendered,
            request,
            rendered == source_text,
            fix.wrong_language_heading_detected,
            fix.official_links_heading_mismatch,
            bullets,
        )
        return cls(MergedDescription(rendered), QualityDiagnostics.of(findings, lexicons))
