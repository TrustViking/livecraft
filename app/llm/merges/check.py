"""Проверка ответа модели на merge: диагностика стиля, проверка покрытия и восстановление форматирования.

Перенесено из restreamer, поведение как есть (CLAUDE.md §14 решение 23), порядок — `merge_executor.py` строки 168–305:
- `merge_validation.py::MergeSemanticDiagnostics`, `_build_merge_semantic_diagnostics` → `MergeDiagnostics.of`;
  `_log_merge_style_diagnostics` → `MergeDiagnostics.log_lines`;
- `_validate_coverage_preserving_merge_or_raise` → `MergeCheck.run`: проверки строго в донорском порядке, первая
  сработавшая даёт отказ-значение `MergeReject`; эхо тезиса чинится на месте (строка лога `hook_echo_repair_applied=yes`);
- `merge_formatting.py::_attempt_expanded_formatting_recovery`, `_normalize_formatting_only_description` →
  `FormattingRecovery.of`: от трёх источников отказ «много эмодзи» снимается снятием эмодзи и повторной проверкой.

Контекст строк лога донора (`branch`, `date_key`, `slot_key`) заменён на `slot=<slot_id>` (`MergeAttemptLabel`).
Текста описания и названия в строках лога нет. Поле `official_links_fill_applied` всегда `no`: вставку блока ссылок
исполнитель донора не делал никогда.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from app.llm.merges.agenda import AgendaLexicon
from app.llm.merges.description import MergedDescription
from app.llm.merges.hook import BadHookLexicon
from app.llm.merges.links import OfficialLinkHints, OfficialLinkSelection
from app.llm.merges.prompt_texts import SERVICE_HINTS_RESOURCE
from app.llm.merges.quality import (
    QualityDiagnostics,
    QualityGateStatus,
    QualityNormalization,
    QualityRequest,
    QualityRules,
)
from app.llm.merges.reject import MergeReject, MergeRejectCode
from app.llm.merges.rules import (
    AGENDA_MIN_BULLETS,
    COMPACT_BULLET_MAX,
    COMPACT_MAX_SOURCES,
    EMOJI_MAX,
    FORMATTING_RECOVERY_MIN_SOURCES,
    HOOK_MARKS,
    HOOK_MIN_CHARS,
    MIN_BULLETS_EXTRA_OVER_SOURCES,
    MIN_BULLETS_FLOOR,
    MIN_BULLETS_MIN_SOURCES,
    OVERLOADED_BULLETS_MIN_LIST,
    OVERLOADED_BULLETS_REJECT,
    STYLE_CONTRACT_VERSION,
)
from app.observability.logging_setup import get_logger
from app.resources.loader import TextResource
from app.texts.description_marks import ALLOWED_BULLET_MARKERS, bullet_marker_for_line, extract_named_entities
from app.texts.paragraphs import normalize_newlines

if TYPE_CHECKING:
    from app.sources.language import TextLanguageDetector
    from app.sources.video import SourceVideo

LOGGER: logging.Logger = get_logger("llm")

# Название-перечень: «1) », «2) » — пункт под номером прямо в названии.
NUMBERED_DUMP_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\d\)\s")
OVERLOADED_DETAIL: Final[str] = "count={count}"
LINE_BREAK: Final[str] = "\n"
LOG_JOINER: Final[str] = ","
LOG_NONE: Final[str] = "none"
YES: Final[str] = "yes"
NO: Final[str] = "no"
NAMED_ENTITIES_METRIC: Final[str] = "informational"
# Действия восстановления форматирования — имена донора в строке лога.
ACTION_REDUCED_EMOJI: Final[str] = "reduced_non_structural_emoji"
ACTION_REAPPLIED_QUALITY: Final[str] = "reapplied_merge_quality_normalization"
OUTCOME_APPLIED: Final[str] = "applied"
OUTCOME_REVEALED: Final[str] = "revealed_non_formatting_issue"


def _flag(value: bool) -> str:
    return YES if value else NO


@dataclass(frozen=True)
class MergeCheckRules:
    """Всё, чем пользуется проверка ответа: правила качества (в них призывы), негодный тезис, заголовки повестки,
    подсказки служебных строк и контекста официальных ссылок."""

    quality: QualityRules
    bad_hooks: BadHookLexicon
    agenda: AgendaLexicon
    service_hints: tuple[str, ...]
    link_hints: OfficialLinkHints

    @classmethod
    def load(cls, detector: TextLanguageDetector | None = None) -> MergeCheckRules:
        return cls(
            quality=QualityRules.load(detector),
            bad_hooks=BadHookLexicon.load(),
            agenda=AgendaLexicon.load(),
            service_hints=TextResource(SERVICE_HINTS_RESOURCE).lines,
            link_hints=OfficialLinkHints.load(),
        )


@dataclass(frozen=True)
class MergeAttemptLabel:
    """Какая попытка merge проверяется: слот, язык блока, модель, номер попытки — начало строк лога."""

    slot_id: str
    language: str
    model: str
    attempt: int

    @property
    def prefix(self) -> str:
        return f"slot={self.slot_id} language={self.language} model={self.model} attempt={self.attempt}"


@dataclass(frozen=True)
class MergeCheckRequest:
    """Что о попытке не меняется между проверкой и восстановлением: метка, название ответа, источники слота,
    отбор официальных ссылок и сколько ссылок было в разобранном ответе (донор считает их до починок текста)."""

    label: MergeAttemptLabel
    title: str = field(repr=False)
    sources: tuple[SourceVideo, ...] = field(repr=False)
    links: OfficialLinkSelection
    links_in_answer: int

    @classmethod
    def of(
        cls,
        label: MergeAttemptLabel,
        title: str,
        answer: MergedDescription,
        sources: Sequence[SourceVideo],
        rules: MergeCheckRules,
    ) -> MergeCheckRequest:
        """Запрос по разобранному ответу: ссылки источников отбираются, ссылки ответа считаются по его тексту."""
        return cls(
            label=label,
            title=title,
            sources=tuple(sources),
            links=OfficialLinkSelection.for_sources(sources, rules.link_hints),
            links_in_answer=answer.official_link_count,
        )

    @property
    def source_count(self) -> int:
        return len(self.sources)


@dataclass(frozen=True)
class MergeDiagnostics:
    """Диагностика стиля описания — поля `MergeSemanticDiagnostics` донора; `quality` — диагностика качества."""

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
    official_links_found_in_sources: int
    official_links_kept: int
    official_links_in_output: int
    official_links_fill_applied: bool
    quality: QualityDiagnostics

    @classmethod
    def of(
        cls,
        request: MergeCheckRequest,
        description: MergedDescription,
        quality: QualityDiagnostics,
        rules: MergeCheckRules,
    ) -> MergeDiagnostics:
        """Диагностика описания; имена из источников — по названию и описанию видео до чистки, как у донора."""
        trimmed: MergedDescription = MergedDescription(str(description.text or "").strip())
        markers: list[str] = [
            marker for marker in map(bullet_marker_for_line, normalize_newlines(trimmed.text).split(LINE_BREAK)) if marker
        ]
        semantic: int = sum(1 for marker in markers if marker in ALLOWED_BULLET_MARKERS)
        source_entities: set[str] = cls._source_entities(request.sources)
        answer_entities: set[str] = extract_named_entities(f"{request.title.strip()}{LINE_BREAK}{trimmed.text}")
        paragraphs: list[str] = trimmed.paragraphs
        first: str = paragraphs[0] if paragraphs else ""
        return cls(
            hook_present=len(first) >= HOOK_MIN_CHARS and any(mark in first for mark in HOOK_MARKS),
            agenda_block_present=len(markers) >= AGENDA_MIN_BULLETS or trimmed.contains_agenda_heading(rules.agenda),
            bullet_points_count=len(markers),
            semantic_bullets_count=semantic,
            bullets_with_emoji_count=semantic,
            bullets_with_plain_marker_count=len(markers) - semantic,
            bullet_marker_types=tuple(dict.fromkeys(markers)),
            named_entities_preserved=len(source_entities & answer_entities),
            source_named_entities_total=len(source_entities),
            emoji_count=trimmed.emoji_count,
            official_links_found_in_sources=request.links.found_in_sources,
            official_links_kept=len(request.links.kept_links),
            official_links_in_output=request.links_in_answer,
            official_links_fill_applied=False,
            quality=quality,
        )

    @staticmethod
    def _source_entities(sources: Sequence[SourceVideo]) -> set[str]:
        entities: set[str] = set()
        for source in sources:
            title: str = source.metadata.title if source.metadata is not None else ""
            body: str = source.metadata.description if source.metadata is not None else ""
            entities.update(extract_named_entities(f"{title.strip()}{LINE_BREAK}{body.strip()}"))
        return entities

    def log_lines(self, label: MergeAttemptLabel) -> tuple[str, str]:
        """Строки `merge_style_coverage` и `merge_semantic_gate` — ключи и порядок донора, без текста описания."""
        return self._style_line(label), self._gate_line(label)

    def _style_line(self, label: MergeAttemptLabel) -> str:
        quality: QualityDiagnostics = self.quality
        return (
            f"merge_style_coverage {label.prefix} style_contract_version={STYLE_CONTRACT_VERSION} "
            f"hook_present={_flag(self.hook_present)} agenda_block_present={_flag(self.agenda_block_present)} "
            f"bullet_points_count={self.bullet_points_count} semantic_bullets_count={self.semantic_bullets_count} "
            f"bullets_with_emoji_count={self.bullets_with_emoji_count} "
            f"bullets_with_plain_marker_count={self.bullets_with_plain_marker_count} "
            f"bullet_marker_types={LOG_JOINER.join(self.bullet_marker_types) or LOG_NONE} "
            f"neutral_bullets_count={quality.neutral_bullets_count} accent_bullets_count={quality.accent_bullets_count} "
            f"accent_marker_types={LOG_JOINER.join(quality.accent_marker_types) or LOG_NONE} "
            f"accent_overflow={_flag(quality.accent_overflow)} block_spacing_ok={_flag(quality.block_spacing_ok)} "
            f"named_entities_preserved={self.named_entities_preserved} "
            f"source_named_entities_total={self.source_named_entities_total} "
            f"named_entities_metric={NAMED_ENTITIES_METRIC} emoji_count={self.emoji_count} "
            f"official_links_found_in_sources={self.official_links_found_in_sources} "
            f"official_links_kept={self.official_links_kept} official_links_in_output={self.official_links_in_output} "
            f"official_links_fill_applied={_flag(self.official_links_fill_applied)}"
        )

    def _gate_line(self, label: MergeAttemptLabel) -> str:
        quality: QualityDiagnostics = self.quality
        codes: str = LOG_JOINER.join(code.value for code in quality.semantic_gate_reason_codes) or LOG_NONE
        return (
            f"merge_semantic_gate {label.prefix} block_language_expected={quality.block_language_expected} "
            f"hook_language_detected={quality.hook_language_detected} "
            f"lead_in_language_detected={quality.lead_in_language_detected} "
            f"links_heading_language_detected={quality.links_heading_language_detected} "
            f"cta_language_detected={quality.cta_language_detected} "
            f"language_consistency_ok={_flag(quality.language_consistency_ok)} "
            f"wrong_language_heading_detected={_flag(quality.wrong_language_heading_detected)} "
            f"script_mix_detected={_flag(quality.script_mix_detected)} "
            f"script_mix_suspects={LOG_JOINER.join(quality.script_mix_suspects) or LOG_NONE} "
            f"semantic_gate_status={quality.semantic_gate_status.value} semantic_gate_reason_codes={codes}"
        )


@dataclass(frozen=True)
class MergeCheckPassed:
    """Ответ прошёл проверку: описание (эхо тезиса, если было, починено) и диагностика до починки — как у донора."""

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
    rules: MergeCheckRules = field(repr=False)

    @classmethod
    def of(cls, request: MergeCheckRequest, normalization: QualityNormalization, rules: MergeCheckRules) -> MergeCheck:
        """Проверка описания после нормализации качества; диагностика стиля строится по нему."""
        diagnostics: MergeDiagnostics = MergeDiagnostics.of(
            request, normalization.description, normalization.diagnostics, rules
        )
        return cls(request, normalization.description, normalization.diagnostics, diagnostics, rules)

    def run(self) -> MergeCheckPassed | MergeReject:
        """Проверки в порядке донора; первая сработавшая — отказ."""
        description: MergedDescription | MergeReject = self._repetition_checked()
        if isinstance(description, MergeReject):
            return description
        reject: MergeReject | None = self._opening_reject(description) or self._structure_reject(description)
        if reject is not None:
            return reject
        if self.quality.semantic_gate_status == QualityGateStatus.HARD_REJECT:
            return MergeReject.semantic_gate([code.value for code in self.quality.semantic_gate_reason_codes])
        return MergeCheckPassed(description=description, diagnostics=self.diagnostics)

    def run_with_recovery(self) -> MergeCheckPassed | MergeReject:
        """Проверка; отказ «много эмодзи» при трёх и больше источниках — попытка восстановления форматирования."""
        verdict: MergeCheckPassed | MergeReject = self.run()
        if isinstance(verdict, MergeCheckPassed):
            return verdict
        return FormattingRecovery.of(self, verdict).verdict

    def _repetition_checked(self) -> MergedDescription | MergeReject:
        """Пересказ по источникам, повтор абзацев, эхо тезиса (чинится), повтор соседних строк."""
        description: MergedDescription = self.description
        if description.looks_like_per_source_dump:
            return MergeReject(MergeRejectCode.PER_SOURCE_ENUMERATION)
        if description.has_duplicate_paragraphs:
            return MergeReject(MergeRejectCode.DUPLICATE_PARAGRAPH)
        if description.has_hook_echo_in_body:
            repaired: MergedDescription | None = description.hook_echo_repaired()
            if repaired is None:
                return MergeReject(MergeRejectCode.HOOK_ECHO_IN_BODY)
            description = repaired
            LOGGER.info("hook_echo_repair_applied=yes %s", self.request.label.prefix)
        if description.has_adjacent_duplicate_lines:
            return MergeReject(MergeRejectCode.DUPLICATE_PARAGRAPH)
        return description

    def _opening_reject(self, description: MergedDescription) -> MergeReject | None:
        """Призыв в начальных строках раньше тезиса и пунктов; служебная строка или негодный тезис в первом абзаце."""
        rules: MergeCheckRules = self.rules
        if description.cta_in_opening_lines(rules.quality.cta, rules.bad_hooks, rules.service_hints):
            return MergeReject(MergeRejectCode.CTA_AS_FIRST_PARAGRAPH)
        if description.cta_in_hook(rules.bad_hooks, rules.service_hints):
            return MergeReject(MergeRejectCode.CTA_IN_HOOK)
        return None

    def _structure_reject(self, description: MergedDescription) -> MergeReject | None:
        """Число пунктов, эмодзи, перегруженные пункты, название-перечень, призыв в тезисе, похожие начала абзацев."""
        bullets: int = self.diagnostics.bullet_points_count
        source_count: int = self.request.source_count
        min_bullets: int = max(source_count + MIN_BULLETS_EXTRA_OVER_SOURCES, MIN_BULLETS_FLOOR)
        if source_count >= MIN_BULLETS_MIN_SOURCES and bullets < min_bullets:
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
        paragraphs: list[str] = description.paragraphs
        if paragraphs and self.rules.quality.cta.starts_with_prefix(paragraphs[0]):
            return MergeReject(MergeRejectCode.CTA_AS_FIRST_PARAGRAPH)
        if description.has_similar_paragraph_prefixes:
            return MergeReject(MergeRejectCode.DUPLICATE_PARAGRAPH)
        return None


@dataclass(frozen=True)
class FormattingRecovery:
    """Восстановление форматирования после отказа: итог (`verdict` — прошедшая проверка или отказ) и что было
    сделано с текстом (`actions`, имена донора). Не применялось — итог есть исходный отказ."""

    verdict: MergeCheckPassed | MergeReject
    actions: tuple[str, ...]

    @classmethod
    def of(cls, check: MergeCheck, reject: MergeReject) -> FormattingRecovery:
        """Только от трёх источников и только для отказа «много эмодзи»: снять эмодзи вне маркеров, дважды
        нормализовать качество (как донор: сначала без названия и числа источников, затем с названием), построить
        диагностику заново и проверить снова. Текст не изменился — исходный отказ без строки лога."""
        if check.request.source_count < FORMATTING_RECOVERY_MIN_SOURCES:
            return cls(verdict=reject, actions=())
        if MergeRejectCode.EXCESSIVE_EMOJI_USAGE.value not in reject.reason_codes:
            return cls(verdict=reject, actions=())
        formatted, actions = cls._formatted(check, reject)
        if formatted.text == check.description.text or not actions:
            return cls(verdict=reject, actions=actions)
        request: MergeCheckRequest = check.request
        normalization: QualityNormalization = formatted.quality_normalized(
            QualityRequest(language=request.label.language, title=request.title), check.rules.quality
        )
        recovered: MergeCheck = MergeCheck.of(request, normalization, check.rules)
        outcome: FormattingRecovery = cls(verdict=recovered.run(), actions=actions)
        LOGGER.info("%s", outcome.log_line(check, reject, recovered.diagnostics.emoji_count))
        return outcome

    @staticmethod
    def _formatted(check: MergeCheck, reject: MergeReject) -> tuple[MergedDescription, tuple[str, ...]]:
        """`_normalize_formatting_only_description` донора: эмодзи снимаются, затем нормализация качества."""
        description: MergedDescription = MergedDescription(str(check.description.text or "").strip())
        actions: list[str] = []
        if MergeRejectCode.EXCESSIVE_EMOJI_USAGE.value in reject.reason_codes:
            stripped, changed = description.without_non_structural_emoji()
            if changed:
                description = stripped
                actions.append(ACTION_REDUCED_EMOJI)
        normalized: MergedDescription = description.quality_normalized(
            QualityRequest(language=check.request.label.language), check.rules.quality
        ).description
        if normalized.text != description.text:
            description = normalized
            actions.append(ACTION_REAPPLIED_QUALITY)
        return description, tuple(actions)

    @property
    def passed(self) -> MergeCheckPassed | None:
        return self.verdict if isinstance(self.verdict, MergeCheckPassed) else None

    @property
    def reject(self) -> MergeReject | None:
        return self.verdict if isinstance(self.verdict, MergeReject) else None

    @property
    def outcome(self) -> str:
        return OUTCOME_APPLIED if self.passed is not None else OUTCOME_REVEALED

    def log_line(self, check: MergeCheck, original: MergeReject, emoji_after: int) -> str:
        """Строка `merge_llm_validation_salvage` с ключами донора; при новом отказе — его коды."""
        replacement: str = (
            ""
            if self.reject is None
            else f" replacement_reason_codes={LOG_JOINER.join(self.reject.reason_codes) or LOG_NONE}"
        )
        return (
            f"merge_llm_validation_salvage {check.request.label.prefix} outcome={self.outcome} "
            f"reason_codes={LOG_JOINER.join(original.reason_codes) or LOG_NONE}{replacement} "
            f"actions={LOG_JOINER.join(self.actions) or LOG_NONE} "
            f"emoji_before={check.diagnostics.emoji_count} emoji_after={emoji_after}"
        )
