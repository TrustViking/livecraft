"""Итог эфира словами людей — одинаково в отчёте и консоли (CLAUDE.md §3 шаг 12, §6 инвариант 6).

`ResultText` говорит, что стало с эфиром: создан, исправлен, совпал, без потока, поток привязан, не допущен, ошибка,
тексты не обновлялись;
что с ключом в форме; какие поля исправить не удалось. Ключ потока — только маской (`mask_stream_key`).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.core.text_format import SPACE
from app.form.question import NO_VALUE
from app.observability.logging_setup import mask_stream_key
from app.output.result import BroadcastResult, KeyState, OutcomeKind
from app.pipeline.admission import AdmissionWording
from app.pipeline.memory import ReplacedBroadcast
from app.ui.messages import msg


class NotAdmittedCase(str, Enum):
    """Что с эфиром не допущенного объекта на канале: канал не проверялся, эфир на канале есть, эфира нет. От вида —
    что программа сделает на следующем запуске; у нескольких эфиров одного вида — те же слова во множественном числе
    (одна строка консоли на причину, app\\output\\attention.py)."""

    CHANNEL = "channel"
    BROADCAST = "broadcast"
    NO_BROADCAST = "no_broadcast"

    @property
    def next_run(self) -> str:
        texts: dict[NotAdmittedCase, str] = {
            NotAdmittedCase.CHANNEL: msg.NOT_ADMITTED_NEXT_CHANNEL,
            NotAdmittedCase.BROADCAST: msg.NOT_ADMITTED_NEXT_BROADCAST,
            NotAdmittedCase.NO_BROADCAST: msg.NOT_ADMITTED_NEXT_NO_BROADCAST,
        }
        return texts[self]

    @property
    def group_consequence(self) -> str:
        texts: dict[NotAdmittedCase, str] = {
            NotAdmittedCase.CHANNEL: msg.NOT_ADMITTED_GROUP_CONSEQUENCE_CHANNEL,
            NotAdmittedCase.BROADCAST: msg.NOT_ADMITTED_GROUP_CONSEQUENCE_BROADCAST,
            NotAdmittedCase.NO_BROADCAST: msg.NOT_ADMITTED_GROUP_CONSEQUENCE_NO_BROADCAST,
        }
        return texts[self]

    @property
    def group_next_run(self) -> str:
        texts: dict[NotAdmittedCase, str] = {
            NotAdmittedCase.CHANNEL: msg.NOT_ADMITTED_GROUP_NEXT_CHANNEL,
            NotAdmittedCase.BROADCAST: msg.NOT_ADMITTED_GROUP_NEXT_BROADCAST,
            NotAdmittedCase.NO_BROADCAST: msg.NOT_ADMITTED_GROUP_NEXT_NO_BROADCAST,
        }
        return texts[self]


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
        """Строка отчёта: в dry-run — с хвостом «не выполнено»; не допущенный и эфир «по номерам» не выполнялись бы
        и так."""
        if not self.is_dry_run or self.result.kind in (OutcomeKind.NOT_ADMITTED, OutcomeKind.KEPT):
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
            OutcomeKind.KEPT: lambda: msg.OUTCOME_KEPT.format(prefix=self.prefix, url=self._url),
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
        case: NotAdmittedCase = self.not_admitted_case
        actions: dict[str, None] = dict.fromkeys(wording.action for wording in wordings)
        return msg.NOT_ADMITTED_LINE.format(
            prefix=self.prefix,
            problems=SPACE.join(wording.problem for wording in wordings),
            consequence=self._consequence(case),
            actions=SPACE.join(actions),
            next_run=case.next_run,
        )

    @property
    def not_admitted_case(self) -> NotAdmittedCase:
        """Что с эфиром не допущенного объекта: канал не готов — не проверялся; иначе эфир на канале есть или нет."""
        if not self.result.is_channel_ready:
            return NotAdmittedCase.CHANNEL
        return NotAdmittedCase.BROADCAST if self.result.broadcast_url else NotAdmittedCase.NO_BROADCAST

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

    def _consequence(self, case: NotAdmittedCase) -> str:
        """Что не сделано с этим эфиром; эфир на канале есть — со ссылкой на него."""
        if case is NotAdmittedCase.BROADCAST:
            return msg.NOT_ADMITTED_CONSEQUENCE_BROADCAST.format(url=self.result.broadcast_url)
        if case is NotAdmittedCase.CHANNEL:
            return msg.NOT_ADMITTED_CONSEQUENCE_CHANNEL
        return msg.NOT_ADMITTED_CONSEQUENCE_NO_BROADCAST

    def _created(self) -> str:
        """Созданный эфир; в dry-run — «будет создан» и отметка ключа по тому же правилу, что у запуска."""
        if self.is_dry_run:
            return msg.OUTCOME_CREATE_PLANNED.format(prefix=self.prefix) + self._form_tail
        return msg.OUTCOME_CREATED.format(prefix=self.prefix, form=self.form_mark)

    def _fixed(self) -> str:
        """Исправленный эфир; ключ в этом запуске в форму не идёт — без отметки (в dry-run тоже, §14 решение 49)."""
        if self.is_dry_run:
            return msg.OUTCOME_FIX_PLANNED.format(prefix=self.prefix, what=self.changed_text) + self._form_tail
        return msg.OUTCOME_FIXED.format(prefix=self.prefix, what=self.changed_text, form=self._form_tail)

    @property
    def _form_tail(self) -> str:
        """Отметка ключа хвостом: ключ в форму не идёт — пусто."""
        return "" if self.result.key_state is None else msg.OUTCOME_FIXED_FORM.format(mark=self.form_mark)

    def _matched(self) -> str:
        """Совпавший эфир; его ключ ушёл (или ушёл бы) в форму — хвостом."""
        text: str = msg.OUTCOME_MATCHED.format(prefix=self.prefix, url=self._url)
        if self.result.key_state is None:
            return text
        return text + msg.OUTCOME_MATCHED_FORM.format(mark=self.form_mark)
