"""Итог эфира для вывода (app\\output\\result.py, result_text.py; CLAUDE.md §3 шаг 12, §6 инварианты 1a, 6): одно
правило постройки из объекта эфира и эфира с меткой программы, тексты итога — одинаково для отчёта и консоли."""
from __future__ import annotations

from pathlib import Path

from app.form.failure import FormFailure, FormProblem
from app.output.result import BroadcastResult, FieldChange, KeyState, OutcomeKind
from app.output.result_text import ResultText
from app.pipeline.decision import Decision
from app.pipeline.memory import ReplacedBroadcast
from app.pipeline.orphan import MarkedBroadcast
from app.pipeline.outcome import OutcomeError
from app.pipeline.plan import PlannedBroadcast
from app.platforms.broadcast import UpcomingBroadcast
from app.platforms.channel import ChannelStatus
from app.platforms.error import PlatformError
from app.platforms.spec import ChangedField
from app.platforms.stream import StreamInfo
from app.tests.fixtures.form import TRAINING_FORM_TITLE
from app.tests.fixtures.output import (
    UA,
    item_at,
    key_at,
    result_of,
    start_at,
    with_found_key,
    with_new_key,
)
from app.tests.fixtures.pipeline import admitted, channel_object, slot_of, training_form, with_changes
from app.tests.fixtures.platform import FAKE_STREAM_URL, channel_of
from app.ui import messages_ru as msg

KEY: str = "aaaa-bbbb-cccc-dddd-6jty"
NOT_CONFIRMED: FormFailure = FormFailure.of_status(FormProblem.NOT_CONFIRMED, TRAINING_FORM_TITLE, 200)


def _updated(item: PlannedBroadcast, *fields: ChangedField) -> PlannedBroadcast:
    """Эфир найден, на площадке видимость «private» и другое описание; расхождения — исправимые."""
    with_found_key(item, "bc17", KEY, Decision.UPDATE)
    item.match.actual = with_changes(item.expected, privacy="private", description="старое")
    item.match.fixes.split_changed(fields)
    return item


# --- постройка из объекта эфира


def test_a_created_broadcast_whose_key_the_form_confirmed() -> None:
    item: PlannedBroadcast = with_new_key(item_at(17), "bc17", KEY)
    item.outcome.should_send_key, item.outcome.is_form_sent = True, True
    result: BroadcastResult = BroadcastResult.of_planned(item, is_dry_run=False)
    assert (result.kind, result.key, result.channel, result.key_state) == (
        OutcomeKind.CREATED, item.slot.key, UA, KeyState.SENT
    )
    assert (result.broadcast_url, result.stream_key, result.title) == (
        "https://www.youtube.com/watch?v=bc17", KEY, item.expected.title
    )


def test_a_key_that_had_to_go_and_did_not_carries_the_form_refusal() -> None:
    item: PlannedBroadcast = with_new_key(item_at(17), "bc17", KEY)
    item.outcome.should_send_key, item.outcome.form_failure = True, NOT_CONFIRMED
    result: BroadcastResult = BroadcastResult.of_planned(item, is_dry_run=False)
    assert (result.key_state, result.failure_text) == (KeyState.FAILED, NOT_CONFIRMED.human)
    assert BroadcastResult.of_planned(item, is_dry_run=True).key_state is KeyState.PLANNED


def test_a_key_the_memory_confirmed_did_not_go_to_the_form() -> None:
    result: BroadcastResult = BroadcastResult.of_planned(with_found_key(item_at(17), "bc17", KEY), is_dry_run=False)
    assert (result.kind, result.key_state) == (OutcomeKind.MATCHED, None)


def test_a_failed_key_without_a_refusal_says_the_form_did_not_confirm() -> None:
    result: BroadcastResult = result_of(OutcomeKind.CREATED, key_state=KeyState.FAILED)
    assert result.failure_text == msg.FORM_FAILURE_UNKNOWN


def test_fixed_fields_are_named_with_before_and_after() -> None:
    item: PlannedBroadcast = _updated(item_at(17), ChangedField.DESCRIPTION, ChangedField.PRIVACY)
    item.match.fixes.mark_fixed((ChangedField.PRIVACY,))
    result: BroadcastResult = BroadcastResult.of_planned(item, is_dry_run=False)
    assert result.kind is OutcomeKind.FIXED
    assert result.changes == (FieldChange(ChangedField.PRIVACY, "private", "public"),)
    assert result.unfixed == ()


