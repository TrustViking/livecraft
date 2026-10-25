"""То, что введено в разделах настроек вкладок окна (CLAUDE.md §8.2 п.6).

Черновик — поля разделов текстом (флажки — bool), их описание (`SETTINGS_FIELDS` — по порядку полей черновика) и одно
правило: перевести введённое в данные livecraft.json (`to_data`). Путь каждого поля — член `SettingKey`, перевод значения — вид поля
(`DraftField.data`). Своих проверок у черновика нет: годность настроек решает тот же загрузчик, что читает
файл. Разделы form и telegram здесь не правятся (ссылку на форму задаёт вкладка «Форма», чат —
вкладка «Telegram») и переносятся как есть; из раздела drive вкладка правит только шаблон папки превью на Диске
(ссылку на папку задают вкладки «Превью» и «Google-документ»); раздел docs — доступ к документу объявлений по ссылке (выбор
словами) и контакты для стримеров в его шапке; раздел cookies — срок напоминания о выгрузке cookies YouTube
(вкладка «Cookies YouTube», §14 решение 73).

Окно — по смотру 18-10-2026 (§14 решение 75): у малых целых чисел (запас до старта эфира, срок хранения, срок
напоминания о cookies) — стрелки (`SpinRange`): нижний предел — минимум загрузчика, верхний и шаг — здесь, ширину всех
полей со стрелками задаёт окно (`SPIN_WIDTH_CHARS`, как у срока токена); модель и
запасная модель OpenAI — выбор из моделей снимка цен не дороже поставочной основной, с ценой в подписи. Значение файла
вне списка окно показывает как есть; загрузчик по-прежнему принимает любое имя модели.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.config.cookies import REMIND_DAYS_MINIMUM
from app.config.docs import DocAccess
from app.config.files import ShippedSettings
from app.config.setting_key import SettingKey
from app.config.settings import (
    KEEP_DAYS_MINIMUM,
    MIN_LEAD_MINUTES_MINIMUM,
    LivecraftSettings,
    ReasoningEffort,
    ServiceTier,
)
from app.llm.backends.openai_model import OpenAiModel, OpenAiTariffs
from app.setup.fields.draft_field import DraftField, DraftKind, SpinRange
from app.ui.messages import msg

FIELD_WIDTH_CHARS: Final[int] = 32
# Стрелки малых чисел (§14 решение 75): верхние пределы и шаги; нижние — минимумы загрузчика.
DAY_STEP: Final[int] = 1
KEEP_DAYS_SPIN: Final[SpinRange] = SpinRange(KEEP_DAYS_MINIMUM, 365, DAY_STEP)
REMIND_DAYS_SPIN: Final[SpinRange] = SpinRange(REMIND_DAYS_MINIMUM, 60, DAY_STEP)
MIN_LEAD_MINUTES_SPIN: Final[SpinRange] = SpinRange(MIN_LEAD_MINUTES_MINIMUM, 1440, 5)
# Модели на выбор (§14 решение 75): снимок цен, не дороже поставочной основной модели; подпись — с ценой.
MODEL_TARIFFS: Final[OpenAiTariffs] = OpenAiTariffs.load()
MODEL_CHOICES: Final[tuple[str, ...]] = MODEL_TARIFFS.not_dearer_than(OpenAiModel(ShippedSettings().settings.llm.model))
MODEL_LABELS: Final[tuple[str, ...]] = tuple(
    msg.SETUP_LLM_MODEL_OPTION.format(
        model=name, input=MODEL_TARIFFS.prices[name].input_usd, output=MODEL_TARIFFS.prices[name].output_usd
    )
    for name in MODEL_CHOICES
)
SECTIONS: Final[tuple[SettingKey, ...]] = (SettingKey.LLM, SettingKey.DRIVE, SettingKey.DOCS, SettingKey.COOKIES)
DOC_ACCESS_CHOICES: Final[tuple[str, ...]] = tuple(access.value for access in DocAccess)
DOC_ACCESS_LABELS: Final[tuple[str, ...]] = tuple(msg.SETUP_DOC_ACCESS_LABELS[choice] for choice in DOC_ACCESS_CHOICES)
# Поля разделов настроек — по порядку полей черновика: раздел вкладки берёт из них свои по ключу.
SETTINGS_FIELDS: Final[tuple[DraftField, ...]] = (
    DraftField(SettingKey.MIN_LEAD_MINUTES, DraftKind.INTEGER, spin=MIN_LEAD_MINUTES_SPIN),
    DraftField(SettingKey.KEEP_DAYS, DraftKind.INTEGER, spin=KEEP_DAYS_SPIN),
    DraftField(SettingKey.AUTO_START, DraftKind.FLAG),
    DraftField(SettingKey.SET_THUMBNAIL, DraftKind.FLAG),
    DraftField(SettingKey.CATEGORY_ID, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
    DraftField(SettingKey.YOUTUBE_PAUSE_SECONDS, DraftKind.NUMBER, width=FIELD_WIDTH_CHARS),
    DraftField(SettingKey.IMAGE_DIR_TEMPLATE, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
    DraftField(SettingKey.DRIVE_PREVIEW_PATH_TEMPLATE, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
    DraftField(SettingKey.TIMEZONE, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
    DraftField(SettingKey.LLM_MODEL, DraftKind.CHOICE, choices=MODEL_CHOICES, labels=MODEL_LABELS),
    DraftField(SettingKey.LLM_FALLBACK_MODEL, DraftKind.CHOICE, choices=MODEL_CHOICES, labels=MODEL_LABELS),
    DraftField(
        SettingKey.LLM_REASONING_EFFORT, DraftKind.CHOICE, choices=tuple(effort.value for effort in ReasoningEffort)
    ),
    DraftField(SettingKey.LLM_SERVICE_TIER, DraftKind.CHOICE, choices=tuple(tier.value for tier in ServiceTier)),
    DraftField(SettingKey.LLM_TIMEOUT_SEC, DraftKind.INTEGER, width=FIELD_WIDTH_CHARS),
    DraftField(SettingKey.LLM_MAX_OUTPUT_TOKENS, DraftKind.INTEGER, width=FIELD_WIDTH_CHARS),
    DraftField(SettingKey.DOCS_ACCESS, DraftKind.CHOICE, choices=DOC_ACCESS_CHOICES, labels=DOC_ACCESS_LABELS),
    DraftField(SettingKey.DOCS_CONTACTS, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
    DraftField(SettingKey.COOKIES_REMIND_DAYS, DraftKind.INTEGER, spin=REMIND_DAYS_SPIN),
)


@dataclass(frozen=True)
class SettingsDraft:
    """Поля разделов настроек: сроки и паузы, настройки эфира, шаблоны папок превью (в image\\ и на Диске), часовой
    пояс, модель LLM, доступ к документу объявлений и контакты в его шапке, срок напоминания о cookies YouTube."""

    min_lead_minutes: str
    keep_days: str
    auto_start: bool
    set_thumbnail: bool
    category_id: str
    youtube_pause_seconds: str
    image_dir_template: str
    drive_preview_path_template: str
    timezone: str
    llm_model: str
    llm_fallback_model: str
    llm_reasoning_effort: str
    llm_service_tier: str
    llm_timeout_sec: str
    llm_max_output_tokens: str
    docs_access: str
    docs_contacts: str
    cookies_remind_days: str

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
            drive_preview_path_template=settings.drive.preview_path_template,
            timezone=settings.timezone,
            llm_model=settings.llm.model,
            llm_fallback_model=settings.llm.fallback_model,
            llm_reasoning_effort=settings.llm.reasoning_effort.value,
            llm_service_tier=settings.llm.service_tier.value,
            llm_timeout_sec=str(settings.llm.timeout_sec),
            llm_max_output_tokens=str(settings.llm.max_output_tokens),
            docs_access=settings.docs.access.value,
            docs_contacts=settings.docs.contacts,
            cookies_remind_days=str(settings.cookies.remind_days),
        )

    def to_data(self, settings: LivecraftSettings) -> dict[str, object]:
        """Данные livecraft.json: данные `settings`, в которых каждое поле черновика стоит на месте своего ключа.

        Всё, чего в разделах нет (разделы form и telegram, ссылка на папку Диска), переносится из `settings` как есть.
        """
        root: dict[str, object] = settings.to_data()
        sections: dict[str, dict[str, object]] = {
            SettingKey.LLM.value: settings.llm.to_data(),
            SettingKey.DRIVE.value: settings.drive.to_data(),
            SettingKey.DOCS.value: settings.docs.to_data(),
            SettingKey.COOKIES.value: settings.cookies.to_data(),
        }
        for field in SETTINGS_FIELDS:
            key: SettingKey = SettingKey(field.key_path)
            sections.get(key.section, root)[key.leaf] = field.data(getattr(self, field.name))
        root.update({section.leaf: sections[section.value] for section in SECTIONS})
        return root

