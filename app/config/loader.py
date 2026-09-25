"""secrets\\livecraft.json + secrets\\channels.json → LivecraftConfig (CLAUDE.md §5, §14 решение 4).

Два файла, оба JSON, все поля обязательные, умолчаний в коде нет. livecraft.json — технический, поставляется
со сборкой заполненным и действует на все каналы: паузы и сроки, настройки эфира (§6 инвариант 7), модель
LLM, контракт формы ключей (§6 инвариант 2), шаблон папки превью и часовой пояс. channels.json заполняет
оператор или настройщик: шесть полей на канал, ключ канала — ник (§6 инвариант 5).

Ключей и id в конфигах нет (§5): ключ OpenAI, id таблицы и диапазон таблицы живут в сейфе (§7.5), и этот
модуль сейфа не знает. Ссылка на форму ключей — открытая настройка `form.url` (§14 решение 15): пустая строка —
«не настроено», и это не ошибка файла.

Файла нет или поля нет — ConfigError с точным ключом; шаблон файла main пишет в лог. Каналы пишет только
save_channels_file (текст — только render_channels_file); прежний файл уходит в channels.previous.json.
Настройки пишет только save_settings_file (текст — только render_settings_file). Данные JSON объект строит
сам (`to_data`); настройщик проверяет свои черновики тем же разбором (`parse_settings`, `parse_channels`).

Перенесено из planers\\app\\config\\loader.py почти целиком; расширено настройками LLM, формы, превью и
часового пояса. Площадки v1 — только YouTube (§1).
"""
from __future__ import annotations

import json
import math
import shutil
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, ClassVar, Final
from urllib.parse import SplitResult
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import pycountry

from app.core.url_text import split_url
from app.paths import write_text_atomically
from app.ui import messages_ru as msg


class Platform(str, Enum):
    """Площадки v1 — только YouTube (§1). Facebook и Rumble — за пределами v1."""

    YOUTUBE = "youtube"


class Privacy(str, Enum):
    """Видимость эфиров канала — из channels.json (§6 инвариант 7)."""

    PUBLIC = "public"
    UNLISTED = "unlisted"


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


class ConfigProblem(str, Enum):
    """Что именно не так: нет файла, нет поля или негодное значение («не настроено» против «сломано»)."""

    FILE_MISSING = "file_missing"
    FIELD_MISSING = "field_missing"
    INVALID = "invalid"


CONFIG_ENCODING: Final[str] = "utf-8"
MIN_LEAD_MINUTES_MINIMUM: Final[int] = 0
KEEP_DAYS_MINIMUM: Final[int] = 1
YOUTUBE_PAUSE_SECONDS_MINIMUM: Final[float] = 0.0   # число, можно дробное (0.5)
LLM_TIMEOUT_SEC_MINIMUM: Final[int] = 1
LLM_MAX_OUTPUT_TOKENS_MINIMUM: Final[int] = 1
LLM_KEY: Final[str] = "llm"
FORM_KEY: Final[str] = "form"
CHANNELS_KEY: Final[str] = "channels"
KEY_SEPARATOR: Final[str] = "."
SETTINGS_KEYS: Final[tuple[str, ...]] = (
    "min_lead_minutes",
    "keep_days",
    "auto_start",
    "set_thumbnail",
    "category_id",
    "youtube_pause_seconds",
    "image_dir_template",
    "timezone",
    LLM_KEY,
    FORM_KEY,
)
LLM_KEYS: Final[tuple[str, ...]] = (
    "model",
    "fallback_model",
    "reasoning_effort",
    "service_tier",
    "timeout_sec",
    "max_output_tokens",
)
FORM_URL_KEY: Final[str] = "url"
FORM_KEYS: Final[tuple[str, ...]] = (FORM_URL_KEY, "fields", "values", "date_format")
CHANNELS_TOP_LEVEL_KEYS: Final[tuple[str, ...]] = (CHANNELS_KEY,)
CHANNEL_KEYS: Final[tuple[str, ...]] = ("platform", "account_name", "handle", "google_account", "languages", "privacy")
# Как render_channels_file раскладывает канал: первая строка — эти поля, вторая — остальные.
CHANNEL_FIRST_LINE_KEYS: Final[tuple[str, ...]] = CHANNEL_KEYS[:4]
CHANNEL_SECOND_LINE_KEYS: Final[tuple[str, ...]] = CHANNEL_KEYS[4:]
CHANNELS_FILE_HEAD: Final[str] = '{\n  "channels": [\n'
CHANNELS_FILE_TAIL: Final[str] = "\n  ]\n}\n"
CHANNEL_LINES: Final[str] = "    {{{first},\n     {second}}}"
CHANNEL_FIELD: Final[str] = "{key}: {value}"
CHANNEL_FIELD_JOINER: Final[str] = ", "
CHANNEL_JOINER: Final[str] = ",\n"
# Как render_settings_file раскладывает livecraft.json: так же, как поставочный файл.
SETTINGS_FILE_INDENT: Final[int] = 2
SETTINGS_FILE_END: Final[str] = "\n"
SHIPPED_TEMPLATE_NAME: Final[str] = "CONFIG_SETTINGS_TEMPLATE"     # «путь» в ошибке разбора шаблона
ALLOWED_JOINER: Final[str] = ", "
# Ник канала (@handle) — ключ канала: уникален на YouTube и не зависит от регистра (§6 инвариант 5).
HANDLE_PREFIX: Final[str] = "@"
HANDLE_MIN_CHARS: Final[int] = 3
HANDLE_MAX_CHARS: Final[int] = 30
HANDLE_FORBIDDEN_CHARS: Final[str] = '<>:"/\\|?*'
UNICODE_FORM: Final[str] = "NFC"
CONTROL_CHAR_LIMIT: Final[int] = 32
# account_name — название канала для людей и формы; одинаковые названия у разных каналов допустимы.
ACCOUNT_NAME_EDGE_CHAR: Final[str] = " "   # YouTube не отдаёт названия с пробелом по краю: такое не совпадёт
ACCOUNT_NAME_MAX_CHARS: Final[int] = 100   # предел названия канала на YouTube
# google_account — подсказка аккаунта при входе, а не проверка почты: ровно один «@», части непустые, без пробелов.
GOOGLE_ACCOUNT_SEPARATOR: Final[str] = "@"

