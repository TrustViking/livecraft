"""Консоль после запуска контура B (app\\output\\console.py, CLAUDE.md §3 шаг 12): «Итог», блоки сверху вниз, группы по
каналам в порядке channels.json, ключ — только маской, подвал путей."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.form.failure import FormFailure, FormProblem
from app.config.channel import ChannelConfig
from app.output.console import RULE_WIDTH, RunConsole
from app.output.report import ReportKind, RunReport
from app.output.result import BroadcastResult, FieldChange, KeyState, OutcomeKind
from app.output.run_failure import RunFailure
from app.output.skipped import SkipKind, SkippedLine, SkippedSlots
from app.pipeline.admission import AdmissionKind, AdmissionReason
from app.pipeline.memory import ReplacedBroadcast
from app.pipeline.outcome import OutcomeError
from app.platforms.error import PlatformError
from app.platforms.spec import ChangedField
from app.slots.slot import SlotKey
from app.tests.fixtures.output import RU, UA, key_at, report_of, result_of
from app.tests.fixtures.platform import channel_of
from app.ui import messages_ru as msg

KANAL_X: ChannelConfig = channel_of("@Kanal.X", "Kanal.X", "ru", "x.owner@example.com")
KANAL_Y: ChannelConfig = channel_of("@Kanal.Y", "Kanal.Y", "uk", "y.owner@example.com")
CHANNEL_ORDER: tuple[str, ...] = ("kanal.x", "kanal.y")      # ключи каналов в порядке channels.json
FULL_KEYS: tuple[str, ...] = ("aaaa-bbbb-cccc-dddd-6jty", "aaaa-bbbb-cccc-dddd-3j1j", "aaaa-bbbb-cccc-dddd-9zzz")
FORM_DOWN: FormFailure = FormFailure.of_status(FormProblem.TRANSPORT_FAILED, "Регистрация", 503)
RESTORED_WARNING: str = "не можем исправить: 19.03.2027 19:00 uk -> Kanal.Y @Kanal.Y — автостарт: нужно да, на площадке нет"
UNDATED_NOTE: str = msg.NOTE_UNDATED_BROADCAST.format(channel="Kanal.X @Kanal.X", title="Брифинг в Конгрессе")
KEYS_SHOWN: str = str(Path("keystreams") / "keys.txt")

# Макет: блоки сверху вниз, пустой блок не печатается, каналы — в порядке channels.json.
SAMPLE_CONSOLE: str = f"""Итог по эфирам (всего 4): опубликовано 2, исправлено 1, уже стояло 1, не допущено 0, ошибок 0.
Слоты вне работы: 2 — нет канала для языка en.
Код выхода 1 — не всё выполнено: ключ не дошёл до стримера 1.

======================= ВНИМАНИЕ =======================
  ключ не дошёл до стримера: 18.03.2027 20:00 ru -> Kanal.X @Kanal.X — {FORM_DOWN.human}
  вернули к плану: 18.03.2027 20:00 ru -> Kanal.X @Kanal.X — видимость: было private, стало unlisted
  {RESTORED_WARNING}

=================== ОПУБЛИКОВАЛИ (2) ===================
  Kanal.X @Kanal.X (x.owner@example.com)
    17.03.2027  19:00  ru  Контроль влажности экономит до 40% энергии
  Kanal.Y @Kanal.Y (y.owner@example.com)
    17.03.2027  19:00  uk  Депортовані діти мають повернутися

==================== ИСПРАВИЛИ (1) =====================
  Kanal.X @Kanal.X (x.owner@example.com)
    18.03.2027  20:00  ru  Второй эфир — обновлено: описание

================== КЛЮЧИ СТРИМЕРУ (3) ==================
  Kanal.X @Kanal.X (x.owner@example.com)
    17.03.2027  19:00  ru  ****-6jty  отправлен в форму
    18.03.2027  20:00  ru  ****-9zzz  НЕ отправлен — {FORM_DOWN.human}
  Kanal.Y @Kanal.Y (y.owner@example.com)
    17.03.2027  19:00  uk  ****-3j1j  отправлен в форму

==================== УЖЕ СТОЯЛО (1) ====================
  Kanal.Y @Kanal.Y (y.owner@example.com)
    19.03.2027  19:00  uk  Третій ефір

