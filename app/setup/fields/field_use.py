"""Какие линии работы пользуются полем окна настройщика (CLAUDE.md §8.2, §14 решения 37, 51).

Поле окна активно, если работает хоть одна линия, которой оно нужно (`LinePlan.works`); иначе оно бледное и
недоступно, а под ним — строка «Нужно линиям: …». Что нужно линии, говорят её нужды (`PART_NEEDS`): форма ключей, папка
материалов на Google Диске, ключ OpenAI, таблица плана, бот Telegram и каналы — поле такой нужды нужно каждой линии,
которой нужна нужда. Остальные поля названы линиями прямо: параметры модели — нейросети; папка превью и её шаблон —
превью на диске; шаблон подпапок на Диске — превью на Google Диске; доступ к документу и контакты в нём — документу;
папка копий — копии документа; настройки эфира — эфирам. Папку пакетов пишет пакет, из неё эфиры от таблицы берут
известные слоты сверки, а при входе «Пакеты» (таблица выключена) из неё берут слоты все линии (§14 решение 51).
При входе «Пакеты» поле нужды, которую закрывают сами пакеты (форма ключей — у каждого пакета своя, таблицы нет;
`PACKAGES_MET_NEEDS`), бледное, и строка под ним говорит, откуда нужда. Часовой пояс и срок хранения старых файлов
нужны всегда.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

from app.config.setting_key import SettingKey
from app.run.line_plan import LinePlan
from app.run.mode import LINE_ORDER, PACKAGES_MET_NEEDS, Need, RunPart
from app.secretsafe.field import SecretField
from app.setup.readiness import VAULT_NEEDS
from app.ui.messages import msg

# Чем окно называет поле: ключом livecraft.json, полем сейфа или нуждой (блок из нескольких полей — каналы, бот и чат).
FieldKey: TypeAlias = SettingKey | SecretField | Need


@dataclass(frozen=True)
class FieldUse:
    """Линии, которым нужно поле (ни одной — поле нужно всегда), и нужда поля, если это поле нужды."""

    parts: frozenset[RunPart]
    need: Need | None = None

    @classmethod
    def of(cls, key: FieldKey) -> FieldUse:
        return FIELD_USES[key]

    @classmethod
    def of_parts(cls, *parts: RunPart) -> FieldUse:
        return cls(frozenset(parts))

    @classmethod
    def of_need(cls, need: Need) -> FieldUse:
        """Поле нужды: нужно каждой линии, которой нужна нужда."""
        return cls(frozenset(part for part in LINE_ORDER if need in part.needs), need)

    @property
    def lines(self) -> tuple[RunPart, ...]:
        """Линии поля в порядке «Главной»."""
        return tuple(part for part in LINE_ORDER if part in self.parts)

    def is_met_by_packages(self, plan: LinePlan) -> bool:
        """Вход «Пакеты», а нужду поля пакеты закрывают сами: форма ключей — у каждого пакета своя, таблицы нет."""
        return plan.source is RunPart.PACKAGES_IN and self.need in PACKAGES_MET_NEEDS

    def is_active(self, plan: LinePlan) -> bool:
        """Поле активно: нужду поля не закрывают пакеты, и оно нужно всегда или работает хоть одна его линия."""
        if self.is_met_by_packages(plan):
            return False
        return not self.parts or any(plan.works(part) for part in self.parts)

    def note(self, plan: LinePlan) -> str:
        """Строка под бледным полем — откуда нужда при входе «Пакеты» или каким линиям оно нужно; у активного поля
        строки нет."""
        if self.is_active(plan):
            return ""
        if self.need is not None and self.is_met_by_packages(plan):
            return msg.SETUP_FIELD_FROM_PACKAGES[self.need.value]
        return msg.SETUP_FIELD_NEEDED_BY.format(lines=msg.LIST_JOINER.join(part.human_label for part in self.lines))


ALWAYS: Final[FieldUse] = FieldUse.of_parts()
BROADCAST: Final[FieldUse] = FieldUse.of_parts(RunPart.BROADCAST)
MERGE: Final[FieldUse] = FieldUse.of_parts(RunPart.MERGE)
FIELD_USES: Final[dict[FieldKey, FieldUse]] = {
    **{need: FieldUse.of_need(need) for need in (
        Need.SHEETS_VAULT, Need.OPENAI_VAULT, Need.FORM, Need.DRIVE_FOLDER, Need.TELEGRAM, Need.CHANNELS
    )},
    **{field: FieldUse.of_need(need) for need, fields in VAULT_NEEDS.items() for field in fields},
    SettingKey.FORM_URL: FieldUse.of_need(Need.FORM),
    SettingKey.LLM_MODEL: MERGE,
    SettingKey.LLM_FALLBACK_MODEL: MERGE,
    SettingKey.LLM_REASONING_EFFORT: MERGE,
    SettingKey.LLM_SERVICE_TIER: MERGE,
    SettingKey.LLM_TIMEOUT_SEC: MERGE,
    SettingKey.LLM_MAX_OUTPUT_TOKENS: MERGE,
    SettingKey.FOLDERS_IMAGES: FieldUse.of_parts(RunPart.LOCAL_PREVIEWS),
    SettingKey.IMAGE_DIR_TEMPLATE: FieldUse.of_parts(RunPart.LOCAL_PREVIEWS),
    SettingKey.DRIVE_PREVIEW_PATH_TEMPLATE: FieldUse.of_parts(RunPart.DRIVE_PREVIEWS),
    SettingKey.DOCS_ACCESS: FieldUse.of_parts(RunPart.DOC),
    SettingKey.DOCS_CONTACTS: FieldUse.of_parts(RunPart.DOC),
    SettingKey.FOLDERS_DOCS: FieldUse.of_parts(RunPart.DOC_COPY),
    SettingKey.FOLDERS_PACKAGES: FieldUse.of_parts(RunPart.PACKAGES_IN, RunPart.PACKAGE, RunPart.BROADCAST),
    SettingKey.CATEGORY_ID: BROADCAST,
    SettingKey.AUTO_START: BROADCAST,
    SettingKey.SET_THUMBNAIL: BROADCAST,
    SettingKey.MIN_LEAD_MINUTES: BROADCAST,
    SettingKey.YOUTUBE_PAUSE_SECONDS: BROADCAST,
    SettingKey.TIMEZONE: ALWAYS,
    SettingKey.KEEP_DAYS: ALWAYS,
    SecretField.SUPPORT_BOT_TOKEN: ALWAYS,      # бот поддержки — логам, а не линии (§14 решение 58)
}
