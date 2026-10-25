"""Лог одного запуска: файл logs\\{дата}_{время}_livecraft.log (DEBUG); маскирование ключей потока.

Ключ потока попадает в лог только через mask_stream_key (CLAUDE.md §6, инвариант 6): полностью он есть
только в keystreams\\keys.txt.

Терминал — только тексты для оператора (messages_ru, печатает app\\ui\\console.py): сырой лог идёт в терминал
только с --debug. Сторонние библиотеки (корневой логгер Python: googleapiclient, google_auth_oauthlib,
openai, urllib3…) и предупреждения warnings пишутся от WARNING в тот же файл; без --debug в терминал
не попадают: у корневого логгера есть свой обработчик, поэтому logging.lastResort не срабатывает.

`RunLog.protect` вешает на обработчики запуска фильтр, который вычёркивает секреты из готовой строки записи
(§7.4). Какой фильтр, решает сейф (`Vault.log_filter`): наблюдаемость о сейфе не знает.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from app.core.clock import Clock
from app.core.dates import FILE_STAMP_FORMAT, require_aware
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LOGGER_NAME_TEMPLATE, LogValue
from app.version import APP_NAME

LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_FILE_TEMPLATE: Final[str] = "{stamp}_livecraft.log"
MASK_PREFIX: Final[str] = "****-"
MASK_HIDDEN: Final[str] = "****"
MASK_VISIBLE_CHARS: Final[int] = 4
THIRD_PARTY_LEVEL: Final[int] = logging.WARNING   # сторонние логгеры — в файл от этого уровня
OWN_LOGGER_PREFIX: Final[str] = LOGGER_NAME_TEMPLATE.format(root=APP_NAME, area="")   # «livecraft.»


def mask_stream_key(value: str | None) -> str:
    """None → "-"; короче 4 символов → "****"; иначе "****-" + последние 4 символа."""
    if value is None:
        return LogValue.EMPTY.value
    if len(value) < MASK_VISIBLE_CHARS:
        return MASK_HIDDEN
    return MASK_PREFIX + value[-MASK_VISIBLE_CHARS:]


@dataclass(frozen=True)
class RunLog:
    """Лог одного запуска: путь файла и свои обработчики — на логгере livecraft и на корневом логгере Python.

    Обработчики одни и те же на обоих логгерах: файл — всегда DEBUG (сторонние — от WARNING), терминал (stderr) —
    только с --debug. `close` снимает и закрывает только свои обработчики: чужие (pytest caplog) остаются.
    """

    path: Path
    handlers: tuple[logging.Handler, ...]

    @classmethod
    def open(cls, log_dir: Path, debug: bool, started: datetime) -> RunLog:
        """`started` — момент начала запуска по часам программы: он даёт имя файлу, а его пояс — время каждой записи."""
        livecraft_logger: logging.Logger = logging.getLogger(APP_NAME)
        formatter: logging.Formatter = logging.Formatter(LOG_FORMAT)
        formatter.converter = Clock(require_aware(started).tzinfo).local_time
        path: Path = log_dir / LOG_FILE_TEMPLATE.format(stamp=started.strftime(FILE_STAMP_FORMAT))
        handlers: list[logging.Handler] = [logging.FileHandler(path, encoding=TEXT_ENCODING)]
        if debug:
            handlers.append(logging.StreamHandler(sys.stderr))
        livecraft_logger.setLevel(logging.DEBUG)
        livecraft_logger.propagate = False
        python_root: logging.Logger = logging.getLogger()
        for handler in handlers:
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(formatter)
            handler.addFilter(_ThirdPartyFilter())
            livecraft_logger.addHandler(handler)
            python_root.addHandler(handler)
        logging.captureWarnings(True)       # warnings.warn — через логгер py.warnings в те же обработчики
        return cls(path=path, handlers=tuple(handlers))

    def protect(self, log_filter: logging.Filter) -> None:
        """Фильтр на каждый обработчик запуска; ставится сразу после чтения сейфа, до первого обращения к сети."""
        for handler in self.handlers:
            handler.addFilter(log_filter)

    def close(self) -> None:
        """Снять свои обработчики с обоих логгеров и закрыть: открытый файл лога не даёт удалить папку (Windows)."""
        for handler in self.handlers:
            logging.getLogger(APP_NAME).removeHandler(handler)
            logging.getLogger().removeHandler(handler)
            handler.close()
        logging.captureWarnings(False)


class _ThirdPartyFilter(logging.Filter):
    """Записи livecraft проходят с любым уровнем, чужие — от THIRD_PARTY_LEVEL."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == APP_NAME or record.name.startswith(OWN_LOGGER_PREFIX):
            return True
        return record.levelno >= THIRD_PARTY_LEVEL
