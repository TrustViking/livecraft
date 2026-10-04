"""Ключи `secrets\\livecraft.json` (CLAUDE.md §5).

Ключ файла — член `SettingKey`, значение члена — путь ключа от корня файла (`llm.model`): из них выводятся и состав
каждого раздела, и данные файла (`to_data` разделов), поэтому ключ описан ровно в одном месте. Разделы файла живут
своими модулями (`settings.py`, `telegram.py`, `drive.py`, `docs.py`, `broadcasts.py`, `lines.py`, `folders.py`) и
берут ключи отсюда.
"""
from __future__ import annotations

from enum import Enum

from app.config.json_node import KEY_SEPARATOR


class SettingKey(str, Enum):
    """Ключи livecraft.json в порядке файла; значение — путь ключа от корня файла."""

    MIN_LEAD_MINUTES = "min_lead_minutes"
    KEEP_DAYS = "keep_days"
    AUTO_START = "auto_start"
    SET_THUMBNAIL = "set_thumbnail"
    CATEGORY_ID = "category_id"
    YOUTUBE_PAUSE_SECONDS = "youtube_pause_seconds"
    IMAGE_DIR_TEMPLATE = "image_dir_template"
    TIMEZONE = "timezone"
    LLM = "llm"
    FORM = "form"
    TELEGRAM = "telegram"
    DRIVE = "drive"
    DOCS = "docs"
    BROADCASTS = "broadcasts"
    LINES = "lines"
    FOLDERS = "folders"
    LLM_MODEL = "llm.model"
    LLM_FALLBACK_MODEL = "llm.fallback_model"
    LLM_REASONING_EFFORT = "llm.reasoning_effort"
    LLM_SERVICE_TIER = "llm.service_tier"
    LLM_TIMEOUT_SEC = "llm.timeout_sec"
    LLM_MAX_OUTPUT_TOKENS = "llm.max_output_tokens"
    FORM_URL = "form.url"
    FORM_FIELDS = "form.fields"
    FORM_VALUES = "form.values"
    FORM_DATE_FORMAT = "form.date_format"
    TELEGRAM_TARGET = "telegram.target"
    TELEGRAM_GROUP_CHAT_ID = "telegram.group_chat_id"
    TELEGRAM_PRIVATE_CHAT_ID = "telegram.private_chat_id"
    TELEGRAM_SUPPORT_CHAT_ID = "telegram.support_chat_id"
    DRIVE_PREVIEW_PATH_TEMPLATE = "drive.preview_path_template"
    DOCS_ACCESS = "docs.access"
    DOCS_CONTACTS = "docs.contacts"
    BROADCASTS_RESEND_KEYS = "broadcasts.resend_keys"
    LINES_PLAN = "lines.plan"
    LINES_MERGE = "lines.merge"
    LINES_LOCAL_PREVIEWS = "lines.local_previews"
    LINES_DRIVE_PREVIEWS = "lines.drive_previews"
    LINES_DOC = "lines.doc"
    LINES_DOC_COPY = "lines.doc_copy"
    LINES_PACKAGE = "lines.package"
    LINES_ANNOUNCE = "lines.announce"
    LINES_BROADCAST = "lines.broadcast"
    LINES_KEYS = "lines.keys"
    FOLDERS_PACKAGES = "folders.packages"
    FOLDERS_DOCS = "folders.docs"
    FOLDERS_IMAGES = "folders.images"

    @classmethod
    def leaves(cls, section: SettingKey | None = None) -> tuple[str, ...]:
        """Имена полей раздела (None — корня файла) в порядке файла."""
        path: str = "" if section is None else section.value
        return tuple(key.leaf for key in cls if key.section == path)

    @property
    def leaf(self) -> str:
        """Имя поля в своём разделе: `model` у `llm.model`."""
        return self.value.rpartition(KEY_SEPARATOR)[-1]

    @property
    def section(self) -> str:
        """Путь раздела, в котором лежит поле; у поля корня — пустая строка."""
        return self.value.rpartition(KEY_SEPARATOR)[0]


class LegacySettingKey(str, Enum):
    """Ключи livecraft.json, которых в настройках больше нет: значение программа сама, один раз, переносит туда, где оно
    теперь живёт, или отбрасывает, если оно больше не нужно, и убирает ключ из файла (`SettingsFile.legacy_value`,
    `drop_legacy`); значение — путь ключа от корня файла."""

    DRIVE_FOLDER_URL = "drive.folder_url"   # папка Google Диска — поле сейфа (§14 решение 39)
    BROADCASTS_TEXT_SOURCE = "broadcasts.text_source"   # источник текстов — по линиям запуска (§14 решение 50)

    @property
    def leaf(self) -> str:
        return self.value.rpartition(KEY_SEPARATOR)[-1]

    @property
    def section(self) -> str:
        return self.value.rpartition(KEY_SEPARATOR)[0]
