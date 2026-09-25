"""Промт merge для слота (restreamer `app\\llm\\merges\\merge_prompt.py::build_llm_merge_prompt_text`).

`MergePrompt.of` готовит источники (`MergeSource`), выбирает контракт (`MergeContract`) по очищенным описаниям и пишет в лог
три строки донора: по источнику, итог по источникам, выбранный контракт. `MergePrompt.text` — промт по боевому шаблону:
шаблон с блоком правил и контракта, затем политика смешения тем и политика ссылок, а инструкция повтора — последней, чтобы
начало промта (правила, контракт, источники) у первой попытки и у повтора совпадало. Запасной ветки донора без шаблона нет:
шаблон всегда приходит из ресурсов программы.

Меньше двух источников — не исключение, а `MergePromptRefusal`: такой слот merge не делает.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pycountry

from app.llm.merges.contract import MergeContract
from app.llm.merges.prompt_texts import MergeContractMode, MergePromptTexts
from app.llm.merges.retry import RetryProfile
from app.llm.merges.source import MergeSource
from app.observability.logging_setup import get_logger

if TYPE_CHECKING:
    from app.sources.video import SourceVideo

LOGGER: logging.Logger = get_logger("llm")

MIN_SOURCES: Final[int] = 2
UNKNOWN_LANGUAGE_NAME: Final[str] = "Unknown"
MERGE_CONTRACT_PLACEHOLDER: Final[str] = "{merge_contract_block}"
PARAGRAPH_BREAK: Final[str] = "\n\n"
YES: Final[str] = "yes"
NO: Final[str] = "no"


def language_full_name(language: str) -> str:
    """Английское название языка по pycountry («uk» → «Ukrainian»); нет в pycountry — код заглавными; пусто — «Unknown».

    Донор: `core\\language_display.py::language_full_name` (запасное — `language_display_name`).
    """
    code: str = str(language or "").strip().lower()
    if not code:
        return UNKNOWN_LANGUAGE_NAME
    found: Any = pycountry.languages.get(alpha_2=code)
    if found is not None:
        return str(found.name)
    return str(language or "").strip().upper()


@dataclass(frozen=True)
class MergePromptRefusal:
    """Промт не собирается: источников меньше двух (merge нужен только для слота из нескольких видео)."""

    language: str
    source_count: int

    @property
    def log_line(self) -> str:
        return f"merge_prompt_refused language={self.language} source_count={self.source_count} min_sources={MIN_SOURCES}"


@dataclass(frozen=True)
class MergePrompt:
    """Промт merge одного слота: язык, источники, контракт, профиль повтора (`None` — первая попытка) и тексты."""

    language: str
    sources: tuple[MergeSource, ...]
    contract: MergeContract
    retry: RetryProfile | None
    texts: MergePromptTexts

    @classmethod
    def of(
        cls,
        language: str,
        videos: Sequence[SourceVideo],
        texts: MergePromptTexts,
        retry: RetryProfile | None = None,
    ) -> MergePrompt | MergePromptRefusal:
        if len(videos) < MIN_SOURCES:
            refusal: MergePromptRefusal = MergePromptRefusal(language=language, source_count=len(videos))
            LOGGER.warning(refusal.log_line)
            return refusal
        sources: tuple[MergeSource, ...] = tuple(MergeSource.of(video, texts) for video in videos)
        contract: MergeContract = MergeContract.select(tuple(source.prompt_description for source in sources), texts)
        prompt: MergePrompt = cls(language=language, sources=sources, contract=contract, retry=retry, texts=texts)
        for line in prompt.log_lines:
            LOGGER.info(line)
        return prompt

    def with_retry(self, retry: RetryProfile | None) -> MergePrompt:
        """Тот же промт с другим профилем повтора: источники и контракт не пересобираются."""
        return MergePrompt(language=self.language, sources=self.sources, contract=self.contract, retry=retry, texts=self.texts)

    @property
    def language_name(self) -> str:
        return language_full_name(self.language)

    @property
    def sources_block(self) -> str:
        return PARAGRAPH_BREAK.join(source.prompt_block(index) for index, source in enumerate(self.sources, start=1))

    def contract_block_with(self, retry: RetryProfile | None) -> str:
        """Правила структуры первыми (общее начало всех промтов), затем контракт; с профилем — ещё инструкция повтора.

        Донор: `_merge_contract_block_with_retry`. В промт блок идёт без повтора (`contract_block`).
        """
        block: str = self.contract.block.strip()
        rules_text: str = self.texts.structural_rules.strip()
        if rules_text:
            block = f"{rules_text}{PARAGRAPH_BREAK}{block}".strip()
        instruction: str = retry.instruction_block if retry is not None else ""
        return f"{block}{PARAGRAPH_BREAK}{instruction}" if instruction else block

    @property
    def contract_block(self) -> str:
        return self.contract_block_with(None)

    @property
    def retry_block(self) -> str:
        return self.retry.instruction_block if self.retry is not None else ""

    @property
    def text(self) -> str:
        """Полный текст промта (ветка донора с шаблоном `llm.merge_title_description_prompt`)."""
        template: str = self.texts.title_description.strip()
        contract_block: str = self.contract_block
        formatted: str = template.format(
            language_name=self.language_name,
            sources_block=self.sources_block,
            youtube_candidates_block="",
            merge_contract_block=contract_block,
        ).strip()
        if MERGE_CONTRACT_PLACEHOLDER not in template:
            formatted = f"{formatted}{PARAGRAPH_BREAK}{contract_block}".strip()
        retry_suffix: str = f"{PARAGRAPH_BREAK}{self.retry_block}" if self.retry_block else ""
        return (
            f"{formatted}{PARAGRAPH_BREAK}{self.texts.cross_domain_policy}{PARAGRAPH_BREAK}"
            f"{self.texts.link_policy}{retry_suffix}"
        ).strip()

    @property
    def source_texts_for_quality(self) -> tuple[str, ...]:
        """Название и очищенное описание каждого источника — для проверки качества ответа."""
        return tuple(source.quality_text for source in self.sources)

    @property
    def log_lines(self) -> tuple[str, ...]:
        """Строки лога донора: `merge_source_text_prepared` на источник, `merge_prompt_sources_ready`,
        `merge_prompt_contract_selected` — счётчики и контракт, без текста источников."""
        raw_total: int = sum(source.description.raw_chars for source in self.sources)
        cleaned_total: int = sum(len(source.prompt_description) for source in self.sources)
        contract: MergeContract = self.contract
        return (
            *(source.log_line(index, self.language) for index, source in enumerate(self.sources, start=1)),
            (
                f"merge_prompt_sources_ready language={self.language} source_count={len(self.sources)} "
                f"raw_source_chars_total={raw_total} cleaned_source_chars_total={cleaned_total} hard_truncation=disabled"
            ),
            (
                f"merge_prompt_contract_selected language={self.language} source_count={contract.source_count} "
                f"contract_mode={contract.mode.value} expected_bullet_range={contract.bullet_range_label} "
                f"expanded_structure_enabled={YES if contract.expanded_structure_enabled else NO} "
                f"narrative_trigger={YES if contract.mode is MergeContractMode.NARRATIVE else NO}"
            ),
        )
