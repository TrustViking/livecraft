"""Файл ключей keystreams\\keys.txt (app\\output\\keys_file.py, CLAUDE.md §6 инварианты 1a, 6): блок на стрим, ключ —
полностью и первой строкой блока, строка «форма» — что сделано в этом запуске, иначе что знает память."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.form.failure import FormFailure, FormProblem
from app.observability.log_event import LogArea
from app.output.keys_file import KeyConfirmation, KeyDelivery, KeyRow, KeysFile
from app.output.run_failure import RunFailure
from app.paths import DataDir, FileName, LivecraftPaths
from app.pipeline.orphan import MarkedBroadcast
from app.pipeline.plan import PlannedBroadcast
from app.platforms.broadcast import UpcomingBroadcast
from app.platforms.stream import StreamInfo
from app.records.record_results import RecordResults
from app.tests.fixtures.form import TRAINING_FORM_TITLE
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.output import (
    RU,
    UA,
    confirmed,
    confirmed_results,
    given_up,
    item_at,
    start_at,
    with_found_key,
    with_new_key,
)
from app.tests.fixtures.pipeline import KYIV, NOW, admitted
from app.tests.fixtures.platform import FAKE_STREAM_URL
from app.ui import messages_ru as msg

FORM_DOWN: FormFailure = FormFailure.of_status(FormProblem.TRANSPORT_FAILED, TRAINING_FORM_TITLE, 503)
SENT_AT: datetime = datetime(2027, 3, 16, 12, 0, tzinfo=KYIV)

# Образец: блок на стрим, ключ — первой строкой блока. Строка «форма» говорит об этом запуске — отправлен сейчас,
# НЕ отправлен новый ключ, — или что знает память о ключе, который уже стоял.
SAMPLE_KEYS: str = f"""# Ключи трансляций. Сгенерировано программой 16.03.2027 12:00.
# Файл перезаписывается на каждом запуске — не править.
# Строка «форма»:
#   «отправлен в форму» — форма подтвердила ключ в этом запуске;
#   «передан в форму» — форма подтвердила этот ключ раньше (память программы);
#   «НЕ отправлен» — ключ должен был уйти и не ушёл: передайте его стримеру вручную;
#   «НЕ отправлен: не допущено» — форма этот эфир не принимает (нет даты или варианта) или канал не подтверждён: эфир стоит, ключ стримеру не передан — передайте вручную;
#   «не отправлялся» — линия «Ключи в форму» выключена: передайте ключ стримеру вручную;
#   «дважды не дошёл до формы» — ключ уходил в форму дважды — первый раз и повтором — и форма его не подтвердила; сам он больше не уйдёт — передать: «все» (выбор «новые | все» в строке «Ключи в форму» на «Главной» окна настройки);
#   «нет подтверждения в памяти программы» — программа не знает, получил ли стример этот ключ.

17.03.2027 19:00  uk  Канал UA @Kanal_UA
  ключ   xxxx-xxxx-xxxx-xxxx-xxxx
  поток  {FAKE_STREAM_URL}
  эфир   https://www.youtube.com/watch?v=abc123
  форма  отправлен в форму 16.03.2027 12:00

17.03.2027 21:00  ru  Канал RU @Kanal_RU
  ключ   yyyy-yyyy-yyyy-yyyy-yyyy
  поток  {FAKE_STREAM_URL}
  эфир   https://www.youtube.com/watch?v=def456
  форма  НЕ отправлен — {FORM_DOWN.human} Передайте стримеру вручную.

18.03.2027 19:00  uk  Канал UA @Kanal_UA
  ключ   zzzz-zzzz-zzzz-zzzz-zzzz
  поток  {FAKE_STREAM_URL}
  эфир   https://www.youtube.com/watch?v=ghi789
  форма  передан в форму 12.03.2027 20:00
