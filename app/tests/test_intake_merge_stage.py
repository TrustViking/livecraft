"""Стадия нейросети прогона режима А (app\\intake\\merge_stage.py): модель — только когда merge нужен хоть одному
слоту, тексты слотов, остановка до конца запуска, строки консоли и лога (CLAUDE.md §3 шаг 2.5, §10).

Нейросеть — только `QueueBackend` (ответы по очереди, исход пробы задан), видео запуска — yt-dlp без сети.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest

from app.intake.builder import SlotGroup
from app.intake.merge_stage import MergeResult, MergeStage, VideoTextReason
from app.llm.errors import LlmErrorKind, LlmRequestError
from app.llm.merges.outcome import MergeOutcome
from app.llm.selection import ModelChoice
from app.llm.usage import COST_FORMAT, RequestUsage, RunUsage, TokenCounts
from app.observability.log_event import LogArea
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.conftest import LLM_SETTINGS
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.merges import (
    BLOCKED_ANSWER,
    BLOCKED_SOURCES,
    BLOCKED_TITLE,
    EXPANDED_SOURCES,
    NOT_JSON,
    SLOT_START,
    STRONG_ANSWER,
    STRONG_HOOK,
    TITLE,
    UNDERFLOW_ANSWER,
    QueueBackend,
    answer,
    error,
    group_of,
    uk_group,
)
from app.tests.fixtures.sources import stub_catalog
from app.ui import messages_ru as msg

SINGLE: tuple[tuple[str, str], ...] = EXPANDED_SOURCES[:1]
ONE_DESCRIBED: tuple[tuple[str, str], ...] = (EXPANDED_SOURCES[0], ("Kharkiv rail and drone update", "  "))


@pytest.fixture
def llm_log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.LLM, logging.INFO) as capture:
        yield capture


def later(hours: int) -> datetime:
    return SLOT_START + timedelta(hours=hours)


def run_stage(backend: QueueBackend, *groups: SlotGroup) -> MergeResult:
    """Стадия на нейросети тестов, настройках `llm` тестов и видео запуска без сети."""
    return MergeStage(backend, LLM_SETTINGS, stub_catalog()).run(groups)


def summary(total: int, merged: int, *reasons: tuple[VideoTextReason, int], blocked: str = "") -> str:
    """Строка итога: причины — по порядку, у проверки перед публикацией — перечень языков `blocked`."""
    items: list[str] = [msg.INTAKE_COUNT_ITEM.format(name=reason.human, count=count) for reason, count in reasons]
    texts: str = msg.ITEM_JOINER.join(
        item + (blocked if reason is VideoTextReason.PUBLISH_BLOCKED else "") for item, (reason, _) in zip(items, reasons)
    )
    wrapped: str = msg.INTAKE_MERGE_REASONS.format(items=texts) if reasons else ""
    video: int = sum(count for _, count in reasons)
    return msg.INTAKE_MERGE_LINE.format(total=total, merged=merged, video=video, reasons=wrapped)


def cost(requests: int, known: bool = True, amount: float = 0.0) -> str:
    template: str = msg.INTAKE_MERGE_COST if known else msg.INTAKE_MERGE_COST_UNKNOWN
    return template.format(requests=requests, cost=COST_FORMAT.format(amount))


def lines_starting(capture: LogCapture, prefix: str) -> list[str]:
    return [line for line in capture.messages() if line.startswith(prefix)]


def reasons_of(result: MergeResult) -> list[VideoTextReason | None]:
    return [slot.video_reason for slot in result.slots]


# --- модель нужна не всегда


def test_when_no_slot_needs_merge_no_model_is_chosen_and_nothing_is_asked(llm_log: LogCapture) -> None:
    """У каждого слота меньше двух непустых описаний: ни пробы, ни запроса; строка итога есть, ошибки нет."""
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)])
    single: SlotGroup = group_of(SINGLE)
    one_described: SlotGroup = group_of(ONE_DESCRIBED, later(1))
    result: MergeResult = run_stage(backend, single, one_described)
    assert backend.probes == [] and backend.requests == []
    assert result.choice is None and result.merge_run is None and not result.has_errors
    assert result.texts_of(single) == single.source_texts and result.texts_of(one_described) == one_described.source_texts
    assert result.console_lines == (summary(2, 0, (VideoTextReason.FEW_DESCRIPTIONS, 2)),)
    assert lines_starting(llm_log, "merge_run_summary") == []
    assert len(lines_starting(llm_log, "llm_run_usage requests=0 ")) == 1


# --- модель выбрана


def test_a_chosen_model_merges_every_slot_that_needs_it(llm_log: LogCapture) -> None:
    """Модель выбирается один раз; слот из трёх источников получает тексты модели по правилам YouTube, слот из одного —
    тексты видео без обращения к нейросети."""
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    merged: SlotGroup = group_of()
    single: SlotGroup = group_of(SINGLE, later(1))
    result: MergeResult = run_stage(backend, merged, single)
    assert backend.probes == [LLM_SETTINGS.model] and len(backend.requests) == 1
    assert backend.requests[0].model_name == LLM_SETTINGS.model
    outcome: MergeOutcome | None = result.slots[0].outcome
    assert outcome is not None and outcome.merged
    texts: SlotTexts = result.texts_of(merged)
    assert texts.origin is SlotTextOrigin.MERGED and texts == outcome.texts.for_youtube(merged.key.slot_id)
    assert result.texts_of(single) == single.source_texts
    assert reasons_of(result) == [None, VideoTextReason.FEW_DESCRIPTIONS]
    assert result.merged == 1 and not result.has_errors
    assert result.choice is not None and result.choice.is_usable
    assert result.console_lines == (
        result.choice.human,
        summary(2, 1, (VideoTextReason.FEW_DESCRIPTIONS, 1)),
        cost(1, known=False),                        # нейросеть тестов не сообщает расход — цена неизвестна
    )
    text: str = "\n".join(result.console_lines)
    assert TITLE not in text and STRONG_HOOK[:40] not in text
    assert len(lines_starting(llm_log, "merge_run_summary merge_success=1 ")) == 1
    assert lines_starting(llm_log, "merge_run_summary")[0].endswith(" stop_reason=-")
    assert len(lines_starting(llm_log, "llm_run_usage requests=1 ")) == 1


def test_a_rejected_or_blocked_answer_gives_the_video_texts_without_a_run_error() -> None:
    """Ответ не принят ни в одной попытке, принятый не прошёл проверку перед публикацией — у слота тексты видео,
    ошибкой запуска это не считается; проверка перед публикацией — с разбивкой по языкам."""
    backend: QueueBackend = QueueBackend(
        replies=[answer(UNDERFLOW_ANSWER), NOT_JSON, NOT_JSON, answer(BLOCKED_ANSWER, BLOCKED_TITLE)], probe_kind=None
    )
    rejected: SlotGroup = group_of()
    blocked: SlotGroup = uk_group(BLOCKED_SOURCES, later(1))
    result: MergeResult = run_stage(backend, rejected, blocked)
    assert backend.replies == [] and not result.has_errors and result.merged == 0
    assert reasons_of(result) == [VideoTextReason.NOT_ACCEPTED, VideoTextReason.PUBLISH_BLOCKED]
    assert result.texts_of(rejected) == rejected.source_texts and result.texts_of(blocked) == blocked.source_texts
    languages: str = msg.INTAKE_SLOTS_LANGUAGES.format(items=msg.INTAKE_COUNT_ITEM.format(name="uk", count=1))
    assert result.console_lines[1] == summary(
        2, 0, (VideoTextReason.NOT_ACCEPTED, 1), (VideoTextReason.PUBLISH_BLOCKED, 1), blocked=languages
    )


# --- модель не выбрана, merge остановлен


def test_without_a_chosen_model_every_slot_gets_the_video_texts_and_the_run_fails(llm_log: LogCapture) -> None:
    """Ключ не принят на пробе: моделей нет — merge не делается, ни одного запроса; слоты с текстами видео."""
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=LlmErrorKind.AUTH)
    needs: SlotGroup = group_of()
    single: SlotGroup = group_of(SINGLE, later(1))
    result: MergeResult = run_stage(backend, needs, single)
    assert result.choice is not None and result.choice.chosen is None
    assert backend.requests == [] and result.merge_run is None and result.has_errors
    assert result.texts_of(needs) == needs.source_texts and result.texts_of(single) == single.source_texts
    assert result.console_lines == (
        result.choice.human,
        summary(2, 0, (VideoTextReason.FEW_DESCRIPTIONS, 1), (VideoTextReason.NO_MODEL, 1)),
        cost(0),
    )
    assert msg.LLM_CHOICE_REFUSED.format(reason=error(LlmErrorKind.AUTH).failure.human) == result.console_lines[0]
    assert lines_starting(llm_log, "merge_run_summary") == []
    assert len(lines_starting(llm_log, "llm_run_usage")) == 1


def test_quota_on_the_first_slot_stops_merge_and_later_slots_ask_nothing(llm_log: LogCapture) -> None:
    backend: QueueBackend = QueueBackend(replies=[error(LlmErrorKind.QUOTA), answer(STRONG_ANSWER)], probe_kind=None)
    first: SlotGroup = group_of()
    second: SlotGroup = group_of(start=later(1))
    single: SlotGroup = group_of(SINGLE, later(2))
    result: MergeResult = run_stage(backend, first, second, single)
    assert len(backend.requests) == 1 and backend.replies == [answer(STRONG_ANSWER)]
    assert result.has_errors and result.merged == 0
    assert reasons_of(result) == [VideoTextReason.STOPPED, VideoTextReason.STOPPED, VideoTextReason.FEW_DESCRIPTIONS]
    for group in (first, second, single):
        assert result.texts_of(group) == group.source_texts
    assert result.choice is not None
    assert result.console_lines == (
        result.choice.human,
        summary(3, 0, (VideoTextReason.FEW_DESCRIPTIONS, 1), (VideoTextReason.STOPPED, 2)),
        cost(0),
        msg.INTAKE_MERGE_STOPPED.format(failure=error(LlmErrorKind.QUOTA).failure.human),
    )
    [summary_line] = lines_starting(llm_log, "merge_run_summary")
    assert summary_line.endswith(" stop_reason=quota_exhausted")
    assert len(lines_starting(llm_log, "llm_run_usage")) == 1


def test_a_model_configuration_error_in_the_middle_keeps_the_merged_slot(llm_log: LogCapture) -> None:
    """Первый слот получил тексты модели, на втором ключ не принят — merge остановлен, третий слот без запроса."""
    replies: list[str | LlmRequestError] = [answer(STRONG_ANSWER), error(LlmErrorKind.AUTH), answer(STRONG_ANSWER)]
    backend: QueueBackend = QueueBackend(replies=replies, probe_kind=None)
    groups: tuple[SlotGroup, ...] = (group_of(), group_of(start=later(1)), group_of(start=later(2)))
    result: MergeResult = run_stage(backend, *groups)
    assert len(backend.requests) == 2 and result.merged == 1 and result.has_errors
    assert reasons_of(result) == [None, VideoTextReason.STOPPED, VideoTextReason.STOPPED]
    assert result.texts_of(groups[0]).origin is SlotTextOrigin.MERGED
    assert result.console_lines[-1] == msg.INTAKE_MERGE_STOPPED.format(failure=error(LlmErrorKind.AUTH).failure.human)


# --- расход


def test_a_known_cost_is_printed_as_is_and_an_unknown_one_as_a_lower_bound() -> None:
    choice: ModelChoice = ModelChoice.select(QueueBackend(probe_kind=None), LLM_SETTINGS.model, "")
    usage: RunUsage = RunUsage()
    usage.add(RequestUsage(TokenCounts(), response_id="r1", model="gpt-x", tier="", label="merge", cost_usd=0.0123))
    assert MergeResult(choice, (), None, usage).console_lines[-1] == cost(1, amount=0.0123)
    usage.add(None)
    assert MergeResult(choice, (), None, usage).console_lines[-1] == cost(2, known=False, amount=0.0123)