================== НЕ ПУБЛИКОВАЛИ (2) ==================
  нет канала для языка en
    17.03.2027  19:00  en  Russia's 20-Year Hybrid War
    18.03.2027  20:00  en  The Invisible Side of Air"""


def _outcomes() -> tuple[BroadcastResult, ...]:
    """Порядок итогов — как их отдаёт отбор (по слоту, потом по названию канала), а не как в channels.json."""
    return (
        result_of(
            OutcomeKind.CREATED, key_at(17), KANAL_Y,
            key_state=KeyState.SENT, title="Депортовані діти мають повернутися", stream_key=FULL_KEYS[1],
        ),
        result_of(
            OutcomeKind.CREATED, key_at(17, language="ru"), KANAL_X,
            key_state=KeyState.SENT, title="Контроль влажности экономит до 40% энергии", stream_key=FULL_KEYS[0],
        ),
        result_of(
            OutcomeKind.FIXED, key_at(18, 20, "ru"), KANAL_X,
            key_state=KeyState.FAILED, form_failure=FORM_DOWN, title="Второй эфир", stream_key=FULL_KEYS[2],
            changes=(
                FieldChange(ChangedField.DESCRIPTION, "-", "-"),
                FieldChange(ChangedField.PRIVACY, "private", "unlisted"),
            ),
        ),
        result_of(
            OutcomeKind.MATCHED, key_at(19), KANAL_Y, title="Третій ефір", stream_key="aaaa-bbbb-cccc-dddd-1111"
        ),
    )


def _sample_report(**overrides: Any) -> RunReport:
    values: dict[str, Any] = dict(
        results=_outcomes(),
        skipped=SkippedSlots((
            SkippedLine(SkipKind.NO_CHANNEL, key_at(17, language="en"), "Russia's 20-Year Hybrid War"),
            SkippedLine(SkipKind.NO_CHANNEL, key_at(18, 20, "en"), "The Invisible Side of Air"),
        )),
        warnings=(RESTORED_WARNING,),
        notes=(msg.WARNING_LIVE_CHAT, UNDATED_NOTE),
        has_kept_keys=True,      # пояснение — только в отчёте, под «Уже запланировано, совпадает»
        keys_file=KEYS_SHOWN,
        channel_order=CHANNEL_ORDER,
    )
    values.update(overrides)
    kind: ReportKind = values.pop("kind", ReportKind.FULL)
    return report_of(kind, **values)


def _render(report: RunReport) -> str:
    return "\n".join(RunConsole(report).lines)


def _block_titles(text: str) -> list[str]:
    return [line.strip(msg.CONSOLE_RULE_CHAR + " ") for line in text.splitlines() if line.startswith(msg.CONSOLE_RULE_CHAR)]


def _block(text: str, title: str) -> list[str]:
    return text.split(title)[1].split("\n\n")[0].splitlines()[1:]


def test_full_run_matches_the_layout() -> None:
    assert _render(_sample_report()) == SAMPLE_CONSOLE


def test_console_has_no_title_it_is_printed_at_start() -> None:
    """Шапку печатает запуск при старте: в итоговом тексте её нет, иначе в прогоне было бы два заголовка."""
    for kind in ReportKind:
        text: str = _render(_sample_report(kind=kind))
        assert text.splitlines()[0].startswith("Итог по эфирам ")
        assert "Livecraft " not in text


def test_blocks_keep_their_order_and_rules_their_width() -> None:
    text: str = _render(_sample_report())
    assert _block_titles(text) == [
        "ВНИМАНИЕ", "ОПУБЛИКОВАЛИ (2)", "ИСПРАВИЛИ (1)", "КЛЮЧИ СТРИМЕРУ (3)", "УЖЕ СТОЯЛО (1)", "НЕ ПУБЛИКОВАЛИ (2)",
    ]
    rules: list[str] = [line for line in text.splitlines() if line.startswith(msg.CONSOLE_RULE_CHAR)]
    assert {len(line) for line in rules} == {RULE_WIDTH}


def test_empty_blocks_are_not_printed_at_all() -> None:
    """Нули видны в «Итоге»; пустого блока нет."""
    text: str = _render(_sample_report(results=(), skipped=SkippedSlots(), warnings=()))
    lines: list[str] = text.splitlines()
    assert lines[0] == "Итог по эфирам (всего 0): опубликовано 0, исправлено 0, уже стояло 0, не допущено 0, ошибок 0."
    assert not any(line.startswith("Слоты вне работы") for line in lines)
    assert _block_titles(text) == []


def test_broadcasts_are_grouped_by_channel_in_channels_json_order() -> None:
    """Шапка канала с почтой — один раз на группу; внутри канала — по порядку слотов."""
    text: str = _render(_sample_report())
    keys_block: list[str] = _block(text, "КЛЮЧИ СТРИМЕРУ (3)")
    assert keys_block[0] == "  Kanal.X @Kanal.X (x.owner@example.com)"
    assert keys_block[1].startswith("    17.03.2027  19:00") and keys_block[2].startswith("    18.03.2027  20:00")
    assert keys_block[3] == "  Kanal.Y @Kanal.Y (y.owner@example.com)"
    assert text.count("  Kanal.X @Kanal.X (x.owner@example.com)") == 3
    assert "-> Kanal.X @Kanal.X" not in text.split("ОПУБЛИКОВАЛИ (2)")[1]


def test_a_channel_outside_channels_json_goes_after_the_known_ones() -> None:
    report: RunReport = _sample_report(
        results=(result_of(OutcomeKind.MATCHED, key_at(17), UA, title="А"), *_outcomes()), warnings=()
    )
    matched: list[str] = _block(_render(report), "УЖЕ СТОЯЛО (2)")
    assert matched[0].startswith("  Kanal.Y") and matched[2].startswith("  Канал UA @Kanal_UA")


def test_the_stream_key_is_masked_and_the_full_key_appears_nowhere() -> None:
    text: str = _render(_sample_report())
    assert "****-6jty" in text and "****-9zzz" in text
    assert all(key not in text for key in FULL_KEYS)


def test_the_paths_are_not_printed_by_the_broadcasts_console() -> None:
    """Путь keys.txt, отчёта и лога называет один подвал запуска (app\\run\\run_report.py), а не консоль эфиров."""
    text: str = _render(_sample_report())
    assert "keystreams" not in text and msg.CONSOLE_LABEL_KEYS + " " not in text
    assert text.splitlines()[-1] == "    18.03.2027  20:00  en  The Invisible Side of Air"


def test_a_settings_only_fix_has_no_tail_in_fixed_and_is_named_in_attention() -> None:
    """Изменилась только видимость: в ИСПРАВИЛИ — строка без «обновлено», во ВНИМАНИЕ — было / стало."""
    fixed: BroadcastResult = result_of(
        OutcomeKind.FIXED, key_at(18, 20, "ru"), KANAL_X,
        key_state=KeyState.SENT, title="Второй эфир", stream_key=FULL_KEYS[2],
        changes=(FieldChange(ChangedField.PRIVACY, "private", "unlisted"),),
    )
    text: str = _render(_sample_report(results=(fixed,), skipped=SkippedSlots(), warnings=()))
    lines: list[str] = text.splitlines()
    assert _block(text, "ИСПРАВИЛИ (1)") == [
        "  Kanal.X @Kanal.X (x.owner@example.com)", "    18.03.2027  20:00  ru  Второй эфир"
    ]
    assert lines[0] == "Итог по эфирам (всего 1): опубликовано 0, исправлено 1, уже стояло 0, не допущено 0, ошибок 0."
    assert (
        "  вернули к плану: 18.03.2027 20:00 ru -> Kanal.X @Kanal.X — видимость: было private, стало unlisted"
    ) in lines
    assert text.count("видимость") == 1


def test_the_console_has_no_markdown_and_no_icons() -> None:
    text: str = _render(_sample_report())
    assert "#" not in text and "\n- " not in text
    assert all(icon not in text for icon in ("✅", "❌", "⚠", "→"))


def test_attention_collects_errors_failures_forms_restored_and_warnings() -> None:
    error: OutcomeError = OutcomeError("youtube", "liveStreamingNotEnabled", msg.YOUTUBE_REASON_TEXT["liveStreamingNotEnabled"])
    report: RunReport = _sample_report(
        results=(
            *_outcomes(),
            result_of(OutcomeKind.ERROR, key_at(20, 20, "ru"), KANAL_X, error=error),
            result_of(OutcomeKind.AMBIGUOUS, key_at(21, 20, "ru"), KANAL_X),
        ),
        failures=(RunFailure.of_channel(RU, PlatformError("quotaExceeded", "HTTP 403")),),
    )
    text: str = _render(report)
    attention: list[str] = text.split("\n\n")[1].splitlines()
    assert msg.CONSOLE_BLOCK_ATTENTION in attention[0]
    assert f"  ошибка: 20.03.2027 20:00 ru -> Kanal.X @Kanal.X — {error.human}" in attention
    assert f"  ошибка: Канал RU @Kanal_RU — {msg.YOUTUBE_REASON_TEXT['quotaExceeded']}" in attention
    # служебный эфир и живой чат — особенности площадки: только в отчёте
    assert UNDATED_NOTE not in text and "служебный эфир" not in text and "живой чат" not in text
    # AMBIGUOUS приходит предупреждением со ссылками — строкой ошибки не дублируется
    assert not any("несколько эфиров" in line for line in attention)
    assert "повторно не отправляется" not in text


def test_dry_run_speaks_of_intent_and_has_no_keys_block() -> None:
    fixed: BroadcastResult = _outcomes()[2]
    report: RunReport = _sample_report(
        kind=ReportKind.DRY_RUN,
        results=(
            result_of(OutcomeKind.CREATED, key_at(17, language="ru"), KANAL_X, title="Эфир"),
            result_of(
                OutcomeKind.FIXED, key_at(18, 20, "ru"), KANAL_X, title="Второй эфир", changes=fixed.changes
            ),
        ),
        warnings=(),
        keys_file=None,
    )
    text: str = _render(report)
    lines: list[str] = text.splitlines()
    assert lines[0] == "Итог по эфирам (всего 2): опубликуем 1, исправим 1, уже стояло 0, не допущено 0, ошибок 0."
    assert _block_titles(text) == ["ВНИМАНИЕ", "ОПУБЛИКУЕМ (1)", "ИСПРАВИМ (1)", "НЕ ПУБЛИКОВАЛИ (2)"]
    assert "    18.03.2027  20:00  ru  Второй эфир — будет обновлено: описание" in lines
    assert (
        "  вернём к плану: 18.03.2027 20:00 ru -> Kanal.X @Kanal.X — видимость: сейчас private, будет unlisted"
    ) in lines
    assert msg.CONSOLE_BLOCK_KEYS not in text and msg.CONSOLE_LABEL_KEYS + " " not in text


def test_status_prints_the_total_the_attention_and_matched_only() -> None:
    report: RunReport = report_of(
        ReportKind.STATUS,
        results=(result_of(OutcomeKind.MATCHED, key_at(17, language="ru"), KANAL_X, title="Эфир", stream_key=FULL_KEYS[0]),),
        failures=(RunFailure.of_channel(RU, PlatformError("quotaExceeded", "квота исчерпана")),),
        keys_file=KEYS_SHOWN,
    )
    text: str = _render(report)
    lines: list[str] = text.splitlines()
    # сбой канала — не эфир: в «Итог по эфирам» не входит, он — во ВНИМАНИЕ и в причинах кода выхода
    assert lines[0] == "Итог по эфирам (всего 1): уже стояло 1, ошибок 0."
    assert _block_titles(text) == ["ВНИМАНИЕ", "УЖЕ СТОЯЛО (1)"]
    assert f"  ошибка: Канал RU @Kanal_RU — {msg.YOUTUBE_REASON_TEXT['quotaExceeded']}" in lines
    assert "квота исчерпана" not in text
    assert "    17.03.2027  19:00  ru  Эфир" in lines
    assert FULL_KEYS[0] not in text


def test_skipped_are_grouped_by_reason_not_by_channel() -> None:
    """Прошедшие слоты не перечисляются (их число — в «Итоге»); счётчик блока — по напечатанным строкам."""
    report: RunReport = _sample_report(
        results=(),
        warnings=(),
        skipped=SkippedSlots((
            SkippedLine(SkipKind.PAST, key_at(14, language="ru"), "Прошлый"),
            SkippedLine(SkipKind.TOO_LATE, key_at(16, 12, "ru", 30), "Скоро", 60),
            SkippedLine(SkipKind.NO_CHANNEL, key_at(17, language="hu"), "Magyar"),
            SkippedLine(SkipKind.NO_CHANNEL, key_at(17, language="en"), "English"),
        )),
    )
    text: str = _render(report)
    assert text.splitlines()[1].startswith("Слоты вне работы: 4 — время старта уже прошло 1, ")
    assert "Прошлый" not in text
    assert _block(text, "НЕ ПУБЛИКОВАЛИ (3)") == [
        "  до старта меньше 60 минут",
        "    16.03.2027  12:30  ru  Скоро",
        "  нет канала для языка en",
        "    17.03.2027  19:00  en  English",
        "  нет канала для языка hu",
        "    17.03.2027  19:00  hu  Magyar",
    ]


def test_only_past_slots_give_no_skipped_block() -> None:
    """План целиком в прошлом: в «Итоге» — число, блока НЕ ПУБЛИКОВАЛИ нет."""
    past: tuple[SkippedLine, ...] = tuple(
        SkippedLine(SkipKind.PAST, SlotKey(key_at(14).start, language), title) for language, title in (("ru", "Прошлый"), ("uk", "Минулий"))
    )
    text: str = _render(_sample_report(results=(), warnings=(), skipped=SkippedSlots(past)))
    assert "Слоты вне работы: 2 — время старта уже прошло." in text.splitlines()
    assert msg.CONSOLE_BLOCK_SKIPPED not in text
    assert "Прошлый" not in text and "Минулий" not in text


def test_not_admitted_objects_are_attention_lines_only() -> None:
    reason: AdmissionReason = AdmissionReason(
        AdmissionKind.FORM_FIELD, "missing_option", "date", "Время стрима: 18.03.2027",
        question="Время стрима", value="18.03.2027", form_name="TEST_Регистрация",
    )
    report: RunReport = report_of(
        results=(
            result_of(
                OutcomeKind.NOT_ADMITTED, key_at(18, 20, "en"), stream_key="abcd-abcd-abcd-abcd-wxyz",
                broadcast_url="https://www.youtube.com/watch?v=qJjIZCbP89s", reasons=(reason,),
            ),
        )
    )
    lines: list[str] = list(RunConsole(report).lines)
    assert lines[0] == "Итог по эфирам (всего 1): опубликовано 0, исправлено 0, уже стояло 0, не допущено 1, ошибок 0."
    assert lines[1:] == [
        "",
        lines[2],
        "  не допущено: 18.03.2027 20:00 en -> Канал UA @Kanal_UA — В форме «TEST_Регистрация» в вопросе "
        "«Время стрима» нет варианта «18.03.2027». Эфир на канале есть (https://www.youtube.com/watch?v=qJjIZCbP89s), "
        "но не исправлялся, ключ стримеру не передан. Добавьте вариант в форму. "
        "Программа передаст ключ на следующем запуске.",
    ]
    assert msg.CONSOLE_BLOCK_ATTENTION in lines[2]


def test_fixed_names_only_what_was_fixed_and_matched_names_the_unfixed_cover() -> None:
    report: RunReport = report_of(
        results=(
            result_of(OutcomeKind.MATCHED, key_at(19, language="ru"), KANAL_X, title="Эфир 19", unfixed=(ChangedField.THUMBNAIL,)),
            result_of(
                OutcomeKind.FIXED, key_at(20, language="ru"), KANAL_X, title="Эфир 20",
                changes=(FieldChange(ChangedField.TITLE, "а", "б"),), unfixed=(ChangedField.THUMBNAIL,),
            ),
        )
    )
    lines: list[str] = list(RunConsole(report).lines)
    fixed: list[str] = [line for line in lines if "20.03.2027" in line]
    matched: list[str] = [line for line in lines if "19.03.2027" in line]
    assert len(fixed) == 1 and fixed[0].endswith("обновлено: название; обложка эфира не поставлена")
    assert len(matched) == 1 and matched[0].endswith("Эфир 19; обложка эфира не поставлена")
    assert lines.index(fixed[0]) < lines.index(matched[0])        # ИСПРАВИЛИ выше УЖЕ СТОЯЛО


def test_two_keys_in_the_form_are_named_with_masked_keys() -> None:
    replaced: ReplacedBroadcast = ReplacedBroadcast("old", "https://www.youtube.com/watch?v=old", FULL_KEYS[1])
    report: RunReport = report_of(
        results=(result_of(OutcomeKind.CREATED, key_state=KeyState.SENT, stream_key=FULL_KEYS[0], replaced=replaced),)
    )
    text: str = "\n".join(RunConsole(report).lines)
    assert (
        "  17.03.2027 19:00 uk -> Канал UA @Kanal_UA: прежний эфир на времени слота не найден — поставлен новый; "
        "в форме на эту дату два ключа: действующий ****-6jty, прежний ****-3j1j"
    ) in text.splitlines()
    assert FULL_KEYS[0] not in text and FULL_KEYS[1] not in text
