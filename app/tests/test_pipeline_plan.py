"""Объект запланированного эфира: допуск, правило отправки ключа «новые | все», итог отправки и запись памяти
(CLAUDE.md §6 инварианты 0, 1a; §14 решения 25, 49)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config.channel import ChannelConfig
from app.config.settings import FormQuestion
from app.core.dates import format_datetime_text
from app.form.answers import FormAnswers
from app.form.failure import FormFailure, FormProblem
from app.form.diagnostic import FormDiagnostic
from app.form.sender import FormConfirmation, FormSender
from app.form.submission import FormSubmission
from app.form.question import NO_VALUE
from app.observability.log_event import LogEvent
from app.pipeline.admission import AdmissionKind, AdmissionReason, AdmissionWording
from app.pipeline.decision import Decision
from app.pipeline.fixes import FIXABLE_FIELDS, REPORTED_FIELDS, FixCall
from app.pipeline.memory import RecordChannelMissing, ReplacedBroadcast
from app.pipeline.outcome import OutcomeError
from app.pipeline.plan import KeyRoute, PlannedBroadcast
from app.platforms.channel import ChannelStatus
from app.platforms.error import PlatformError
from app.platforms.spec import ChangedField
from app.platforms.stream import StreamInfo
from app.platforms.video import VideoFixes
from app.records.record_results import RecordResults
from app.records.slot_record import SlotRecord, SlotStage
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.form import SHORT_URL, SUCCESS_PAGE, TRAINING_FORM_TITLE, FakeForms
from app.tests.fixtures.pipeline import (
    CLOCK,
    CREATED,
    FORM,
    NOT_IN_FORM,
    NOW,
    TOMORROW,
    admitted,
    channel_object,
    planned_of,
    slot_of,
    too_late,
    training_form,
    upcoming_of,
    with_changes,
    with_response_url,
)
from app.tests.fixtures.platform import FAKE_STREAM_URL, channel_of
from app.ui.messages import msg

BEFORE_MEMORY: datetime = (NOW - timedelta(days=6)).astimezone(timezone.utc)
FOUND_KEY: str = "fkey-fkey-fkey-fkey-fkey"
OTHER_RESPONSE_URL: str = "https://docs.google.com/forms/d/e/BATTLE/formResponse"

TO_FORM: KeyRoute = KeyRoute(to_form=True, resend=False)
RESEND: KeyRoute = KeyRoute(to_form=True, resend=True)


def _item(language: str = "uk", start: datetime = TOMORROW) -> PlannedBroadcast:
    """Объект на канале, который обслуживает язык слота."""
    return planned_of(slot_of(start, language), channel_of("@yt_all", "yt_all", language))


def _with_found_key(item: PlannedBroadcast) -> PlannedBroadcast:
    """На площадке стоит эфир слота с меткой программы и ключом FOUND_KEY."""
    item.match.found = upcoming_of(item.slot, BEFORE_MEMORY)
    item.match.stream = StreamInfo("fs", item.slot.slot_id, FAKE_STREAM_URL, FOUND_KEY)
    return item


def _memory_item(tmp_path: Path, *, found: bool = True, decision: Decision = Decision.MATCH) -> PlannedBroadcast:
    """Допущенный объект тренировочной формы; found — эфир с меткой программы уже стоит на канале."""
    item: PlannedBroadcast = admitted(_item(), tmp_path)
    if found:
        _with_found_key(item).decision = decision
    return item


def _remember(item: PlannedBroadcast) -> PlannedBroadcast:
    """Прошлый запуск: форма подтвердила текущую тройку объекта — запись в памяти."""
    return _stored(_confirmed(item))


def _confirmed(item: PlannedBroadcast) -> PlannedBroadcast:
    """Форма подтвердила отправку ключа в этом запуске — итог в память объекта."""
    item.admission.answer(item.slot, item.channel, item.match.key)
    item.outcome.is_form_sent = True
    item.remember_send(CLOCK)
    item.outcome.is_form_sent = False
    return item


def _unconfirmed(item: PlannedBroadcast, times: int = 1) -> PlannedBroadcast:
    """Прошлые запуски отправили текущий ключ `times` раз, форма не подтвердила ни разу — запись в памяти."""
    for _ in range(times):
        item.remember_send(CLOCK)
    return _stored(item)


def _stored(item: PlannedBroadcast) -> PlannedBroadcast:
    """Результаты этого запуска — записью памяти, как их прочтёт следующий запуск."""
    item.memory.record = item.to_record(CLOCK, SlotStage.PUBLISHED)
    item.memory.confirmed = None
    return item


def _decided(item: PlannedBroadcast) -> bool:
    item.decide_key_delivery(TO_FORM)
    return item.outcome.should_send_key


# --- поля и части объекта


def test_fields_are_split_once_and_completely() -> None:
    """Каждое сверяемое поле либо исправляется, либо только сообщается — третьего нет."""
    assert FIXABLE_FIELDS | REPORTED_FIELDS == frozenset(ChangedField)
    assert not FIXABLE_FIELDS & REPORTED_FIELDS


def test_split_changed_separates_fixable_and_reported() -> None:
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    item.match.fixes.split_changed((ChangedField.PRIVACY, ChangedField.AUTO_START, ChangedField.MARKER))
    assert item.match.fixes.changed == (ChangedField.PRIVACY, ChangedField.MARKER)
    assert item.match.fixes.reported == (ChangedField.AUTO_START,)
    assert item.match.fixes.fix_calls == frozenset({FixCall.VIDEO, FixCall.STREAM})
    assert item.match.fixes.fields_fixed_by(FixCall.VIDEO) == (ChangedField.PRIVACY,)


def test_fields_come_from_slot_channel_and_form() -> None:
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    assert (item.slot.slot_id, item.channel.account_name, item.form) == ("17-03-2027_1900_uk", "yt_ua", FORM)
    assert item.expected.marker == item.slot.slot_id and item.decision is Decision.CREATE


def test_object_is_born_without_key() -> None:
    """Объект знает только слот, канал и форму: о прошлых запусках ему нечего помнить."""
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    assert (item.match.key, item.match.broadcast_id, item.memory.record) == (None, None, None)
    assert (item.outcome.should_send_key, item.outcome.is_form_sent, item.is_key_undelivered) == (False, False, False)


def test_found_key_is_taken_from_the_platform() -> None:
    item: PlannedBroadcast = _with_found_key(planned_of(slot_of(TOMORROW)))
    key = item.match.key
    assert key is not None and (key.broadcast_id, key.stream_key, key.stream_url) == ("fbc", FOUND_KEY, FAKE_STREAM_URL)
    assert key.broadcast_url == "https://www.youtube.com/watch?v=fbc" == item.match.found_url
    assert item.outcome.should_send_key is False            # найденный ключ сам по себе в форму не идёт
    assert item.is_key_undelivered is False


def test_found_broadcast_without_stream_has_no_key() -> None:
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    item.match.found = upcoming_of(item.slot, BEFORE_MEMORY)
    assert item.match.key is None and item.match.broadcast_id == "fbc"


def test_new_key_waits_for_the_form() -> None:
    item: PlannedBroadcast = _with_found_key(planned_of(slot_of(TOMORROW)))
    item.match.take_new_key(CREATED)                        # новый ключ главнее найденного
    assert item.match.key == CREATED and item.outcome.should_send_key is False
    item.decide_key_delivery(TO_FORM)
    assert item.outcome.should_send_key is True and item.is_key_undelivered is True
    item.outcome.is_form_sent = True
    assert item.is_key_undelivered is False


def test_kept_key_needs_a_confirmation_of_the_current_key() -> None:
    item: PlannedBroadcast = _with_found_key(planned_of(slot_of(TOMORROW)))
    assert item.has_kept_key is False                       # памяти о ключе нет
    _confirmed(item)
    assert item.has_kept_key is True
    item.outcome.error = OutcomeError(origin="youtube", code="forbidden", human="нельзя")
    assert item.has_kept_key is False                       # ошибка — это не прежний ключ
    item.outcome.error = None
    item.match.take_new_key(CREATED)                        # привязка потока: ключ новый
    assert item.has_kept_key is False


def test_a_platform_error_carries_the_text_of_the_refusal() -> None:
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    refusal: PlatformError = PlatformError("liveStreamingNotEnabled", "HTTP 403: live streaming")
    error: OutcomeError = OutcomeError.of_platform(item.channel, refusal)
    assert error == OutcomeError("youtube", "liveStreamingNotEnabled", refusal.human, "HTTP 403: live streaming")
    assert error.human == msg.YOUTUBE_REASON_TEXT["liveStreamingNotEnabled"]


def test_the_last_error_is_the_form_refusal_then_the_broadcast_error() -> None:
    """Снимок памяти читает `last_error`: отказ формы главнее ошибки эфира; сбоев нет — None."""
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    assert item.outcome.last_error is None
    item.outcome.error = OutcomeError.of_platform(item.channel, PlatformError("quotaExceeded", "HTTP 403"))
    assert item.outcome.last_error == msg.YOUTUBE_REASON_TEXT["quotaExceeded"]
    failure: FormFailure = FormFailure(FormProblem.NOT_CONFIRMED, TRAINING_FORM_TITLE, "", "no confirmation")
    item.outcome.form_failure = failure
    assert item.outcome.last_error == failure.human


def test_slot_fields_survive_platform_data() -> None:
    slot = slot_of(TOMORROW)
    item: PlannedBroadcast = planned_of(slot)
    expected = item.expected
    _with_found_key(item)
    item.match.take_new_key(CREATED)
    assert item.slot is slot and item.expected is expected and item.channel == channel_of()


# --- допуск к публикации (PlannedBroadcast.admit)


def test_ready_channel_and_complete_form_admit_the_object(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(_item(), tmp_path)
    answers: FormAnswers | None = item.admission.answers
    assert item.admission.is_admitted and item.decision is Decision.CREATE
    assert answers is not None and answers.missing == ()
    assert answers.pending == ("You Tube Stream Key", "Stream-URL (YT)")   # ключ и адрес — не причина


@pytest.mark.parametrize("status", [ChannelStatus.REFUSED, ChannelStatus.FAILED, ChannelStatus.NEEDS_LOGIN])
def test_channel_not_ready_is_a_reason(tmp_path: Path, status: ChannelStatus) -> None:
    item: PlannedBroadcast = admitted(_item(), tmp_path, status)
    assert item.decision is Decision.NOT_ADMITTED and not item.admission.is_admitted
    assert item.admission.reasons == (
        AdmissionReason(AdmissionKind.CHANNEL, status.value, None, msg.ADMISSION_CHANNEL_TEXT[status.value]),
    )


def test_unreadable_form_is_a_reason() -> None:
    item: PlannedBroadcast = _item()
    failure: FormFailure = FormFailure(FormProblem.STRUCTURE_UNREADABLE, SHORT_URL, "", "no FB_PUBLIC_LOAD_DATA_")
    item.admit(channel_object(item.channel), failure)
    assert item.admission.reasons == (
        AdmissionReason(
            AdmissionKind.FORM_UNREADABLE, "structure_unreadable", None, failure.human, form_name=SHORT_URL
        ),
    )
    assert item.decision is Decision.NOT_ADMITTED and item.admission.answers is None


# --- причина недопуска словами человека (AdmissionReason.wording)


@pytest.mark.parametrize("status", [ChannelStatus.REFUSED, ChannelStatus.FAILED, ChannelStatus.NEEDS_LOGIN])
def test_a_channel_reason_says_what_is_wrong_and_what_to_do(tmp_path: Path, status: ChannelStatus) -> None:
    [reason] = admitted(_item(), tmp_path, status).admission.reasons
    assert reason.wording == AdmissionWording(
        msg.ADMISSION_CHANNEL_PROBLEM[status.value], msg.ADMISSION_CHANNEL_ACTION[status.value]
    )


def test_an_unreadable_form_is_named_by_its_own_text() -> None:
    item: PlannedBroadcast = _item()
    failure: FormFailure = FormFailure(FormProblem.TRANSPORT_FAILED, SHORT_URL, "код ответа 503", "HTTP 503")
    item.admit(channel_object(item.channel), failure)
    [reason] = item.admission.reasons
    assert reason.wording == AdmissionWording(failure.human, msg.ADMISSION_ACTION_FORM_UNREADABLE)
    assert reason.wording.problem == f"Форма ключей «{SHORT_URL}» недоступна (код ответа 503)."


def test_a_missing_option_names_the_form_the_question_and_the_value(tmp_path: Path) -> None:
    [reason] = admitted(_item("en", NOT_IN_FORM), tmp_path).admission.reasons
    assert reason.wording == AdmissionWording(
        f"В форме «{TRAINING_FORM_TITLE}» в вопросе «Время стрима ( Stream time )» нет варианта «18.03.2027».",
        "Добавьте вариант в форму.",
    )


def test_an_option_without_text_in_the_settings_is_not_the_form_s_fault(tmp_path: Path) -> None:
    """Вариант «-»: настройки формы не дали текста варианта — форме тут не поможешь."""
    [reason] = admitted(_item("de"), tmp_path).admission.reasons
    assert reason.value == NO_VALUE
    assert reason.wording == AdmissionWording(
        msg.ADMISSION_MISSING_SETTINGS_TEXT.format(question=reason.question, form=TRAINING_FORM_TITLE),
        msg.ADMISSION_ACTION_MISSING_SETTINGS_TEXT,
    )


def test_required_questions_without_answer_name_the_questions() -> None:
    reason: AdmissionReason = AdmissionReason(
        AdmissionKind.FORM_FIELD, "required_missing", None, "Q1, Q2", question="Q1, Q2", form_name="Форма"
    )
    assert reason.wording == AdmissionWording(
        msg.ADMISSION_REQUIRED_MISSING.format(form="Форма", question="Q1, Q2"), msg.ADMISSION_ACTION_REQUIRED_MISSING
    )


def test_date_without_option_is_a_form_field_reason(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(_item("en", NOT_IN_FORM), tmp_path)
    assert item.admission.reasons == (
        AdmissionReason(
            AdmissionKind.FORM_FIELD,
            "missing_option",
            "date",
            "Время стрима ( Stream time ): 18.03.2027",
            question="Время стрима ( Stream time )",
            value="18.03.2027",
            form_name=TRAINING_FORM_TITLE,
        ),
    )
    assert item.decision is Decision.NOT_ADMITTED


def test_language_without_option_is_a_form_field_reason(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(_item("de"), tmp_path)
    assert [(reason.kind, reason.code, reason.field) for reason in item.admission.reasons] == [
        (AdmissionKind.FORM_FIELD, "missing_option", "language")
    ]


def test_reasons_keep_their_order(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(_item("de", NOT_IN_FORM), tmp_path, ChannelStatus.FAILED)
    assert [reason.kind for reason in item.admission.reasons] == [
        AdmissionKind.CHANNEL, AdmissionKind.FORM_FIELD, AdmissionKind.FORM_FIELD
    ]


def test_too_late_object_gets_its_objects_but_no_reasons(tmp_path: Path) -> None:
    item: PlannedBroadcast = too_late(_item("en", NOT_IN_FORM))
    admitted(item, tmp_path, ChannelStatus.REFUSED)
    assert item.admission.is_admitted and item.decision is Decision.TOO_LATE
    assert item.admission.key_form is not None and item.admission.channel is not None


def test_answers_with_key_and_url_are_complete(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(_item(), tmp_path)
    item.match.take_new_key(CREATED)
    assert not item.is_key_ready_to_send                    # решения ещё нет, ответ без ключа и адреса
    item.decide_key_delivery(TO_FORM)
    assert item.admission.is_complete and item.is_key_ready_to_send
    item.outcome.is_form_sent = True
    assert not item.is_key_ready_to_send


def test_stream_url_not_in_options_makes_answers_incomplete(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(_item(), tmp_path)
    item.match.take_new_key(with_changes(CREATED, stream_url="rtmp://b.rtmp.youtube.com/live2"))
    answers: FormAnswers | None = item.admission.answer(item.slot, item.channel, item.match.key)
    assert answers is not None and not answers.is_complete
    assert [missing.field for missing in answers.missing] == [FormQuestion.STREAM_URL]
    assert not item.is_key_ready_to_send
    assert item.admission.is_admitted                       # допуск уже решён; адрес — забота отправки


def test_object_without_form_has_no_answer_to_send() -> None:
    """Объект не проходил допуск: он не задержан, но ответа формы у него нет — ключ не готов к отправке."""
    item: PlannedBroadcast = _item()
    item.match.take_new_key(CREATED)
    item.decide_key_delivery(TO_FORM)
    assert item.admission.is_admitted and item.outcome.should_send_key
    assert item.admission.answers is None and not item.is_key_ready_to_send and item.is_key_undelivered


def test_submission_is_built_by_the_object(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(_item(), tmp_path)
    item.match.take_new_key(CREATED)
    item.decide_key_delivery(TO_FORM)
    submission: FormSubmission = item.submission()
    assert (submission.slot_id, submission.handle, submission.stream_key) == (
        "17-03-2027_1900_uk", "@yt_all", CREATED.stream_key
    )
    assert submission.form is item.admission.key_form and submission.answers is item.admission.answers


def test_form_gets_the_channel_values_after_the_login_phase(tmp_path: Path) -> None:
    """Канал выровнен при входе (§14 решение 25): форма получает новые название и ник в том же запуске."""
    item: PlannedBroadcast = admitted(_item(), tmp_path)
    renamed: ChannelConfig = with_changes(item.channel, account_name="Новое название", handle="@new_all")
    channel = item.admission.channel
    assert channel is not None
    channel.realign(renamed, Path("new.json"))
    item.match.take_new_key(CREATED)
    item.decide_key_delivery(TO_FORM)
    assert "Новое название" in {answer.value for answer in item.admission.answers.answers}
    assert item.submission().handle == "@new_all"
    assert item.channel.account_name == "yt_all"            # значения, с которыми объект построен, не меняются


# --- память: одно правило отправки ключа (decide_key_delivery)


def test_created_key_goes(tmp_path: Path) -> None:
    item: PlannedBroadcast = _memory_item(tmp_path, found=False)
    item.match.take_new_key(CREATED)
    assert _decided(item)


def test_matched_and_confirmed_key_does_not_go(tmp_path: Path) -> None:
    assert not _decided(_remember(_memory_item(tmp_path)))


def test_a_standing_broadcast_without_confirmation_does_not_send_at_new(tmp_path: Path) -> None:
    """«новые» (§14 решение 49): эфир уже стоял — ключ не уходит, даже если подтверждения в памяти нет."""
    assert not _decided(_memory_item(tmp_path))


def test_updated_with_the_same_answers_does_not_go(tmp_path: Path) -> None:
    assert not _decided(_remember(_memory_item(tmp_path, decision=Decision.UPDATE)))


def test_a_standing_broadcast_does_not_send_even_with_other_answers(tmp_path: Path) -> None:
    """Название канала выровняли при входе — ответ формы другой, но эфир стоял: при «новые» ключ не уходит, при «все» —
    уходит."""
    item: PlannedBroadcast = _remember(_memory_item(tmp_path, decision=Decision.UPDATE))
    channel = item.admission.channel
    assert channel is not None
    channel.realign(with_changes(channel.config, account_name="Новое название"), Path("t.json"))
    assert not _decided(item)
    item.decide_key_delivery(RESEND)
    assert item.outcome.should_send_key


def test_recreated_broadcast_has_a_new_key_that_goes(tmp_path: Path) -> None:
    item: PlannedBroadcast = _remember(_memory_item(tmp_path))
    item.match.found = item.match.stream = None
    item.match.take_new_key(CREATED)
    assert _decided(item)


def test_the_form_address_does_not_make_a_standing_key_go(tmp_path: Path) -> None:
    """Другая форма, эфир стоял: при «новые» ключ не уходит (§14 решение 49)."""
    item: PlannedBroadcast = _remember(_memory_item(tmp_path))
    form = item.admission.key_form
    assert form is not None
    item.admission.key_form = with_response_url(form, OTHER_RESPONSE_URL)
    assert not _decided(item)


def test_too_late_and_not_admitted_keys_do_not_go(tmp_path: Path) -> None:
    assert not _decided(too_late(_memory_item(tmp_path)))
    blocked: PlannedBroadcast = _memory_item(tmp_path)
    blocked.admission.reasons = (AdmissionReason(AdmissionKind.FORM_FIELD, "missing_option", "date", "дата"),)
    assert not _decided(blocked)


def test_with_the_keys_line_off_no_key_goes(tmp_path: Path) -> None:
    """Линия «Ключи в форму» не идёт (§14 решение 37): ключ не уходит ни новый, ни при повторной передаче — одно
    правило `decide_key_delivery`."""
    for item in (_memory_item(tmp_path), _remember(_memory_item(tmp_path))):
        item.decide_key_delivery(KeyRoute(to_form=False, resend=True))
        assert not item.outcome.should_send_key and not item.is_key_undelivered


def test_without_the_form_the_admission_is_the_channel_only(tmp_path: Path) -> None:
    """Ключи в форму не идут — формы нет: готовый канал допускает объект, ответа формы нет; канал не готов — причина."""
    item: PlannedBroadcast = _item()
    item.admit(channel_object(item.channel), None)
    assert item.admission.is_admitted and item.admission.answers is None and item.decision is Decision.CREATE
    refused: PlannedBroadcast = _item()
    refused.admit(channel_object(refused.channel, ChannelStatus.REFUSED), None)
    assert [reason.kind for reason in refused.admission.reasons] == [AdmissionKind.CHANNEL]


def test_resend_sends_the_key_that_memory_confirms(tmp_path: Path) -> None:
    """«все» (решение 49): ключ уходит, что бы ни помнила память."""
    for item in (_remember(_memory_item(tmp_path)), _memory_item(tmp_path), _unconfirmed(_memory_item(tmp_path), 2)):
        item.decide_key_delivery(RESEND)
        assert item.outcome.should_send_key and not item.is_key_given_up


def test_resend_keeps_the_other_conditions(tmp_path: Path) -> None:
    """Повторная передача не отправляет ключ too_late, не допущенного объекта и без адреса потока."""
    late: PlannedBroadcast = too_late(_remember(_memory_item(tmp_path)))
    blocked: PlannedBroadcast = _remember(_memory_item(tmp_path))
    blocked.admission.reasons = (AdmissionReason(AdmissionKind.FORM_FIELD, "missing_option", "date", "дата"),)
    no_url: PlannedBroadcast = _memory_item(tmp_path)
    no_url.match.stream = StreamInfo("fs", no_url.slot.slot_id, "", FOUND_KEY)
    for item in (late, blocked, no_url):
        item.decide_key_delivery(RESEND)
        assert not item.outcome.should_send_key


def test_key_without_stream_url_does_not_go(tmp_path: Path) -> None:
    """Прочитанный поток бывает без адреса: ключ взять неоткуда."""
    item: PlannedBroadcast = _memory_item(tmp_path)
    item.match.stream = StreamInfo("fs", item.slot.slot_id, "", FOUND_KEY)
    assert not _decided(item)


def test_error_of_another_step_does_not_cancel_the_key(tmp_path: Path) -> None:
    item: PlannedBroadcast = _memory_item(tmp_path, found=False)
    item.match.take_new_key(CREATED)
    item.decision = Decision.ERROR
    item.outcome.error = OutcomeError(origin="package", code="preview_missing", human="нет превью")
    assert _decided(item)


def test_incomplete_answers_still_mean_the_key_must_go(tmp_path: Path) -> None:
    """Адреса потока нет среди вариантов: ключ должен уйти, но готов не был — «НЕ отправлен»."""
    item: PlannedBroadcast = _memory_item(tmp_path, found=False)
    item.match.take_new_key(with_changes(CREATED, stream_url="rtmp://b.rtmp.youtube.com/live2"))
    assert _decided(item) and not item.is_key_ready_to_send and item.is_key_undelivered


# --- неподтверждённый ключ: один повтор (§14 решение 49)


def test_a_key_the_form_did_not_confirm_goes_once_more(tmp_path: Path) -> None:
    """Эфир создан прошлым запуском, форма ключ не подтвердила: при «новые» он уходит ещё один раз."""
    item: PlannedBroadcast = _unconfirmed(_memory_item(tmp_path))
    assert item.memory.results.unconfirmed_sends(FOUND_KEY, item.admission.response_url(item.form)) == 1
    assert _decided(item) and not item.is_key_given_up


def test_a_key_the_form_did_not_confirm_twice_does_not_go_and_says_so(tmp_path: Path) -> None:
    """Вторая неподтверждённая отправка — последняя: ключ сам больше не уходит, объект называет это (строка отчёта с
    действием «все»)."""
    item: PlannedBroadcast = _unconfirmed(_memory_item(tmp_path), 2)
    assert not _decided(item) and item.is_key_given_up and not item.is_key_undelivered


def test_a_confirmation_clears_the_count_and_a_new_key_starts_from_zero(tmp_path: Path) -> None:
    """Подтверждение формы снимает счёт; другой ключ (эфир создан заново) и другая форма — счёта нет."""
    item: PlannedBroadcast = _unconfirmed(_memory_item(tmp_path), 2)
    _stored(_confirmed(item))
    url: str = item.admission.response_url(item.form)
    assert item.memory.results.unconfirmed is None and not item.is_key_given_up
    counted: PlannedBroadcast = _unconfirmed(_memory_item(tmp_path), 2)
    assert counted.memory.results.unconfirmed_sends(CREATED.stream_key, url) == 0
    assert counted.memory.results.unconfirmed_sends(FOUND_KEY, OTHER_RESPONSE_URL) == 0
    assert counted.memory.results.unconfirmed_sends(None, url) == 0
    counted.match.take_new_key(CREATED)
    assert _decided(counted) and not counted.is_key_given_up


def test_a_too_late_or_unadmitted_key_is_not_given_up(tmp_path: Path) -> None:
    """Про ключ, который в запуске и так не шёл бы (too_late, не допущен), строки «не дошёл дважды» нет."""
    late: PlannedBroadcast = too_late(_unconfirmed(_memory_item(tmp_path), 2))
    blocked: PlannedBroadcast = _unconfirmed(_memory_item(tmp_path), 2)
    blocked.admission.reasons = (AdmissionReason(AdmissionKind.FORM_FIELD, "missing_option", "date", "дата"),)
    for item in (late, blocked):
        assert not _decided(item) and not item.is_key_given_up


# --- запись памяти


def test_record_carries_results_and_keeps_the_confirmation(tmp_path: Path) -> None:
    item: PlannedBroadcast = _remember(_memory_item(tmp_path))
    record: SlotRecord = item.to_record(CLOCK, SlotStage.ADMITTED)
    assert record.youtube_channel_id == "UCfakeyt_all"                  # id канала из ответа YouTube
    assert record.slot_start_utc == "2027-03-17T17:00:00+00:00"
    assert record.stage is SlotStage.KEY_CONFIRMED                     # не откатывается для того же ключа
    assert (record.results.stream_key, record.results.stream_id, record.results.confirmed_stream_key) == (
        FOUND_KEY, "fs", FOUND_KEY
    )
    assert record.snapshot is not None and record.snapshot.decision == "match"
    item.match.found = item.match.stream = None
    item.match.take_new_key(CREATED)                                   # эфир создан заново
    renewed: SlotRecord = item.to_record(CLOCK, SlotStage.PUBLISHED)
    assert renewed.stage is SlotStage.PUBLISHED and renewed.results.stream_key == CREATED.stream_key
    assert renewed.results.confirmed_stream_key == FOUND_KEY           # прежнее подтверждение — до нового


def test_record_needs_a_ready_channel(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(_item(), tmp_path, ChannelStatus.FAILED)
    assert item.admission.channel_id is None
    with pytest.raises(RecordChannelMissing):
        item.to_record(CLOCK, SlotStage.ADMITTED)


def test_unchanged_record_is_not_saved_again(tmp_path: Path) -> None:
    item: PlannedBroadcast = _memory_item(tmp_path)
    first: SlotRecord | None = item.memory.record_to_save(item.to_record(CLOCK, SlotStage.PUBLISHED))
    assert first is not None
    item.memory.remember_record(first)
    later: StoppedClock = StoppedClock.at(NOW + timedelta(hours=1))
    assert item.memory.record_to_save(item.to_record(later, SlotStage.PUBLISHED)) is None   # другой только момент
    item.match.take_new_key(CREATED)
    assert item.memory.record_to_save(item.to_record(later, SlotStage.PUBLISHED)) is not None


def test_moments_are_written_by_the_clock_of_the_program(tmp_path: Path) -> None:
    """Инвариант 4: момент записи — DD-MM-YYYY HH:MM по поясу программы, а не по поясу, в котором пришёл момент."""
    clock: StoppedClock = StoppedClock.at(NOW.astimezone(timezone.utc), NOW.tzinfo)
    item: PlannedBroadcast = _memory_item(tmp_path)
    item.admission.answer(item.slot, item.channel, item.match.key)
    item.outcome.is_form_sent = True
    item.remember_send(clock)
    record: SlotRecord = item.to_record(clock, SlotStage.PUBLISHED)
    assert record.updated_at == record.results.published_at == record.results.confirmed_at == "16-03-2027 12:00"


def test_published_moment_stays_while_the_key_is_the_same(tmp_path: Path) -> None:
    item: PlannedBroadcast = _memory_item(tmp_path)
    item.memory.record = item.to_record(CLOCK, SlotStage.PUBLISHED)
    later: StoppedClock = StoppedClock.at(NOW + timedelta(hours=2))
    assert item.to_record(later, SlotStage.PUBLISHED).results.published_at == format_datetime_text(NOW)


def test_fixed_and_unfixed_fields_change_only_through_their_methods(tmp_path: Path) -> None:
    fixes = _memory_item(tmp_path, decision=Decision.UPDATE).match.fixes
    fixes.mark_unfixed(ChangedField.THUMBNAIL)
    fixes.mark_fixed((ChangedField.TITLE,))
    fixes.mark_unfixed(ChangedField.TITLE)                 # уже исправлено — «не удалось» не ставится
    assert (fixes.fixed, fixes.unfixed) == ((ChangedField.TITLE,), (ChangedField.THUMBNAIL,))
    fixes.mark_fixed((ChangedField.THUMBNAIL, ChangedField.CATEGORY))   # порядок — как в ChangedField
    assert fixes.fixed == (ChangedField.TITLE, ChangedField.CATEGORY, ChangedField.THUMBNAIL)
    assert fixes.unfixed == ()


def test_recorded_thumbnail_overrides_the_placeholder_only_for_the_same_broadcast(tmp_path: Path) -> None:
    item: PlannedBroadcast = _memory_item(tmp_path)
    item.match.actual = with_changes(item.expected, has_own_thumbnail=False)
    assert not item.match.apply_recorded_thumbnail(item.memory.recorded_thumbnail)   # записи нет — решает картинка
    item.memory.remember_thumbnail("fbc", CLOCK)
    item.memory.record = item.to_record(CLOCK, SlotStage.PUBLISHED)
    assert (item.memory.record.results.thumbnail_broadcast_id, item.memory.record.results.thumbnail_set_at) == (
        "fbc", format_datetime_text(NOW)
    )
    assert item.match.apply_recorded_thumbnail(item.memory.recorded_thumbnail)
    assert item.match.actual.has_own_thumbnail is True
    assert not item.match.apply_recorded_thumbnail(item.memory.recorded_thumbnail)   # уже своя
    other: PlannedBroadcast = _memory_item(tmp_path)
    other.match.found = upcoming_of(other.slot, BEFORE_MEMORY, "new")
    other.memory.record = item.memory.record
    other.match.actual = with_changes(other.expected, has_own_thumbnail=False)
    assert not other.match.apply_recorded_thumbnail(other.memory.recorded_thumbnail)
    assert other.match.actual.has_own_thumbnail is False


def test_thumbnail_fact_is_carried_while_the_broadcast_is_the_same(tmp_path: Path) -> None:
    item: PlannedBroadcast = _memory_item(tmp_path)
    item.memory.remember_thumbnail("fbc", CLOCK)
    item.memory.record = item.to_record(CLOCK, SlotStage.PUBLISHED)
    later: PlannedBroadcast = _memory_item(tmp_path)
    later.memory.record = item.memory.record
    assert later.to_record(CLOCK, SlotStage.PUBLISHED).results.thumbnail_broadcast_id == "fbc"
    renewed: PlannedBroadcast = _memory_item(tmp_path, found=False)
    renewed.memory.record = item.memory.record
    renewed.match.take_new_key(CREATED)                     # эфир создан заново — прежний факт не про него
    assert renewed.to_record(CLOCK, SlotStage.PUBLISHED).results.thumbnail_broadcast_id is None


def test_replaced_broadcast_is_remembered_before_the_new_record(tmp_path: Path) -> None:
    """Эфир создан заново, а память помнит другой эфир с подтверждённым ключом: в форме теперь два ключа."""
    item: PlannedBroadcast = _remember(_memory_item(tmp_path))
    assert item.memory.remember_replaced(CREATED) == ReplacedBroadcast(
        broadcast_id="fbc", broadcast_url="https://www.youtube.com/watch?v=fbc", stream_key=FOUND_KEY
    )
    same: PlannedBroadcast = _remember(_memory_item(tmp_path))
    assert same.memory.remember_replaced(with_changes(CREATED, broadcast_id="fbc")) is None
    unconfirmed: PlannedBroadcast = _memory_item(tmp_path)
    unconfirmed.memory.record = with_changes(item.to_record(CLOCK, SlotStage.PUBLISHED), results=RecordResults("fbc"))
    assert unconfirmed.memory.remember_replaced(CREATED) is None


def test_other_training_form_date_is_known(tmp_path: Path) -> None:
    """Тренировочная форма тестов принимает 17.03.2027 — на ней стоят тесты допуска."""
    assert "17.03.2027" in training_form(tmp_path).accepted_dates


# --- правила одного эфира для прогона части «эфиры» (задача 5.7)


def test_video_fixes_of_a_found_broadcast_become_its_fixes_and_only_new_ones_are_returned() -> None:
    """Категория и видимость, исправленные у ресурса видео, — исправление эфира; уже известное расхождение не новое."""
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    item.match.fixes.split_changed((ChangedField.TITLE, ChangedField.PRIVACY))
    added: tuple[ChangedField, ...] = item.match.fixes.take_video_fixes(VideoFixes(category_set=True, privacy_set=True))
    assert added == (ChangedField.CATEGORY,)
    assert item.match.fixes.changed == (ChangedField.TITLE, ChangedField.CATEGORY, ChangedField.PRIVACY)
    assert item.match.fixes.fixed == (ChangedField.CATEGORY, ChangedField.PRIVACY)
    assert item.match.fixes.take_video_fixes(VideoFixes(language_set=True)) == ()


@pytest.mark.parametrize(
    ("decision", "is_own"),
    [
        (Decision.CREATE, True),
        (Decision.UPDATE, True),
        (Decision.MATCH, True),
        (Decision.NO_STREAM, False),
        (Decision.TOO_LATE, False),
        (Decision.AMBIGUOUS, False),
        (Decision.ERROR, False),
        (Decision.NOT_ADMITTED, False),
    ],
)
def test_only_created_fixed_and_matched_broadcasts_are_the_programs_own(decision: Decision, is_own: bool) -> None:
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    item.match.take_new_key(CREATED)
    assert item.match.own_broadcast_id(decision) == (CREATED.broadcast_id if is_own else None)


def test_a_form_reply_marks_the_key_sent_or_keeps_the_refusal(tmp_path: Path) -> None:
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    refusal: FormFailure = FormFailure(FormProblem.NOT_CONFIRMED, TRAINING_FORM_TITLE, "HTTP 200", "status=200")
    assert item.outcome.take_form_reply(refusal, NOW) is False
    assert (item.outcome.is_form_sent, item.outcome.form_failure) == (False, refusal)
    admitted(item, tmp_path)
    item.match.take_new_key(CREATED)
    item.decide_key_delivery(TO_FORM)
    sender: FormSender = FormSender(FakeForms.answering(SUCCESS_PAGE).http, FormDiagnostic(tmp_path, CLOCK))
    reply: FormConfirmation | FormFailure = sender.send(item.submission())
    assert item.outcome.take_form_reply(reply, NOW) is True
    assert (item.outcome.is_form_sent, item.outcome.form_sent_at, item.outcome.form_failure) == (True, NOW, None)


def test_the_spec_log_fields_are_one_rule_for_expected_and_found() -> None:
    """broadcast_expected и broadcast_found — один набор полей: тексты — длиной и в кавычках, описание — началом."""
    item: PlannedBroadcast = planned_of(slot_of(TOMORROW))
    line: str = item.expected.logged(LogEvent.of("broadcast_expected")).text
    assert line.startswith("broadcast_expected start=2027-03-17T17:00:00+00:00 marker=17-03-2027_1900_uk ")
    assert 'title="Эфир" title_len=4 description_len=14 description_head="Описание эфира"' in line
    assert line.endswith("privacy=public category_id=22 auto_start=yes auto_stop=yes latency=normal has_own_thumbnail=-")
