"""Итог одного эфира для вывода контура B (CLAUDE.md §3 шаг 12, §6 инварианты 1a, 6).

`BroadcastResult` — что стало с эфиром в этом запуске: вид итога, слот, канал (значения после фазы входов, §14
решение 25), ссылка на эфир, название по спеке, ключ потока, состояние ключа в форме и отказ формы, исправленные и
неисправленные поля, причины недопуска и прежний эфир с подтверждённым ключом. Строится одним правилом из объекта
эфира (`of_planned`, правила итога — `PlannedResult`) и, в --status, из эфира с меткой программы на площадке
(`of_marked`). Ключ потока здесь — полностью: маскирует его вывод (отчёт и консоль), полностью он только в keys.txt.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.channel import ChannelConfig
from app.core.youtube_video import YouTubeVideoId
from app.form.failure import FormFailure
from app.form.question import NO_VALUE
from app.pipeline.admission import AdmissionKind, AdmissionReason, AdmissionWording
from app.pipeline.decision import Decision
from app.pipeline.fixes import FieldFixes
from app.pipeline.memory import ReplacedBroadcast
from app.pipeline.orphan import MarkedBroadcast
from app.pipeline.outcome import OutcomeError
from app.pipeline.plan import PlannedBroadcast
from app.platforms.broadcast import CreatedBroadcast
from app.platforms.spec import BroadcastSpec, ChangedField, SpecValue
from app.slots.slot import SlotKey
from app.ui.messages import msg


class OutcomeKind(str, Enum):
    CREATED = "created"
    FIXED = "fixed"
    MATCHED = "matched"
    NO_STREAM = "no_stream"               # эфир есть, привязанного потока нет — ключ взять неоткуда
    STREAM_ATTACHED = "stream_attached"   # эфир был без потока, поток привязан этим запуском
    ERROR = "error"
    AMBIGUOUS = "ambiguous"
    NOT_ADMITTED = "not_admitted"         # не допущен: на площадке ничего не делали, в форму не слали


# Требуют внимания и дают код выхода 1.
ERROR_KINDS: Final[frozenset[OutcomeKind]] = frozenset(
    {OutcomeKind.ERROR, OutcomeKind.AMBIGUOUS, OutcomeKind.NO_STREAM}
)
# Привязанный поток — тоже новый ключ, поэтому он в «Создано».
CREATED_KINDS: Final[frozenset[OutcomeKind]] = frozenset({OutcomeKind.CREATED, OutcomeKind.STREAM_ATTACHED})
DECISION_KINDS: Final[dict[Decision, OutcomeKind]] = {
    Decision.CREATE: OutcomeKind.CREATED,
    Decision.UPDATE: OutcomeKind.FIXED,
    Decision.MATCH: OutcomeKind.MATCHED,
    Decision.NO_STREAM: OutcomeKind.NO_STREAM,
    Decision.TOO_LATE: OutcomeKind.MATCHED,     # в итоги не входит: слот — в разделе «Пропущено»
    Decision.AMBIGUOUS: OutcomeKind.AMBIGUOUS,
    Decision.ERROR: OutcomeKind.ERROR,
    Decision.NOT_ADMITTED: OutcomeKind.NOT_ADMITTED,
}
# Тексты и обложка эфира правятся по плану штатно; настройки, которые программа вернула к плану, — во «Внимание».
CONTENT_FIELDS: Final[frozenset[ChangedField]] = frozenset(
    {ChangedField.TITLE, ChangedField.DESCRIPTION, ChangedField.THUMBNAIL}
)


class KeyState(str, Enum):
    """Ключ, который в этом запуске должен был дойти до стримера (инвариант 1a)."""

    SENT = "sent"          # форма подтвердила ответ
    FAILED = "failed"      # не подтвердила
    PLANNED = "planned"    # --dry-run: ключ ушёл бы в форму


@dataclass(frozen=True)
class ShownValue:
    """Значение поля спеки для людей: да / нет, прочерк, как есть."""

    value: SpecValue

    @property
    def text(self) -> str:
        if self.value is None or self.value == "":
            return NO_VALUE
        if isinstance(self.value, bool):
            return msg.SPEC_VALUE_TRUE if self.value else msg.SPEC_VALUE_FALSE
        return self.value


@dataclass(frozen=True)
class KeyFailure:
    """Почему ключ этого запуска не дошёл до формы — предложением для людей; отказа нет — форма не подтвердила."""

    failure: FormFailure | None

    @property
    def text(self) -> str:
        return msg.FORM_FAILURE_UNKNOWN if self.failure is None else self.failure.human


@dataclass(frozen=True)
class FieldChange:
    """Исправленное поле: как было на площадке и как стало по плану — словами людей; прочерк — площадка не вернула."""

    field: ChangedField
    before: str
    after: str

    @property
    def is_content(self) -> bool:
        """Текст или обложка эфира: правятся штатно, о настройках программа говорит отдельно."""
        return self.field in CONTENT_FIELDS

    @property
    def name(self) -> str:
        return msg.CHANGED_FIELD_TEXT[self.field.value]


@dataclass(frozen=True)
class SlotLabel:
    """Слот и канал для людей: «17.03.2027 19:00 uk -> Канал @ник» — начало строк отчёта и консоли."""

    key: SlotKey
    channel: ChannelConfig

    @classmethod
    def of(cls, item: PlannedBroadcast) -> SlotLabel:
        """Канал объекта — значения после фазы входов."""
        return cls(item.slot.key, item.admission.channel_config(item.channel))

    @property
    def text(self) -> str:
        key: SlotKey = self.key
        return msg.OUTCOME_SLOT_PREFIX.format(
            date=key.human_date, time=key.time_text, language=key.language, channel=self.channel.label
        )


@dataclass(frozen=True)
class PlannedResult:
    """Правила итога по объекту эфира; в dry-run действий не было — что было бы исправлено и отправлено."""

    item: PlannedBroadcast
    is_dry_run: bool

    @property
    def applied(self) -> tuple[ChangedField, ...]:
        """Что исправлено по факту; в dry-run — что было бы исправлено."""
        fixes: FieldFixes = self.item.match.fixes
        return fixes.changed if self.is_dry_run else fixes.fixed

    @property
    def kind(self) -> OutcomeKind:
        """Ошибка главнее решения; привязанный поток — новый ключ; исправить ничего не удалось — эфир стоит как был."""
        if self.item.outcome.error is not None:
            return OutcomeKind.ERROR
        if self.item.match.stream_attached:
            return OutcomeKind.STREAM_ATTACHED
        kind: OutcomeKind = DECISION_KINDS[self.item.decision]
        if kind is OutcomeKind.FIXED and not self.applied:
            return OutcomeKind.MATCHED
        return kind

    @property
    def key_state(self) -> KeyState | None:
        """None — ключ в этом запуске в форму не шёл: его нет или память хранит его подтверждение."""
        if not self.item.outcome.should_send_key or not self.item.match.stream_key:
            return None
        if self.is_dry_run:
            return KeyState.PLANNED
        return KeyState.SENT if self.item.outcome.is_form_sent else KeyState.FAILED

    @property
    def broadcast_url(self) -> str | None:
        """Эфир ключа, иначе найденный без потока; эфира нет — None."""
        key: CreatedBroadcast | None = self.item.match.key
        return self.item.match.found_url if key is None else key.broadcast_url

    def change(self, name: ChangedField) -> FieldChange:
        """Было — как на площадке, стало — как в плане; у обложки — словами: отпечатки человеку ничего не скажут."""
        if name is ChangedField.THUMBNAIL:
            return FieldChange(name, msg.THUMBNAIL_BEFORE, msg.THUMBNAIL_AFTER)
        actual: BroadcastSpec | None = self.item.match.actual
        before: str = ShownValue(None if actual is None else actual.value(name)).text
        return FieldChange(name, before, ShownValue(self.item.expected.value(name)).text)


@dataclass(frozen=True)
class BroadcastResult:
    """Итог эфира. `key_state` None — ключ в этом запуске в форму не шёл; `form_failure` — почему он не дошёл."""

    kind: OutcomeKind
    key: SlotKey
    channel: ChannelConfig
    broadcast_url: str | None = None
    title: str = ""
    stream_key: str | None = None
    key_state: KeyState | None = None
    form_failure: FormFailure | None = None
    error: OutcomeError | None = None
    changes: tuple[FieldChange, ...] = ()
    unfixed: tuple[ChangedField, ...] = ()
    reasons: tuple[AdmissionReason, ...] = ()
    replaced: ReplacedBroadcast | None = None

    @classmethod
    def of_planned(cls, item: PlannedBroadcast, *, is_dry_run: bool) -> BroadcastResult:
        """Итог объекта эфира; неисправленных полей в dry-run нет: исправлять не пытались."""
        rules: PlannedResult = PlannedResult(item, is_dry_run)
        return cls(
            kind=rules.kind,
            key=item.slot.key,
            channel=item.admission.channel_config(item.channel),
            broadcast_url=rules.broadcast_url,
            title=item.expected.title,
            stream_key=item.match.stream_key,
            key_state=rules.key_state,
            form_failure=item.outcome.form_failure,
            error=item.outcome.error,
            changes=tuple(rules.change(name) for name in rules.applied),
            unfixed=() if is_dry_run else item.match.fixes.unfixed,
            reasons=item.admission.reasons,
            replaced=item.memory.replaced,
        )

    @classmethod
    def of_marked(cls, marked: MarkedBroadcast) -> BroadcastResult:
        """--status: эфир с меткой программы, найденный на канале, — уже стоит."""
        return cls(
            kind=OutcomeKind.MATCHED,
            key=marked.key,
            channel=marked.channel,
            broadcast_url=YouTubeVideoId(marked.broadcast.broadcast_id).watch_url,
            title=marked.broadcast.title.strip(),
            stream_key=marked.stream.stream_name,
        )

    @property
    def label(self) -> SlotLabel:
        return SlotLabel(self.key, self.channel)

    @property
    def is_channel_ready(self) -> bool:
        """Канал подтверждён: причины недопуска — не про канал."""
        return not any(reason.kind is AdmissionKind.CHANNEL for reason in self.reasons)

    @property
    def wordings(self) -> tuple[AdmissionWording, ...]:
        return tuple(reason.wording for reason in self.reasons)

    @property
    def failure_text(self) -> str:
        return KeyFailure(self.form_failure).text

    @property
    def error_text(self) -> str:
        """Текст ошибки эфира для людей; ошибки нет — прочерк."""
        return NO_VALUE if self.error is None else self.error.human
