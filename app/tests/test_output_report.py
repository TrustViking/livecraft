"""Отчёт запуска контура B (app\\output\\report.py, report_text.py, run_exit.py, run_totals.py, skipped.py,
run_lines.py, run_failure.py; CLAUDE.md §3 шаг 12, §10): разделы и их порядок, счётчики, код выхода, строки из объектов
запуска и часть «Эфиры YouTube» отчёта запуска."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.config.channel import ChannelConfig
from app.form.failure import FormFailure, FormProblem
from app.output.console import RunConsole
from app.output.report import ReportKind, ReportRequest, RunReport
from app.output.report_text import ReportText
from app.output.result import BroadcastResult, FieldChange, KeyState, OutcomeKind
from app.output.run_exit import RunExit
from app.output.run_failure import RunFailure
from app.output.run_lines import FactsCheck, OrphanLine, RunNotes, WarningText
from app.output.run_totals import RunTotals
from app.output.skipped import SkipKind, SkippedLine, SkippedSlots
from app.packages.package_line import PackageLine, PackageLines, PackageLineStatus
from app.paths import FileName, LivecraftPaths
from app.pipeline.decision import Decision
from app.pipeline.memory import ReplacedBroadcast
from app.pipeline.orphan import ChannelFailure, MarkedScan, OrphanBroadcast, OrphanKind
from app.pipeline.outcome import OutcomeError, OutcomeWarning, WarningStep
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.selection import Selection
from app.platforms.broadcast import BroadcastFacts, UpcomingBroadcast
from app.platforms.channel import ChannelStatus
from app.platforms.error import PlatformError
from app.platforms.notice import PlatformNotice, PlatformNoticeKind
from app.platforms.spec import BroadcastSpec, ChangedField
from app.run.exit_code import RunOutcome
from app.run.mode import RunMode
from app.run.report_section import PartReport
from app.run.request import RunRequest
from app.run.run_report import RunReportFile
from app.slots.slot import SlotEntry, SlotKey, StreamSlot
from app.tests.fixtures.form import TRAINING_FORM_TITLE
from app.tests.fixtures.output import (
    RU,
    UA,
    confirmed,
    item_at,
    key_at,
    report_of,
    report_request,
    result_of,
    start_at,
    with_found_key,
    with_new_key,
)
from app.tests.fixtures.pipeline import KYIV, LIMITS, admitted, request_of, slot_of, with_changes
from app.tests.fixtures.platform import channel_of
from app.ui import messages_ru as msg
from app.version import APP_VERSION

KEYS_SHOWN: str = str(Path("keystreams") / "keys.txt")
NOT_CONFIRMED: FormFailure = FormFailure.of_status(FormProblem.NOT_CONFIRMED, TRAINING_FORM_TITLE, 200)
LIVE_OFF: OutcomeError = OutcomeError("youtube", "liveStreamingNotEnabled", msg.YOUTUBE_REASON_TEXT["liveStreamingNotEnabled"])
QUOTA: PlatformError = PlatformError("quotaExceeded", "HTTP 403: quota")
UA_PREFIX: str = "-> Канал UA @Kanal_UA"

# Образец: итог и то, ради чего отчёт открывают, сверху; справка ниже; пустых разделов нет.
SAMPLE_REPORT: str = f"""# Livecraft {APP_VERSION} — отчёт 16.03.2027 12:00

## Эфиры YouTube

Итог по эфирам (всего 5): опубликовано 2, исправлено 1, уже стояло 1, не допущено 0, ошибок 1.
Слоты вне работы: 3 — время старта уже прошло 1, до старта меньше 60 минут 1, нет канала для языка en 1.
Код выхода 1 — не всё выполнено: ошибок по эфирам 1, ключ не дошёл до стримера 1.
Файл ключей: {KEYS_SHOWN}

### Ключ не дошёл до стримера
- 19.03.2027 19:00 uk {UA_PREFIX} — {NOT_CONFIRMED.human} Эфир на канале стоит — передайте ключ стримеру из keys.txt вручную

### Ошибки
- 20.03.2027 19:00 uk {UA_PREFIX} — {LIVE_OFF.human}

### Создано (2)
- 17.03.2027 19:00 uk {UA_PREFIX} — эфир создан, ключ отправлен в форму
- 19.03.2027 19:00 uk {UA_PREFIX} — эфир создан, ключ в форму НЕ отправлен. {NOT_CONFIRMED.human} Следующий запуск отправит его снова, а пока передайте ключ стримеру из keys.txt вручную