"""


def _sent(item: PlannedBroadcast) -> PlannedBroadcast:
    item.outcome.should_send_key, item.outcome.is_form_sent, item.outcome.form_sent_at = True, True, SENT_AT
    return item


def _failed(item: PlannedBroadcast) -> PlannedBroadcast:
    item.outcome.should_send_key, item.outcome.form_failure = True, FORM_DOWN
    return item


def _row(item: PlannedBroadcast) -> KeyRow:
    return KeyRow.of_planned(item, KYIV, to_form=True)


def _sample_rows() -> list[KeyRow]:
    sent: PlannedBroadcast = _sent(with_new_key(item_at(17), "abc123", "xxxx-xxxx-xxxx-xxxx-xxxx"))
    failed: PlannedBroadcast = _failed(with_new_key(item_at(17, 21, "ru", RU), "def456", "yyyy-yyyy-yyyy-yyyy-yyyy"))
    kept: PlannedBroadcast = confirmed(with_found_key(item_at(18), "ghi789", "zzzz-zzzz-zzzz-zzzz-zzzz"))
    return [_row(kept), _row(failed), _row(sent)]


def test_render_matches_the_sample() -> None:
    assert KeysFile(tuple(_sample_rows()), NOW).text == SAMPLE_KEYS


def test_the_row_takes_everything_from_the_object() -> None:
    """Дата, время, язык и канал — из слота и канала; ключ и ссылка — с площадки."""
    row: KeyRow = _row(with_found_key(item_at(17), "abc123", "xxxx-xxxx-xxxx-xxxx-xxxx"))
    assert (row.key, row.channel) == (item_at(17).slot.key, UA)
    assert (row.stream_key, row.stream_url, row.broadcast_url) == (
        "xxxx-xxxx-xxxx-xxxx-xxxx", FAKE_STREAM_URL, "https://www.youtube.com/watch?v=abc123"
    )


def test_an_object_without_a_key_shows_dashes() -> None:
    lines: tuple[str, ...] = _row(item_at(17)).block
    assert lines[1:4] == ("  ключ   -", "  поток  -", "  эфир   -")


def test_form_texts_speak_about_this_run_then_the_memory() -> None:
    new: PlannedBroadcast = with_new_key(item_at(17), "abc123", "xxxx-xxxx-xxxx-xxxx-xxxx")
    new.outcome.should_send_key = True
    assert KeyDelivery(new, KYIV).text == f"НЕ отправлен — {msg.FORM_FAILURE_UNKNOWN} Передайте стримеру вручную."
    new.outcome.form_failure = FormFailure.of_status(FormProblem.NOT_CONFIRMED, TRAINING_FORM_TITLE, 200)
    assert KeyDelivery(new, KYIV).text == (
        f"НЕ отправлен — Форма ключей «{TRAINING_FORM_TITLE}» не подтвердила запись ответа (код ответа 200). "
        "Передайте стримеру вручную."
    )
    _sent(new)
    assert KeyDelivery(new, KYIV).text == "отправлен в форму 16.03.2027 12:00"
    found: PlannedBroadcast = with_found_key(item_at(17), "abc123", "xxxx-xxxx-xxxx-xxxx-xxxx")
    assert KeyDelivery(found, KYIV).text == "нет подтверждения в памяти программы"
    assert KeyDelivery(confirmed(found), KYIV).text == "передан в форму 12.03.2027 20:00"
    assert KeyDelivery(given_up(found), KYIV).text == (
        "дважды не дошёл до формы — передать: «все» (выбор «новые | все» в строке «Ключи в форму» на «Главной» окна "
        "настройки)"
    )
    other: PlannedBroadcast = confirmed(with_found_key(item_at(17), "abc123", "wwww-wwww-wwww-wwww-wwww"))
    with_found_key(other, "abc123", "xxxx-xxxx-xxxx-xxxx-xxxx")     # подтверждение было про другой ключ
    assert KeyDelivery(other, KYIV).text == "нет подтверждения в памяти программы"


def test_with_the_keys_line_off_the_form_line_names_it() -> None:
    """Линия «Ключи в форму» выключена (§14 решение 37): ключ в форму не уходил — так и сказано, с названием линии;
    памяти подтверждений строка не спрашивает."""
    found: PlannedBroadcast = confirmed(with_found_key(item_at(17), "abc123", "xxxx-xxxx-xxxx-xxxx-xxxx"))
    assert KeyDelivery(found, KYIV, to_form=False).text == "не отправлялся: линия «Ключи в форму» выключена"
    row: KeyRow = KeyRow.of_planned(found, KYIV, to_form=False)
    assert row.block[-1] == "  форма  не отправлялся: линия «Ключи в форму» выключена"


def test_the_status_row_reads_the_confirmation_from_memory() -> None:
    item: PlannedBroadcast = item_at(17)
    marked: MarkedBroadcast = MarkedBroadcast(
        channel=UA,
        broadcast=UpcomingBroadcast("abc123", start_at(17), "Эфир", "", "s1"),
        stream=StreamInfo("s1", item.slot.slot_id, FAKE_STREAM_URL, "xxxx-xxxx-xxxx-xxxx-xxxx"),
        key=item.slot.key,
    )
    row: KeyRow = KeyRow.of_marked(marked, RecordResults(), KYIV)
    assert (row.form_text, row.stream_key, row.broadcast_url) == (
        "нет подтверждения в памяти программы", "xxxx-xxxx-xxxx-xxxx-xxxx", "https://www.youtube.com/watch?v=abc123"
    )
    remembered: RecordResults = confirmed_results("xxxx-xxxx-xxxx-xxxx-xxxx")
    assert KeyRow.of_marked(marked, remembered, KYIV).form_text == "передан в форму 12.03.2027 20:00"


def test_a_confirmation_without_a_moment_shows_a_dash() -> None:
    results: RecordResults = RecordResults(confirmed_stream_key="xxxx-xxxx-xxxx-xxxx-xxxx")
    assert KeyConfirmation(results, "xxxx-xxxx-xxxx-xxxx-xxxx", KYIV).text == "передан в форму -"


def test_an_empty_file_has_only_comment_lines(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    with LogCapture.on(LogArea.OUTPUT) as capture:
        path: Path | RunFailure = KeysFile((), NOW).write(paths)
    assert path == paths.file(FileName.KEYS) == tmp_path / "keystreams" / "keys.txt"
    lines: list[str] = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(msg.KEYS_FILE_HEADER) and all(line.startswith("# ") for line in lines)
    assert capture.messages() == [f"keys_written path={Path('keystreams') / 'keys.txt'} rows=0"]


def test_the_full_key_is_written_only_to_the_file(tmp_path: Path) -> None:
    """Ключ потока полностью — только в keys.txt (инвариант 6)."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    path: Path | RunFailure = KeysFile(tuple(_sample_rows()), NOW).write(paths)
    assert isinstance(path, Path)
    text: str = path.read_text(encoding="utf-8")
    assert "  ключ   xxxx-xxxx-xxxx-xxxx-xxxx" in text and "****" not in text


