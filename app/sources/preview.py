"""Обложка источника: скачивание и JPEG, пригодный для YouTube (CLAUDE.md §2: `media\\image_normalizer.py`).

Готовая обложка — значение шва `app\\slots\\preview.py::Preview`; здесь — как её получить: `PreviewDownloader`
скачивает, `PreviewNormalizer` делает из скачанного JPEG.

Нормализация: Pillow → RGB → JPEG quality 90. Обложку эфира ставит `thumbnails.set` (этап 4) с типом `image/jpeg`
и потолком YouTube 2 МБ, поэтому исходный формат «как есть» не сохраняется: не открылась картинка или не ужалась
до 2 МБ (quality 90, затем 80 и 70) — это проблема обложки, а не обложка.

Скачивание — `requests.get` с таймаутом 20 с плюс повторы `RetryLoop` (§11)
на 429, 5xx, обрыве связи и таймауте; 404 и прочие 4xx — отказ сразу.
"""
from __future__ import annotations

import io
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Final

import requests
from PIL import Image, UnidentifiedImageError

from app.core.retry import RETRYABLE_HTTP_STATUSES, AttemptFailure, RetryLoop, RetryPolicy, RetryRun, RetryStep
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.slots.preview import Preview
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.SOURCES_PREVIEW)

JPEG_FORMAT: Final[str] = "JPEG"
RGB_MODE: Final[str] = "RGB"
IMAGE_SIZE_TEMPLATE: Final[str] = "{width}x{height}"
JPEG_QUALITIES: Final[tuple[int, ...]] = (90, 80, 70)   # первая — основная; дальше — чтобы уложиться в MAX_BYTES
PREVIEW_TIMEOUT_SEC: Final[float] = 20.0
OK_STATUSES: Final[range] = range(200, 300)
RETRYABLE_ERRORS: Final[tuple[type[Exception], ...]] = (requests.ConnectionError, requests.Timeout)
# Pillow: не картинка, битый файл, «бомба распаковки» — всё это «не картинка» для обложки.
IMAGE_ERRORS: Final[tuple[type[Exception], ...]] = (UnidentifiedImageError, OSError, Image.DecompressionBombError)


class PreviewProblem(str, Enum):
    """Почему у источника нет пригодной обложки. Без обложки эфир ставится без своей обложки."""

    NO_URL = "no_url"              # ни yt-dlp, ни id видео не дали адреса
    NOT_FOUND = "not_found"        # 404
    REJECTED = "rejected"          # прочие 4xx и неповторяемые сбои запроса
    UNAVAILABLE = "unavailable"    # повторы кончились на 429, 5xx, обрыве или таймауте
    NOT_IMAGE = "not_image"        # Pillow не открыл скачанное
    TOO_LARGE = "too_large"        # больше MAX_BYTES и при самом низком качестве

    @classmethod
    def for_status(cls, status: int) -> PreviewProblem:
        """Причина по коду ответа: 429 и 5xx — временно недоступно, 404 — нет такой картинки, прочее — отказ."""
        if status in RETRYABLE_HTTP_STATUSES:
            return cls.UNAVAILABLE
        return cls.NOT_FOUND if status == HTTPStatus.NOT_FOUND else cls.REJECTED

    @property
    def human(self) -> str:
        return msg.PREVIEW_PROBLEMS[self.value]


class PreviewEvent(str, Enum):
    """События скачивания обложки в логе."""

    DOWNLOADED = "preview_downloaded"
    DOWNLOAD_RETRY = "preview_download_retry"
    DOWNLOAD_FAILED = "preview_download_failed"
    NOT_IMAGE = "preview_not_image"
    NORMALIZED = "preview_normalized"
    TOO_LARGE = "preview_too_large"


