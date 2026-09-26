"""Общие объекты тестов merge: годные источники без сети, образцовые ответы модели, нейросеть за разъёмом с очередью
ответов, слот и merge запуска, тексты промта с заменёнными шаблонами (CLAUDE.md §11)."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from zoneinfo import ZoneInfo

from app.intake.builder import SlotGroup
from app.llm.backend import LlmRequest, LlmResponse
from app.llm.errors import LlmErrorKind, LlmRequestError
from app.llm.merges.job import MergeJob
from app.llm.merges.merge_rules import MergeRules
from app.llm.merges.prompt_texts import MergeContractMode, MergePromptTexts
from app.llm.merges.run import MergeRun
from app.llm.usage import RunUsage
from app.slots.slot import SlotKey
from app.sources.video import SourceVideo
from app.tests.conftest import LLM_SETTINGS
from app.tests.fixtures.sources import admitted_row, ready_source

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
# Начало слота merge — тот же момент со смещением вместо пояса.
SLOT_START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=timezone(timedelta(hours=3)))
RULES: MergeRules = MergeRules.load()
TEXTS: MergePromptTexts = RULES.texts
FAKE_BACKEND: str = "fake"
MODEL: str = "gpt-x"
NEUTRAL: str = chr(0x1F539)
NOT_JSON: str = "not json at all"

# Три источника об одном вечере: Брюссель, Харьков, Женева — у каждого свои факты и свой спикер.
EXPANDED_SOURCES: tuple[tuple[str, str], ...] = (
    (
        "Brussels sanctions vote briefing",
        "In Brussels, Anna Kovalenko tracks the March 18 sanctions vote, budget amendments, and customs delays after "
        "the commission session.",
    ),
    (
        "Kharkiv rail and drone update",
        "In Kharkiv, Oleh Martynenko reports 17 drone strikes, rail hub outages, and evacuation routes for Saltivka "
        "districts.",
    ),
    (
        "Geneva relief corridor desk",
        "From Geneva, Marta Leone outlines the aid corridor timetable, WHO cargo counts, and donor pledges for Odesa "
        "and Mykolaiv hospitals.",
    ),
)
STRONG_BULLETS: tuple[str, ...] = (
    "Brussels sanctions vote, budget amendments, and customs delays after the March 18 commission session",
    "Anna Kovalenko tracks coalition counts and the pressure points before the chamber debate",
    "Kharkiv rail hub outages after 17 drone strikes across Saltivka districts",
    "Oleh Martynenko details evacuation routes, depot damage, and recovery sequencing on the eastern line",
    "Geneva aid corridor timetable, WHO cargo counts, and donor pledges for Odesa hospitals",
    "Marta Leone breaks down how Mykolaiv deliveries depend on the next donor release window",
)
STRONG_HOOK: str = (
    "Tonight we align the Brussels vote, the Kharkiv transport shock, and the Geneva aid timetable into one grounded "
    "briefing. Each source keeps its own factual lane, and the summary stays concrete instead of leaning on editorial "
    "gloss."
)
STRONG_CLOSE: str = (
    "The closing paragraph ties the political vote, frontline logistics, and medical supply chain into a clear "
    "next-step agenda without flattening the sources into one generic thesis."
)
# Перегруженные пункты (длиннее 500 знаков) без общих слов: соседние строки не повтор.
LONG_ALPHA: str = "alpha " * 90
LONG_BETA: str = "beta " * 110
HOOK: str = "Tonight we map the sanctions vote and what it changes for the next operational window."


def bullets(lines: tuple[str, ...] | list[str]) -> str:
    """Пункты с нейтральным маркером, по строке на пункт."""
    return "\n".join(f"{NEUTRAL} {line}" for line in lines)


TITLE: str = "Brussels, Kharkiv, Geneva: the operational agenda tonight"
STRONG_ANSWER: str = f"{STRONG_HOOK}\n\nIn this stream you'll see:\n{bullets(STRONG_BULLETS)}\n\n{STRONG_CLOSE}"
THIN_ANSWER: str = f"{STRONG_HOOK}\n\n{bullets(STRONG_BULLETS[:3])}\n\n{STRONG_CLOSE}"
OVERLOADED_ANSWER: str = f"{STRONG_HOOK}\n\n{bullets([LONG_ALPHA, LONG_BETA, *STRONG_BULLETS[:4]])}\n\n{STRONG_CLOSE}"
CTA_FIRST_ANSWER: str = f"Subscribe to the channel for more updates.\n\n{STRONG_HOOK}\n\n{bullets(STRONG_BULLETS)}"
ADJACENT_ANSWER: str = (
    f"{STRONG_HOOK}\n\n{bullets([STRONG_BULLETS[0]])}\n{bullets([STRONG_BULLETS[0] + ' again'])}\n"
    f"{bullets(STRONG_BULLETS[1:])}"
)
UNDERFLOW_ANSWER: str = "One single paragraph only."
OVERFLOW_ANSWER: str = "\n\n".join(
    f"Paragraph number {index} with its own distinct content about topic {index}." for index in range(8)
)


def merge_video(row_number: int, title: str, description: str, language: str = "en") -> SourceVideo:
    """Годный источник слота без сети; ссылка своя на каждый ряд."""
    return ready_source(admitted_row(row_number, f"https://youtu.be/{row_number:011d}", START), title, description, language)


def sources_of(pairs: tuple[tuple[str, str], ...]) -> tuple[SourceVideo, ...]:
    """Источники по парам «название, описание» — ряды с первого."""
    return tuple(merge_video(index + 1, title, body) for index, (title, body) in enumerate(pairs))


def answer(description: str, title: str = TITLE) -> str:
    """Ответ модели по схеме merge."""
    return json.dumps({"title": title, "description": description}, ensure_ascii=False)


def error(kind: LlmErrorKind) -> LlmRequestError:
    return LlmRequestError(kind, backend=FAKE_BACKEND, detail=kind.value)


@dataclass
class QueueBackend:
    """Нейросеть за разъёмом: сохранённые ответы по очереди; отказ — `LlmRequestError` в очереди."""

    replies: list[str | LlmRequestError] = field(default_factory=list)
    structured: bool = False
    requests: list[LlmRequest] = field(default_factory=list)
    run_usage: RunUsage = field(default_factory=RunUsage)

    @property
    def name(self) -> str:
        return FAKE_BACKEND

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        reply: str | LlmRequestError = self.replies.pop(0)
        if isinstance(reply, LlmRequestError):
            raise reply
        payload: object = json.loads(reply) if self.structured else None
        self.run_usage.add(None)
        return LlmResponse(
            text=reply,
            structured=payload if isinstance(payload, dict) else None,
            model=request.model_name,
        )

    def probe(self, model_name: str) -> LlmResponse | LlmRequestError:
        return error(LlmErrorKind.FAILED)

    @property
    def prompts(self) -> list[str]:
        return [request.prompt for request in self.requests]


def group_of(pairs: tuple[tuple[str, str], ...] = EXPANDED_SOURCES, start: datetime = SLOT_START) -> SlotGroup:
    """Группа слота: источники с второго ряда, язык en."""
    videos: tuple[SourceVideo, ...] = tuple(
        merge_video(index + 2, title, body) for index, (title, body) in enumerate(pairs)
    )
    return SlotGroup(SlotKey(start=start, language="en"), videos)


def job_of(group: SlotGroup, merge_run: MergeRun) -> MergeJob:
    """Merge слота группы: её ключ и источники в порядке рядов."""
    return MergeJob(group.key, group.videos, merge_run)


def run_with(*replies: str | LlmRequestError) -> tuple[MergeRun, QueueBackend]:
    """Merge запуска на нейросети с этой очередью ответов."""
    backend: QueueBackend = QueueBackend(replies=list(replies))
    return MergeRun(backend=backend, model=MODEL, settings=LLM_SETTINGS, rules=RULES), backend


def texts_with(
    contracts: Mapping[MergeContractMode, str] | None = None,
    reinforcements: Mapping[str, tuple[str, ...]] | None = None,
    **changes: str,
) -> MergePromptTexts:
    """Тексты промта с заменёнными шаблонами: контракты, строки повтора, прочие тексты по имени поля."""
    texts: MergePromptTexts = replace(TEXTS, **changes)
    if contracts is not None:
        texts = replace(texts, contracts=MappingProxyType(dict(contracts)))
    if reinforcements is not None:
        texts = replace(texts, retry_reinforcements=MappingProxyType(dict(reinforcements)))
    return texts