def test_dry_run_names_what_would_be_fixed() -> None:
    item: PlannedBroadcast = _updated(item_at(17), ChangedField.DESCRIPTION, ChangedField.THUMBNAIL)
    result: BroadcastResult = BroadcastResult.of_planned(item, is_dry_run=True)
    assert result.kind is OutcomeKind.FIXED
    assert [change.field for change in result.changes] == [ChangedField.DESCRIPTION, ChangedField.THUMBNAIL]
    assert result.changes[1] == FieldChange(ChangedField.THUMBNAIL, msg.THUMBNAIL_BEFORE, msg.THUMBNAIL_AFTER)
    assert result.changes[0].before.startswith("старое")


def test_nothing_fixed_means_the_broadcast_stands_as_it_was() -> None:
    """Исправить не удалось (обложка): итог «уже стояло» с хвостом, а не «исправлено»."""
    item: PlannedBroadcast = _updated(item_at(17), ChangedField.THUMBNAIL)
    item.match.fixes.mark_unfixed(ChangedField.THUMBNAIL)
    result: BroadcastResult = BroadcastResult.of_planned(item, is_dry_run=False)
    assert (result.kind, result.changes, result.unfixed) == (OutcomeKind.MATCHED, (), (ChangedField.THUMBNAIL,))
    assert ResultText(result).body.endswith("; обложка эфира не поставлена")


def test_a_bound_stream_is_a_new_key_and_an_error_beats_every_decision() -> None:
    item: PlannedBroadcast = with_new_key(item_at(17), "bc17", KEY)
    item.decision, item.match.stream_attached = Decision.MATCH, True
    assert BroadcastResult.of_planned(item, is_dry_run=False).kind is OutcomeKind.STREAM_ATTACHED
    refusal: PlatformError = PlatformError("liveStreamingNotEnabled", "HTTP 403")
    item.outcome.error = OutcomeError.of_platform(item.channel, refusal)
    result: BroadcastResult = BroadcastResult.of_planned(item, is_dry_run=False)
    assert (result.kind, result.error_text) == (OutcomeKind.ERROR, refusal.human)


def test_the_channel_is_named_with_its_values_after_the_login_phase(tmp_path: Path) -> None:
    """Канал, выровненный при входе, в выводе — с новыми названием и ником (§14 решение 25)."""
    item: PlannedBroadcast = item_at(17)
    item.admit(channel_object(channel_of("@Kanal_UA_new", "Канал UA новый", "uk")), training_form(tmp_path))
    assert BroadcastResult.of_planned(item, is_dry_run=False).label.text == (
        "17.03.2027 19:00 uk -> Канал UA новый @Kanal_UA_new"
    )


def test_a_marked_broadcast_of_the_status_run_stands() -> None:
    slot = slot_of(start_at(17), "uk")
    marked: MarkedBroadcast = MarkedBroadcast(
        channel=UA,
        broadcast=UpcomingBroadcast("abc", slot.start, "  Эфир  ", "", "s1"),
        stream=StreamInfo("s1", slot.slot_id, FAKE_STREAM_URL, KEY),
        key=slot.key,
    )
    result: BroadcastResult = BroadcastResult.of_marked(marked)
    assert (result.kind, result.title, result.stream_key, result.broadcast_url) == (
        OutcomeKind.MATCHED, "Эфир", KEY, "https://www.youtube.com/watch?v=abc"
    )


# --- тексты итога


def test_the_prefix_is_the_date_for_people_time_language_and_channel() -> None:
    assert ResultText(result_of(OutcomeKind.MATCHED, key_at(17, 21, "ru"))).prefix == (
        "17.03.2027 21:00 ru -> Канал UA @Kanal_UA"
    )


def test_texts_of_every_kind() -> None:
    prefix: str = "17.03.2027 19:00 uk -> Канал UA @Kanal_UA"
    error: OutcomeError = OutcomeError("youtube", "forbidden", "отказ YouTube")
    assert ResultText(result_of(OutcomeKind.CREATED, key_state=KeyState.SENT)).body == (
        f"{prefix} — эфир создан, ключ отправлен в форму"
    )
    assert ResultText(result_of(OutcomeKind.AMBIGUOUS)).body.startswith(f"{prefix} — на канале несколько эфиров")
    assert ResultText(result_of(OutcomeKind.ERROR, error=error)).body == f"{prefix} — отказ YouTube"
    assert ResultText(result_of(OutcomeKind.NO_STREAM, broadcast_url="u1")).body.startswith(
        f"{prefix} — эфир на канале есть (u1), но к нему не привязан поток"
    )
    assert ResultText(result_of(OutcomeKind.STREAM_ATTACHED, key_state=KeyState.SENT)).body == (
        f"{prefix} — эфир был без потока, поток привязан, ключ отправлен в форму"
    )


