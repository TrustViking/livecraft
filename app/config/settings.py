"""Технические настройки `secrets\\livecraft.json` (CLAUDE.md §5, §6 инварианты 2, 4, 7).

Файл действует на все каналы: паузы и сроки, настройки эфира, модель LLM, контракт формы ключей, шаблон папки
превью и часовой пояс. Ключи файла — члены `SettingKey`, значение члена — путь ключа (`llm.model`): из них
выводятся и состав каждого раздела, и данные файла (`to_data`), поэтому ключ описан ровно в одном месте.
Каждый объект строит себя сам из узла JSON (`from_node`) в пару к `to_data` и сам говорит, что с ним не так по
смыслу (`problem`).

Ключей и id здесь нет (§5): ключ OpenAI, id таблицы и диапазон живут в сейфе (§7.5). Ссылка на форму ключей —
открытая настройка `form.url` (§14 решение 15): пустая строка — «не настроено», и это не ошибка файла.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, ClassVar, Final
from urllib.parse import SplitResult
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from app.config.channel import Platform
from app.config.json_node import KEY_SEPARATOR, JsonNode, SettingProblem, json_value
from app.core.url_text import HTTPS_SCHEME, split_url
from app.ui import messages_ru as msg

MIN_LEAD_MINUTES_MINIMUM: Final[int] = 0
KEEP_DAYS_MINIMUM: Final[int] = 1
YOUTUBE_PAUSE_SECONDS_MINIMUM: Final[float] = 0.0   # число, можно дробное (0.5)
LLM_TIMEOUT_SEC_MINIMUM: Final[int] = 1
LLM_MAX_OUTPUT_TOKENS_MINIMUM: Final[int] = 1
# Подстановки шаблона папки превью: папка image\{date}\{language} (§5).
IMAGE_TEMPLATE_PLACEHOLDERS: Final[tuple[str, ...]] = ("date", "language")
IMAGE_TEMPLATE_PLACEHOLDER: Final[str] = "{{{name}}}"
IMAGE_TEMPLATE_PROBE: Final[str] = "probe"
# Формат даты формы обязан содержать день, месяц и год.
DATE_DIRECTIVES: Final[tuple[str, ...]] = ("%d", "%m", "%Y")
# Ссылка на форму ключей: https, длинная (docs.google.com/forms/…) или короткая (forms.gle/<код>).
FORM_LONG_HOST: Final[str] = "docs.google.com"
FORM_LONG_PATH_PREFIX: Final[str] = "/forms/"
FORM_SHORT_HOST: Final[str] = "forms.gle"
URL_PATH_SEPARATOR: Final[str] = "/"


class ReasoningEffort(str, Enum):
    """Допустимые уровни reasoning модели: правило допустимости — сам enum, а не проверка по месту."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ServiceTier(str, Enum):
    """Тарифы OpenAI: default, flex (дешевле и медленнее), fast / priority (дороже и быстрее)."""

    DEFAULT = "default"
    FLEX = "flex"
    FAST = "fast"
    PRIORITY = "priority"


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


class FormQuestion(str, Enum):
    """Вопросы формы ключей, которые программа знает (`form.fields`); значение — имя поля в файле."""

    LANGUAGE = "language"
    ACCOUNT_NAME = "account_name"
    DATE = "date"
    PLATFORM = "platform"
    STREAM_KEY = "stream_key"
    STREAM_URL = "stream_url"
    TIME = "time"
    BROADCAST_URL = "broadcast_url"
    SLOT_ID = "slot_id"


@dataclass(frozen=True)
class LlmSettings:
    """Модель LLM и её параметры (§8.2, вкладка 5). Допустимые уровни и тарифы — в своих enum."""

    model: str
    fallback_model: str
    reasoning_effort: ReasoningEffort
    service_tier: ServiceTier
    timeout_sec: int
    max_output_tokens: int

    @classmethod
    def from_node(cls, node: JsonNode) -> LlmSettings:
        """Раздел `llm` файла."""
        node.mapping(SettingKey.leaves(SettingKey.LLM))
        return cls(
            model=node.field(SettingKey.LLM_MODEL.leaf).text(),
            fallback_model=node.field(SettingKey.LLM_FALLBACK_MODEL.leaf).text(),
            reasoning_effort=node.field(SettingKey.LLM_REASONING_EFFORT.leaf).choice(ReasoningEffort),
            service_tier=node.field(SettingKey.LLM_SERVICE_TIER.leaf).choice(ServiceTier),
            timeout_sec=node.field(SettingKey.LLM_TIMEOUT_SEC.leaf).integer(LLM_TIMEOUT_SEC_MINIMUM),
            max_output_tokens=node.field(SettingKey.LLM_MAX_OUTPUT_TOKENS.leaf).integer(
                LLM_MAX_OUTPUT_TOKENS_MINIMUM
            ),
        )

    def to_data(self) -> dict[str, Any]:
        """Раздел `llm` файла livecraft.json, поля в порядке ключей."""
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.LLM)}


