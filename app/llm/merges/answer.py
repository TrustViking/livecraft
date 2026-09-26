"""Ответ модели на merge: разбор в проверенный объект `MergeAnswer` или отказ `MergeReject` (CLAUDE.md §14 решение 23).

`MergeAnswer.SCHEMA` — схема ответа, с которой идёт запрос (ровно название и описание, название до 99 знаков); те же
ключи и пределы проверяет разбор. Порядок правил разбора: при пределе тела от семи абзацев ответ ровно на один абзац
длиннее отвергается до разбора ключей (слияние такого тела исказило бы структуру), затем объект JSON → ровно ключи
title и description → значения не списки и не объекты → непустые строки → призыв в первой строке описания (до всякого
восстановления) → раскладка тела и хвоста → снятие служебных строк → число абзацев тела 2..предел → название
1..99 знаков без эмодзи.

Строки лога `merge_payload_parsed` и `merge_description_tail_analysis` — числа и виды блоков; текста ответа в них нет.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Final

from app.core.text_format import SPACE, WHITESPACE_RUN_PATTERN
from app.llm.backend import LlmResponse
from app.llm.json_text import PARSE_CANDIDATE, PARSE_DIRECT, parse_json_tolerant
from app.llm.merges import rules
from app.llm.merges.description import MergedDescription
from app.llm.merges.emoji import EMOJI_PATTERN
from app.llm.merges.layout import DescriptionLayout
from app.llm.merges.opening import DescriptionOpening
from app.llm.merges.reject import MergeReject, MergeRejectCode
from app.observability.log_event import LogArea, LogEvent, LogValue, get_logger
from app.texts.description_marks import CtaLexicon
from app.texts.paragraphs import split_paragraphs

LOGGER: logging.Logger = get_logger(LogArea.LLM)

TITLE_KEY: Final[str] = "title"
DESCRIPTION_KEY: Final[str] = "description"
REQUIRED_KEYS: Final[tuple[str, ...]] = (TITLE_KEY, DESCRIPTION_KEY)
SCHEMA_NAME: Final[str] = "merge_summary_v2"
# Схема ответа merge: ровно название (1..99 знаков) и непустое описание — те же ключи и пределы проверяет разбор.
RESPONSE_SCHEMA: Final[dict[str, object]] = {
    "name": SCHEMA_NAME,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": list(REQUIRED_KEYS),
        "properties": {
            TITLE_KEY: {"type": "string", "minLength": rules.TITLE_MIN_CHARS, "maxLength": rules.TITLE_MAX_CHARS},
            DESCRIPTION_KEY: {"type": "string", "minLength": 1},
        },
    },
}
INVALID_TYPE_DETAIL: Final[str] = "invalid_type:{key}"
TITLE_NOT_TEXT: Final[str] = "not_text"
TITLE_EMPTY: Final[str] = "empty_after_normalization"
TITLE_EMOJI: Final[str] = "emoji"
DESCRIPTION_NOT_TEXT: Final[str] = TITLE_NOT_TEXT


class AnswerParseMode(str, Enum):
    """Как найден объект ответа: готовый JSON по схеме, весь текст или единственный объект `{…}` внутри текста."""

    STRUCTURED = "structured_payload"
    DIRECT = PARSE_DIRECT
    CANDIDATE = PARSE_CANDIDATE


class AnswerEvent(str, Enum):
    """События разбора ответа в логе."""

    REJECTED = "merge_answer_rejected"
    PARSED = "merge_payload_parsed"
    TAIL_ANALYSIS = "merge_description_tail_analysis"


class TailStatus(str, Enum):
    """Чем кончился разбор описания в строке раскладки."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MergePayload:
    """Объект JSON ответа модели, как он найден и какой моделью; `data` None — объекта нет. Значения в `repr`
    не печатаются."""

    data: dict[str, object] | None = field(repr=False)
    mode: AnswerParseMode | None
    model: str

    @classmethod
    def of(cls, response: LlmResponse) -> MergePayload:
        if response.structured is not None:
            return cls(data=response.structured, mode=AnswerParseMode.STRUCTURED, model=response.model)
        try:
            data, mode = parse_json_tolerant(response.text)
        except RecursionError:                 # глубоко вложенный JSON — не объект ответа
            return cls(data=None, mode=None, model=response.model)
        return cls(data=data, mode=AnswerParseMode(mode) if data is not None else None, model=response.model)

    @property
    def description_value(self) -> object:
        return None if self.data is None else self.data.get(DESCRIPTION_KEY)

    def overflow_reject(self, max_body_paragraphs: int) -> MergeReject | None:
        """Тело длиннее предела ровно на один абзац при пределе от семи — отказ до разбора ключей."""
        description: object = self.description_value
        if not isinstance(description, str) or max_body_paragraphs < rules.SINGLE_STEP_OVERFLOW_MIN_LIMIT:
            return None
        body_count: int = DescriptionLayout.of(description, max_body_paragraphs).body_paragraph_count
        if body_count != max_body_paragraphs + 1:
            return None
        return MergeReject.of_paragraph_count(body_count, max_body_paragraphs)

    def shape_reject(self) -> MergeReject | None:
        """Объект есть, ключи ровно title и description, значения — непустые строки."""
        if self.data is None:
            return MergeReject(MergeRejectCode.NOT_JSON_OBJECT)
        keys: set[str] = set(self.data.keys())
        missing: list[str] = sorted(key for key in REQUIRED_KEYS if key not in keys)
        if missing:
            return MergeReject(MergeRejectCode.MISSING_KEYS, LogValue.LIST_SEPARATOR.join(missing))
        extra: list[str] = sorted(key for key in keys if key not in REQUIRED_KEYS)
        if extra:
            return MergeReject(MergeRejectCode.EXTRA_KEYS, LogValue.LIST_SEPARATOR.join(extra))
        for key in REQUIRED_KEYS:
            if isinstance(self.data.get(key), (list, dict)):
                return MergeReject(MergeRejectCode.UNEXPECTED, INVALID_TYPE_DETAIL.format(key=key))
        if not self._is_filled(TITLE_KEY):
            return MergeReject(MergeRejectCode.INVALID_TITLE, TITLE_NOT_TEXT)
        if not self._is_filled(DESCRIPTION_KEY):
            return MergeReject(MergeRejectCode.INVALID_DESCRIPTION, DESCRIPTION_NOT_TEXT)
        return None

    def _is_filled(self, key: str) -> bool:
        """Значение ключа — непустая строка."""
        value: object = None if self.data is None else self.data.get(key)
        return isinstance(value, str) and bool(value.strip())

    def rejected(self, reject: MergeReject) -> MergeReject:
        """Отказ — строкой лога с моделью и причинами."""
        reject.extend(LogEvent.of(AnswerEvent.REJECTED, model=self.model)).emit(LOGGER)
        return reject