@dataclass(frozen=True)
class PreviewNormalizer:
    """Картинка, которую открывает Pillow → JPEG не больше `Preview.MAX_BYTES`: качество — по порядку `qualities`."""

    qualities: tuple[int, ...] = JPEG_QUALITIES

    def normalized(self, raw: bytes) -> PreviewResult:
        """Готовая обложка или проблема: не открылась картинка — NOT_IMAGE, не ужалась — TOO_LARGE."""
        try:
            with Image.open(io.BytesIO(raw)) as image:
                rgb: Image.Image = image.convert(RGB_MODE)
        except IMAGE_ERRORS as error:
            not_image: LogEvent = LogEvent.of(PreviewEvent.NOT_IMAGE, bytes=len(raw), error=type(error).__name__)
            not_image.emit(LOGGER, logging.WARNING)
            return PreviewResult.failed(PreviewProblem.NOT_IMAGE)
        size: str = IMAGE_SIZE_TEMPLATE.format(width=rgb.width, height=rgb.height)
        data: bytes = b""
        for quality in self.qualities:
            data = self._encode(rgb, quality)
            if len(data) <= Preview.MAX_BYTES:
                normalized: LogEvent = LogEvent.of(PreviewEvent.NORMALIZED, size=size, bytes=len(data), quality=quality)
                normalized.emit(LOGGER, logging.DEBUG)
                return PreviewResult.ready(Preview(data=data, width=rgb.width, height=rgb.height))
        LogEvent.of(PreviewEvent.TOO_LARGE, size=size, bytes=len(data)).emit(LOGGER, logging.WARNING)
        return PreviewResult.failed(PreviewProblem.TOO_LARGE)

    def _encode(self, image: Image.Image, quality: int) -> bytes:
        output: io.BytesIO = io.BytesIO()
        image.save(output, format=JPEG_FORMAT, quality=quality)
        return output.getvalue()


@dataclass(frozen=True)
class PreviewResult:
    """Обложка или причина, почему её нет. Ровно одно из двух полей заполнено.

    Отдельный объект, а не поле `problem` у `Preview`: тогда каждая `Preview` — годный JPEG ≤ 2 МБ без
    проверок у того, кто её ставит на YouTube, а объекта «обложка без картинки» не бывает.
    """

    preview: Preview | None
    problem: PreviewProblem | None

    @classmethod
    def ready(cls, preview: Preview) -> PreviewResult:
        return cls(preview=preview, problem=None)

    @classmethod
    def failed(cls, problem: PreviewProblem) -> PreviewResult:
        return cls(preview=None, problem=problem)

    @property
    def is_ok(self) -> bool:
        return self.preview is not None


@dataclass(frozen=True)
class PreviewDownloader:
    """Скачивание обложек. `session_get` — `requests.get` или подделка; `policy`, `rng`, `sleep` — параметрами."""

    session_get: Callable[..., requests.Response] = requests.get
    timeout_sec: float = PREVIEW_TIMEOUT_SEC
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep
    normalizer: PreviewNormalizer = field(default_factory=PreviewNormalizer)

    def preview(self, url: str) -> PreviewResult:
        """Обложка по адресу: скачать и нормализовать; нет адреса — NO_URL без обращения."""
        if not url:
            return PreviewResult.failed(PreviewProblem.NO_URL)
        downloaded: bytes | PreviewProblem = self.download(url)
        if isinstance(downloaded, PreviewProblem):
            return PreviewResult.failed(downloaded)
        return self.normalizer.normalized(downloaded)

    def download(self, url: str) -> bytes | PreviewProblem:
        """Байты по адресу; сбои 429, 5xx, обрыв и таймаут — повторами по `policy`, прочее — причиной."""
        run: RetryRun[bytes] = RetryLoop(self.policy, self.rng, self.sleep).run(
            lambda: self._attempt(url), lambda step: self._note_retry(url, step)
        )
        if run.failure is not None:
            problem: PreviewProblem = PreviewProblem(run.failure.reason)
            failed: LogEvent = LogEvent.of(PreviewEvent.DOWNLOAD_FAILED, url=url, problem=problem)
            failed.extended(**run.failure.log_fields, attempts=run.attempts).emit(LOGGER, logging.WARNING)
            return problem
        data: bytes = run.value or b""
        downloaded: LogEvent = LogEvent.of(PreviewEvent.DOWNLOADED, url=url, bytes=len(data), attempts=run.attempts)
        downloaded.emit(LOGGER, logging.DEBUG)
        return data

    def _note_retry(self, url: str, step: RetryStep) -> None:
        retry: LogEvent = LogEvent.of(PreviewEvent.DOWNLOAD_RETRY, url=url, **step.failure.log_fields)
        retry.extended(retry=step.retry, delay_sec=round(step.delay_sec, 1)).emit(LOGGER, logging.WARNING)

    def _attempt(self, url: str) -> bytes | AttemptFailure:
        try:
            response: requests.Response = self.session_get(url, timeout=self.timeout_sec)
        except requests.RequestException as error:
            is_retryable: bool = isinstance(error, RETRYABLE_ERRORS)
            problem: PreviewProblem = PreviewProblem.UNAVAILABLE if is_retryable else PreviewProblem.REJECTED
            return AttemptFailure(problem, is_retryable, error_name=type(error).__name__, cause=error)
        status: int = int(response.status_code)
        if status not in OK_STATUSES:
            problem = PreviewProblem.for_status(status)
            return AttemptFailure(problem, problem is PreviewProblem.UNAVAILABLE, status)
        return bytes(response.content)
