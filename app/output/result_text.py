"""Итог эфира словами людей — одинаково в отчёте и консоли (CLAUDE.md §3 шаг 12, §6 инвариант 6).

`ResultText` говорит, что стало с эфиром: создан, исправлен, совпал, без потока, поток привязан, не допущен, ошибка;
что с ключом в форме; какие поля исправить не удалось. Ключ потока — только маской (`mask_stream_key`).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.core.text_format import SPACE
from app.form.question import NO_VALUE
from app.observability.logging_setup import mask_stream_key
from app.output.result import BroadcastResult, KeyState, OutcomeKind
from app.pipeline.admission import AdmissionWording
from app.pipeline.memory import ReplacedBroadcast
from app.ui.messages import msg


@dataclass(frozen=True)
class NotAdmittedState:
    """Что с эфиром не допущенного объекта на канале и что программа сделает на следующем запуске."""

    consequence: str
    next_run: str


@dataclass(frozen=True)
class ResultText:
    """Тексты одного итога; `is_dry_run` — запуск без действий: «будет создан», «будет исправлено»."""

    result: BroadcastResult
    is_dry_run: bool = False

    @property
    def prefix(self) -> str:
        return self.result.label.text

    @property
    def line(self) -> str:
        """Строка отчёта: в dry-run — с хвостом «не выполнено»; не допущенный не выполнялся бы и так."""
        if not self.is_dry_run or self.result.kind is OutcomeKind.NOT_ADMITTED:
            return self.body
        return self.body + msg.OUTCOME_DRY_RUN_SUFFIX

    @property
    def body(self) -> str:
        """Текст итога по его виду."""
        texts: dict[OutcomeKind, Callable[[], str]] = {
            OutcomeKind.CREATED: self._created,
            OutcomeKind.FIXED: lambda: self._fixed() + self.unfixed_tail,
            OutcomeKind.MATCHED: lambda: self._matched() + self.unfixed_tail,
            OutcomeKind.AMBIGUOUS: lambda: msg.OUTCOME_AMBIGUOUS.format(prefix=self.prefix),
            OutcomeKind.NO_STREAM: lambda: msg.OUTCOME_NO_STREAM.format(prefix=self.prefix, url=self._url),
            OutcomeKind.NOT_ADMITTED: lambda: self.not_admitted,
            OutcomeKind.STREAM_ATTACHED: lambda: msg.OUTCOME_STREAM_ATTACHED.format(
                prefix=self.prefix, form=self.form_mark
            ),
            OutcomeKind.ERROR: lambda: msg.OUTCOME_ERROR.format(prefix=self.prefix, text=self.result.error_text),
        }
        return texts[self.result.kind]()

    @property
    def form_mark(self) -> str:
        """Что с ключом этого запуска в форме; ключ в форму не шёл — прочерк."""
        state: KeyState | None = self.result.key_state
        if state is None:
            return NO_VALUE
        if state is KeyState.FAILED:
            return msg.FORM_MARK_FAILED.format(reason=self.result.failure_text)
        return msg.FORM_MARK_SENT if state is KeyState.SENT else msg.FORM_MARK_PLANNED

    @property
    def unfixed_tail(self) -> str:
        """Хвост «обложка не поставлена»; исправлено всё, что надо было, — пусто."""
        if not self.result.unfixed:
            return ""
        what: str = msg.LIST_JOINER.join(
            msg.UNFIXED_FIELD_TEXT.get(name.value, msg.CHANGED_FIELD_TEXT[name.value]) for name in self.result.unfixed
        )
        return msg.OUTCOME_UNFIXED.format(what=what)

    @property
    def changed_text(self) -> str:
        """Исправленные поля через запятую."""
        return msg.LIST_JOINER.join(change.name for change in self.result.changes)

    @property
    def not_admitted(self) -> str:
        """Не допущенный объект: чего не хватает, что не сделано, что сделать и что программа сделает сама."""
        wordings: tuple[AdmissionWording, ...] = self.result.wordings
        state: NotAdmittedState = self._not_admitted_state
        actions: dict[str, None] = dict.fromkeys(wording.action for wording in wordings)
        return msg.NOT_ADMITTED_LINE.format(
            prefix=self.prefix,
            problems=SPACE.join(wording.problem for wording in wordings),
            consequence=state.consequence,
            actions=SPACE.join(actions),
            next_run=state.next_run,
        )

    @property
    def not_delivered(self) -> str:
        """Раздел «Ключ не дошёл до стримера»: эфир стоит, а стример ключа не получил."""
        return msg.NOT_DELIVERED_LINE.format(prefix=self.prefix, reason=self.result.failure_text)

    def two_keys(self, replaced: ReplacedBroadcast) -> str:
        """Эфир слота заменён новым, а прежний ключ форма уже подтверждала: в форме на дату два ключа."""
        return msg.TWO_KEYS_LINE.format(
            prefix=self.prefix,
            old_url=replaced.broadcast_url,
            new_url=self._url,
            new_key=mask_stream_key(self.result.stream_key),
            old_key=mask_stream_key(replaced.stream_key),
        )

    @property
    def _url(self) -> str:
        return self.result.broadcast_url or NO_VALUE

    @property
    def _not_admitted_state(self) -> NotAdmittedState:
        if not self.result.is_channel_ready:
            return NotAdmittedState(msg.NOT_ADMITTED_CONSEQUENCE_CHANNEL, msg.NOT_ADMITTED_NEXT_CHANNEL)
        if self.result.broadcast_url:
            consequence: str = msg.NOT_ADMITTED_CONSEQUENCE_BROADCAST.format(url=self.result.broadcast_url)
            return NotAdmittedState(consequence, msg.NOT_ADMITTED_NEXT_BROADCAST)
        return NotAdmittedState(msg.NOT_ADMITTED_CONSEQUENCE_NO_BROADCAST, msg.NOT_ADMITTED_NEXT_NO_BROADCAST)

    def _created(self) -> str:
        if self.is_dry_run:
            return msg.OUTCOME_CREATE_PLANNED.format(prefix=self.prefix)
        return msg.OUTCOME_CREATED.format(prefix=self.prefix, form=self.form_mark)

    def _fixed(self) -> str:
        if self.is_dry_run:
            return msg.OUTCOME_FIX_PLANNED.format(prefix=self.prefix, what=self.changed_text)
        form: str = "" if self.result.key_state is None else msg.OUTCOME_FIXED_FORM.format(mark=self.form_mark)
        return msg.OUTCOME_FIXED.format(prefix=self.prefix, what=self.changed_text, form=form)

    def _matched(self) -> str:
        """Совпавший эфир; его ключ ушёл (или ушёл бы) в форму — хвостом."""
        text: str = msg.OUTCOME_MATCHED.format(prefix=self.prefix, url=self._url)
        if self.result.key_state is None:
            return text
        return text + msg.OUTCOME_MATCHED_FORM.format(mark=self.form_mark)
