"""Объект запланированного эфира — рабочая единица контура B (CLAUDE.md §3 шаги 8–11, §6 инварианты 0, 1, 1a).

Один объект = один эфир одного слота на одном канале. Объект рождается из слота, канала и формы ключей; ключ и
ссылка приходят только с площадки (`BroadcastMatch`). Из памяти объект получает только результаты прошлых запусков
(`BroadcastMemory`); задания из памяти не берутся. После фазы входов объект получает объект своего канала и свою форму
и сам решает, допущен ли он (`admit` — единственное место правила допуска, `Admission`); линия «Ключи в форму» не
идёт — формы нет, допуск только по каналу. Должен ли ключ уйти в форму, решает одно правило — `decide_key_delivery`
по правилам ключей запуска (`KeyRoute`: «новые | все», §14 решение 49); ответ формы строит сам объект (`submission`),
итог отправки — подтверждение формы или ещё одна неподтверждённая отправка — в его память (`remember_send`), запись
памяти — он же (`to_record`). Моменты — по часам программы (инвариант 4).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import timezone
from typing import Final

from app.config.channel import ChannelConfig
from app.config.settings import FormSettings
from app.core.clock import Clock
from app.core.dates import ISO_TIMESPEC, format_datetime_text
from app.form.failure import FormFailure
from app.form.key_form import KeyForm
from app.form.submission import FormSubmission
from app.pipeline.admission import Admission
from app.pipeline.decision import Decision
from app.pipeline.match import BroadcastMatch
from app.pipeline.memory import BroadcastMemory, RecordChannelMissing
from app.pipeline.outcome import BroadcastOutcome
from app.platforms.channel import Channel
from app.platforms.spec import BroadcastSpec
from app.records.record_results import RecordResults
from app.records.slot_record import RecordSnapshot, SlotRecord, SlotStage
from app.slots.slot import StreamSlot

# Повторов неподтверждённого ключа при «новые» — один (§14 решение 49): вторая неподтверждённая отправка — последняя.
KEY_RETRIES: Final[int] = 1


@dataclass(frozen=True)
class KeyRoute:
    """Правила ключей одного запуска: идёт ли линия «Ключи в форму» (`to_form`, §14 решение 37) и какие ключи передать
    (`resend`: «все» — ключи всех эфиров запуска; иначе «новые», §14 решения 36, 49)."""

    to_form: bool
    resend: bool


@dataclass
class PlannedBroadcast:
    """Изменяемый намеренно: части заполняются по ходу запуска. Слот, канал, форма и спека после конструктора не
    меняются; `channel` — значения канала, с которыми объект построен, значения канала сейчас —
    `admission.channel_config` (§14 решение 25). `form` — форма ключей этого эфира: в режиме А — из livecraft.json,
    в режиме Б — из пакета.
    """

    slot: StreamSlot
    channel: ChannelConfig
    form: FormSettings
    expected: BroadcastSpec
    is_too_late: bool = False      # слот внутри min_lead_minutes: только чтение площадки, ключ храним
    decision: Decision = Decision.CREATE
    match: BroadcastMatch = field(default_factory=BroadcastMatch)
    admission: Admission = field(default_factory=Admission)
    memory: BroadcastMemory = field(default_factory=BroadcastMemory)
    outcome: BroadcastOutcome = field(default_factory=BroadcastOutcome)

    def admit(self, channel: Channel, form: KeyForm | FormFailure | None) -> None:
        """Единственное место правила допуска: канал → форма не прочиталась → незаполненные поля формы. Формы нет
        (линия «Ключи в форму» не идёт) — только канал.

        too_late допуск не проходит (у него свой путь только на чтение): объект канала и форма запоминаются, причин нет.
        """
        self.admission = Admission.of(channel, form)
        self.admission.answer(self.slot, self.channel, None)
        if self.is_too_late:
            return
        self.admission.reasons = self.admission.found_reasons
        if self.admission.reasons:
            self.decision = Decision.NOT_ADMITTED

    def decide_key_delivery(self, route: KeyRoute) -> None:
        """ЕДИНСТВЕННОЕ правило отправки ключа в форму (инвариант 1a, §14 решение 49).

        Ключ должен уйти, если идёт линия «Ключи в форму», объект допущен, не too_late, ключ и адрес потока взяты с
        площадки в этом запуске, и: «все» (`route.resend`) — всегда; «новые» — эфир поставлен на YouTube этим запуском
        (создан или получил поток, `BroadcastMatch.published`), либо прошлая отправка этого же ключа в эту же форму не
        подтверждена формой и повтора ещё не было. Уже стоявший эфир при «новые» ключ не передаёт, даже если
        подтверждения в памяти нет. Откуда слот — из таблицы или из пакета — не важно; ключ уходит в форму своего слота.
        Ошибка другого шага отправку не отменяет. Полны ли ответы, решает `is_key_ready_to_send`: неполные — ключ
        «должен был уйти и не ушёл».
        """
        self.admission.answer(self.slot, self.channel, self.match.key)
        is_new: bool = self.match.published is not None
        sends: int = self.memory.results.unconfirmed_sends(self.match.stream_key, self.admission.response_url(self.form))
        self.outcome.should_send_key = (
            route.to_form
            and self.admission.is_admitted
            and not self.is_too_late
            and self.match.has_full_key
            and (route.resend or is_new or 0 < sends <= KEY_RETRIES)
        )

    def remember_send(self, clock: Clock) -> None:
        """Итог отправки ключа этого запуска — в память объекта: форма подтвердила — ключ, адрес формы и ответы с
        моментом подтверждения, счёт неподтверждённых отправок снят; не подтвердила (или ответ неполный и POST не было)
        — ещё одна неподтверждённая отправка этого ключа в эту форму."""
        url: str = self.admission.response_url(self.form)
        if not self.outcome.is_form_sent:
            self.memory.confirmed = self.memory.results.with_unconfirmed_send(self.match.stream_key or "", url)
            return
        self.memory.confirmed = replace(
            self.memory.results,
            confirmed_stream_key=self.match.stream_key,
            confirmed_form_url=url,
            confirmed_answers=self.admission.answers_record,
            confirmed_at=format_datetime_text(clock.now()),
            unconfirmed=None,
        )

    def to_record(self, clock: Clock, stage: SlotStage) -> SlotRecord:
        """Запись объекта: снимок для людей и результаты. Стадия не откатывается ниже достигнутого для этого ключа."""
        channel_id: str | None = self.admission.channel_id
        if channel_id is None:
            raise RecordChannelMissing(self.slot.slot_id)
        moment: str = format_datetime_text(clock.now())
        results: RecordResults = self.memory.record_results(self.match, moment)
        reached: list[SlotStage] = [stage]
        if results.stream_key:
            reached.append(SlotStage.PUBLISHED)
        if results.confirms_key(results.stream_key):
            reached.append(SlotStage.KEY_CONFIRMED)
        return SlotRecord(
            slot_id=self.slot.slot_id,
            youtube_channel_id=channel_id,
            slot_start_utc=self.slot.start.astimezone(timezone.utc).isoformat(timespec=ISO_TIMESPEC),
            stage=max(reached, key=lambda reached_stage: reached_stage.rank),
            updated_at=moment,
            results=results,
            snapshot=self._snapshot(),
        )

    @property
    def is_key_ready_to_send(self) -> bool:
        """Ключ должен уйти, он есть, форма его в этом запуске ещё не подтвердила и ответ формы полный."""
        is_waiting: bool = self.outcome.should_send_key and not self.outcome.is_form_sent
        return is_waiting and bool(self.match.stream_key) and self.admission.is_complete

    @property
    def is_key_undelivered(self) -> bool:
        """Ключ должен дойти до стримера, а до формы ещё не дошёл: код выхода 1 и «НЕ отправлен» в keys.txt."""
        return self.outcome.should_send_key and bool(self.match.stream_key) and not self.outcome.is_form_sent

    @property
    def is_key_given_up(self) -> bool:
        """Ключ этого эфира уходил в форму без подтверждения и первый раз, и повтором — сам он больше не уходит
        (§14 решение 49): передать его можно только выбором «все». В этом запуске он в форму не шёл."""
        if self.outcome.should_send_key or not self.admission.is_admitted or self.is_too_late:
            return False
        sends: int = self.memory.results.unconfirmed_sends(self.match.stream_key, self.admission.response_url(self.form))
        return self.match.has_full_key and sends > KEY_RETRIES

    @property
    def has_kept_key(self) -> bool:
        """Память хранит подтверждение текущего ключа, и в этом запуске он повторно не отправлялся."""
        if self.outcome.should_send_key or self.outcome.is_form_sent or self.outcome.error is not None:
            return False
        return self.memory.results.confirms_key(self.match.stream_key)

    def submission(self) -> FormSubmission:
        """Ответ формы для отправки — только готового ключа (`is_key_ready_to_send`); ник — канала сейчас."""
        return self.admission.submission(self.slot.slot_id, self.admission.channel_config(self.channel).handle)

    def _snapshot(self) -> RecordSnapshot:
        channel: ChannelConfig = self.admission.channel_config(self.channel)
        return RecordSnapshot(
            date=self.slot.date,
            time=self.slot.time,
            language=self.slot.language,
            account_name=channel.account_name,
            handle=channel.handle,
            title=self.expected.title,
            form_url=self.form.url,
            decision=self.decision.value,
            admission_reasons=tuple(reason.text for reason in self.admission.reasons),
            last_error=self.outcome.last_error,
            warnings=tuple(warning.record_text for warning in self.outcome.warnings),
        )
