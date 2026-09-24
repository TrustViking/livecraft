"""Обложка источника: скачивание и JPEG, пригодный для YouTube (CLAUDE.md §2: `media\\image_normalizer.py`).

Нормализация — правило донора `normalize_thumbnail` (restreamer): Pillow → RGB → JPEG quality 90. Обложку
эфира ставит `thumbnails.set` (этап 4) с типом `image/jpeg` и потолком YouTube 2 МБ, поэтому, в отличие
от донора, исходный формат «как есть» не сохраняется: не открылась картинка или не ужалась до 2 МБ
(quality 90, затем 80 и 70) — это проблема обложки, а не обложка.

Скачивание — донор `HttpClient.get_bytes` (`requests.get`, таймаут 20 с) плюс повторы по `RetryPolicy` (§11)
на 429, 5xx, обрыве связи и таймауте; 404 и прочие 4xx — отказ сразу.
"""
from __future__ import annotations

import io
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

import requests
from PIL import Image, UnidentifiedImageError

from app.core.retry import RetryPolicy
from app.observability.logging_setup import get_logger
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "sources.preview"
LOGGER = get_logger(LOGGER_NAME)

MIME_TYPE: Final[str] = "image/jpeg"
JPEG_FORMAT: Final[str] = "JPEG"
RGB_MODE: Final[str] = "RGB"
JPEG_QUALITIES: Final[tuple[int, ...]] = (90, 80, 70)   # первая — донора; дальше — чтобы уложиться в MAX_BYTES
PREVIEW_TIMEOUT_SEC: Final[float] = 20.0
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
NOT_FOUND_STATUS: Final[int] = 404
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

    @property
    def human(self) -> str:
        return msg.PREVIEW_PROBLEMS[self.value]


@dataclass(frozen=True)
class Preview:
    """Готовая обложка: JPEG не больше MAX_BYTES и её размеры в пикселях."""

    MAX_BYTES: ClassVar[int] = 2 * 1024 * 1024      # потолок YouTube для thumbnails.set

    data: bytes
    width: int
    height: int

    @property
    def mime_type(self) -> str:
        return MIME_TYPE

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @classmethod
    def from_image_bytes(cls, raw: bytes) -> PreviewResult:
        """Любая картинка, которую открывает Pillow → JPEG ≤ MAX_BYTES; иначе — проблема."""
        try:
            with Image.open(io.BytesIO(raw)) as image:
                rgb: Image.Image = image.convert(RGB_MODE)
        except IMAGE_ERRORS as error:
            LOGGER.warning("preview_not_image bytes=%d error=%s", len(raw), type(error).__name__)
            return PreviewResult.failed(PreviewProblem.NOT_IMAGE)
        for quality in JPEG_QUALITIES:
            data: bytes = cls._encode(rgb, quality)
            if len(data) <= cls.MAX_BYTES:
                LOGGER.debug("preview_normalized size=%dx%d bytes=%d quality=%d", *rgb.size, len(data), quality)
                return PreviewResult.ready(cls(data=data, width=rgb.width, height=rgb.height))
        LOGGER.warning("preview_too_large size=%dx%d bytes=%d", *rgb.size, len(data))
        return PreviewResult.failed(PreviewProblem.TOO_LARGE)

    @staticmethod
    def _encode(image: Image.Image, quality: int) -> bytes:
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
class PreviewFailure:
    """Одно неудачное скачивание: причина, код ответа, повторять ли, имя исключения для лога."""

    problem: PreviewProblem
    status: int | None
    is_retryable: bool
    error: str = "-"

    @classmethod
    def from_status(cls, status: int) -> PreviewFailure:
        if status in RETRYABLE_STATUSES:
            return cls(problem=PreviewProblem.UNAVAILABLE, status=status, is_retryable=True)
        if status == NOT_FOUND_STATUS:
            return cls(problem=PreviewProblem.NOT_FOUND, status=status, is_retryable=False)
        return cls(problem=PreviewProblem.REJECTED, status=status, is_retryable=False)

    @classmethod
    def from_error(cls, error: requests.RequestException) -> PreviewFailure:
        is_retryable: bool = isinstance(error, RETRYABLE_ERRORS)
        problem: PreviewProblem = PreviewProblem.UNAVAILABLE if is_retryable else PreviewProblem.REJECTED
        return cls(problem=problem, status=None, is_retryable=is_retryable, error=type(error).__name__)

    @property
    def log_line(self) -> str:
        status: str = str(self.status) if self.status is not None else "-"
        return f"status={status} error={self.error}"


@dataclass(frozen=True)
class PreviewDownloader:
    """Скачивание обложек. `session_get` — `requests.get` или подделка; `policy`, `rng`, `sleep` — параметрами."""

    session_get: Callable[..., Any] = requests.get
    timeout_sec: float = PREVIEW_TIMEOUT_SEC
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep

    def preview(self, url: str) -> PreviewResult:
        """Обложка по адресу: скачать и нормализовать; нет адреса — NO_URL без обращения."""
        if not url:
            return PreviewResult.failed(PreviewProblem.NO_URL)
        downloaded: bytes | PreviewProblem = self.download(url)
        if isinstance(downloaded, PreviewProblem):
            return PreviewResult.failed(downloaded)
        return Preview.from_image_bytes(downloaded)

    def download(self, url: str) -> bytes | PreviewProblem:
        """Байты по адресу; сбои 429, 5xx, обрыв и таймаут — повторами по `policy`, прочее — причиной."""
        retry_number: int = 0
        while True:
            outcome: bytes | PreviewFailure = self._attempt(url)
            if not isinstance(outcome, PreviewFailure):
                LOGGER.debug("preview_downloaded url=%s bytes=%d attempts=%d", url, len(outcome), retry_number + 1)
                return outcome
            retry_number += 1
            if not outcome.is_retryable or not self.policy.has_retry_left(retry_number):
                LOGGER.warning(
                    "preview_download_failed url=%s problem=%s %s attempts=%d",
                    url, outcome.problem.value, outcome.log_line, retry_number,
                )
                return outcome.problem
            delay: float = self.policy.delay_sec(retry_number, self.rng)
            LOGGER.warning(
                "preview_download_retry url=%s %s retry=%d delay_sec=%.1f", url, outcome.log_line, retry_number, delay
            )
            self.sleep(delay)

    def _attempt(self, url: str) -> bytes | PreviewFailure:
        try:
            response: Any = self.session_get(url, timeout=self.timeout_sec)
        except requests.RequestException as error:
            return PreviewFailure.from_error(error)
        status: int = int(response.status_code)
        if status not in OK_STATUSES:
            return PreviewFailure.from_status(status)
        return bytes(response.content)