@dataclass(frozen=True)
class MergeAnswer:
    """Принятый ответ модели: название, описание (тело и хвост), число абзацев тела. Тексты в `repr` не печатаются."""

    SCHEMA: ClassVar[dict[str, object]] = RESPONSE_SCHEMA

    title: str = field(repr=False)
    description: MergedDescription
    layout: DescriptionLayout
    paragraph_count: int
    parse_mode: AnswerParseMode
    model: str

    @classmethod
    def parse(cls, response: LlmResponse, max_body_paragraphs: int, cta: CtaLexicon) -> MergeAnswer | MergeReject:
        """Ответ модели → принятый ответ или отказ с кодом; исключений не бросает."""
        payload: MergePayload = MergePayload.of(response)
        reject: MergeReject | None = payload.overflow_reject(max_body_paragraphs) or payload.shape_reject()
        if reject is not None or payload.data is None or payload.mode is None:
            return payload.rejected(reject or MergeReject(MergeRejectCode.NOT_JSON_OBJECT))
        raw_description: MergedDescription = MergedDescription(str(payload.data[DESCRIPTION_KEY]))
        if DescriptionOpening(raw_description).starts_with_cta(cta):
            return payload.rejected(MergeReject(MergeRejectCode.CTA_AS_FIRST_PARAGRAPH))
        draft: _AnswerDraft = _AnswerDraft(
            payload=payload,
            mode=payload.mode,
            title_value=str(payload.data[TITLE_KEY]),
            layout=DescriptionLayout.of(raw_description.text, max_body_paragraphs),
            max_body_paragraphs=max_body_paragraphs,
        )
        return draft.finish()

    @property
    def tail_recovery_applied(self) -> bool:
        return self.layout.recovery_applied

    @property
    def event(self) -> LogEvent:
        """Строка о принятом ответе: модель, как найден объект, длины текстов и число абзацев тела."""
        return LogEvent.of(
            AnswerEvent.PARSED,
            model=self.model,
            parse_mode=self.parse_mode,
            title_length=len(self.title),
            description_length=len(self.description.text),
            paragraph_count=self.paragraph_count,
        )