### Исправлено (1)
- 18.03.2027 19:00 uk {UA_PREFIX} — на YouTube отличалось: описание; исправлено, ключ и ссылка прежние, ключ отправлен в форму

### Уже запланировано, совпадает (1)
- 17.03.2027 21:00 ru -> Канал RU @Kanal_RU — https://www.youtube.com/watch?v=def456

### Пропущено
- 15.03.2027 19:00 uk — уже прошло
- 17.03.2027 19:00 en — нет канала для языка en
- 16.03.2027 12:30 uk — до старта меньше 60 минут
"""

EMPTY_REPORT: str = f"""# Livecraft {APP_VERSION} — отчёт 16.03.2027 12:00

## Эфиры YouTube

Итог по эфирам (всего 0): опубликовано 0, исправлено 0, уже стояло 0, не допущено 0, ошибок 0.
"""

DRY_RUN_REPORT: str = f"""# Livecraft {APP_VERSION} — отчёт 16.03.2027 12:00 (dry-run)

## Эфиры YouTube

Итог по эфирам (всего 1): опубликуем 1, исправим 0, уже стояло 0, не допущено 0, ошибок 0.

### Создано (1)
- 17.03.2027 19:00 uk {UA_PREFIX} — эфира нет, будет создан — не выполнено (dry-run)
"""

STATUS_REPORT: str = f"""# Livecraft {APP_VERSION} — отчёт 16.03.2027 12:00

## Эфиры YouTube

Итог по эфирам (всего 1): уже стояло 1, ошибок 0.
Код выхода 1 — не всё выполнено: ошибок каналов и файлов программы 1.
Файл ключей: {KEYS_SHOWN}

### Ошибки
- Канал RU @Kanal_RU — {QUOTA.human}