def test_a_file_that_cannot_be_written_is_a_failure_of_the_run(tmp_path: Path) -> None:
    paths: LivecraftPaths = LivecraftPaths(tmp_path)
    paths.dir(DataDir.KEYSTREAMS).write_text("не папка", encoding="utf-8")
    with LogCapture.on(LogArea.OUTPUT) as capture:
        written: Path | RunFailure = KeysFile(tuple(_sample_rows()), NOW).write(paths)
    assert isinstance(written, RunFailure)
    assert written.subject == str(Path("keystreams") / "keys.txt")
    assert written.human.startswith("файл ключей не записан: ")
    [line] = capture.messages()
    assert line.startswith(f"keys_write_failed path={Path('keystreams') / 'keys.txt'} error=")
    assert "xxxx-xxxx" not in line


def test_the_key_is_the_first_line_of_each_block() -> None:
    """Ключ — ради него файл и открывают — стоит первым в блоке, а не в конце длинной строки."""
    row: KeyRow = _row(with_found_key(item_at(17), "abc123", "xxxx-xxxx-xxxx-xxxx-xxxx"))
    lines: list[str] = KeysFile((row,), NOW).text.splitlines()
    header: int = len(msg.KEYS_FILE_HEADER)
    assert lines[header] == ""
    assert lines[header + 1] == "17.03.2027 19:00  uk  Канал UA @Kanal_UA"
    assert lines[header + 2] == "  ключ   xxxx-xxxx-xxxx-xxxx-xxxx"
    assert all(len(line) <= 80 for line in lines[header + 1:])