@dataclass(frozen=True)
class _AnswerDraft:
    """Ответ после проверки формы и призыва: раскладка готова, осталось проверить описание, абзацы и название."""

    payload: MergePayload
    mode: AnswerParseMode
    title_value: str = field(repr=False)
    layout: DescriptionLayout
    max_body_paragraphs: int

    def finish(self) -> MergeAnswer | MergeReject:
        if self.layout.blocked_reason is not None:
            return self._rejected_after_layout(MergeReject(self.layout.blocked_reason))
        description: MergedDescription = MergedDescription(self.layout.full_text).without_meta_lines()
        if not description.text:
            return self.payload.rejected(MergeReject(MergeRejectCode.DESCRIPTION_EMPTY))
        paragraph_count: int = len(split_paragraphs(self.layout.body_text))
        if not rules.MIN_BODY_PARAGRAPHS <= paragraph_count <= self.max_body_paragraphs:
            return self._rejected_after_layout(MergeReject.of_paragraph_count(paragraph_count, self.max_body_paragraphs))
        title: str | MergeReject = self._title()
        if isinstance(title, MergeReject):
            return self.payload.rejected(title)
        answer: MergeAnswer = MergeAnswer(title, description, self.layout, paragraph_count, self.mode, self.payload.model)
        answer.event.emit(LOGGER)
        self._tail_event(TailStatus.ACCEPTED).emit(LOGGER)
        return answer

    def _title(self) -> str | MergeReject:
        """Пробелы схлопнуты, не длиннее 99 знаков, без эмодзи."""
        title: str = WHITESPACE_RUN_PATTERN.sub(SPACE, self.title_value.strip())
        if len(title) > rules.TITLE_MAX_CHARS:
            title = title[: rules.TITLE_MAX_CHARS].rstrip()
        if len(title) < rules.TITLE_MIN_CHARS:
            return MergeReject(MergeRejectCode.INVALID_TITLE, TITLE_EMPTY)
        if EMOJI_PATTERN.search(title):
            return MergeReject(MergeRejectCode.INVALID_TITLE, TITLE_EMOJI)
        return title

    def _tail_event(self, status: TailStatus) -> LogEvent:
        """Строка раскладки описания: модель, поля раскладки и итог."""
        event: LogEvent = self.layout.extend(LogEvent.of(AnswerEvent.TAIL_ANALYSIS, model=self.payload.model))
        return event.extended(final_status=status)

    def _rejected_after_layout(self, reject: MergeReject) -> MergeReject:
        """Отказ, до которого дошла раскладка: сначала строка раскладки с причиной, затем строка отказа."""
        self._tail_event(TailStatus.REJECTED).extended(reject_reason=reject.code).emit(LOGGER)
        return self.payload.rejected(reject)
