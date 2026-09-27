"""Стадия нейросети прогона режима А: merge каждого слота между источниками и слотами (CLAUDE.md §3 шаг 2.5, §10).

`MergeStage` сначала решает, нужна ли модель вообще: если merge не нужен ни одному слоту (у всех меньше двух
непустых описаний — `MergeSources.needs_merge`), модель не выбирается и к нейросети нет ни одного обращения. Иначе
модель выбирается один раз (`ModelChoice.select`), и группы слотов по порядку проходят merge (`MergeJob`) на одном
merge запуска (`MergeRun`). Модель не выбрана — merge не делается; квота или ошибка настройки модели — merge
остановлен до конца запуска (`MergeRun.stop`). В обоих случаях слоты получают тексты видео, пакет пишется, а запуск
кончается ошибкой (§10, код 1). Ответ, не принятый ни в одной попытке или не прошедший проверку перед публикацией, —
тексты видео у одного слота, но не ошибка запуска.

`MergeResult` — итог стадии: выбор модели, итог каждого слота (`MergeSlot`), merge запуска и расход. Он даёт тексты
слота группы и сам строит строки консоли и лога. В строках консоли нет ни названий, ни описаний, ни ключа (§7.4).
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from app.config.settings import LlmSettings
from app.core.counts import CountItem, Counts
from app.intake.builder import SlotGroup
from app.llm.backend import LlmBackend
from app.llm.errors import LlmFailure
from app.llm.merges.job import MergeJob, MergeSources
from app.llm.merges.merge_rules import MergeRules
from app.llm.merges.outcome import MergeOutcome
from app.llm.merges.run import MergeRun
from app.llm.selection import ModelChoice
from app.llm.usage import COST_FORMAT, RunUsage
from app.observability.log_event import LogArea, get_logger
from app.slots.texts import SlotTexts
from app.sources.video import SourceCatalog
from app.ui import messages_ru as msg

LOGGER: logging.Logger = get_logger(LogArea.LLM)


class VideoTextReason(str, Enum):
    """Почему слот получил тексты видео, а не тексты модели. Значение — идентификатор для лога."""

    FEW_DESCRIPTIONS = "few_descriptions"    # меньше двух непустых описаний — сводить нечего
    NOT_ACCEPTED = "not_accepted"            # ответ модели не принят ни в одной попытке
    PUBLISH_BLOCKED = "publish_blocked"      # ответ принят, но не прошёл проверку перед публикацией
    STOPPED = "stopped"                      # merge остановлен до конца запуска: квота или настройка модели
    NO_MODEL = "no_model"                    # модель не выбрана

    @property
    def human(self) -> str:
        return msg.INTAKE_MERGE_VIDEO_REASONS[self.value]


@dataclass(frozen=True)
class MergeSlot:
    """Итог стадии по одной группе: группа, итог её merge (None — модель не спрашивали: merge запуска не шёл) и
    остановлен ли merge запуска к концу этого слота."""

    group: SlotGroup
    outcome: MergeOutcome | None
    run_stopped: bool

    @classmethod
    def of(cls, group: SlotGroup, merge_run: MergeRun) -> MergeSlot:
        """Merge группы на merge запуска; остановка, случившаяся на этом слоте, остаётся за ним."""
        outcome: MergeOutcome = MergeJob(group.key, group.videos, merge_run).run()
        return cls(group=group, outcome=outcome, run_stopped=merge_run.stop_reason is not None)

    @classmethod
    def unmerged(cls, group: SlotGroup) -> MergeSlot:
        """Группа, до которой merge запуска не дошёл: модель не выбиралась или не выбрана."""
        return cls(group=group, outcome=None, run_stopped=False)

    @property
    def is_merged(self) -> bool:
        return self.outcome is not None and self.outcome.merged

    @property
    def texts(self) -> SlotTexts:
        """Тексты модели по правилам YouTube либо тексты видео группы."""
        if self.outcome is not None and self.outcome.merged:
            return self.outcome.texts.for_youtube(self.group.key.slot_id)
        return self.group.source_texts

    @property
    def video_reason(self) -> VideoTextReason | None:
        """Почему у слота тексты видео; у слота с текстами модели — None."""
        if self.is_merged:
            return None
        if not MergeSources(self.group.videos).needs_merge:
            return VideoTextReason.FEW_DESCRIPTIONS
        if self.outcome is None:
            return VideoTextReason.NO_MODEL
        if self.run_stopped:
            return VideoTextReason.STOPPED
        return VideoTextReason.PUBLISH_BLOCKED if self.outcome.publish_blocked else VideoTextReason.NOT_ACCEPTED


@dataclass(frozen=True)
class MergeResult:
    """Итог стадии нейросети: выбор модели (None — merge не был нужен ни одному слоту), итоги слотов в порядке групп,
    merge запуска (None — модель не выбиралась или не выбрана) и расход нейросети за запуск."""

    choice: ModelChoice | None
    slots: tuple[MergeSlot, ...]
    merge_run: MergeRun | None
    usage: RunUsage

    @classmethod
    def without_model(cls, choice: ModelChoice | None, groups: Sequence[SlotGroup], usage: RunUsage) -> MergeResult:
        """Merge не шёл: модель не была нужна (`choice` None) или не выбрана — у всех слотов тексты видео."""
        slots: tuple[MergeSlot, ...] = tuple(MergeSlot.unmerged(group) for group in groups)
        return cls(choice=choice, slots=slots, merge_run=None, usage=usage)

    def texts_of(self, group: SlotGroup) -> SlotTexts:
        """Окончательные тексты слота группы этого запуска."""
        return next(slot.texts for slot in self.slots if slot.group.key.slot_id == group.key.slot_id)

    @property
    def merged(self) -> int:
        """Сколько слотов получили тексты модели."""
        return sum(1 for slot in self.slots if slot.is_merged)

    @property
    def stop_failure(self) -> LlmFailure | None:
        """Отказ нейросети, который остановил merge до конца запуска."""
        return None if self.merge_run is None else self.merge_run.stop_failure

    @property
    def has_errors(self) -> bool:
        """Модель не выбрана или merge остановлен до конца запуска — ошибка запуска (§10)."""
        return (self.choice is not None and not self.choice.is_usable) or self.stop_failure is not None

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Модель (если выбиралась), итог по слотам, расход (если к нейросети обращались), остановка."""
        model: tuple[str, ...] = () if self.choice is None else (self.choice.human,)
        cost: tuple[str, ...] = () if self.choice is None else (self._cost_line,)
        failure: LlmFailure | None = self.stop_failure
        stopped: tuple[str, ...] = () if failure is None else (msg.INTAKE_MERGE_STOPPED.format(failure=failure.human),)
        return (*model, self._summary_line, *cost, *stopped)

    def log(self) -> None:
        """Строки `merge_run_summary` (если merge шёл) и `llm_run_usage` — по одной на запуск."""
        if self.merge_run is not None:
            self.merge_run.event.emit(LOGGER)
        self.usage.event.emit(LOGGER)

    @property
    def _reasons(self) -> Counts[VideoTextReason]:
        """Слоты с текстами видео по причинам в порядке перечисления; нулевых причин нет."""
        reasons: list[VideoTextReason] = [reason for slot in self.slots if (reason := slot.video_reason) is not None]
        return Counts.of(reasons, order=tuple(VideoTextReason))

    @property
    def _summary_line(self) -> str:
        reasons: Counts[VideoTextReason] = self._reasons
        items: str = msg.ITEM_JOINER.join(self._reason_text(item) for item in reasons.items)
        wrapped: str = msg.INTAKE_MERGE_REASONS.format(items=items) if reasons.items else ""
        return msg.INTAKE_MERGE_LINE.format(
            total=len(self.slots), merged=self.merged, video=reasons.total, reasons=wrapped
        )

    def _reason_text(self, item: CountItem[VideoTextReason]) -> str:
        """Причина и число слотов; у проверки перед публикацией — ещё и по языкам."""
        text: str = item.text(msg.INTAKE_COUNT_ITEM, lambda reason: reason.human)
        if item.key is not VideoTextReason.PUBLISH_BLOCKED:
            return text
        blocked: Counts[str] = Counts.of(
            slot.group.key.language for slot in self.slots if slot.video_reason is VideoTextReason.PUBLISH_BLOCKED
        )
        return text + blocked.wrapped(msg.INTAKE_SLOTS_LANGUAGES, msg.INTAKE_COUNT_ITEM, msg.LIST_JOINER, str)

    @property
    def _cost_line(self) -> str:
        """Расход за запуск; цена части ответов неизвестна — «не меньше»."""
        template: str = msg.INTAKE_MERGE_COST if self.usage.cost_known else msg.INTAKE_MERGE_COST_UNKNOWN
        return template.format(requests=self.usage.requests, cost=COST_FORMAT.format(self.usage.cost_usd))