@dataclass(frozen=True)
class FormSettings:
    """Форма ключей (§6 инвариант 2): ссылка, названия вопросов, тексты вариантов, формат даты.

    Ссылка — открытая настройка (§14 решение 15): уходит в пакет .bcast открытым текстом. Пустая ссылка —
    форма не настроена (§5); это не ошибка файла, а неготовая часть режима. Значение вопроса None — вопроса
    в форме нет, поле не уходит.
    """

    FIELD_KEYS: ClassVar[tuple[str, ...]] = tuple(question.value for question in FormQuestion)
    VALUE_KEYS: ClassVar[tuple[str, ...]] = (FormQuestion.LANGUAGE.value, FormQuestion.PLATFORM.value)

    url: str
    fields: dict[str, str | None]
    values: dict[str, dict[str, str]]
    date_format: str

    @classmethod
    def from_node(cls, node: JsonNode) -> FormSettings:
        """Раздел `form` файла: состав вопросов и вариантов — по `FIELD_KEYS` и `VALUE_KEYS`."""
        node.mapping(SettingKey.leaves(SettingKey.FORM))
        fields: JsonNode = node.field(SettingKey.FORM_FIELDS.leaf).mapping(cls.FIELD_KEYS)
        values: JsonNode = node.field(SettingKey.FORM_VALUES.leaf).mapping(cls.VALUE_KEYS)
        return cls(
            url=node.field(SettingKey.FORM_URL.leaf).string(),
            fields={key: fields.field(key).nullable_text() for key in cls.FIELD_KEYS},
            values={key: values.field(key).text_mapping() for key in cls.VALUE_KEYS},
            date_format=node.field(SettingKey.FORM_DATE_FORMAT.leaf).text(),
        )

    def to_data(self) -> dict[str, Any]:
        """Раздел `form`: ссылка первой, вопросы и варианты — как прочитаны, в том же порядке."""
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.FORM)}

    @property
    def is_configured(self) -> bool:
        """Ссылка на форму задана: без неё ключи отправлять некуда, а пакет .bcast не собрать."""
        return bool(self.url)

    @property
    def url_problem(self) -> SettingProblem | None:
        """Что не так со ссылкой: https, длинная (docs.google.com/forms/…) или короткая (forms.gle/<код>).

        Пустая ссылка годна — это «не настроено». Хост сверяется со всем `netloc`, а не только с именем:
        «docs.google.com@чужой.хост» и чужой порт не проходят. Пробелы не прощаются ни внутри, ни по краям:
        в файле ссылка лежит ровно такой, какой уйдёт в пакет. Адрес, который не разбирается (`https://[bad`), —
        та же проблема ссылки, а не исключение: иначе одна негодная строка роняла бы запуск и окно настройки.
        """
        if not self.url:
            return None
        parts: SplitResult | None = None if any(char.isspace() for char in self.url) else split_url(self.url)
        if parts is None or not self._is_form_address(parts):
            return SettingProblem(key=SettingKey.FORM_URL.value, text=msg.CONFIG_PROBLEM_FORM_URL)
        return None

    @property
    def problem(self) -> SettingProblem | None:
        """Что не так с формой по смыслу; путь — от корня файла. Состав ключей проверяет разбор."""
        url_problem: SettingProblem | None = self.url_problem
        if url_problem is not None:
            return url_problem
        if Platform.YOUTUBE.value not in self.values.get(FormQuestion.PLATFORM.value, {}):
            return SettingProblem(
                key=f"{SettingKey.FORM_VALUES.value}{KEY_SEPARATOR}{FormQuestion.PLATFORM.value}",
                text=msg.CONFIG_PROBLEM_FORM_PLATFORM.format(platform=Platform.YOUTUBE.value),
            )
        absent: tuple[str, ...] = tuple(item for item in DATE_DIRECTIVES if item not in self.date_format)
        if absent:
            text: str = msg.CONFIG_PROBLEM_FORM_DATE_FORMAT.format(
                required=msg.LIST_JOINER.join(DATE_DIRECTIVES), absent=msg.LIST_JOINER.join(absent)
            )
            return SettingProblem(key=SettingKey.FORM_DATE_FORMAT.value, text=text)
        return None

    def _is_form_address(self, parts: SplitResult) -> bool:
        """https и хост формы целиком: длинная ссылка — с путём /forms/…, короткая — с кодом после хоста."""
        host: str = parts.netloc.lower()
        is_long: bool = host == FORM_LONG_HOST and parts.path.startswith(FORM_LONG_PATH_PREFIX)
        is_short: bool = host == FORM_SHORT_HOST and bool(parts.path.strip(URL_PATH_SEPARATOR))
        return parts.scheme.lower() == HTTPS_SCHEME and (is_long or is_short)


