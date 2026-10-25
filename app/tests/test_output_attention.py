"""Сводка блока ВНИМАНИЕ консоли (app\\output\\attention.py, CLAUDE.md §14 решение 78): не допущенные эфиры одной
причины — одной строкой с числом и значениями, одиночный — прежней строкой, прочие повторы — с числом."""
from __future__ import annotations

from app.config.channel import ChannelConfig
from app.output.attention import AttentionLines, NotAdmittedSummary
from app.output.console import RunConsole
from app.output.report import RunReport
from app.output.result import BroadcastResult, OutcomeKind
from app.output.result_text import ResultText
from app.pipeline.admission import AdmissionKind, AdmissionReason
from app.platforms.channel import ChannelStatus
from app.tests.fixtures.output import key_at, report_of, result_of
from app.tests.fixtures.platform import channel_of
from app.ui import messages_ru as msg
from app.ui.console_table import TableMark

FORM: str = "TEST_Регистрация"
QUESTION: str = "Время стрима ( Stream time )"
CHANNELS: tuple[ChannelConfig, ...] = tuple(
    channel_of(f"@Kanal.{letter}", f"Kanal.{letter}", "uk", f"{letter.lower()}.owner@example.com") for letter in "ABCDEF"
)
DAYS: tuple[int, ...] = (17, 18, 19, 20, 21, 22, 23)
WIDTH: int = 80


def _date_missing(day: int, question: str = QUESTION) -> AdmissionReason:
    value: str = f"{day}.03.2027"
    return AdmissionReason(
        AdmissionKind.FORM_FIELD, "missing_option", "date", f"{question}: {value}",
        question=question, value=value, form_name=FORM,
    )


def _not_admitted(day: int, channel: ChannelConfig, *reasons: AdmissionReason) -> BroadcastResult:
    return result_of(OutcomeKind.NOT_ADMITTED, key_at(day), channel, reasons=reasons or (_date_missing(day),))


def _week() -> tuple[BroadcastResult, ...]:
    """42 эфира: 7 дат на 6 каналах, ни одной даты нет в форме — как в прогоне 0.1.11."""
    return tuple(_not_admitted(day, channel) for day in DAYS for channel in CHANNELS)


def test_broadcasts_with_one_reason_are_one_line_with_the_count_and_every_date() -> None:
    lines: tuple[str, ...] = NotAdmittedSummary(_week()).lines
    dates: str = ", ".join(f"{day}.03.2027" for day in DAYS)
    assert lines == (
        f"  не допущено эфиров — 42: В форме «{FORM}» в вопросе «{QUESTION}» нет вариантов: {dates}. "
        "Эфиры не созданы, ключи стримеру не переданы. Добавьте варианты в форму. "
        "Программа создаст эфиры на следующем запуске.",
    )


def test_another_reason_is_its_own_line_and_a_separate_entry_of_the_block() -> None:
    """Другой вопрос формы — другая причина: своя строка, во ВНИМАНИЕ — через «-»."""
    other: BroadcastResult = _not_admitted(24, CHANNELS[0], _date_missing(24, "Язык"))
    report: RunReport = report_of(results=(*_week(), other))
    lines: list[str] = list(RunConsole(report, WIDTH).lines)
    attention: list[str] = lines[lines.index(" ВНИМАНИЕ ".center(WIDTH, "=")) + 1:]
    assert attention[0].startswith("  не допущено эфиров — 42: ")
    assert attention[1] == TableMark.SEPARATOR.value * WIDTH
    assert attention[2] == msg.CONSOLE_ATTENTION_NOT_ADMITTED.format(text=ResultText(other).not_admitted)
    assert attention[3] == TableMark.RULE.value * WIDTH


def test_a_single_broadcast_keeps_its_own_line() -> None:
    single: BroadcastResult = _not_admitted(17, CHANNELS[0])
    assert NotAdmittedSummary((single,)).lines == (
        msg.CONSOLE_ATTENTION_NOT_ADMITTED.format(text=ResultText(single).not_admitted),
    )


def test_a_broadcast_with_several_reasons_keeps_its_own_line() -> None:
    """Причин несколько — строка эфира, как прежде; эфиры с одной причиной идут своей строкой."""
    double: BroadcastResult = _not_admitted(17, CHANNELS[0], _date_missing(17), _date_missing(17, "Язык"))
    others: tuple[BroadcastResult, ...] = tuple(_not_admitted(18, channel) for channel in CHANNELS[1:3])
    lines: tuple[str, ...] = NotAdmittedSummary((double, *others)).lines
    assert lines[0] == msg.CONSOLE_ATTENTION_NOT_ADMITTED.format(text=ResultText(double).not_admitted)
    assert lines[1].startswith("  не допущено эфиров — 2: ") and "нет вариантов: 18.03.2027." in lines[1]


def test_a_broadcast_already_on_the_channel_is_another_group() -> None:
    """Исход другой (эфир на канале есть) — другие слова, своя строка."""
    standing: BroadcastResult = result_of(
        OutcomeKind.NOT_ADMITTED, key_at(17), CHANNELS[0], reasons=(_date_missing(17),),
        broadcast_url="https://www.youtube.com/watch?v=qJjIZCbP89s",
    )
    lines: tuple[str, ...] = NotAdmittedSummary((standing, *_week())).lines
    assert len(lines) == 2
    assert lines[0] == msg.CONSOLE_ATTENTION_NOT_ADMITTED.format(text=ResultText(standing).not_admitted)
    assert lines[1].startswith("  не допущено эфиров — 42: ")


def test_a_reason_without_a_value_names_the_broadcasts() -> None:
    """Канал не подтверждён: значения нет — строка перечисляет эфиры."""
    channel_down: AdmissionReason = AdmissionReason.of_channel(ChannelStatus.NEEDS_LOGIN)
    results: tuple[BroadcastResult, ...] = tuple(_not_admitted(day, CHANNELS[0], channel_down) for day in (17, 18))
    labels: str = "; ".join(result.label.text for result in results)
    [line] = NotAdmittedSummary(results).lines
    assert line.startswith("  не допущено эфиров — 2: ")
    assert f"Эфиры: {labels}." in line
    assert msg.NOT_ADMITTED_GROUP_NEXT_CHANNEL in line


def test_the_same_attention_lines_are_one_line_with_the_count() -> None:
    assert AttentionLines(("а", "б", "а")).collapsed == ("а (×2)", "б")