@dataclass(frozen=True)
class MergeStage:
    """Стадия нейросети одного запуска: нейросеть за разъёмом, настройки `llm` и видео запуска (тот же кеш, что у
    источников: им пользуются рекомендуемые материалы)."""

    backend: LlmBackend
    settings: LlmSettings
    catalog: SourceCatalog

    def run(self, groups: Sequence[SlotGroup]) -> MergeResult:
        """Merge групп по порядку; итог — строками лога в конце стадии."""
        result: MergeResult = self._result(groups)
        result.log()
        return result

    def _result(self, groups: Sequence[SlotGroup]) -> MergeResult:
        """Модель — только если merge нужен хоть одному слоту; не выбрана — merge не делается."""
        usage: RunUsage = self.backend.run_usage
        if not any(MergeSources(group.videos).needs_merge for group in groups):
            return MergeResult.without_model(None, groups, usage)
        choice: ModelChoice = ModelChoice.select(self.backend, self.settings.model, self.settings.fallback_model)
        if choice.chosen is None:
            return MergeResult.without_model(choice, groups, usage)
        merge_run: MergeRun = MergeRun(
            backend=self.backend,
            model=choice.chosen,
            settings=self.settings,
            rules=MergeRules.load(),
            catalog=self.catalog,
        )
        slots: tuple[MergeSlot, ...] = tuple(MergeSlot.of(group, merge_run) for group in groups)
        return MergeResult(choice=choice, slots=slots, merge_run=merge_run, usage=usage)
