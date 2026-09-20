"""Логи livecraft: файл logs\\{дата}_{время}_livecraft.log (DEBUG); маскирование ключей потока.

Ключ потока попадает в лог только через mask_stream_key (CLAUDE.md §6, инвариант 6): полностью он есть
только в keystreams\\keys.txt.

Терминал — только тексты для оператора (messages_ru, печатает main.py): сырой лог идёт в терминал
только с --debug. Сторонние библиотеки (корневой логгер Python: googleapiclient, google_auth_oauthlib,
openai, urllib3…) и предупреждения warnings пишутся от WARNING в тот же файл; без --debug в терминал
не попадают: у корневого логгера есть свой обработчик, поэтому logging.lastResort не срабатывает.

SecretScrubber вычёркивает известные секреты из **готовой** строки записи (§7.4) — последний рубеж на
случай чужой библиотеки: googleapiclient, openai и urllib3 пишут полные URL в DEBUG, и наш код на это
никак не влияет. Это страховка, а не разрешение писать секреты: свой код обязан писать ярлык и отпечаток
(`SecretValue.log_label`) и без фильтра. Фильтр вешается после setup_logging, когда сейф уже открыт.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

from app.core.dates import FILE_STAMP_FORMAT
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault

ROOT_LOGGER_NAME: Final[str] = "livecraft"
LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_FILE_TEMPLATE: Final[str] = "{stamp}_livecraft.log"
LOG_ENCODING: Final[str] = "utf-8"
MASK_PREFIX: Final[str] = "****-"
MASK_HIDDEN: Final[str] = "****"
MASK_EMPTY: Final[str] = "-"
MASK_VISIBLE_CHARS: Final[int] = 4
THIRD_PARTY_LEVEL: Final[int] = logging.WARNING   # сторонние логгеры — в файл от этого уровня

_THIRD_PARTY_HANDLERS: list[logging.Handler] = []   # свои обработчики на корневом логгере Python


def get_logger(name: str) -> logging.Logger:
    """Дочерний логгер livecraft: livecraft.<name> (CLAUDE.md §11)."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def setup_logging(logs_dir: Path, debug: bool) -> Path:
    """Файл — всегда DEBUG (сторонние — от WARNING); терминал — только с --debug (DEBUG в stderr)."""
    close_logging()
    formatter: logging.Formatter = logging.Formatter(LOG_FORMAT)
    stamp: str = datetime.now().astimezone().strftime(FILE_STAMP_FORMAT)
    log_path: Path = logs_dir / LOG_FILE_TEMPLATE.format(stamp=stamp)
    file_handler: logging.FileHandler = logging.FileHandler(log_path, encoding=LOG_ENCODING)
    handlers: list[logging.Handler] = [file_handler]
    if debug:
        handlers.append(logging.StreamHandler(sys.stderr))
    livecraft_logger: logging.Logger = logging.getLogger(ROOT_LOGGER_NAME)
    livecraft_logger.setLevel(logging.DEBUG)
    livecraft_logger.propagate = False
    for handler in handlers:
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        handler.addFilter(_ThirdPartyFilter())
        livecraft_logger.addHandler(handler)
    _attach_third_party(handlers)
    return log_path


def close_logging() -> None:
    """Снять и закрыть обработчики (на Windows открытый файл лога не даёт удалить папку).

    С корневого логгера Python снимаются только свои обработчики: чужие (pytest caplog) остаются.
    """
    python_root: logging.Logger = logging.getLogger()
    for handler in _THIRD_PARTY_HANDLERS:
        python_root.removeHandler(handler)
    _THIRD_PARTY_HANDLERS.clear()
    livecraft_logger: logging.Logger = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(livecraft_logger.handlers):
        livecraft_logger.removeHandler(handler)
        handler.close()
    logging.captureWarnings(False)


def mask_stream_key(value: str | None) -> str:
    """None → "-"; короче 4 символов → "****"; иначе "****-" + последние 4 символа."""
    if value is None:
        return MASK_EMPTY
    if len(value) < MASK_VISIBLE_CHARS:
        return MASK_HIDDEN
    return MASK_PREFIX + value[-MASK_VISIBLE_CHARS:]


class SecretScrubber(logging.Filter):
    """Вычёркивает известные секреты из готовой строки записи. Записей не выбрасывает — только чистит.

    Страховка, а не разрешение писать секреты (§7.4): свой код пишет ярлык и отпечаток и без фильтра.
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


class _ThirdPartyFilter(logging.Filter):
    """Записи livecraft проходят с любым уровнем, чужие — от THIRD_PARTY_LEVEL."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == ROOT_LOGGER_NAME or record.name.startswith(ROOT_LOGGER_NAME + "."):
            return True
        return record.levelno >= THIRD_PARTY_LEVEL


def install_secret_filter(vault: Vault) -> None:
    """Повесить SecretScrubber на все обработчики этого запуска; пустой сейф — вешать нечего.

    Зовётся после setup_logging, когда сейф открыт. close_logging снимает обработчики вместе с фильтром,
    поэтому после каждого нового setup_logging фильтр ставится заново.
    """
    secrets: tuple[SecretValue, ...] = vault.secrets()
    if not secrets:
        return
    scrubber: SecretScrubber = SecretScrubber(secrets)
    for handler in _own_handlers():
        handler.addFilter(scrubber)


def _own_handlers() -> list[logging.Handler]:
    """Обработчики логгера livecraft и свои обработчики на корневом логгере Python, каждый по одному разу."""
    handlers: list[logging.Handler] = list(logging.getLogger(ROOT_LOGGER_NAME).handlers)
    for handler in _THIRD_PARTY_HANDLERS:
        if not any(handler is known for known in handlers):
            handlers.append(handler)
    return handlers


def _attach_third_party(handlers: list[logging.Handler]) -> None:
    """Корневой логгер Python получает те же обработчики; warnings.warn — через логгер py.warnings."""
    python_root: logging.Logger = logging.getLogger()
    for handler in handlers:
        python_root.addHandler(handler)
        _THIRD_PARTY_HANDLERS.append(handler)
    logging.captureWarnings(True)
