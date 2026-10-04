"""Допуск эфира к публикации и ответ формы ключей для него (CLAUDE.md §3 шаг 9, §6 инварианты 0, 2; §14 решение 25).

После фазы входов объект эфира получает объект своего канала и свою форму — прочитанную или отказ чтения
(`FormBook.form_for`), а когда линия «Ключи в форму» не идёт — без формы (§14 решение 37: форма не читается, допуск
только по каналу). Из них `Admission` знает причины недопуска по порядку: канал не подтверждён → форма не
прочиталась → незаполненные поля формы. Ключ и адрес потока до публикации неизвестны — «ожидаются», причиной не
считаются. Значения канала для формы — из объекта канала после фазы входов: канал, выровненный при входе, отвечает
новыми названием и ником в том же запуске. Причина сама говорит человеку, чего не хватает и что сделать (`wording`):
один текст для отчёта, консоли и keys.txt.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.config.channel import ChannelConfig
from app.config.settings import FormSettings
from app.form.answers import AnswerValues, FormAnswers, MissingAnswer
from app.form.failure import FormFailure, FormProblem
from app.form.key_form import KeyForm
from app.form.question import NO_VALUE
from app.form.submission import FormSubmission
from app.platforms.broadcast import CreatedBroadcast
from app.platforms.channel import Channel, ChannelStatus
from app.records.record_results import ConfirmedAnswer
from app.slots.slot import StreamSlot
from app.ui.messages import msg


class AdmissionKind(str, Enum):
    CHANNEL = "channel"                  # канал не READY
    FORM_UNREADABLE = "form_unreadable"  # форма не прочиталась
    FORM_FIELD = "form_field"            # в форме нет варианта или обязательный вопрос без ответа


@dataclass(frozen=True)
class AdmissionWording:
    """Причина недопуска словами человека: чего не хватает и что сделать — по предложению."""

    problem: str
    action: str


@dataclass(frozen=True)
class AdmissionReason:
    """Почему объект не допущен. `text` — для владельца, без оформления (его делает отчёт).

    CHANNEL — короткая причина по статусу канала, код — статус (полный текст отказа канала — в объекте канала);
    FORM_UNREADABLE — отказ формы для человека, код — `FormProblem`; FORM_FIELD — «вопрос: значение», код —
    `FormProblem`, поле настроек формы, вопрос и значение — ещё и по отдельности. `form_name` — имя формы для людей:
    заголовок, у непрочитанной — ссылка.
    """

    kind: AdmissionKind
    code: str
    field: str | None
    text: str
    question: str = ""
    value: str = ""
    form_name: str = ""

    @classmethod
    def of_channel(cls, status: ChannelStatus) -> AdmissionReason:
        return cls(AdmissionKind.CHANNEL, status.value, None, msg.ADMISSION_CHANNEL_TEXT[status.value])

    @classmethod
    def of_failure(cls, failure: FormFailure) -> AdmissionReason:
        return cls(AdmissionKind.FORM_UNREADABLE, failure.problem.value, None, failure.human, form_name=failure.form)

    @classmethod
    def of_missing(cls, missing: MissingAnswer, form_name: str) -> AdmissionReason:
        field: str | None = None if missing.field is None else missing.field.value
        kind: AdmissionKind = AdmissionKind.FORM_FIELD
        text: str = missing.detail
        return cls(kind, missing.problem.value, field, text, missing.question, missing.value, form_name)

    @property
    def wording(self) -> AdmissionWording:
        """Чего не хватает и что сделать. Вариант «-» — настройки формы не дали текста варианта: форме тут не поможешь."""
        if self.kind is AdmissionKind.CHANNEL:
            return AdmissionWording(msg.ADMISSION_CHANNEL_PROBLEM[self.code], msg.ADMISSION_CHANNEL_ACTION[self.code])
        if self.kind is AdmissionKind.FORM_UNREADABLE:
            return AdmissionWording(self.text, msg.ADMISSION_ACTION_FORM_UNREADABLE)
        if self.code == FormProblem.REQUIRED_MISSING.value:
            problem: str = msg.ADMISSION_REQUIRED_MISSING.format(form=self.form_name, question=self.question)
            return AdmissionWording(problem, msg.ADMISSION_ACTION_REQUIRED_MISSING)
        if self.value == NO_VALUE:
            missing: str = msg.ADMISSION_MISSING_SETTINGS_TEXT.format(form=self.form_name, question=self.question)
            return AdmissionWording(missing, msg.ADMISSION_ACTION_MISSING_SETTINGS_TEXT)
        option: str = msg.ADMISSION_MISSING_OPTION.format(form=self.form_name, question=self.question, value=self.value)
        return AdmissionWording(option, msg.ADMISSION_ACTION_MISSING_OPTION)


@dataclass
class Admission:
    """Объект канала и форма запуска, ответ формы этого эфира и причины недопуска. Изменяемый намеренно: ответ
    перестраивается, когда объект берёт ключ с площадки. Пустой — объект ещё не проходил допуск и не задержан им."""

    channel: Channel | None = None
    key_form: KeyForm | None = None
    failure: FormFailure | None = None
    answers: FormAnswers | None = None
    reasons: tuple[AdmissionReason, ...] = ()

    @classmethod
    def of(cls, channel: Channel, form: KeyForm | FormFailure | None) -> Admission:
        """Объект канала и форма — прочитанная, отказ чтения или никакой (ключи в форму не идут)."""
        if isinstance(form, FormFailure):
            return cls(channel=channel, failure=form)
        return cls(channel=channel, key_form=form)

    @property
    def is_admitted(self) -> bool:
        return not self.reasons

    @property
    def found_reasons(self) -> tuple[AdmissionReason, ...]:
        """Причины по порядку: канал не READY → форма не прочиталась → незаполненные поля ответа."""
        reasons: list[AdmissionReason] = []
        if self.channel is not None and self.channel.status is not ChannelStatus.READY:
            reasons.append(AdmissionReason.of_channel(self.channel.status))
        if self.failure is not None:
            reasons.append(AdmissionReason.of_failure(self.failure))
        if self.answers is not None:
            reasons.extend(AdmissionReason.of_missing(missing, self.answers.form) for missing in self.answers.missing)
        return tuple(reasons)

    def channel_config(self, built: ChannelConfig) -> ChannelConfig:
        """Значения канала сейчас: из объекта канала после фазы входов; объекта нет — те, с которыми объект построен."""
        return built if self.channel is None else self.channel.config

    @property
    def channel_id(self) -> str | None:
        """Id канала на YouTube — ключ записи памяти; канал не READY или YouTube его не прислал — None."""
        if self.channel is None or self.channel.status is not ChannelStatus.READY or self.channel.info is None:
            return None
        return self.channel.info.youtube_channel_id

    def answer(self, slot: StreamSlot, built: ChannelConfig, key: CreatedBroadcast | None) -> FormAnswers | None:
        """Ответ формы по значениям эфира: ключ и адрес — взятые с площадки, их нет — «ожидаются»; формы нет — None."""
        if self.key_form is not None:
            values: AnswerValues = AnswerValues(
                language=slot.language,
                start=slot.start,
                account_name=self.channel_config(built).account_name,
                stream_key=None if key is None else key.stream_key,
                stream_url=None if key is None else key.stream_url,
            )
            self.answers = self.key_form.answers(values)
        return self.answers

    @property
    def is_complete(self) -> bool:
        """Ответ есть и полный: ни одного незаполненного и ожидаемого поля."""
        return self.answers is not None and self.answers.is_complete

    def response_url(self, form: FormSettings) -> str:
        """Адрес, куда уходит ответ: у прочитанной формы — её formResponse, иначе — ссылка настроек формы."""
        return form.url if self.key_form is None else self.key_form.structure.response_url

    @property
    def answers_record(self) -> tuple[ConfirmedAnswer, ...]:
        """Текущие ответы в виде памяти: entry_id, вопрос, значение."""
        return () if self.answers is None else tuple(ConfirmedAnswer.of(answer) for answer in self.answers.answers)

    def submission(self, slot_id: str, handle: str) -> FormSubmission:
        """Ответ формы, готовый к отправке; зовётся только при полном ответе прочитанной формы."""
        return FormSubmission(form=self.key_form, answers=self.answers, slot_id=slot_id, handle=handle)