LANGUAGE_CODE_LENGTH: Final[int] = 2   # ISO 639-1
# Плейсхолдеры шаблона папки превью: папка image\{date}\{language} (§5).
IMAGE_TEMPLATE_PLACEHOLDERS: Final[tuple[str, ...]] = ("date", "language")
IMAGE_TEMPLATE_PROBE: Final[str] = "probe"
# Ссылка на форму ключей: https, длинная (docs.google.com/forms/…) или короткая (forms.gle/<код>).
FORM_URL_SCHEME: Final[str] = "https"
FORM_LONG_HOST: Final[str] = "docs.google.com"
FORM_LONG_PATH_PREFIX: Final[str] = "/forms/"
FORM_SHORT_HOST: Final[str] = "forms.gle"
URL_PATH_SEPARATOR: Final[str] = "/"


class ConfigError(Exception):
    """Ошибка конфигурации: файл, ключ и причина; текст — для оператора (messages_ru)."""

    def __init__(
        self,
        *,
        config_path: Path,
        key_path: str,
        problem: str,
        kind: ConfigProblem = ConfigProblem.INVALID,
    ) -> None:
        super().__init__(msg.CONFIG_ERROR.format(path=config_path, key=key_path, problem=problem))
        self.config_path: Path = config_path
        self.key_path: str = key_path
        self.problem: str = problem
        self.kind: ConfigProblem = kind


@dataclass(frozen=True)
class SettingProblem:
    """Что не так со значением настройки: ключ относительно объекта и русский текст причины."""

    key: str
    text: str


@dataclass(frozen=True)
class ChannelConfig:
    """Ровно шесть полей channels.json. handle — ник как в файле (файл токена, --auth);
    key — его единственная нормализация, ключ всех словарей и кешей по каналу (§6 инвариант 5).
    google_account — почта аккаунта Google канала: подсказка браузеру при входе.
    """

    platform: Platform
    account_name: str
    handle: str
    google_account: str
    languages: tuple[str, ...]
    privacy: Privacy

    @property
    def key(self) -> str:
        """Единственная нормализация ника: без «@», NFC, без различия регистра."""
        return unicodedata.normalize(UNICODE_FORM, self.handle).removeprefix(HANDLE_PREFIX).casefold()

    def to_data(self) -> dict[str, Any]:
        """Канал как объект channels.json, поля в порядке CHANNEL_KEYS."""
        return {
            "platform": self.platform.value,
            "account_name": self.account_name,
            "handle": self.handle,
            "google_account": self.google_account,
            "languages": list(self.languages),
            "privacy": self.privacy.value,
        }


@dataclass(frozen=True)
class LlmSettings:
    """Модель LLM и её параметры (§8.2, вкладка 3). Допустимые уровни и тарифы — в своих enum."""

    model: str
    fallback_model: str
    reasoning_effort: ReasoningEffort
    service_tier: ServiceTier
    timeout_sec: int
    max_output_tokens: int

    def to_data(self) -> dict[str, Any]:
        """Раздел llm файла livecraft.json, поля в порядке LLM_KEYS."""
        return {
            "model": self.model,
            "fallback_model": self.fallback_model,
            "reasoning_effort": self.reasoning_effort.value,
            "service_tier": self.service_tier.value,
            "timeout_sec": self.timeout_sec,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True)
