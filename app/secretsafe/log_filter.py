"""Фильтр лога, который вычёркивает значения сейфа из готовой строки записи (CLAUDE.md §7.4).

Последний рубеж на случай чужой библиотеки: googleapiclient, openai и urllib3 пишут полные URL в DEBUG, и наш код
на это никак не влияет. Это страховка, а не разрешение писать секреты: свой код обязан писать ярлык и отпечаток
(`SecretValue.log_label`) и без фильтра. Фильтр строит сейф (`Vault.log_filter`), вешает лог запуска
(`RunLog.protect`) — сразу после чтения сейфа.
"""
from __future__ import annotations

import logging

from app.secretsafe.value import SecretValue


class SecretScrubber(logging.Filter):
    """Вычёркивает известные секреты из готовой строки записи. Записей не выбрасывает — только чистит.

    Чистится именно готовый текст: секрет может прийти и шаблоном (`LOGGER.info(url)`), и аргументом
    (`LOGGER.info("url=%s", url)`), а составить значение целиком можно только после подстановки.
    Что именно вычёркивать, фильтр не знает: вычёркивает сам секрет (`SecretValue.scrub`).
    """

    def __init__(self, secrets: tuple[SecretValue, ...]) -> None:
        super().__init__()
        self.secrets: tuple[SecretValue, ...] = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        self._clean(record)
        return True

    def _clean(self, record: logging.LogRecord) -> None:
        """Готовый текст — на место шаблона, аргументы больше не нужны."""
        try:
            text: str = record.getMessage()
        except (TypeError, ValueError, KeyError):
            # Шаблон и аргументы не сходятся: запись всё равно не отформатируется, а её msg и args
            # logging напечатает в stderr через handleError — поэтому чистим их по отдельности.
            self._clean_parts(record)
            return
        cleaned: str = self._scrub(text)
        if cleaned == text:
            return
        record.msg = cleaned
        record.args = ()

    def _clean_parts(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._scrub_value(item) for item in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: self._scrub_value(item) for key, item in record.args.items()}

    def _scrub_value(self, item: object) -> object:
        return self._scrub(item) if isinstance(item, str) else item

    def _scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = secret.scrub(text)
        return text