def test_a_failed_key_says_why_and_what_to_do() -> None:
    result: BroadcastResult = result_of(OutcomeKind.CREATED, key_state=KeyState.FAILED, form_failure=NOT_CONFIRMED)
    assert ResultText(result).body == (
        "17.03.2027 19:00 uk -> Канал UA @Kanal_UA — эфир создан, ключ в форму НЕ отправлен. "
        f"{NOT_CONFIRMED.human} Следующий запуск отправит его снова, а пока передайте ключ стримеру из keys.txt вручную"
    )


def test_dry_run_speaks_of_intent_and_marks_the_line() -> None:
    created: ResultText = ResultText(result_of(OutcomeKind.CREATED), is_dry_run=True)
    assert created.line == "17.03.2027 19:00 uk -> Канал UA @Kanal_UA — эфира нет, будет создан — не выполнено (dry-run)"
    fixed: ResultText = ResultText(
        result_of(OutcomeKind.FIXED, changes=(FieldChange(ChangedField.TITLE, "а", "б"),)), is_dry_run=True
    )
    assert fixed.body.endswith("на YouTube отличается: название; будет исправлено, ключ уйдёт в форму")


def test_not_admitted_says_what_is_missing_what_is_not_done_and_what_to_do(tmp_path: Path) -> None:
    item: PlannedBroadcast = with_found_key(admitted(item_at(18, 20), tmp_path), "qJjIZCbP89s", KEY)
    item.decision = Decision.NOT_ADMITTED
    text: str = ResultText(BroadcastResult.of_planned(item, is_dry_run=False)).not_admitted
    assert text == (
        f"18.03.2027 20:00 uk -> Канал UA @Kanal_UA — В форме «{TRAINING_FORM_TITLE}» в вопросе "
        "«Время стрима ( Stream time )» нет варианта «18.03.2027». Эфир на канале есть "
        "(https://www.youtube.com/watch?v=qJjIZCbP89s), но не исправлялся, ключ стримеру не передан. "
        "Добавьте вариант в форму. Программа передаст ключ на следующем запуске."
    )


def test_not_admitted_by_the_channel_did_not_check_broadcasts(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(item_at(17), tmp_path, ChannelStatus.REFUSED)
    text: str = ResultText(BroadcastResult.of_planned(item, is_dry_run=False)).not_admitted
    assert text.endswith(
        "Эфиры на канале не проверялись, ключ стримеру не передан. При входе выберите в браузере нужный канал. "
        "Программа проверит канал на следующем запуске."
    )


def test_not_admitted_without_a_broadcast_will_be_created_next_run() -> None:
    item: PlannedBroadcast = item_at(17)
    item.admit(channel_object(UA), NOT_CONFIRMED)
    text: str = ResultText(BroadcastResult.of_planned(item, is_dry_run=False)).not_admitted
    assert text.endswith(
        "Эфир не создан, ключ стримеру не передан. Проверьте, что форма ключей открывается по своей ссылке. "
        "Программа создаст эфир на следующем запуске."
    )


def test_the_same_action_of_two_reasons_is_named_once(tmp_path: Path) -> None:
    item: PlannedBroadcast = admitted(item_at(18, 20, "de"), tmp_path)
    actions: list[str] = [wording.action for wording in BroadcastResult.of_planned(item, is_dry_run=False).wordings]
    text: str = ResultText(BroadcastResult.of_planned(item, is_dry_run=False)).not_admitted
    assert len(actions) == 2
    assert all(text.count(action) == 1 for action in actions)


def test_two_keys_show_the_keys_only_masked() -> None:
    replaced: ReplacedBroadcast = ReplacedBroadcast("old", "https://www.youtube.com/watch?v=old", "oldk-oldk-oldk-3j1j")
    result: BroadcastResult = result_of(OutcomeKind.CREATED, broadcast_url="u-new", stream_key=KEY, replaced=replaced)
    text: str = ResultText(result).two_keys(replaced)
    assert "****-6jty" in text and "****-3j1j" in text
    assert KEY not in text and replaced.stream_key not in text
