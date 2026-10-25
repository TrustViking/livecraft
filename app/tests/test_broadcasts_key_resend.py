"""Повторная передача ключей (app\\broadcasts\\key_resend.py, §6 инвариант 1a, §14 решение 36) — прогоном части «эфиры»
на подделках площадки и формы: ключ, подтверждение которого память хранит, уходит снова только при включённом
переключателе; после полной передачи переключатель выключается сам."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.broadcasts.stage import BroadcastPartResult
from app.config.broadcasts import BroadcastSettings
from app.config.files import SettingsFile
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea
from app.output.result import KeyState
from app.paths import LivecraftPaths
from app.run.exit_code import RunOutcome
from app.slots.slot import StreamSlot
from app.tests.fixtures.broadcasts import FORM_REFUSED, BroadcastBench, report_of, sent_values
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.pipeline import PREVIEW, TEXTS, TOMORROW, slot_of, with_changes
from app.ui import messages_ru as msg

UK: StreamSlot = slot_of(TOMORROW, "uk", TEXTS, (PREVIEW,))
FIRST_KEY: str = "fake-0001-0000-0000-0000"


@pytest.fixture
def bench(livecraft_paths: LivecraftPaths) -> BroadcastBench:
    """Два канала с токенами; livecraft.json на диске — с настройками стенда."""
    bench: BroadcastBench = BroadcastBench.with_tokens(livecraft_paths)
    SettingsFile.of(livecraft_paths).save(bench.settings)
    return bench


def _resend(bench: BroadcastBench, resend_keys: bool) -> None:
    """Переключатель повторной передачи — в настройках запуска и в файле, как его оставило окно."""
    bench.settings = with_changes(bench.settings, broadcasts=BroadcastSettings(resend_keys))
    SettingsFile.of(bench.paths).save(bench.settings)


def _file_resend(bench: BroadcastBench) -> bool:
    data: Any = json.loads(SettingsFile.of(bench.paths).path.read_text(encoding=TEXT_ENCODING))
    return bool(data["broadcasts"]["resend_keys"])


def _key_state(result: BroadcastPartResult) -> KeyState | None:
    [item] = report_of(result).results
    return item.key_state


def _confirmed_once(bench: BroadcastBench) -> None:
    """Прошлый запуск: эфир создан, форма подтвердила ключ — память хранит тройку."""
    assert bench.run(UK).outcome is RunOutcome.DONE and len(bench.posts) == 1


def test_a_confirmed_key_does_not_go_again_without_resend(bench: BroadcastBench) -> None:
    _confirmed_once(bench)
    result: BroadcastPartResult = bench.run(UK)
    assert len(bench.posts) == 1 and _key_state(result) is None
    assert result.resend is None


def test_a_confirmed_key_goes_again_with_resend_and_the_switch_turns_off(bench: BroadcastBench) -> None:
    _confirmed_once(bench)
    _resend(bench, True)
    with LogCapture.on(LogArea.BROADCASTS) as log:
        result: BroadcastPartResult = bench.run(UK)
    assert len(bench.posts) == 2 and FIRST_KEY in sent_values(bench.posts[1])
    assert _key_state(result) is KeyState.SENT and result.outcome is RunOutcome.DONE
    assert not _file_resend(bench)
    line: str = msg.KEYS_RESEND_SWITCHED_OFF.format(sent=1)
    assert result.resend is not None and result.resend.line == line and result.console_lines[-1] == line
    assert "keys_resend sent=1 undelivered=0 switched_off=yes" in log.messages()


def test_the_switch_off_keeps_the_rest_of_the_file(bench: BroadcastBench) -> None:
    """Выключение пишет только раздел broadcasts, поверх файла, как он на диске."""
    _resend(bench, True)
    file: SettingsFile = SettingsFile.of(bench.paths)
    file.save(with_changes(file.load(), keep_days=12))
    bench.run(UK)
    assert file.load().keep_days == 12 and not file.load().broadcasts.resend_keys


def test_an_undelivered_key_keeps_the_switch_on(bench: BroadcastBench) -> None:
    _resend(bench, True)
    bench.post_replies = (FORM_REFUSED,)
    with LogCapture.on(LogArea.BROADCASTS) as log:
        result: BroadcastPartResult = bench.run(UK)
    assert _key_state(result) is KeyState.FAILED and result.outcome is RunOutcome.FAILED
    assert _file_resend(bench)
    line: str = msg.KEYS_RESEND_KEPT.format(sent=0, undelivered=1)
    assert result.resend is not None and result.resend.line == line and line in result.console_lines
    assert "keys_resend sent=0 undelivered=1 switched_off=no" in log.messages()


def test_a_settings_file_that_does_not_take_the_write_is_code_1(bench: BroadcastBench) -> None:
    """Все ключи дошли, а файл настроек не записался: строка с причиной и что сделать, код 1 части."""
    _resend(bench, True)
    path: Path = SettingsFile.of(bench.paths).path
    path.unlink()
    path.mkdir()                      # на месте файла — папка: запись не проходит
    result: BroadcastPartResult = bench.run(UK)
    assert _key_state(result) is KeyState.SENT and report_of(result).exit.outcome is RunOutcome.DONE
    assert result.resend is not None and result.resend.write_failure is not None
    assert result.outcome is RunOutcome.FAILED
    assert result.resend.line == msg.KEYS_RESEND_WRITE_FAILED.format(sent=1, reason=result.resend.write_failure)
    assert result.resend.line in result.console_lines


def test_a_dry_run_with_resend_plans_the_key_and_touches_nothing(bench: BroadcastBench) -> None:
    """--dry-run: «отправим ключ» по правилу с повторной передачей, в форму ничего, файл настроек тот же."""
    _confirmed_once(bench)
    _resend(bench, True)
    before: bytes = SettingsFile.of(bench.paths).path.read_bytes()
    result: BroadcastPartResult = bench.run(UK, dry_run=True)
    assert _key_state(result) is KeyState.PLANNED and len(bench.posts) == 1
    assert result.resend is None and SettingsFile.of(bench.paths).path.read_bytes() == before


def test_status_with_resend_touches_nothing(bench: BroadcastBench) -> None:
    _confirmed_once(bench)
    _resend(bench, True)
    result: BroadcastPartResult = bench.status()
    assert result.resend is None and _file_resend(bench) and len(bench.posts) == 1