class FormSettings:
    """Форма ключей (§6 инвариант 2): ссылка, названия вопросов, тексты вариантов, формат даты.

    Ссылка — открытая настройка (§14 решение 15): уходит в пакет .bcast открытым текстом. Пустая ссылка —
    форма не настроена (§5); это не ошибка файла, а неготовая часть режима. Живой разбор формы из этого
    объекта не строится (задача 4.2): здесь форма только прочитана и проверена. Значение вопроса None —
    вопроса в форме нет, поле не уходит.
    """

    FIELD_KEYS: ClassVar[tuple[str, ...]] = (
        "language",
        "account_name",
        "date",
        "platform",
        "stream_key",
        "stream_url",
        "time",
        "broadcast_url",
        "slot_id",
    )
    VALUE_KEYS: ClassVar[tuple[str, ...]] = ("language", "platform")
    DATE_DIRECTIVES: ClassVar[tuple[str, ...]] = ("%d", "%m", "%Y")
    PLATFORM_VALUES_KEY: ClassVar[str] = "platform"

    url: str
    fields: dict[str, str | None]
    values: dict[str, dict[str, str]]
    date_format: str

    def to_data(self) -> dict[str, Any]:
        """Раздел form файла livecraft.json: ссылка первой, вопросы и варианты — как прочитаны, в том же порядке."""
        return {
            FORM_URL_KEY: self.url,
            "fields": dict(self.fields),
            "values": {key: dict(texts) for key, texts in self.values.items()},
            "date_format": self.date_format,
        }

    @property
    def is_configured(self) -> bool:
        """Ссылка на форму задана: без неё ключи отправлять некуда, а пакет .bcast не собрать."""
        return bool(self.url)

    @property
    def url_problem(self) -> SettingProblem | None:
        """Что не так со ссылкой: https, длинная (docs.google.com/forms/…) или короткая (forms.gle/<код>).

        Пустая ссылка годна — это «не настроено». Хост сверяется со всем `netloc`, а не только с именем:
        «docs.google.com@чужой.хост» и чужой порт не проходят. Пробелы не прощаются ни внутри, ни по краям:
        в файле ссылка лежит ровно такой, какой уйдёт в пакет. Редирект и viewform разбирает сама форма
        (задача 4.2), здесь — только чей это адрес. Адрес, который не разбирается (`https://[bad`), — та же
        проблема ссылки, а не исключение: иначе одна негодная строка роняла бы запуск и окно настройки.
        """
        if not self.url:
            return None
        if any(char.isspace() for char in self.url):
            return SettingProblem(key=FORM_URL_KEY, text=msg.CONFIG_PROBLEM_FORM_URL)
        parts: SplitResult | None = split_url(self.url)
        if parts is None:
            return SettingProblem(key=FORM_URL_KEY, text=msg.CONFIG_PROBLEM_FORM_URL)
        host: str = parts.netloc.lower()
        is_long: bool = host == FORM_LONG_HOST and parts.path.startswith(FORM_LONG_PATH_PREFIX)
        is_short: bool = host == FORM_SHORT_HOST and bool(parts.path.strip(URL_PATH_SEPARATOR))
        if parts.scheme.lower() != FORM_URL_SCHEME or not (is_long or is_short):
            return SettingProblem(key=FORM_URL_KEY, text=msg.CONFIG_PROBLEM_FORM_URL)
        return None

    @property
    def problem(self) -> SettingProblem | None:
        """Что не так с формой по смыслу; состав ключей проверяет разбор по FIELD_KEYS и VALUE_KEYS."""
        url_problem: SettingProblem | None = self.url_problem
        if url_problem is not None:
            return url_problem
        platforms: dict[str, str] = self.values.get(self.PLATFORM_VALUES_KEY, {})
        if Platform.YOUTUBE.value not in platforms:
            return SettingProblem(
                key=f"values{KEY_SEPARATOR}{self.PLATFORM_VALUES_KEY}",
                text=msg.CONFIG_PROBLEM_FORM_PLATFORM.format(platform=Platform.YOUTUBE.value),
            )
        absent: tuple[str, ...] = tuple(item for item in self.DATE_DIRECTIVES if item not in self.date_format)
        if absent:
            return SettingProblem(
                key="date_format",
                text=msg.CONFIG_PROBLEM_FORM_DATE_FORMAT.format(
                    required=ALLOWED_JOINER.join(self.DATE_DIRECTIVES), absent=ALLOWED_JOINER.join(absent)
                ),
            )
        return None


