"""Контракт описания merge: compact / expanded / narrative — по числу источников и их сходству.

`MergeContract.select`: от трёх источников — расширенный контракт (диапазон пунктов растёт с числом источников,
от четырёх — строка-якорь спикеров), от двух и «одно событие» — повествовательный, иначе компактный.
`max_body_paragraphs` контракта — предел абзацев тела, с которым разбирается ответ модели (`MergeAnswer`);
`MergeContract.min_bullets` — сколько пунктов нужно описанию слота из стольких источников.

Имена ищутся двумя разными правилами, и это разные вопросы. «Одно событие» сравнивает источники между собой по
цепочкам слов с заглавной буквы, из которых сняты все не-словесные знаки (`CapitalizedRuns`): регистр и короткие
слова («NATO EU») сохраняются, чтобы совпадение означало то же событие. Строка-якорь называет модели спикеров
по правилу имён собственных описания (`app\\texts\\description_marks.py::extract_named_entities`): слова не короче
трёх букв, в нижнем регистре — так имя в якоре совпадает с именем, которое потом ищется в ответе.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.core.text_format import NEWLINE, SPACE, WHITESPACE_RUN_PATTERN
from app.llm.merges import rules
from app.llm.merges.prompt_texts import MergeContractMode, MergePromptTexts, Placeholder, PromptTemplate
from app.texts.description_marks import extract_named_entities

__all__ = ["BulletRange", "CapitalizedRuns", "MergeContract", "MergeContractMode", "SourceTextSet"]

NON_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\w]")
RANGE_TEMPLATE: Final[str] = "{low}-{high}"


@dataclass(frozen=True)
class CapitalizedRuns:
    """Цепочки из двух и больше слов подряд, начинающихся с заглавной буквы; из слов сняты не-словесные знаки.

    Правило «одного события»: источники сравниваются по таким цепочкам, регистр сохраняется."""

    text: str

    @property
    def names(self) -> set[str]:
        runs: set[str] = set()
        current: list[str] = []
        for word in (*WHITESPACE_RUN_PATTERN.split(self.text), ""):
            cleaned: str = NON_WORD_PATTERN.sub("", word)
            if cleaned and cleaned[0].isalpha() and cleaned[0].isupper():
                current.append(cleaned)
                continue
            if len(current) >= rules.EVENT_NAME_MIN_WORDS:
                runs.add(SPACE.join(current))
            current = []
        return runs


@dataclass(frozen=True)
class SourceTextSet:
    """Тексты источников слота, по которым выбирается контракт: сходство источников и имена спикеров."""

    texts: tuple[str, ...]

    @property
    def shares_single_event(self) -> bool:
        """Не меньше пяти цепочек имён встречаются хотя бы в двух источниках — источники об одном событии."""
        per_source: list[set[str]] = [CapitalizedRuns(text).names for text in self.texts]
        everything: set[str] = set().union(*per_source) if per_source else set()
        shared: int = sum(
            1 for run in everything if sum(1 for runs in per_source if run in runs) >= rules.NARRATIVE_SHARED_IN_SOURCES
        )
        return shared >= rules.NARRATIVE_MIN_SHARED_ENTITIES

    @property
    def speaker_names(self) -> tuple[str, ...]:
        """До восьми имён из всех источников: сначала самые длинные, при равной длине — по алфавиту."""
        names: set[str] = set()
        for text in self.texts:
            names.update(extract_named_entities(text))
        return tuple(sorted(names, key=lambda name: (-len(name), name))[: rules.SPEAKER_NAMES_MAX])

    def speaker_anchor_line(self, texts: MergePromptTexts) -> str:
        """Строка-якорь спикеров для четырёх и больше источников; нет имён — пусто."""
        source_count: int = len(self.texts)
        if source_count < rules.SPEAKER_ANCHOR_MIN_SOURCES:
            return ""
        names: tuple[str, ...] = self.speaker_names
        if not names:
            return ""
        return texts.speaker_anchor_line(source_count, min(len(names), source_count - 1), names)


@dataclass(frozen=True)
class BulletRange:
    """Сколько пунктов просит контракт: от `low` до `high`; `label` — «4-7»."""

    low: int
    high: int

    @classmethod
    def compact(cls) -> BulletRange:
        return cls(rules.COMPACT_BULLET_MIN, rules.COMPACT_BULLET_MAX)

    @classmethod
    def expanded(cls, source_count: int) -> BulletRange:
        """Диапазон растёт с числом источников."""
        for max_sources, low, high in rules.EXPANDED_BULLET_RANGES:
            if source_count <= max_sources:
                return cls(low, high)
        return cls(*rules.EXPANDED_BULLET_RANGE_LARGE)

    @property
    def label(self) -> str:
        return RANGE_TEMPLATE.format(low=self.low, high=self.high)


@dataclass(frozen=True)
class MergeContract:
    """Выбранный контракт: режим, диапазон пунктов, предел абзацев тела и текст блока контракта для промта."""

    mode: MergeContractMode
    source_count: int
    bullet_range_min: int
    bullet_range_max: int
    expanded_structure_enabled: bool
    max_body_paragraphs: int
    block: str

    @property
    def bullet_range_label(self) -> str | None:
        """«4-7» и подобное; у повествовательного контракта пунктов нет — `None`."""
        if self.mode is MergeContractMode.NARRATIVE:
            return None
        return BulletRange(self.bullet_range_min, self.bullet_range_max).label

    @classmethod
    def min_bullets(cls, source_count: int) -> int:
        """Сколько пунктов нужно описанию слота из стольких источников: на один больше источников, не меньше пяти."""
        return max(source_count + rules.MIN_BULLETS_EXTRA_OVER_SOURCES, rules.MIN_BULLETS_FLOOR)

    @classmethod
    def select(cls, source_texts: tuple[str, ...], texts: MergePromptTexts) -> MergeContract:
        """Контракт по числу источников и их текстам (очищенным описаниям источников)."""
        sources: SourceTextSet = SourceTextSet(texts=source_texts)
        count: int = len(source_texts)
        if count >= rules.EXPANDED_MIN_SOURCES:
            return cls._expanded(sources, texts)
        if count >= rules.NARRATIVE_MIN_SOURCES and sources.shares_single_event:
            return cls._simple(MergeContractMode.NARRATIVE, count, texts)
        return cls._simple(MergeContractMode.COMPACT, count, texts)

    @classmethod
    def _compact_values(cls, source_count: int) -> Mapping[Placeholder, object]:
        compact: BulletRange = BulletRange.compact()
        return {
            Placeholder.SOURCE_COUNT: source_count,
            Placeholder.COMPACT_BULLET_MIN: compact.low,
            Placeholder.COMPACT_BULLET_MAX: compact.high,
            Placeholder.COMPACT_BULLET_RANGE: compact.label,
        }

    @classmethod
    def _expanded(cls, sources: SourceTextSet, texts: MergePromptTexts) -> MergeContract:
        count: int = len(sources.texts)
        bullets: BulletRange = BulletRange.expanded(count)
        anchor: str = sources.speaker_anchor_line(texts)
        template: PromptTemplate = texts.contract_template(MergeContractMode.EXPANDED)
        compact: Mapping[Placeholder, object] = cls._compact_values(count)
        block: str = template.filled(
            {
                Placeholder.SOURCE_COUNT: count,
                Placeholder.EXPANDED_BULLET_MIN: bullets.low,
                Placeholder.EXPANDED_BULLET_MAX: bullets.high,
                Placeholder.EXPANDED_BULLET_RANGE: bullets.label,
                Placeholder.COMPACT_BULLET_MIN: compact[Placeholder.COMPACT_BULLET_MIN],
                Placeholder.COMPACT_BULLET_MAX: compact[Placeholder.COMPACT_BULLET_MAX],
                Placeholder.COMPACT_BULLET_RANGE: compact[Placeholder.COMPACT_BULLET_RANGE],
                Placeholder.SPEAKER_ANCHOR_LINE: anchor,
            }
        )
        if anchor and Placeholder.SPEAKER_ANCHOR_LINE.token not in template.text:
            block = f"{block}{NEWLINE}{anchor}".strip()
        return cls(
            mode=MergeContractMode.EXPANDED,
            source_count=count,
            bullet_range_min=bullets.low,
            bullet_range_max=bullets.high,
            expanded_structure_enabled=True,
            max_body_paragraphs=rules.EXPANDED_MAX_BODY_PARAGRAPHS,
            block=block,
        )

    @classmethod
    def _simple(cls, mode: MergeContractMode, count: int, texts: MergePromptTexts) -> MergeContract:
        """Компактный или повествовательный контракт: шаблон с числом источников и компактным диапазоном;
        у повествовательного пунктов нет (диапазон 0-0), тело длиннее."""
        is_narrative: bool = mode is MergeContractMode.NARRATIVE
        bullets: BulletRange = BulletRange(0, 0) if is_narrative else BulletRange.compact()
        return cls(
            mode=mode,
            source_count=count,
            bullet_range_min=bullets.low,
            bullet_range_max=bullets.high,
            expanded_structure_enabled=False,
            max_body_paragraphs=(
                rules.NARRATIVE_MAX_BODY_PARAGRAPHS if is_narrative else rules.COMPACT_MAX_BODY_PARAGRAPHS
            ),
            block=texts.contract_template(mode).filled(cls._compact_values(count)),
        )
