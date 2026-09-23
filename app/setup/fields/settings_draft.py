"""То, что введено на вкладке «Настройки запуска» (CLAUDE.md §8.2 п.3).

Черновик — поля вкладки текстом (флажки — bool) и одно правило: перевести введённое в данные livecraft.json
(`to_data`). Своих проверок у черновика нет: годность настроек решает тот же загрузчик, что читает файл
(§16, решения к задаче 2.2). Не переводится в число — уходит текстом, и ошибку с именем поля назовёт загрузчик.
Контракт формы на вкладке не правится: раздел form переносится как есть.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

from app.config.loader import FORM_KEY, LLM_KEY, FormSettings, LivecraftSettings

# Дробная часть паузы в окне пишется как удобно человеку: «0,5» и «0.5» — одно число.
DECIMAL_COMMA: Final[str] = ","
DECIMAL_POINT: Final[str] = "."


@dataclass(frozen=True)
class SettingsDraft:
    """Поля вкладки 3: сроки и паузы, настройки эфира, шаблон превью, часовой пояс, модель LLM."""

    min_lead_minutes: str
    keep_days: str
    auto_start: bool
    set_thumbnail: bool
    category_id: str
    youtube_pause_seconds: str
    image_dir_template: str
    timezone: str
    llm_model: str
    llm_fallback_model: str
    llm_reasoning_effort: str
    llm_service_tier: str
    llm_timeout_sec: str
    llm_max_output_tokens: str

    @classmethod
    def of(cls, settings: LivecraftSettings) -> SettingsDraft:
        """Черновик годных настроек — то, что окно показывает в полях."""
        return cls(
            min_lead_minutes=str(settings.min_lead_minutes),
            keep_days=str(settings.keep_days),
            auto_start=settings.auto_start,
            set_thumbnail=settings.set_thumbnail,
            category_id=settings.category_id,
            youtube_pause_seconds=str(settings.youtube_pause_seconds),
            image_dir_template=settings.image_dir_template,
            timezone=settings.timezone,
            llm_model=settings.llm.model,
            llm_fallback_model=settings.llm.fallback_model,
            llm_reasoning_effort=settings.llm.reasoning_effort.value,
            llm_service_tier=settings.llm.service_tier.value,
            llm_timeout_sec=str(settings.llm.timeout_sec),
            llm_max_output_tokens=str(settings.llm.max_output_tokens),
        )

    def to_data(self, form: FormSettings) -> dict[str, Any]:
        """Данные livecraft.json из введённого; form — контракт формы, переносится без изменений."""
        return {
            "min_lead_minutes": self._integer(self.min_lead_minutes),
            "keep_days": self._integer(self.keep_days),
            "auto_start": self.auto_start,
            "set_thumbnail": self.set_thumbnail,
            "category_id": self.category_id.strip(),
            "youtube_pause_seconds": self._pause_seconds,
            "image_dir_template": self.image_dir_template.strip(),
            "timezone": self.timezone.strip(),
            LLM_KEY: {
                "model": self.llm_model.strip(),
                "fallback_model": self.llm_fallback_model.strip(),
                "reasoning_effort": self.llm_reasoning_effort.strip(),
                "service_tier": self.llm_service_tier.strip(),
                "timeout_sec": self._integer(self.llm_timeout_sec),
                "max_output_tokens": self._integer(self.llm_max_output_tokens),
            },
            FORM_KEY: form.to_data(),
        }

    @property
    def _pause_seconds(self) -> float | str:
        """Пауза — конечное число, запятая допустима; nan, inf и не число уходят текстом — на ошибку загрузчика."""
        try:
            value: float = float(self.youtube_pause_seconds.strip().replace(DECIMAL_COMMA, DECIMAL_POINT))
        except ValueError:
            return self.youtube_pause_seconds
        if not math.isfinite(value):
            return self.youtube_pause_seconds
        return value

    @staticmethod
    def _integer(text: str) -> int | str:
        """Целое из текста поля; не вышло — текст как есть, на ошибку загрузчика."""
        try:
            return int(text.strip())
        except ValueError:
            return text
