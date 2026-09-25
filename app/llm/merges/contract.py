"""Контракт описания merge: compact / expanded / narrative (restreamer `app\\llm\\merges\\merge_prompt.py`).

`MergeContract.select` — `_select_merge_contract_mode` донора: от трёх источников — расширенный контракт (диапазон пунктов
растёт с числом источников, от четырёх — строка-якорь спикеров), от двух и «одно событие» — повествовательный, иначе
компактный. `max_body_paragraphs` контракта — предел абзацев тела, с которым разбирается ответ модели (`MergeAnswer`).

У донора два разных поиска имён, и оба перенесены как есть, без объединения: «одно событие» ищет цепочки слов с заглавной
буквы после снятия всех не-словесных знаков (`_sources_share_single_event`, своя внутренняя функция), а строка-якорь
берёт имена правилом `merge_text_utils._extract_named_entities` (здесь — `app\\texts\\description_marks.py`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.llm.merges import rules
from app.llm.merges.prompt_texts import MergeContractMode, MergePromptTexts, fill_placeholders
from app.texts.description_marks import extract_named_entities

__all__ = ["MergeContract", "MergeContractMode", "SourceTextSet"]

WORD_SPLIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
NON_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\w]")
MIN_RUN_WORDS: Final[int] = 2
SPEAKER_ANCHOR_PLACEHOLDER: Final[str] = "{speaker_anchor_line}"
RANGE_JOINER: Final[str] = "-"


def capitalized_runs(text: str) -> set[str]:
    """Цепочки из двух и больше слов подряд, начинающихся с заглавной буквы; из слов сняты не-словесные знаки.

    Внутренняя `_extract_named_entities` донора в `_sources_share_single_event` — чистое преобразование строки.
    """
    runs: set[str] = set()
    current: list[str] = []
    for word in WORD_SPLIT_PATTERN.split(text):
        cleaned: str = NON_WORD_PATTERN.sub("", word)
        if cleaned and cleaned[0].isalpha() and cleaned[0].isupper():
            current.append(cleaned)
            continue
        if len(current) >= MIN_RUN_WORDS:
            runs.add(" ".join(current))
        current = []
    if len(current) >= MIN_RUN_WORDS:
        runs.add(" ".join(current))
    return runs


@dataclass(frozen=True)
class SourceTextSet:
    """Тексты источников слота, по которым выбирается контракт: сходство источников и имена спикеров."""

    texts: tuple[str, ...]

    @property
    def shares_single_event(self) -> bool:
        """Не меньше пяти цепочек имён встречаются хотя бы в двух источниках — источники об одном событии."""
        per_source: list[set[str]] = [capitalized_runs(text) for text in self.texts]
        everything: set[str] = set().union(*per_source) if per_source else set()
        shared: int = sum(1 for run in everything if sum(1 for runs in per_source if run in runs) >= 2)
        return shared >= rules.NARRATIVE_MIN_SHARED_ENTITIES

    @property
    def speaker_names(self) -> tuple[str, ...]:
        """До восьми имён из всех источников: сначала самые длинные, при равной длине — по алфавиту."""
        names: set[str] = set()
        for text in self.texts:
            names.update(extract_named_entities(text))
        return tuple(sorted(names, key=lambda name: (-len(name), name))[: rules.SPEAKER_NAMES_MAX])

    def speaker_anchor_line(self, source_count: int, texts: MergePromptTexts) -> str:
        """Строка-якорь спикеров для четырёх и больше источников; нет имён — пусто."""
        if source_count < rules.SPEAKER_ANCHOR_MIN_SOURCES:
            return ""
        names: tuple[str, ...] = self.speaker_names
        if not names:
            return ""
        return texts.speaker_anchor_line(source_count, min(len(names), source_count - 1), names)


def _expanded_bullet_range(source_count: int) -> tuple[int, int]:
    for max_sources, bullet_min, bullet_max in rules.EXPANDED_BULLET_RANGES:
        if source_count <= max_sources:
            return bullet_min, bullet_max
    return rules.EXPANDED_BULLET_RANGE_LARGE


def _range_label(bullet_min: int, bullet_max: int) -> str:
    return f"{bullet_min}{RANGE_JOINER}{bullet_max}"


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
        """«4-7» и подобное; у повествовательного контракта пунктов нет — `None`, как у донора."""
        if self.mode is MergeContractMode.NARRATIVE:
            return None
        return _range_label(self.bullet_range_min, self.bullet_range_max)

    @classmethod
    def select(cls, source_texts: tuple[str, ...], texts: MergePromptTexts) -> MergeContract:
        """Контракт по числу источников и их текстам (донор передаёт очищенные описания источников)."""
        sources: SourceTextSet = SourceTextSet(texts=source_texts)
        count: int = len(source_texts)
        if count >= rules.EXPANDED_MIN_SOURCES:
            return cls._expanded(sources, texts)
        if count >= rules.NARRATIVE_MIN_SOURCES and sources.shares_single_event:
            return cls._narrative(count, texts)
        return cls._compact(count, texts)

    @staticmethod
    def _compact_values(source_count: int) -> dict[str, object]:
        return {
            "source_count": source_count,
            "compact_bullet_min": rules.COMPACT_BULLET_MIN,
            "compact_bullet_max": rules.COMPACT_BULLET_MAX,
            "compact_bullet_range": _range_label(rules.COMPACT_BULLET_MIN, rules.COMPACT_BULLET_MAX),
        }

    @classmethod
    def _expanded(cls, sources: SourceTextSet, texts: MergePromptTexts) -> MergeContract:
        count: int = len(sources.texts)
        bullet_min, bullet_max = _expanded_bullet_range(count)
        anchor: str = sources.speaker_anchor_line(count, texts)
        template: str = texts.contract_template(MergeContractMode.EXPANDED)
        compact: dict[str, object] = cls._compact_values(count)
        block: str = fill_placeholders(
            template,
            {
                "source_count": count,
                "expanded_bullet_min": bullet_min,
                "expanded_bullet_max": bullet_max,
                "expanded_bullet_range": _range_label(bullet_min, bullet_max),
                "compact_bullet_min": compact["compact_bullet_min"],
                "compact_bullet_max": compact["compact_bullet_max"],
                "compact_bullet_range": compact["compact_bullet_range"],
                "speaker_anchor_line": anchor,
            },
        )
        if anchor and SPEAKER_ANCHOR_PLACEHOLDER not in template:
            block = f"{block}\n{anchor}".strip()
        return cls(
            mode=MergeContractMode.EXPANDED,
            source_count=count,
            bullet_range_min=bullet_min,
            bullet_range_max=bullet_max,
            expanded_structure_enabled=True,
            max_body_paragraphs=rules.EXPANDED_MAX_BODY_PARAGRAPHS,
            block=block,
        )

    @classmethod
    def _narrative(cls, count: int, texts: MergePromptTexts) -> MergeContract:
        block: str = fill_placeholders(texts.contract_template(MergeContractMode.NARRATIVE), cls._compact_values(count))
        return cls(
            mode=MergeContractMode.NARRATIVE,
            source_count=count,
            bullet_range_min=0,
            bullet_range_max=0,
            expanded_structure_enabled=False,
            max_body_paragraphs=rules.NARRATIVE_MAX_BODY_PARAGRAPHS,
            block=block,
        )

    @classmethod
    def _compact(cls, count: int, texts: MergePromptTexts) -> MergeContract:
        block: str = fill_placeholders(texts.contract_template(MergeContractMode.COMPACT), cls._compact_values(count))
        return cls(
            mode=MergeContractMode.COMPACT,
            source_count=count,
            bullet_range_min=rules.COMPACT_BULLET_MIN,
            bullet_range_max=rules.COMPACT_BULLET_MAX,
            expanded_structure_enabled=False,
            max_body_paragraphs=rules.COMPACT_MAX_BODY_PARAGRAPHS,
            block=block,
        )
