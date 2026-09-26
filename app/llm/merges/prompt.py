"""Промт merge для слота: источники, контракт и тексты промта в одном объекте.

`MergePrompt.of` готовит источники (`MergeSource`), выбирает контракт (`MergeContract`) по очищенным описаниям и пишет в лог
строку по каждому источнику, итог по источникам и выбранный контракт. `MergePrompt.text` — промт по шаблону: шаблон с
блоком правил и контракта, затем политика смешения тем и политика ссылок, а инструкция повтора — последней, чтобы
начало промта (правила, контракт, источники) у первой попытки и у повтора совпадало.

Меньше двух источников — не исключение, а `MergePromptRefusal`: такой слот merge не делает.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

import pycountry

from app.core.text_format import PARAGRAPH_BREAK
from app.llm.merges import rules
from app.llm.merges.contract import MergeContract
from app.llm.merges.prompt_texts import MergeContractMode, MergePromptTexts
from app.llm.merges.retry import RetryProfile
from app.llm.merges.source import MergeSource
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.sources.video import SourceVideo

LOGGER: logging.Logger = get_logger(LogArea.LLM)

UNKNOWN_LANGUAGE_NAME: Final[str] = "Unknown"
LANGUAGE_NAME_FIELD: Final[str] = "name"           # английское название языка в записи справочника pycountry
MERGE_CONTRACT_PLACEHOLDER: Final[str] = "{merge_contract_block}"
HARD_TRUNCATION_DISABLED: Final[str] = "disabled"   # тексты источников в промт идут целиком


class PromptEvent(str, Enum):
    """События промта в логе."""

    REFUSED = "merge_prompt_refused"
    SOURCES_READY = "merge_prompt_sources_ready"
    CONTRACT_SELECTED = "merge_prompt_contract_selected"


@dataclass(frozen=True)
class MergePromptRefusal:
    """Промт не собирается: источников меньше двух (merge нужен только для слота из нескольких видео)."""

    language: str
    source_count: int

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(
            PromptEvent.REFUSED,
            language=self.language,
            source_count=self.source_count,
            min_sources=rules.PROMPT_MIN_SOURCES,
        )


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
        if len(videos) < rules.PROMPT_MIN_SOURCES:
            refusal: MergePromptRefusal = MergePromptRefusal(language=language, source_count=len(videos))
            refusal.event.emit(LOGGER, logging.WARNING)
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
        """Английское название языка блока по справочнику pycountry («uk» → «Ukrainian»); кода нет в справочнике —
        код заглавными; кода нет — «Unknown»."""
        code: str = self.language.strip().lower()
        if not code:
            return UNKNOWN_LANGUAGE_NAME
        record: object | None = pycountry.languages.get(alpha_2=code)
        return code.upper() if record is None else str(getattr(record, LANGUAGE_NAME_FIELD))

    @property
    def sources_block(self) -> str:
        return PARAGRAPH_BREAK.join(source.prompt_block(index) for index, source in enumerate(self.sources, start=1))

    def contract_block_with(self, retry: RetryProfile | None) -> str:
        """Правила структуры первыми (общее начало всех промтов), затем контракт; с профилем — ещё инструкция повтора.

        В промт блок идёт без повтора (`contract_block`): инструкция повтора стоит в конце промта.
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
        """Полный текст промта по шаблону `merge_prompt_title_description.txt`."""
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
    def log_lines(self) -> tuple[str, ...]:
        """Строки лога: `merge_source_text_prepared` на источник, `merge_prompt_sources_ready`,
        `merge_prompt_contract_selected` — счётчики и контракт, без текста источников."""
        contract: MergeContract = self.contract
        sources_ready: LogEvent = LogEvent.of(
            PromptEvent.SOURCES_READY,
            language=self.language,
            source_count=len(self.sources),
            raw_source_chars_total=sum(source.description.raw_chars for source in self.sources),
            cleaned_source_chars_total=sum(len(source.prompt_description) for source in self.sources),
            hard_truncation=HARD_TRUNCATION_DISABLED,
        )
        contract_selected: LogEvent = LogEvent.of(
            PromptEvent.CONTRACT_SELECTED,
            language=self.language,
            source_count=contract.source_count,
            contract_mode=contract.mode,
            expected_bullet_range=contract.bullet_range_label,
            expanded_structure_enabled=contract.expanded_structure_enabled,
            narrative_trigger=contract.mode is MergeContractMode.NARRATIVE,
        )
        return (
            *(source.log_line(index, self.language) for index, source in enumerate(self.sources, start=1)),
            sources_ready.text,
            contract_selected.text,
        )