### Запланировано на каналах (1)
- 17.03.2027 19:00 uk {UA_PREFIX} — https://www.youtube.com/watch?v=abc
"""


def _text(report: RunReport) -> str:
    """Отчёт запуска с одной частью — эфиров, как его пишет запуск."""
    return RunReportFile(report.started, report.is_dry_run, (ReportText(report).part(()),)).text


def _headers(report: RunReport) -> list[str]:
    return [line for line in _text(report).splitlines() if line.startswith("### ")]


def _sent(day: int) -> BroadcastResult:
    return result_of(OutcomeKind.CREATED, key_at(day), key_state=KeyState.SENT)


def test_render_matches_the_sample() -> None:
    report: RunReport = report_of(
        results=(
            _sent(17),
            result_of(OutcomeKind.CREATED, key_at(19), key_state=KeyState.FAILED, form_failure=NOT_CONFIRMED),
            result_of(
                OutcomeKind.FIXED,
                key_at(18),
                changes=(FieldChange(ChangedField.DESCRIPTION, "-", "-"),),
                key_state=KeyState.SENT,
            ),
            result_of(
                OutcomeKind.MATCHED, key_at(17, 21, "ru"), RU, broadcast_url="https://www.youtube.com/watch?v=def456"
            ),
            result_of(OutcomeKind.ERROR, key_at(20), error=LIVE_OFF),
        ),
        skipped=SkippedSlots((
            SkippedLine(SkipKind.PAST, key_at(15), "Прошлый"),
            SkippedLine(SkipKind.NO_CHANNEL, key_at(17, language="en"), "English"),
            SkippedLine(SkipKind.TOO_LATE, key_at(16, 12, minute=30), "Скоро", 60),
        )),
        keys_file=KEYS_SHOWN,
    )
    assert _text(report) == SAMPLE_REPORT


def test_empty_sections_are_not_printed() -> None:
    assert _text(report_of()) == EMPTY_REPORT


def test_dry_run_marks_the_title_and_every_outcome() -> None:
    assert _text(report_of(ReportKind.DRY_RUN, results=(result_of(OutcomeKind.CREATED),))) == DRY_RUN_REPORT


def test_status_report_structure() -> None:
    report: RunReport = report_of(
        ReportKind.STATUS,
        results=(result_of(OutcomeKind.MATCHED, broadcast_url="https://www.youtube.com/watch?v=abc"),),
        failures=(RunFailure.of_channel(RU, QUOTA),),
        keys_file=KEYS_SHOWN,
    )
    assert _text(report) == STATUS_REPORT


def test_the_kind_of_report_follows_the_run_request() -> None:
    assert ReportKind.of(RunRequest(RunMode.RUN, None, dry_run=False, debug=False)) is ReportKind.FULL
    assert ReportKind.of(RunRequest(RunMode.RUN, None, dry_run=True, debug=False)) is ReportKind.DRY_RUN
    assert ReportKind.of(RunRequest(RunMode.STATUS, None, dry_run=False, debug=False)) is ReportKind.STATUS


def test_orphans_section_appears_only_when_present() -> None:
    orphan: str = OrphanLine(_orphan(OrphanKind.ORPHAN, 19), KYIV).text
    text: str = _text(report_of(orphans=(orphan,)))
    assert (
        "### Перенесён или отменён? (1)\n"
        "- 19.03.2027 12:00 uk -> Канал UA @Kanal_UA — https://www.youtube.com/watch?v=old — эфир не удалён\n"
    ) in text
    assert "### Уже запланировано" not in text
    assert "Перенесён или отменён" not in _text(report_of())


def _orphan(kind: OrphanKind, day: int) -> OrphanBroadcast:
    """Эфир с меткой слота 19.03.2027 12:00 uk; стоит на площадке в `day` в 14:00 по Киеву."""
    slot_key: SlotKey = key_at(19, 12)
    broadcast: UpcomingBroadcast = UpcomingBroadcast("old", start_at(day, 14), "Эфир", "", "s1")
    return OrphanBroadcast(channel=UA, broadcast=broadcast, marker=slot_key.slot_id, key=slot_key, kind=kind)


def test_a_moved_broadcast_says_where_it_stands_in_the_program_zone() -> None:
    assert OrphanLine(_orphan(OrphanKind.MOVED, 21), KYIV).text == (
        "19.03.2027 12:00 uk -> Канал UA @Kanal_UA — https://www.youtube.com/watch?v=old — стоит на 21.03.2027 14:00: "
        "время эфира менял владелец, программа его не трогает"
    )


def test_matched_fixed_ambiguous_and_error_texts() -> None:
    report: RunReport = report_of(
        results=(
            result_of(OutcomeKind.MATCHED, broadcast_url="u1"),
            result_of(
                OutcomeKind.FIXED,
                changes=(FieldChange(ChangedField.TITLE, "а", "б"), FieldChange(ChangedField.DESCRIPTION, "-", "-")),
            ),
            _sent(17),
            result_of(OutcomeKind.AMBIGUOUS),
            result_of(OutcomeKind.ERROR, error=OutcomeError("youtube", "forbidden", "отказ YouTube")),
        )
    )
    text: str = _text(report)
    assert f"{UA_PREFIX} — u1\n" in text
    assert "отличалось: название, описание; исправлено, ключ и ссылка прежние\n" in text
    assert "эфир создан, ключ отправлен в форму\n" in text
    assert "несколько эфиров на эту минуту без маркера программы" in text
    assert f"{UA_PREFIX} — отказ YouTube\n" in text
    assert text.splitlines()[4] == (
        "Итог по эфирам (всего 5): опубликовано 1, исправлено 1, уже стояло 1, не допущено 0, ошибок 2."
    )
    assert "✅" not in text and "❌" not in text and "планер" not in text


def test_errors_and_warnings_come_before_reference_sections() -> None:
    """Отчёт открывают ради ошибок и предупреждений — они сразу после итога, справка ниже."""
    report: RunReport = report_of(
        results=(_sent(17), result_of(OutcomeKind.ERROR, error=LIVE_OFF)),
        warnings=("предупреждение",),
        notes=(msg.WARNING_LIVE_CHAT,),
        mismatches=("расхождение",),
        skipped=SkippedSlots((SkippedLine(SkipKind.PAST, key_at(15), "Прошлый"),)),
    )
    assert _headers(report) == [
        "### Ошибки",
        "### Предупреждения",
        "### Расхождения с платформой",
        "### Создано (1)",
        "### Пропущено",
        msg.REPORT_SECTION_NOTES,
    ]
    failed: RunReport = report_of(
        results=(result_of(OutcomeKind.CREATED, key_state=KeyState.FAILED, form_failure=NOT_CONFIRMED),)
    )
    assert _headers(failed) == ["### Ключ не дошёл до стримера", "### Создано (1)"]


def test_not_delivered_section_only_when_the_form_failed() -> None:
    """Ключ, не дошедший до стримера, — сразу под итогом; счётчики и раздел «Создано» прежние."""
    assert "Ключ не дошёл до стримера" not in _text(report_of(results=(_sent(17),)))
    failed: RunReport = report_of(
        results=(
            _sent(17),
            result_of(OutcomeKind.STREAM_ATTACHED, key_at(18), key_state=KeyState.FAILED, form_failure=NOT_CONFIRMED),
        )
    )
    lines: list[str] = _text(failed).splitlines()
    assert lines[4] == "Итог по эфирам (всего 2): опубликовано 2, исправлено 0, уже стояло 0, не допущено 0, ошибок 0."
    assert lines[7] == "### Ключ не дошёл до стримера"
    assert lines[8].startswith(f"- 18.03.2027 19:00 uk {UA_PREFIX} — {NOT_CONFIRMED.human}")
    assert "### Создано (2)" in lines
    assert failed.totals.errors == 0


def test_platform_notes_are_the_last_section_of_the_report() -> None:
    report: RunReport = report_of(warnings=("обложка не поставлена",), notes=(msg.WARNING_LIVE_CHAT,))
    text: str = _text(report)
    assert text.index("### Предупреждения") < text.index(msg.REPORT_SECTION_NOTES)
    assert text.rstrip("\n").endswith(f"- {msg.WARNING_LIVE_CHAT}")


def test_kept_key_note_is_a_lead_line_under_the_matched_section() -> None:
    """Поведение программы, а не особенность площадки — пояснение сразу под заголовком «совпадает»."""
    matched: BroadcastResult = result_of(OutcomeKind.MATCHED, broadcast_url="https://www.youtube.com/watch?v=b1")
    lines: list[str] = _text(report_of(results=(matched,), has_kept_keys=True)).splitlines()
    header: int = lines.index(msg.REPORT_SECTION_MATCHED.format(count=1))
    assert lines[header + 1] == msg.WARNING_KEPT_KEY
    assert lines[header + 2].startswith("- 17.03.2027 19:00 uk")
    assert msg.REPORT_SECTION_NOTES not in lines
    assert msg.WARNING_KEPT_KEY not in _text(report_of(results=(matched,)))


def test_totals_are_counted_once_for_report_and_console() -> None:
    report: RunReport = report_of(
        results=(
            _sent(17),
            result_of(OutcomeKind.STREAM_ATTACHED, key_state=KeyState.FAILED),
            result_of(OutcomeKind.MATCHED),
            result_of(OutcomeKind.NO_STREAM),
            result_of(OutcomeKind.NOT_ADMITTED),
        ),
        failures=(RunFailure.of_channel(RU, QUOTA),),
        orphans=("сирота",),
    )
    assert report.totals == RunTotals(
        created=2,
        fixed=0,
        matched=1,
        not_admitted=1,      # не допущенный — не ошибка
        errors=1,
        broadcasts=5,
        failures=1,
        orphans=1,
        skipped=0,
        undelivered=1,
    )
    assert report.summary_lines == RunConsole(report).lines[: len(report.summary_lines)]


# --- код выхода контура B: единственное правило — RunReport.exit


def test_not_admitted_alone_gives_done_without_reasons() -> None:
    run_exit: RunExit = report_of(results=(result_of(OutcomeKind.NOT_ADMITTED), _sent(17))).exit
    assert (run_exit.outcome, run_exit.reasons, run_exit.line, run_exit.log_reasons) == (RunOutcome.DONE, (), None, ())


@pytest.mark.parametrize(
    ("report", "reason"),
    [
        (report_of(results=(result_of(OutcomeKind.ERROR, error=LIVE_OFF),)), "errors:1"),
        (report_of(results=(result_of(OutcomeKind.AMBIGUOUS), result_of(OutcomeKind.NO_STREAM))), "errors:2"),
        (report_of(failures=(RunFailure.of_channel(RU, QUOTA),)), "failures:1"),
        (report_of(results=(result_of(OutcomeKind.CREATED, key_state=KeyState.FAILED),)), "key_undelivered:1"),
    ],
)
def test_real_problems_give_failed(report: RunReport, reason: str) -> None:
    """Ошибка эфира, сбой канала и неотправленный ключ — код 1; не допущенный рядом этого не меняет."""
    with_not_admitted: RunReport = report_of(
        results=(*report.results, result_of(OutcomeKind.NOT_ADMITTED)), failures=report.failures
    )
    for found in (report, with_not_admitted):
        assert (found.exit.outcome, found.exit.log_reasons) == (RunOutcome.FAILED, (reason,))
        assert found.exit.outcome.exit_code.value == 1


def test_exit_line_only_when_there_are_reasons() -> None:
    """Код 0 — строки «Код выхода» нет ни в «Итоге», ни в отчёте, ни в консоли; код 1 — есть, с причинами."""
    quiet: RunReport = report_of(results=(result_of(OutcomeKind.NOT_ADMITTED),))
    loud: RunReport = report_of(
        results=(result_of(OutcomeKind.NOT_ADMITTED),), failures=(RunFailure.of_channel(RU, QUOTA),)
    )
    expected: str = "Код выхода 1 — не всё выполнено: ошибок каналов и файлов программы 1."
    assert not [line for line in quiet.summary_lines if line.startswith("Код выхода")]
    assert "Код выхода" not in _text(quiet) and "Код выхода" not in "\n".join(RunConsole(quiet).lines)
    assert loud.summary_lines[-1] == expected
    assert expected in _text(loud).splitlines()
    assert expected in RunConsole(loud).lines


# --- строки из объектов запуска


def test_a_thumbnail_upload_limit_is_explained() -> None:
    item: PlannedBroadcast = item_at(17)
    line: str = WarningText(item).text(OutcomeWarning(WarningStep.THUMBNAIL, "uploadRateLimitExceeded", "HTTP 429"))
    assert line == (
        f"17.03.2027 19:00 uk {UA_PREFIX}: " + msg.WARNING_STEP_TEXT["thumbnail"] + " — "
        + msg.THUMBNAIL_REASON_TEXT["uploadRateLimitExceeded"]
    )


def test_an_unknown_reason_keeps_the_code_and_the_google_message() -> None:
    line: str = WarningText(item_at(17)).text(OutcomeWarning(WarningStep.THUMBNAIL, "somethingNew", "HTTP 400: x"))
    assert line.endswith(msg.WARNING_STEP_TEXT["thumbnail"] + " — somethingNew (HTTP 400: x)")
    known: str = WarningText(item_at(17)).text(OutcomeWarning(WarningStep.SETTINGS, "quotaExceeded", "HTTP 403"))
    assert known.endswith(msg.WARNING_STEP_TEXT["settings"] + " — " + msg.YOUTUBE_REASON_TEXT["quotaExceeded"])


def test_a_reported_field_and_an_ambiguous_minute_name_values_and_links() -> None:
    item: PlannedBroadcast = with_found_key(item_at(17), "bc17", "aaaa-bbbb-cccc-dddd-eeee")
    item.match.actual = with_changes(item.expected, auto_start=False)
    item.match.ambiguous_urls = ("https://www.youtube.com/watch?v=a", "https://www.youtube.com/watch?v=b")
    reported: str = WarningText(item).text(OutcomeWarning(WarningStep.REPORTED_FIELD, "auto_start"))
    ambiguous: str = WarningText(item).text(OutcomeWarning(WarningStep.AMBIGUOUS, "2"))
    assert reported.startswith(f"не можем исправить: 17.03.2027 19:00 uk {UA_PREFIX} — автостарт: нужно да, на площадке нет;")
    assert ambiguous.endswith("оставьте один: https://www.youtube.com/watch?v=a, https://www.youtube.com/watch?v=b")


def _facts(item: PlannedBroadcast, **values: object) -> BroadcastFacts:
    """Факты площадки, совпадающие с планом эфира; `values` — что разошлось."""
    expected: BroadcastSpec = item.expected
    facts: BroadcastFacts = BroadcastFacts(
        broadcast_id="bc17",
        title=expected.title,
        description=expected.description,
        start_utc=item.slot.start,
        privacy_status=expected.privacy,
        made_for_kids=False,
        age_restricted=False,
        default_language=item.slot.language,
        default_audio_language=item.slot.language,
        category_id=expected.category_id,
        bound_stream_id="s1",
        stream_marker=item.slot.slot_id,
        auto_start=expected.auto_start,
        auto_stop=expected.auto_stop,
        latency_preference=expected.latency_preference,
    )
    return with_changes(facts, **values)


def test_facts_that_match_the_plan_give_no_mismatch() -> None:
    item: PlannedBroadcast = with_found_key(item_at(17), "bc17", "aaaa-bbbb-cccc-dddd-eeee")
    assert FactsCheck(item, LIMITS, KYIV).lines == ()
    item.match.facts = _facts(item)
    assert FactsCheck(item, LIMITS, KYIV).lines == ()


def test_mismatches_name_what_was_wanted_and_what_is_on_the_platform() -> None:
    item: PlannedBroadcast = with_found_key(item_at(17), "bc17", "aaaa-bbbb-cccc-dddd-eeee")
    item.match.facts = _facts(
        item,
        description="другое\nописание",
        start_utc=item.slot.start + timedelta(hours=1),
        default_language="en",
        made_for_kids=True,
    )
    prefix: str = f"17.03.2027 19:00 uk {UA_PREFIX}"
    assert FactsCheck(item, LIMITS, KYIV).lines == (
        f"{prefix}: описание — хотели: 14 символов, начало «Описание эфира»; "
        "на платформе: 15 символов, начало «другое описание»",
        f"{prefix}: время старта — хотели: 17.03.2027 19:00; на платформе: 17.03.2027 20:00",
        f"{prefix}: язык — хотели: uk; на платформе: en",
        f"{prefix}: аудитория — хотели: не для детей; на платформе: для детей",
    )


def test_the_mark_of_a_new_stream_is_not_a_mismatch() -> None:
    """Поток создан этим запуском: перечитывание фактов может ещё не видеть его метку."""
    item: PlannedBroadcast = with_new_key(item_at(17), "bc17", "aaaa-bbbb-cccc-dddd-eeee")
    item.match.facts = _facts(item, stream_marker=None)
    assert FactsCheck(item, LIMITS, KYIV).lines == ()
    item.decision = Decision.MATCH
    assert FactsCheck(item, LIMITS, KYIV).lines == (
        f"17.03.2027 19:00 uk {UA_PREFIX}: маркер потока — хотели: {item.slot.slot_id}; на платформе: -",
    )


def test_undated_notices_are_platform_notes_once_per_channel_and_title(tmp_path: Path) -> None:
    """Канал за запуск читается не раз: одинаковое замечание — одна строка; в предупреждения не идёт."""
    notice: PlatformNotice = PlatformNotice(PlatformNoticeKind.UNDATED_BROADCAST, "Канал UA", "Брифинг", "@Kanal_UA")
    other: PlatformNotice = PlatformNotice(PlatformNoticeKind.UNDATED_BROADCAST, "Канал RU", "Брифинг", "@Kanal_RU")
    notes: RunNotes = RunNotes((), (notice, other, notice), (), LivecraftPaths(tmp_path))
    assert notes.platform_notes == (
        msg.NOTE_UNDATED_BROADCAST.format(channel="Канал UA @Kanal_UA", title="Брифинг"),
        msg.NOTE_UNDATED_BROADCAST.format(channel="Канал RU @Kanal_RU", title="Брифинг"),
    )
    assert notes.run_warnings == ()


def test_run_warnings_collect_the_run_the_broadcasts_the_forms_and_the_channels(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    item: PlannedBroadcast = item_at(17)
    item.outcome.warn(OutcomeWarning(WarningStep.LANGUAGE, "quotaExceeded"))
    page: Path = paths.logs_dir / "form_response.html"
    item.outcome.form_failure = FormFailure(FormProblem.NOT_CONFIRMED, "Форма", "", "no", diagnostic=page)
    twin: PlannedBroadcast = item_at(17, language="ru", channel=RU)
    twin.outcome.form_failure = item.outcome.form_failure
    channel: PlatformNotice = PlatformNotice(PlatformNoticeKind.CHANNEL, "", "", text="канал выровнен")
    notes: RunNotes = RunNotes((item, twin), (channel, channel), ("память не записана",), paths)
    assert notes.run_warnings == (
        "память не записана",
        WarningText(item).text(item.outcome.warnings[0]),
        msg.WARNING_FORM_DIAGNOSTIC.format(path=str(Path("logs") / "form_response.html")),
        "канал выровнен",
    )


def test_the_live_chat_is_a_platform_note_once_per_run() -> None:
    items: list[PlannedBroadcast] = [with_new_key(item_at(day), f"bc{day}", "aaaa-bbbb-cccc-dddd-eeee") for day in (17, 18)]
    for item in items:
        item.match.facts = _facts(item, live_chat_id="chat")
    assert RunNotes(tuple(items), (), (), LivecraftPaths(Path("r"))).platform_notes == (msg.WARNING_LIVE_CHAT,)


def test_skipped_lines_come_from_the_past_the_lead_time_and_the_selection() -> None:
    """Прошедшие — только языков каналов запуска; слот на двух каналах — одна строка; по порядку слотов."""
    second_ua: ChannelConfig = channel_of("@Kanal_UA2", "Канал UA 2", "uk")
    slots: tuple[StreamSlot, ...] = (
        slot_of(start_at(16, 12, 30), "uk"), slot_of(start_at(17), "uk"), slot_of(start_at(17), "hu")
    )
    selection: Selection = Selection.of(request_of(slots, (UA, second_ua, RU)))
    past: tuple[SlotEntry, ...] = tuple(
        SlotEntry(slot.key, slot.texts, (), slot.sources) for slot in (slot_of(start_at(15), "uk"), slot_of(start_at(15), "hu"))
    )
    skipped: SkippedSlots = SkippedSlots.of(selection, past, {"uk", "ru"}, 60)
    assert [line.text for line in skipped.lines] == [
        "15.03.2027 19:00 uk — уже прошло",
        "16.03.2027 12:30 uk — до старта меньше 60 минут",
        "17.03.2027 19:00 hu — нет канала для языка hu",
    ]
    assert skipped.summary_line == (
        "Слоты вне работы: 3 — время старта уже прошло 1, до старта меньше 60 минут 1, нет канала для языка hu 1."
    )


def test_one_skip_reason_is_named_without_a_count() -> None:
    skipped: SkippedSlots = SkippedSlots((SkippedLine(SkipKind.PAST, key_at(15), "а"), SkippedLine(SkipKind.PAST, key_at(14), "б")))
    assert skipped.summary_line == "Слоты вне работы: 2 — время старта уже прошло."
    assert SkippedSlots().summary_line is None


def test_a_refused_channel_is_one_failure_line_for_all_its_objects(tmp_path: Path) -> None:
    refused: list[PlannedBroadcast] = [admitted(item_at(day), tmp_path, ChannelStatus.NEEDS_LOGIN) for day in (17, 18)]
    ready: PlannedBroadcast = admitted(item_at(17, language="ru", channel=RU), tmp_path)
    [failure] = RunFailure.channel_refusals([*refused, ready])
    assert failure.subject == "Канал UA @Kanal_UA"
    assert failure.text == f"Канал UA @Kanal_UA — {msg.YOUTUBE_REASON_TEXT['loginRequired']}"


# --- отчёт из входов прогона


def test_the_report_is_built_from_the_run_objects(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    created: PlannedBroadcast = with_new_key(item_at(17), "bc17", "aaaa-bbbb-cccc-dddd-6jty")
    created.outcome.should_send_key, created.outcome.is_form_sent = True, True
    kept: PlannedBroadcast = confirmed(with_found_key(item_at(17, 21, "ru", RU), "bc21", "aaaa-bbbb-cccc-dddd-3j1j"))
    soon: PlannedBroadcast = item_at(16, 12)
    soon.is_too_late, soon.decision = True, Decision.TOO_LATE
    selection: Selection = Selection(planned=(soon, created, kept), skipped=())
    orphan: OrphanBroadcast = _orphan(OrphanKind.ORPHAN, 19)
    keys: Path = paths.file(FileName.KEYS)
    report: RunReport = RunReport.of(report_request(selection, paths, orphans=(orphan,), keys_file=keys))
    assert [result.kind for result in report.results] == [OutcomeKind.CREATED, OutcomeKind.MATCHED]
    assert report.has_kept_keys and report.keys_file == KEYS_SHOWN
    assert report.channel_order == ("kanal_ua", "kanal_ru")
    assert [line.kind for line in report.skipped.lines] == [SkipKind.TOO_LATE]
    assert report.orphans == (OrphanLine(orphan, KYIV).text,)
    assert report.exit.outcome is RunOutcome.DONE


def test_the_status_report_takes_the_marked_broadcasts_and_the_silent_channels(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    scan: MarkedScan = MarkedScan(broadcasts=(), failures=(ChannelFailure(RU, QUOTA),))
    failure: RunFailure = RunFailure.of_keys_file(KEYS_SHOWN, PermissionError("denied"))
    request: ReportRequest = report_request(Selection((), ()), paths, kind=ReportKind.STATUS, scan=scan, keys_file=failure)
    report: RunReport = RunReport.of(request)
    assert report.failures == (RunFailure.of_channel(RU, QUOTA), failure)
    assert report.keys_file is None
    assert report.exit.log_reasons == ("failures:2",)


def test_the_stream_key_is_only_masked_in_the_report() -> None:
    key: str = "aaaa-bbbb-cccc-dddd-6jty"
    replaced: ReplacedBroadcast = ReplacedBroadcast("old", "https://www.youtube.com/watch?v=old", "oldk-oldk-oldk-oldk-3j1j")
    report: RunReport = report_of(
        results=(result_of(OutcomeKind.CREATED, stream_key=key, broadcast_url="u", replaced=replaced),)
    )
    text: str = _text(report)
    assert "### В форме два ключа на один слот (1)" in text
    assert "****-6jty" in text and "****-3j1j" in text
    assert key not in text and replaced.stream_key not in text


def test_the_broadcasts_total_goes_to_the_log_line() -> None:
    """Итог эфиров строкой лога: вид запуска, итоги, сбои, код выхода контура B и причины."""
    report: RunReport = report_of(results=(_sent(17),))
    assert ReportText(report).event.text == "broadcasts_report kind=full results=1 failures=0 exit_code=0 reason=-"


def test_the_broadcasts_part_names_the_keys_file_for_the_footer() -> None:
    """Путь keys.txt часть отдаёт подвалу запуска; строки хвоста (расход, повторная передача) — после итога."""
    part: PartReport = ReportText(report_of(keys_file=KEYS_SHOWN)).part(("расход",))
    assert part.keys_file == KEYS_SHOWN
    assert part.body[-2:] == (msg.REPORT_TOTAL_KEYS_FILE.format(path=KEYS_SHOWN), "расход")
    assert ReportText(report_of()).part(()).keys_file is None


def test_not_admitted_section_goes_after_not_delivered_and_before_errors(tmp_path: Path) -> None:
    missing_date: PlannedBroadcast = admitted(item_at(18, 20), tmp_path)
    refused: PlannedBroadcast = admitted(item_at(17, language="ru", channel=RU), tmp_path, ChannelStatus.REFUSED)
    results: tuple[BroadcastResult, ...] = tuple(
        BroadcastResult.of_planned(item, is_dry_run=False) for item in (missing_date, refused)
    )
    report: RunReport = report_of(
        results=(
            result_of(OutcomeKind.CREATED, key_state=KeyState.FAILED, form_failure=NOT_CONFIRMED),
            *results,
        ),
        failures=RunFailure.channel_refusals([missing_date, refused]),
    )
    text: str = _text(report)
    lines: list[str] = text.splitlines()
    assert lines[4] == "Итог по эфирам (всего 3): опубликовано 1, исправлено 0, уже стояло 0, не допущено 2, ошибок 0."
    assert text.index("### Ключ не дошёл до стримера") < text.index("### Не допущено к публикации (2)") < text.index(
        "### Ошибки"
    )
    assert sum(1 for line in lines if line.startswith("- Канал RU @Kanal_RU — ")) == 1


# --- пакеты режима Б: раздел отчёта, ВНИМАНИЕ консоли, причина кода выхода


ACCEPTED_PACKAGE: PackageLine = PackageLine("plan.bcast", PackageLineStatus.ACCEPTED, slots_total=2, slots_mine=1)
BROKEN_PACKAGE: PackageLine = PackageLine("broken.bcast", PackageLineStatus.DAMAGED, detail="не ZIP-архив (x)")


def test_the_packages_are_a_report_section_after_the_skipped_slots() -> None:
    report: RunReport = report_of(packages=PackageLines((ACCEPTED_PACKAGE, BROKEN_PACKAGE)))
    section: str = "\n".join(
        (msg.REPORT_SECTION_PACKAGES, *(msg.REPORT_ITEM.format(text=line.text) for line in (ACCEPTED_PACKAGE, BROKEN_PACKAGE)))
    )
    assert section in _text(report)
    assert "broken.bcast — пакет повреждён: не ZIP-архив (x); файл не тронут" in _text(report)


def test_an_unreadable_package_is_an_exit_reason_and_an_attention_line() -> None:
    report: RunReport = report_of(packages=PackageLines((ACCEPTED_PACKAGE, BROKEN_PACKAGE)))
    assert report.exit.outcome is RunOutcome.FAILED and report.exit.log_reasons == ("packages:1",)
    assert report.exit.line == msg.SUMMARY_EXIT_FAILED.format(
        code=1, reasons=msg.EXIT_REASON_TEXT["packages"].format(count=1)
    )
    lines: tuple[str, ...] = RunConsole(report).lines
    assert msg.CONSOLE_ATTENTION_PACKAGE.format(text=BROKEN_PACKAGE.text) in lines
    assert msg.CONSOLE_ATTENTION_PACKAGE.format(text=ACCEPTED_PACKAGE.text) not in lines


def test_read_packages_do_not_change_the_exit_code() -> None:
    report: RunReport = report_of(packages=PackageLines((ACCEPTED_PACKAGE,)))
    assert report.exit.outcome is RunOutcome.DONE and report.totals.unreadable_packages == 0


def test_the_request_gives_the_report_its_packages(tmp_path: Path) -> None:
    lines: PackageLines = PackageLines((BROKEN_PACKAGE,))
    request: ReportRequest = report_request(Selection((), ()), LivecraftPaths(tmp_path), packages=lines)
    assert RunReport.of(request).packages == lines