def test_rows_follow_the_order_of_slots() -> None:
    rows: list[KeyRow] = [
        _row(with_found_key(item_at(day, hour, language, channel), f"b{day}{hour}", "kkkk-kkkk-kkkk-kkkk-kkkk"))
        for day, hour, language, channel in ((18, 19, "uk", UA), (17, 19, "ru", RU), (17, 19, "uk", UA))
    ]
    titles: list[str] = [line for line in KeysFile(tuple(rows), NOW).text.splitlines() if line.startswith("1")]
    assert titles == [
        "17.03.2027 19:00  uk  Канал UA @Kanal_UA",
        "17.03.2027 19:00  ru  Канал RU @Kanal_RU",
        "18.03.2027 19:00  uk  Канал UA @Kanal_UA",
    ]


def test_a_not_admitted_key_says_why_it_was_not_sent(tmp_path: Path) -> None:
    item: PlannedBroadcast = with_found_key(admitted(item_at(18, 20, "en", UA), tmp_path), "qJjIZCbP89s", "wwww-wwww")
    assert KeyDelivery(item, KYIV).text == (
        f"НЕ отправлен: не допущено — В форме «{TRAINING_FORM_TITLE}» в вопросе «Время стрима ( Stream time )» "
        "нет варианта «18.03.2027»."
    )
    assert (_row(item).stream_key, _row(item).broadcast_url) == ("wwww-wwww", "https://www.youtube.com/watch?v=qJjIZCbP89s")


def test_the_header_quotes_the_real_form_lines(tmp_path: Path) -> None:
    """Тексты в кавычках шапки — ровно начала строк «форма», которые пишет файл, во всех семи состояниях."""
    keys_off: PlannedBroadcast = with_found_key(item_at(18, 21), "pqr901", "tttt-tttt-tttt-tttt-tttt")
    items: list[PlannedBroadcast] = [
        _sent(with_new_key(item_at(17), "abc123", "xxxx-xxxx-xxxx-xxxx-xxxx")),
        confirmed(with_found_key(item_at(17, 21), "ghi789", "zzzz-zzzz-zzzz-zzzz-zzzz")),
        _failed(with_new_key(item_at(17, 21, "ru", RU), "def456", "yyyy-yyyy-yyyy-yyyy-yyyy")),
        with_found_key(admitted(item_at(18, 20, "en", UA), tmp_path), "jkl012", "wwww-wwww-wwww-wwww-wwww"),
        given_up(with_found_key(item_at(17, 22), "jkl345", "vvvv-vvvv-vvvv-vvvv-vvvv")),
        with_found_key(item_at(17, 23), "mno678", "uuuu-uuuu-uuuu-uuuu-uuuu"),
    ]
    rows: tuple[KeyRow, ...] = (*(_row(item) for item in items), KeyRow.of_planned(keys_off, KYIV, to_form=False))
    lines: list[str] = KeysFile(rows, NOW).text.splitlines()
    quoted: list[str] = [line.split("«")[1].split("»")[0] for line in lines[: len(msg.KEYS_FILE_HEADER)][3:]]
    form_values: list[str] = [line.removeprefix("  форма  ") for line in lines if line.startswith("  форма  ")]
    assert len(quoted) == len(form_values) == 7
    # каждой строке «форма» — ровно одна цитата шапки (самая длинная подходящая) и наоборот
    matched: list[str] = [max((lead for lead in quoted if value.startswith(lead)), key=len) for value in form_values]
    assert sorted(matched) == sorted(quoted)