@dataclass(frozen=True)
class LivecraftSettings:
    """Технические настройки livecraft.json: действуют на все каналы.

    `timezone` — основная зона дат и времени (§6 инвариант 4). Объект сам проверяет, что зона читается,
    и сам отдаёт её готовой (`zone`). База зон — пакет tzdata (§14 решение 10): на Windows своей у Python нет.
    """

    min_lead_minutes: int
    keep_days: int
    auto_start: bool
    set_thumbnail: bool
    category_id: str          # категория эфира на площадке; по справочнику YouTube не проверяется
    youtube_pause_seconds: float   # наименьший промежуток между любыми двумя обращениями к YouTube
    image_dir_template: str   # папка превью относительно image\: {date} и {language}
    timezone: str
    llm: LlmSettings
    form: FormSettings

    @classmethod
    def from_node(cls, root: JsonNode) -> LivecraftSettings:
        """Корень файла: сначала состав и вид каждого поля, затем смысл (`problem`) — ошибка с путём от корня."""
        root.mapping(SettingKey.leaves())
        settings: LivecraftSettings = cls(
            min_lead_minutes=root.field(SettingKey.MIN_LEAD_MINUTES.leaf).integer(MIN_LEAD_MINUTES_MINIMUM),
            keep_days=root.field(SettingKey.KEEP_DAYS.leaf).integer(KEEP_DAYS_MINIMUM),
            auto_start=root.field(SettingKey.AUTO_START.leaf).boolean(),
            set_thumbnail=root.field(SettingKey.SET_THUMBNAIL.leaf).boolean(),
            category_id=root.field(SettingKey.CATEGORY_ID.leaf).text(),
            youtube_pause_seconds=root.field(SettingKey.YOUTUBE_PAUSE_SECONDS.leaf).number(
                YOUTUBE_PAUSE_SECONDS_MINIMUM
            ),
            image_dir_template=root.field(SettingKey.IMAGE_DIR_TEMPLATE.leaf).text(),
            timezone=root.field(SettingKey.TIMEZONE.leaf).text(),
            llm=LlmSettings.from_node(root.field(SettingKey.LLM.leaf)),
            form=FormSettings.from_node(root.field(SettingKey.FORM.leaf)),
        )
        root.check(settings.problem)
        return settings

    def to_data(self) -> dict[str, Any]:
        """Данные livecraft.json, поля в порядке ключей; разделы `llm` и `form` пишут себя сами."""
        sections: dict[str, dict[str, Any]] = {
            SettingKey.LLM.leaf: self.llm.to_data(),
            SettingKey.FORM.leaf: self.form.to_data(),
        }
        return {
            leaf: sections[leaf] if leaf in sections else json_value(getattr(self, leaf))
            for leaf in SettingKey.leaves()
        }

    @property
    def zone(self) -> ZoneInfo:
        """Часовой пояс программы. Настройки, прошедшие разбор, дают его всегда: зону проверил `problem`."""
        return ZoneInfo(self.timezone)

    @property
    def problem(self) -> SettingProblem | None:
        """Что не так с настройками по смыслу: форма, шаблон папки превью и часовой пояс."""
        return self.form.problem or self._image_template_problem or self._timezone_problem

    @property
    def _timezone_problem(self) -> SettingProblem | None:
        """Зона читается и названа каноническим именем базы tzdata.

        Одного ZoneInfo мало: на Windows он открывает и «Europe\\Kyiv», и «Europe/Kyiv » с пробелом —
        файловая система прощает то, чего нет в базе зон. Сверка со списком базы отсекает такие имена.
        """
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            # ZoneInfoNotFoundError — нет такой зоны; ValueError — имя не ключ базы: пустое, с «..»,
            # абсолютное, с нулевым символом, или файл базы, который не является зоной.
            return SettingProblem(key=SettingKey.TIMEZONE.value, text=msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN)
        if self.timezone not in available_timezones():
            return SettingProblem(key=SettingKey.TIMEZONE.value, text=msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN)
        return None

    @property
    def _image_template_problem(self) -> SettingProblem | None:
        """Шаблон папки превью — относительный, с {date} и {language}, без чужих подстановок."""
        template: str = self.image_dir_template
        key: str = SettingKey.IMAGE_DIR_TEMPLATE.value
        absent: tuple[str, ...] = tuple(
            name for name in IMAGE_TEMPLATE_PLACEHOLDERS if IMAGE_TEMPLATE_PLACEHOLDER.format(name=name) not in template
        )
        if absent:
            text: str = msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS.format(absent=msg.LIST_JOINER.join(absent))
            return SettingProblem(key=key, text=text)
        if PureWindowsPath(template).is_absolute() or PurePosixPath(template).is_absolute():
            return SettingProblem(key=key, text=msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE)
        try:
            template.format(**{name: IMAGE_TEMPLATE_PROBE for name in IMAGE_TEMPLATE_PLACEHOLDERS})
        except (KeyError, IndexError, ValueError):
            return SettingProblem(key=key, text=msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT)
        return None