@dataclass(frozen=True)
class LivecraftSettings:
    """Технические настройки livecraft.json: действуют на все каналы.

    `timezone` — основная зона дат и времени (§6 инвариант 4). Объект сам проверяет, что зона читается,
    и сам отдаёт её готовой (`zone`): кто переводит время ряда в момент старта, спрашивает зону здесь, а не
    строит её по месту. База зон — пакет tzdata (§14 решение 10): на Windows своей у Python нет.
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

    def to_data(self) -> dict[str, Any]:
        """Данные livecraft.json, поля в порядке SETTINGS_KEYS."""
        return {
            "min_lead_minutes": self.min_lead_minutes,
            "keep_days": self.keep_days,
            "auto_start": self.auto_start,
            "set_thumbnail": self.set_thumbnail,
            "category_id": self.category_id,
            "youtube_pause_seconds": self.youtube_pause_seconds,
            "image_dir_template": self.image_dir_template,
            "timezone": self.timezone,
            LLM_KEY: self.llm.to_data(),
            FORM_KEY: self.form.to_data(),
        }

    @property
    def zone(self) -> ZoneInfo:
        """Часовой пояс программы. Настройки, прошедшие загрузчик, дают его всегда: зону проверил `problem`."""
        return ZoneInfo(self.timezone)

    @property
    def problem(self) -> SettingProblem | None:
        """Что не так с настройками по смыслу: шаблон папки превью и часовой пояс."""
        return self._image_template_problem or self._timezone_problem

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
            return SettingProblem(key="timezone", text=msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN)
        if self.timezone not in available_timezones():
            return SettingProblem(key="timezone", text=msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN)
        return None

    @property
    def _image_template_problem(self) -> SettingProblem | None:
        """Шаблон папки превью — относительный, с {date} и {language}, без чужих подстановок."""
        template: str = self.image_dir_template
        absent: tuple[str, ...] = tuple(
            name for name in IMAGE_TEMPLATE_PLACEHOLDERS if f"{{{name}}}" not in template
        )
        if absent:
            return SettingProblem(
                key="image_dir_template",
                text=msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS.format(absent=ALLOWED_JOINER.join(absent)),
            )
        if PureWindowsPath(template).is_absolute() or PurePosixPath(template).is_absolute():
            return SettingProblem(key="image_dir_template", text=msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE)
        try:
            template.format(**{name: IMAGE_TEMPLATE_PROBE for name in IMAGE_TEMPLATE_PLACEHOLDERS})
        except (KeyError, IndexError, ValueError):
            return SettingProblem(key="image_dir_template", text=msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT)
        return None


@dataclass(frozen=True)
class LivecraftConfig:
    """Настройки и каналы одного запуска."""

    settings: LivecraftSettings
    channels: tuple[ChannelConfig, ...]


def load_settings(path: Path) -> LivecraftSettings:
    """secrets\\livecraft.json → технические настройки."""
    return parse_settings(_read_json(path), path)


def load_channels(path: Path) -> tuple[ChannelConfig, ...]:
    """secrets\\channels.json → каналы."""
    return parse_channels(_read_json(path), path)


def parse_settings(raw: Any, path: Path) -> LivecraftSettings:
    """Уже прочитанные данные livecraft.json → настройки. path — только для ConfigError."""
    return _ConfigParser(path).parse_settings(raw)


def parse_channels(raw: Any, path: Path) -> tuple[ChannelConfig, ...]:
    """Уже прочитанные данные channels.json → каналы. path — только для ConfigError."""
    return _ConfigParser(path).parse_channels(raw)


@dataclass(frozen=True)
class ShippedSettings:
    """Поставочный вид livecraft.json (§5): файла в git нет, программа кладёт его сама, когда его нет.

    `template` — текст шаблона (CONFIG_SETTINGS_TEMPLATE): без чьих-либо данных, ссылка на форму пуста
    (§14 решение 16). Шаблон разбирается тем же загрузчиком, что и файл; негодный шаблон — ошибка программы.
    Существующий файл не трогается никогда: в нём настройки человека, а сломанный файл называет загрузчик.
    """

    template: str

    @property
    def settings(self) -> LivecraftSettings:
        """Настройки шаблона. Шаблон не разобрался — ValueError с путём ключа: это ошибка программиста."""
        try:
            return parse_settings(json.loads(self.template), Path(SHIPPED_TEMPLATE_NAME))
        except json.JSONDecodeError as error:
            raise ValueError(f"shipped settings template is not JSON: {error}") from error
        except ConfigError as error:
            raise ValueError(f"shipped settings template is invalid at {error.key_path}: {error.problem}") from error

    def install(self, config_file: Path) -> bool:
        """Нет файла — записать поставочный вид атомарно и вернуть True; файл есть — ничего не трогать, False.

        Пишется разобранный шаблон тем же render_settings_file, что и настройщик: негодный шаблон на диск
        не попадает, а текст файла совпадает с шаблоном байт в байт (тест держит это равенство).
        """
        if config_file.exists():
            return False
        write_text_atomically(config_file, render_settings_file(self.settings), CONFIG_ENCODING)
        return True


def render_channels_file(channels: Iterable[ChannelConfig]) -> str:
    """Текст channels.json в том виде, в каком его пишет человек: канал — две строки."""
    body: str = CHANNEL_JOINER.join(_channel_lines(channel) for channel in channels)
    return CHANNELS_FILE_HEAD + body + CHANNELS_FILE_TAIL


def save_channels_file(channels_file: Path, previous_file: Path, channels: Iterable[ChannelConfig]) -> None:
    """Прежний файл байт в байт — в previous_file (перезаписывается), новый — атомарно. Сбой — OSError."""
    text: str = render_channels_file(channels)
    if channels_file.is_file():
        shutil.copyfile(channels_file, previous_file)
    write_text_atomically(channels_file, text, CONFIG_ENCODING)


def render_settings_file(settings: LivecraftSettings) -> str:
    """Текст livecraft.json: тот же вид, что у поставочного файла.

    Только стандартный JSON: настройки после разбора конечны всегда, а объект, собранный в обход загрузчика
    с NaN или бесконечностью, даёт ValueError, а не файл, который другие программы не прочитают.
    """
    text: str = json.dumps(settings.to_data(), indent=SETTINGS_FILE_INDENT, ensure_ascii=False, allow_nan=False)
    return text + SETTINGS_FILE_END


def save_settings_file(config_file: Path, settings: LivecraftSettings) -> None:
    """Новый livecraft.json — атомарно; копии прежнего нет (§5 такого файла не называет). Сбой — OSError."""
    write_text_atomically(config_file, render_settings_file(settings), CONFIG_ENCODING)


def allowed_values(enum_type: type[Enum]) -> str:
    """Допустимые значения поля — и для ошибки, и для подсказки к шаблону channels.json."""
    return ALLOWED_JOINER.join(str(member.value) for member in enum_type)


def normalize_account_name(value: str) -> str:
    """Одна форма Unicode (NFC): «й» одним символом и «и» + знак — одно название."""
    return unicodedata.normalize(UNICODE_FORM, value)


def handle_problem(value: str) -> str | None:
    """None — ник годится; иначе что именно не так. value — уже в NFC.

    Той же проверкой проходит ник, который программа сама пишет в channels.json при выравнивании.
    """
    if not value.startswith(HANDLE_PREFIX):
        return msg.CONFIG_PROBLEM_HANDLE_PREFIX.format(value=value, prefix=HANDLE_PREFIX)
    body: str = value[len(HANDLE_PREFIX):]
    if not HANDLE_MIN_CHARS <= len(body) <= HANDLE_MAX_CHARS:
        return msg.CONFIG_PROBLEM_HANDLE_LENGTH.format(
            value=value, minimum=HANDLE_MIN_CHARS, maximum=HANDLE_MAX_CHARS, length=len(body)
        )
    for char in body:
        if char.isspace() or ord(char) < CONTROL_CHAR_LIMIT or char in HANDLE_FORBIDDEN_CHARS:
            return msg.CONFIG_PROBLEM_HANDLE_CHAR.format(value=value, char=repr(char))
    return None


def account_name_problem(value: str) -> str | None:
    """None — название годится; иначе что именно не так. value — уже в NFC и непустое."""
    if len(value) > ACCOUNT_NAME_MAX_CHARS:
        return msg.CONFIG_PROBLEM_ACCOUNT_NAME_TOO_LONG.format(maximum=ACCOUNT_NAME_MAX_CHARS, length=len(value))
    if any(ord(char) < CONTROL_CHAR_LIMIT for char in value):
        return msg.CONFIG_PROBLEM_ACCOUNT_NAME_CONTROL
    if value.startswith(ACCOUNT_NAME_EDGE_CHAR) or value.endswith(ACCOUNT_NAME_EDGE_CHAR):
        return msg.CONFIG_PROBLEM_ACCOUNT_NAME_SPACE_EDGE.format(value=value)
    return None


def _is_google_account(value: str) -> bool:
    """Минимальная честная проверка: local@domain, обе части непустые, пробелов нет."""
    local, separator, domain = value.partition(GOOGLE_ACCOUNT_SEPARATOR)
    if not separator or not local or not domain or GOOGLE_ACCOUNT_SEPARATOR in domain:
        return False
    return not any(char.isspace() for char in value)


def _is_language_code(value: Any) -> bool:
    """Код языка ISO 639-1: ровно две строчные латинские буквы, и справочник pycountry его знает.

    Строчность проверяется отдельно: поиск pycountry регистр не различает и нашёл бы «UK».
    """
    is_shaped: bool = (
        isinstance(value, str)
        and len(value) == LANGUAGE_CODE_LENGTH
        and value.isascii()
        and value.isalpha()
        and value.islower()
    )
    return is_shaped and pycountry.languages.get(alpha_2=value) is not None


def _channel_lines(channel: ChannelConfig) -> str:
    values: dict[str, Any] = channel.to_data()
    return CHANNEL_LINES.format(
        first=_channel_fields(values, CHANNEL_FIRST_LINE_KEYS),
        second=_channel_fields(values, CHANNEL_SECOND_LINE_KEYS),
    )


def _channel_fields(values: dict[str, Any], keys: tuple[str, ...]) -> str:
    return CHANNEL_FIELD_JOINER.join(
        CHANNEL_FIELD.format(key=json.dumps(key), value=json.dumps(values[key], ensure_ascii=False)) for key in keys
    )


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(
            config_path=path,
            key_path=msg.CONFIG_ROOT_KEY,
            problem=msg.CONFIG_PROBLEM_FILE_MISSING,
            kind=ConfigProblem.FILE_MISSING,
        )
    try:
        return json.loads(path.read_text(encoding=CONFIG_ENCODING), object_pairs_hook=_UniquePairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError(
            config_path=path,
            key_path=msg.CONFIG_ROOT_KEY,
            problem=msg.CONFIG_PROBLEM_JSON.format(error=error),
        ) from error


class _UniquePairs(dict[str, Any]):
    """Объект JSON с повтором поля: json молча взял бы последнее значение."""

    def __init__(self, pairs: Iterable[tuple[str, Any]]) -> None:
        super().__init__()
        self.duplicates: list[str] = []
        for key, value in pairs:
            if key in self:
                self.duplicates.append(key)
            self[key] = value


class _ConfigParser:
    """Разбор объекта JSON; каждая ошибка — ConfigError с путём поля (channels[1].languages, form.fields.date)."""

    def __init__(self, config_path: Path) -> None:
        self._config_path: Path = config_path

    def parse_settings(self, raw: Any) -> LivecraftSettings:
        root: dict[str, Any] = self._mapping(raw, key_path=msg.CONFIG_ROOT_KEY, prefix="", allowed=SETTINGS_KEYS)
        settings: LivecraftSettings = LivecraftSettings(
            min_lead_minutes=self._int(root, "min_lead_minutes", prefix="", minimum=MIN_LEAD_MINUTES_MINIMUM),
            keep_days=self._int(root, "keep_days", prefix="", minimum=KEEP_DAYS_MINIMUM),
            auto_start=self._bool(root, "auto_start", prefix=""),
            set_thumbnail=self._bool(root, "set_thumbnail", prefix=""),
            category_id=self._text(root, "category_id", prefix=""),
            youtube_pause_seconds=self._number(
                root, "youtube_pause_seconds", prefix="", minimum=YOUTUBE_PAUSE_SECONDS_MINIMUM
            ),
            image_dir_template=self._text(root, "image_dir_template", prefix=""),
            timezone=self._text(root, "timezone", prefix=""),
            llm=self._llm(root[LLM_KEY]),
            form=self._form(root[FORM_KEY]),
        )
        self._raise_problem(settings.problem, prefix="")
        return settings

    def parse_channels(self, raw: Any) -> tuple[ChannelConfig, ...]:
        root: dict[str, Any] = self._mapping(
            raw,
            key_path=msg.CONFIG_ROOT_KEY,
            prefix="",
            allowed=CHANNELS_TOP_LEVEL_KEYS,
        )
        return self._channels(root)

    def _llm(self, raw: Any) -> LlmSettings:
        prefix: str = LLM_KEY + KEY_SEPARATOR
        mapping: dict[str, Any] = self._mapping(raw, key_path=LLM_KEY, prefix=prefix, allowed=LLM_KEYS)
        return LlmSettings(
            model=self._text(mapping, "model", prefix=prefix),
            fallback_model=self._text(mapping, "fallback_model", prefix=prefix),
            reasoning_effort=self._choice(mapping, "reasoning_effort", prefix=prefix, enum_type=ReasoningEffort),
            service_tier=self._choice(mapping, "service_tier", prefix=prefix, enum_type=ServiceTier),
            timeout_sec=self._int(mapping, "timeout_sec", prefix=prefix, minimum=LLM_TIMEOUT_SEC_MINIMUM),
            max_output_tokens=self._int(
                mapping, "max_output_tokens", prefix=prefix, minimum=LLM_MAX_OUTPUT_TOKENS_MINIMUM
            ),
        )

    def _form(self, raw: Any) -> FormSettings:
        prefix: str = FORM_KEY + KEY_SEPARATOR
        mapping: dict[str, Any] = self._mapping(raw, key_path=FORM_KEY, prefix=prefix, allowed=FORM_KEYS)
        fields_prefix: str = f"{prefix}fields{KEY_SEPARATOR}"
        fields_raw: dict[str, Any] = self._mapping(
            mapping["fields"], key_path=f"{prefix}fields", prefix=fields_prefix, allowed=FormSettings.FIELD_KEYS
        )
        values_prefix: str = f"{prefix}values{KEY_SEPARATOR}"
        values_raw: dict[str, Any] = self._mapping(
            mapping["values"], key_path=f"{prefix}values", prefix=values_prefix, allowed=FormSettings.VALUE_KEYS
        )
        form: FormSettings = FormSettings(
            url=self._string(mapping, FORM_URL_KEY, prefix=prefix),
            fields={key: self._nullable_text(fields_raw, key, prefix=fields_prefix) for key in FormSettings.FIELD_KEYS},
            values={key: self._text_mapping(values_raw, key, prefix=values_prefix) for key in FormSettings.VALUE_KEYS},
            date_format=self._text(mapping, "date_format", prefix=prefix),
        )
        self._raise_problem(form.problem, prefix=prefix)
        return form

    def _raise_problem(self, problem: SettingProblem | None, *, prefix: str) -> None:
        """Объект сам сказал, что с ним не так; разбору остаётся приписать путь и файл."""
        if problem is not None:
            raise self._error(f"{prefix}{problem.key}", problem.text)

    def _error(self, key_path: str, problem: str, kind: ConfigProblem = ConfigProblem.INVALID) -> ConfigError:
        return ConfigError(config_path=self._config_path, key_path=key_path, problem=problem, kind=kind)

    def _mapping(
        self,
        raw: Any,
        *,
        key_path: str,
        prefix: str,
        allowed: tuple[str, ...],
    ) -> dict[str, Any]:
        """Неизвестное или повторённое поле — ошибка с его именем; отсутствующие проверяются следом."""
        if not isinstance(raw, dict):
            raise self._error(key_path, msg.CONFIG_PROBLEM_NOT_MAPPING)
        for key in raw:
            if key not in allowed:
                raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_UNKNOWN_KEY)
        duplicates: list[str] = getattr(raw, "duplicates", [])
        if duplicates:
            raise self._error(f"{prefix}{duplicates[0]}", msg.CONFIG_PROBLEM_DUPLICATE_KEY)
        for key in allowed:
            if key not in raw:
                raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_MISSING_KEY, ConfigProblem.FIELD_MISSING)
        return dict(raw)

    def _text(self, mapping: dict[str, Any], key: str, *, prefix: str) -> str:
        value: Any = mapping[key]
        if not isinstance(value, str) or not value.strip():
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_NON_EMPTY_STRING)
        return value

    def _string(self, mapping: dict[str, Any], key: str, *, prefix: str) -> str:
        """Строка, которая может быть пустой: пустое значение открытой настройки — «не настроено» (§5)."""
        value: Any = mapping[key]
        if not isinstance(value, str):
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_STRING)
        return value

    def _nullable_text(self, mapping: dict[str, Any], key: str, *, prefix: str) -> str | None:
        """Название вопроса формы: непустая строка либо null — вопроса в форме нет (§6 инвариант 2)."""
        value: Any = mapping[key]
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_TEXT_OR_NULL)
        return value

    def _text_mapping(self, mapping: dict[str, Any], key: str, *, prefix: str) -> dict[str, str]:
        """Тексты вариантов вопроса: объект «код → непустой текст», хотя бы один вариант."""
        value: Any = mapping[key]
        valid: bool = isinstance(value, dict) and bool(value) and all(
            isinstance(code, str) and code.strip() and isinstance(text, str) and text.strip()
            for code, text in value.items()
        )
        if not valid:
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_TEXT_MAPPING)
        duplicates: list[str] = getattr(value, "duplicates", [])
        if duplicates:
            raise self._error(f"{prefix}{key}{KEY_SEPARATOR}{duplicates[0]}", msg.CONFIG_PROBLEM_DUPLICATE_KEY)
        return dict(value)

    def _int(self, mapping: dict[str, Any], key: str, *, prefix: str, minimum: int) -> int:
        value: Any = mapping[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_INT_MIN.format(minimum=minimum))
        return value

    def _number(self, mapping: dict[str, Any], key: str, *, prefix: str, minimum: float) -> float:
        """Число, можно дробное: int и float — да; bool, строка, NaN, бесконечность и меньше минимума — ошибка.

        json.loads принимает NaN, Infinity и -Infinity, а nan < minimum ложно: без проверки конечности
        такое значение прошло бы минимум.
        """
        value: Any = mapping[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=minimum))
        if not math.isfinite(value):
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_NUMBER_FINITE)
        if value < minimum:
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=minimum))
        return float(value)

    def _bool(self, mapping: dict[str, Any], key: str, *, prefix: str) -> bool:
        value: Any = mapping[key]
        if not isinstance(value, bool):
            raise self._error(f"{prefix}{key}", msg.CONFIG_PROBLEM_BOOL)
        return value

    def _choice(self, mapping: dict[str, Any], key: str, *, prefix: str, enum_type: type[Enum]) -> Any:
        """Значение из перечня: допустимые значения задаёт сам enum, разбор лишь сверяет."""
        value: Any = mapping[key]
        try:
            return enum_type(value)
        except ValueError:
            raise self._error(
                f"{prefix}{key}",
                msg.CONFIG_PROBLEM_CHOICE.format(allowed=allowed_values(enum_type)),
            ) from None

    def _channels(self, root: dict[str, Any]) -> tuple[ChannelConfig, ...]:
        raw: Any = root[CHANNELS_KEY]
        if not isinstance(raw, list) or not raw:
            raise self._error(CHANNELS_KEY, msg.CONFIG_PROBLEM_CHANNELS_EMPTY)
        channels: list[ChannelConfig] = []
        for index, raw_channel in enumerate(raw):
            prefix: str = f"{CHANNELS_KEY}[{index}]{KEY_SEPARATOR}"
            channel: ChannelConfig = self._channel(raw_channel, prefix=prefix)
            self._check_unique(channel, channels, prefix=prefix)
            channels.append(channel)
        return tuple(channels)

    def _check_unique(self, channel: ChannelConfig, earlier: list[ChannelConfig], *, prefix: str) -> None:
        """Ник — ключ канала: повтор без учёта регистра — ошибка. Названия могут совпадать."""
        for other in earlier:
            if other.key == channel.key:
                raise self._error(
                    f"{prefix}handle",
                    msg.CONFIG_PROBLEM_HANDLE_DUPLICATE.format(value=channel.handle, other=other.handle),
                )

    def _channel(self, raw: Any, *, prefix: str) -> ChannelConfig:
        mapping: dict[str, Any] = self._mapping(
            raw,
            key_path=prefix.rstrip(KEY_SEPARATOR),
            prefix=prefix,
            allowed=CHANNEL_KEYS,
        )
        return ChannelConfig(
            platform=self._platform(mapping, prefix=prefix),
            account_name=self._account_name(mapping, prefix=prefix),
            handle=self._handle(mapping, prefix=prefix),
            google_account=self._google_account(mapping, prefix=prefix),
            languages=self._languages(mapping, prefix=prefix),
            privacy=self._choice(mapping, "privacy", prefix=prefix, enum_type=Privacy),
        )

    def _account_name(self, mapping: dict[str, Any], *, prefix: str) -> str:
        """Название приводится к NFC до проверок: дальше везде — только эта форма."""
        value: str = normalize_account_name(self._text(mapping, "account_name", prefix=prefix))
        problem: str | None = account_name_problem(value)
        if problem is not None:
            raise self._error(f"{prefix}account_name", problem)
        return value

    def _handle(self, mapping: dict[str, Any], *, prefix: str) -> str:
        """Ник хранится как в файле (NFC); сравнивается только через ChannelConfig.key."""
        value: str = unicodedata.normalize(UNICODE_FORM, self._text(mapping, "handle", prefix=prefix))
        problem: str | None = handle_problem(value)
        if problem is not None:
            raise self._error(f"{prefix}handle", problem)
        return value

    def _google_account(self, mapping: dict[str, Any], *, prefix: str) -> str:
        value: str = self._text(mapping, "google_account", prefix=prefix)
        if not _is_google_account(value):
            raise self._error(f"{prefix}google_account", msg.CONFIG_PROBLEM_GOOGLE_ACCOUNT.format(value=value))
        return value

    def _platform(self, mapping: dict[str, Any], *, prefix: str) -> Platform:
        value: str = self._text(mapping, "platform", prefix=prefix)
        try:
            return Platform(value)
        except ValueError:
            raise self._error(
                f"{prefix}platform",
                msg.CONFIG_PROBLEM_PLATFORM_UNKNOWN.format(value=value, allowed=allowed_values(Platform)),
            ) from None

    def _languages(self, mapping: dict[str, Any], *, prefix: str) -> tuple[str, ...]:
        """Непустой список кодов ISO 639-1 из справочника pycountry без повторов.

        Код вне справочника («uk-ua», «ukr», «xx») канал молча оставил бы без слотов, поэтому он — проблема
        поля с первым негодным значением, а не тихий пропуск.
        """
        value: Any = mapping["languages"]
        key_path: str = f"{prefix}languages"
        if not isinstance(value, list) or not value:
            raise self._error(key_path, msg.CONFIG_PROBLEM_LANGUAGES)
        unknown: list[Any] = [item for item in value if not _is_language_code(item)]
        if unknown:
            raise self._error(key_path, msg.CONFIG_PROBLEM_LANGUAGE_UNKNOWN.format(value=unknown[0]))
        duplicates: list[str] = sorted({item for item in value if value.count(item) > 1})
        if duplicates:
            raise self._error(key_path, msg.CONFIG_PROBLEM_LANGUAGE_DUPLICATE.format(value=duplicates[0]))
        return tuple(value)
