"""Повторная передача ключей после полного запуска (CLAUDE.md §6 инвариант 1a, §14 решение 36).

Переключатель `broadcasts.resend_keys` включает человек, когда у стримера пропали строки с ключами: в этом запуске
ключ каждого допущенного эфира уходит в форму, даже если память хранит его подтверждение. Дальше программа решает
сама: все ключи, которые должны были уйти, форма подтвердила, — переключатель выключается (иначе каждый следующий
запуск задваивал бы все строки у стримера); не дошёл хоть один — остаётся включённым, и следующий запуск передаст
заново. Запись — поверх свежего файла настроек (`SettingsFile.save_broadcasts`); файл не записался — строка с
причиной и что сделать, ошибка части. Только полный запуск: --dry-run ничего не отправляет, --status ключей не шлёт.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.config.broadcasts import BroadcastSettings
from app.config.files import SettingsFile
from app.core.errors import os_error_reason
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.output.report import ReportKind, RunReport
from app.output.result import KeyState
from app.ui.messages import msg

LOGGER = get_logger(LogArea.BROADCASTS)


class KeyResendEvent(str, Enum):
    """События повторной передачи ключей в логе."""

    RESEND = "keys_resend"


@dataclass(frozen=True)
class KeysResent:
    """Итог повторной передачи: ключей подтверждено, не дошло, выключен ли переключатель и почему файл не записался
    (None — записался или писать было нечего)."""

    sent: int
    undelivered: int
    switched_off: bool = False
    write_failure: str | None = None

    @property
    def has_errors(self) -> bool:
        """Переключатель должен был выключиться, а файл не записался — ошибка части (код 1)."""
        return self.write_failure is not None

    @property
    def line(self) -> str:
        if self.write_failure is not None:
            return msg.KEYS_RESEND_WRITE_FAILED.format(sent=self.sent, reason=self.write_failure)
        if self.undelivered:
            return msg.KEYS_RESEND_KEPT.format(sent=self.sent, undelivered=self.undelivered)
        return msg.KEYS_RESEND_SWITCHED_OFF.format(sent=self.sent)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(
            KeyResendEvent.RESEND, sent=self.sent, undelivered=self.undelivered, switched_off=self.switched_off
        )


@dataclass(frozen=True)
class KeyResend:
    """Файл настроек и раздел broadcasts, с которым шёл запуск."""

    file: SettingsFile
    settings: BroadcastSettings

    def after(self, report: RunReport) -> KeysResent | None:
        """После части «эфиры»: полный запуск с включённой повторной передачей, где хоть один ключ должен был уйти, —
        выключить её, если дошли все; иначе — None, файл не трогается."""
        if report.kind is not ReportKind.FULL or not self.settings.resend_keys:
            return None
        sent: int = sum(1 for result in report.results if result.key_state is KeyState.SENT)
        undelivered: int = report.totals.undelivered
        if sent + undelivered == 0:
            return None
        resent: KeysResent = KeysResent(sent=sent, undelivered=undelivered)
        if not undelivered:
            resent = self._switch_off(resent)
        resent.event.emit(LOGGER)
        return resent

    def _switch_off(self, resent: KeysResent) -> KeysResent:
        try:
            self.file.save_broadcasts(self.file.latest.broadcasts.with_resend(False))
        except OSError as error:
            return KeysResent(sent=resent.sent, undelivered=0, write_failure=os_error_reason(error))
        return KeysResent(sent=resent.sent, undelivered=0, switched_off=True)
