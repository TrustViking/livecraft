"""Ответ модели на merge: разбор в проверенный объект `MergeAnswer` или отказ `MergeReject` (CLAUDE.md §14 решение 23).

Порядок правил — донорский (restreamer): сначала предварительная проверка
`merge_executor.py::MergeExecutor._enforce_single_step_overflow_policy` (при пределе тела от семи абзацев ответ
ровно на один абзац длиннее отвергается до разбора ключей — слияние такого тела исказило бы структуру),
затем шаги `merge_parser.py::parse_merge_response_or_raise`: объект JSON → ровно ключи title и description →
значения не списки и не объекты → непустые строки → призыв в первой строке описания (до всякого
восстановления) → раскладка тела и хвоста → снятие служебных строк → число абзацев тела 2..предел → название
1..99 знаков без эмодзи.

Строки лога `merge_payload_parsed` и `merge_description_tail_analysis` — с ключами донора; текста ответа в них нет.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from app.llm.backend import LlmResponse
from app.llm.json_text import PARSE_CANDIDATE, PARSE_DIRECT, parse_json_tolerant
from app.llm.merges.description import MergedDescription
from app.llm.merges.layout import DescriptionLayout
from app.llm.merges.reject import MergeReject, MergeRejectCode
from app.observability.logging_setup import get_logger
from app.texts.description_marks import CtaLexicon
from app.texts.paragraphs import split_paragraphs

LOGGER: logging.Logger = get_logger("llm")

TITLE_KEY: Final[str] = "title"
DESCRIPTION_KEY: Final[str] = "description"
REQUIRED_KEYS: Final[tuple[str, ...]] = (TITLE_KEY, DESCRIPTION_KEY)
KEYS_JOINER: Final[str] = ","
TITLE_MIN_CHARS: Final[int] = 1
TITLE_MAX_CHARS: Final[int] = 99
MIN_BODY_PARAGRAPHS: Final[int] = 2
# Предел тела, начиная с которого ответ ровно на один абзац длиннее отвергается до восстановления.
SINGLE_STEP_OVERFLOW_MIN_LIMIT: Final[int] = 7
EMOJI_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", flags=re.UNICODE)
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
INVALID_TYPE_DETAIL: Final[str] = "invalid_type:{key}"
PARAGRAPH_COUNT_DETAIL: Final[str] = "body_paragraphs={count} allowed={low}..{high}"
TITLE_NOT_TEXT: Final[str] = "not_text"
TITLE_EMPTY: Final[str] = "empty_after_normalization"
TITLE_EMOJI: Final[str] = "emoji"
DESCRIPTION_NOT_TEXT: Final[str] = "not_text"


class AnswerParseMode(str, Enum):
    """Как найден объект ответа: готовый JSON по схеме, весь текст или единственный объект `{…}` внутри текста."""

    STRUCTURED = "structured_payload"
    DIRECT = PARSE_DIRECT
    CANDIDATE = PARSE_CANDIDATE


@dataclass(frozen=True)
class MergePayload:
    """Объект JSON ответа модели и как он найден; `data` None — объекта нет. Значения в `repr` не печатаются."""

    data: dict[str, Any] | None = field(repr=False)
    mode: AnswerParseMode | None

    @classmethod
    def of(cls, response: LlmResponse) -> MergePayload:
        if response.structured is not None:
            return cls(data=response.structured, mode=AnswerParseMode.STRUCTURED)
        try:
            data, mode = parse_json_tolerant(response.text)
        except RecursionError:                 # глубоко вложенный JSON; донор ловил любое исключение разбора
            return cls(data=None, mode=None)
        return cls(data=data, mode=AnswerParseMode(mode) if data is not None else None)

    @property
    def description_value(self) -> object:
        return None if self.data is None else self.data.get(DESCRIPTION_KEY)

    def overflow_reject(self, max_body_paragraphs: int) -> MergeReject | None:
        """Предварительная проверка донора: тело длиннее предела ровно на один абзац при пределе от семи."""
        description: object = self.description_value
        if not isinstance(description, str) or max_body_paragraphs < SINGLE_STEP_OVERFLOW_MIN_LIMIT:
            return None
        body_count: int = DescriptionLayout.of(description, max_body_paragraphs).body_paragraph_count
        if body_count != max_body_paragraphs + 1:
            return None
        return MergeAnswer.paragraph_count_reject(body_count, max_body_paragraphs)

    def shape_reject(self) -> MergeReject | None:
        """Объект есть, ключи ровно title и description, значения — непустые строки."""
        if self.data is None:
            return MergeReject(MergeRejectCode.NOT_JSON_OBJECT)
        keys: set[str] = set(self.data.keys())
        missing: list[str] = sorted(key for key in REQUIRED_KEYS if key not in keys)
        if missing:
            return MergeReject(MergeRejectCode.MISSING_KEYS, KEYS_JOINER.join(missing))
        extra: list[str] = sorted(key for key in keys if key not in REQUIRED_KEYS)
        if extra:
            return MergeReject(MergeRejectCode.EXTRA_KEYS, KEYS_JOINER.join(extra))
        for key in REQUIRED_KEYS:
            if isinstance(self.data.get(key), (list, dict)):
                return MergeReject(MergeRejectCode.UNEXPECTED, INVALID_TYPE_DETAIL.format(key=key))
        if not self._is_filled_text(self.data.get(TITLE_KEY)):
            return MergeReject(MergeRejectCode.INVALID_TITLE, TITLE_NOT_TEXT)
        if not self._is_filled_text(self.data.get(DESCRIPTION_KEY)):
            return MergeReject(MergeRejectCode.INVALID_DESCRIPTION, DESCRIPTION_NOT_TEXT)
        return None

    @staticmethod
    def _is_filled_text(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class MergeAnswer:
    """Принятый ответ модели: название, описание (тело и хвост), число абзацев тела. Тексты в `repr` не печатаются."""

    title: str = field(repr=False)
    description: MergedDescription
    layout: DescriptionLayout
    paragraph_count: int
    parse_mode: AnswerParseMode
    model: str

    @classmethod
    def parse(
        cls, response: LlmResponse, max_body_paragraphs: int, cta: CtaLexicon | None = None
    ) -> MergeAnswer | MergeReject:
        """Ответ модели → принятый ответ или отказ с кодом; исключений не бросает."""
        payload: MergePayload = MergePayload.of(response)
        reject: MergeReject | None = payload.overflow_reject(max_body_paragraphs) or payload.shape_reject()
        if reject is not None or payload.data is None or payload.mode is None:
            return cls._rejected(response.model, reject or MergeReject(MergeRejectCode.NOT_JSON_OBJECT))
        raw_description: MergedDescription = MergedDescription(str(payload.data[DESCRIPTION_KEY]))
        if raw_description.opens_with_cta(cta or CtaLexicon.load()):
            return cls._rejected(response.model, MergeReject(MergeRejectCode.CTA_AS_FIRST_PARAGRAPH))
        draft: _AnswerDraft = _AnswerDraft(
            model=response.model,
            mode=payload.mode,
            title_value=str(payload.data[TITLE_KEY]),
            layout=DescriptionLayout.of(raw_description.text, max_body_paragraphs),
            max_body_paragraphs=max_body_paragraphs,
        )
        return draft.finish()

    @staticmethod
    def paragraph_count_reject(count: int, max_body_paragraphs: int) -> MergeReject:
        """Абзацев тела меньше двух — недобор, больше предела — перебор."""
        code: MergeRejectCode = (
            MergeRejectCode.PARAGRAPH_UNDERFLOW if count < MIN_BODY_PARAGRAPHS else MergeRejectCode.PARAGRAPH_OVERFLOW
        )
        detail: str = PARAGRAPH_COUNT_DETAIL.format(count=count, low=MIN_BODY_PARAGRAPHS, high=max_body_paragraphs)
        return MergeReject(code, detail)

    @staticmethod
    def _rejected(model: str, reject: MergeReject) -> MergeReject:
        LOGGER.info("merge_answer_rejected model=%s %s", model, reject.log_line)
        return reject

    @property
    def tail_recovery_applied(self) -> bool:
        return self.layout.recovery_applied

    @property
    def log_line(self) -> str:
        return (
            f"model={self.model} parse_mode={self.parse_mode.value} title_length={len(self.title)} "
            f"description_length={len(self.description.text)} paragraph_count={self.paragraph_count}"
        )


@dataclass(frozen=True)
class _AnswerDraft:
    """Ответ после проверки формы и призыва: раскладка готова, осталось проверить описание, абзацы и название."""

    model: str
    mode: AnswerParseMode
    title_value: str = field(repr=False)
    layout: DescriptionLayout
    max_body_paragraphs: int

    def finish(self) -> MergeAnswer | MergeReject:
        if self.layout.blocked_reason is not None:
            return self._rejected(MergeReject(self.layout.blocked_reason), with_layout=True)
        description: MergedDescription = MergedDescription(self.layout.full_text).without_meta_lines()
        if not description.text:
            return self._rejected(MergeReject(MergeRejectCode.DESCRIPTION_EMPTY))
        paragraph_count: int = len(split_paragraphs(self.layout.body_text))
        if not MIN_BODY_PARAGRAPHS <= paragraph_count <= self.max_body_paragraphs:
            reject: MergeReject = MergeAnswer.paragraph_count_reject(paragraph_count, self.max_body_paragraphs)
            return self._rejected(reject, with_layout=True)
        title: str | MergeReject = self._title()
        if isinstance(title, MergeReject):
            return self._rejected(title)
        answer: MergeAnswer = MergeAnswer(title, description, self.layout, paragraph_count, self.mode, self.model)
        LOGGER.info("merge_payload_parsed %s", answer.log_line)
        LOGGER.info(
            "merge_description_tail_analysis model=%s %s final_status=accepted", self.model, self.layout.log_fields
        )
        return answer

    def _title(self) -> str | MergeReject:
        """Пробелы схлопнуты, не длиннее 99 знаков, без эмодзи."""
        title: str = WHITESPACE_RUN_PATTERN.sub(" ", self.title_value.strip())
        if len(title) > TITLE_MAX_CHARS:
            title = title[:TITLE_MAX_CHARS].rstrip()
        if len(title) < TITLE_MIN_CHARS:
            return MergeReject(MergeRejectCode.INVALID_TITLE, TITLE_EMPTY)
        if EMOJI_PATTERN.search(title):
            return MergeReject(MergeRejectCode.INVALID_TITLE, TITLE_EMOJI)
        return title

    def _rejected(self, reject: MergeReject, with_layout: bool = False) -> MergeReject:
        if with_layout:
            LOGGER.info(
                "merge_description_tail_analysis model=%s %s final_status=rejected reject_reason=%s",
                self.model,
                self.layout.log_fields,
                reject.code.value,
            )
        return MergeAnswer._rejected(self.model, reject)
