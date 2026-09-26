"""То, что введено на вкладке «Настройки запуска» (CLAUDE.md §8.2 п.3).

Черновик — поля вкладки текстом (флажки — bool), их описание (`FIELDS`) и одно правило: перевести введённое в
данные livecraft.json (`to_data`). Путь каждого поля — член `SettingKey`, перевод значения — вид поля
(`DraftField.data`). Своих проверок у черновика нет: годность настроек решает тот же загрузчик, что читает
файл. Из раздела form на вкладке правится только ссылка на форму (`form_url`, открытая настройка — §14
решение 15); контракт формы (вопросы, варианты, формат даты) переносится как есть.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from app.config.settings import LivecraftSettings, ReasoningEffort, ServiceTier, SettingKey
from app.setup.fields.draft_field import DraftField, DraftKind

FIELD_WIDTH_CHARS: Final[int] = 32
URL_WIDTH_CHARS: Final[int] = 64       # ссылка на форму длинная: в узком поле её не проверить глазами
SECTIONS: Final[tuple[SettingKey, ...]] = (SettingKey.LLM, SettingKey.FORM)


@dataclass(frozen=True)
class SettingsDraft:
    """Поля вкладки: ссылка на форму ключей, сроки и паузы, настройки эфира, шаблон превью, часовой пояс,
    модель LLM."""

    FIELDS: ClassVar[tuple[DraftField, ...]] = (
        DraftField(SettingKey.FORM_URL, DraftKind.TEXT, width=URL_WIDTH_CHARS),
        DraftField(SettingKey.MIN_LEAD_MINUTES, DraftKind.INTEGER, width=FIELD_WIDTH_CHARS),
        DraftField(SettingKey.KEEP_DAYS, DraftKind.INTEGER, width=FIELD_WIDTH_CHARS),
        DraftField(SettingKey.AUTO_START, DraftKind.FLAG),
        DraftField(SettingKey.SET_THUMBNAIL, DraftKind.FLAG),
        DraftField(SettingKey.CATEGORY_ID, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
        DraftField(SettingKey.YOUTUBE_PAUSE_SECONDS, DraftKind.NUMBER, width=FIELD_WIDTH_CHARS),
        DraftField(SettingKey.IMAGE_DIR_TEMPLATE, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
        DraftField(SettingKey.TIMEZONE, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
        DraftField(SettingKey.LLM_MODEL, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
        DraftField(SettingKey.LLM_FALLBACK_MODEL, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
        DraftField(
            SettingKey.LLM_REASONING_EFFORT, DraftKind.CHOICE, choices=tuple(effort.value for effort in ReasoningEffort)
        ),
        DraftField(SettingKey.LLM_SERVICE_TIER, DraftKind.CHOICE, choices=tuple(tier.value for tier in ServiceTier)),
        DraftField(SettingKey.LLM_TIMEOUT_SEC, DraftKind.INTEGER, width=FIELD_WIDTH_CHARS),
        DraftField(SettingKey.LLM_MAX_OUTPUT_TOKENS, DraftKind.INTEGER, width=FIELD_WIDTH_CHARS),
    )

    form_url: str
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
            form_url=settings.form.url,
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

    def to_data(self, settings: LivecraftSettings) -> dict[str, object]:
        """Данные livecraft.json: данные `settings`, в которых каждое поле черновика стоит на месте своего ключа.

        Всё, чего на вкладке нет (контракт формы), переносится из `settings` как есть.
        """
        root: dict[str, object] = settings.to_data()
        sections: dict[str, dict[str, object]] = {
            SettingKey.LLM.value: settings.llm.to_data(),
            SettingKey.FORM.value: settings.form.to_data(),
        }
        for field in self.FIELDS:
            key: SettingKey = SettingKey(field.key_path)
            sections.get(key.section, root)[key.leaf] = field.data(getattr(self, field.name))
        root.update({section.leaf: sections[section.value] for section in SECTIONS})
        return root
