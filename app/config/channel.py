"""Каналы `secrets\\channels.json` (CLAUDE.md §5, §6 инвариант 5, §8.2 п.2).

Файл заполняет оператор или настройщик: шесть полей на канал (`ChannelKey`). Ключ канала — ник: правило ника
(форма Unicode, «@», длина, символы, сравнение без регистра) держит `ChannelHandle`, им же пользуется и контур B.
Канал сам говорит, что с ним не так (`ChannelConfig.problem`), список каналов — повтор ника
(`ConfiguredChannels.problem`) и какие языки каналы обслуживают (`served_languages`). Площадки v1 — только YouTube.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final

from app.config.json_node import JsonNode, SettingProblem, allowed_values, json_value
from app.core.language_code import LanguageCode
from app.core.text_format import SPACE
from app.ui import messages_ru as msg

UNICODE_FORM: Final[str] = "NFC"
CONTROL_CHAR_LIMIT: Final[int] = 32
# account_name — название канала для людей и формы; одинаковые названия у разных каналов допустимы.
ACCOUNT_NAME_MAX_CHARS: Final[int] = 100   # предел названия канала на YouTube
# google_account — подсказка аккаунта при входе, а не проверка почты: ровно один «@», части непустые, без пробелов.
GOOGLE_ACCOUNT_SEPARATOR: Final[str] = "@"


class Platform(str, Enum):
    """Площадки v1 — только YouTube (§1). Facebook и Rumble — за пределами v1."""

    YOUTUBE = "youtube"


class Privacy(str, Enum):
    """Видимость эфиров канала — из channels.json (§6 инвариант 7)."""

    PUBLIC = "public"
    UNLISTED = "unlisted"


class ChannelsFileKey(str, Enum):
    """Поля корня channels.json."""

    CHANNELS = "channels"


class ChannelKey(str, Enum):
    """Поля канала в channels.json, в порядке файла; значение — имя поля внутри канала."""

    PLATFORM = "platform"
    ACCOUNT_NAME = "account_name"
    HANDLE = "handle"
    GOOGLE_ACCOUNT = "google_account"
    LANGUAGES = "languages"
    PRIVACY = "privacy"

    @classmethod
    def leaves(cls) -> tuple[str, ...]:
        return tuple(key.value for key in cls)


@dataclass(frozen=True)
class ChannelHandle:
    """Ник канала (@handle) — ключ канала: уникален на YouTube и не зависит от регистра (§6 инвариант 5).

    `text` — ник как в файле (форма NFC): по нему назван файл токена и его вводят в `--auth`. `key` — его
    единственная нормализация: ключ всех словарей, кешей и группировок по каналу.
    """

    PREFIX: ClassVar[str] = "@"
    MIN_CHARS: ClassVar[int] = 3
    MAX_CHARS: ClassVar[int] = 30
    FORBIDDEN_CHARS: ClassVar[str] = '<>:"/\\|?*'

    text: str

    @classmethod
    def of(cls, raw: str) -> ChannelHandle:
        """Ник в одной форме Unicode: «й» одним символом и «и» + знак — один ник."""
        return cls(text=unicodedata.normalize(UNICODE_FORM, raw))

    @property
    def key(self) -> str:
        """Без «@» и без различия регистра."""
        return self.text.removeprefix(self.PREFIX).casefold()

    @property
    def problem(self) -> str | None:
        """None — ник годится; иначе что именно не так. Той же проверкой проходит ник, который программа
        сама пишет в channels.json при выравнивании."""
        if not self.text.startswith(self.PREFIX):
            return msg.CONFIG_PROBLEM_HANDLE_PREFIX.format(value=self.text, prefix=self.PREFIX)
        body: str = self.text[len(self.PREFIX):]
        if not self.MIN_CHARS <= len(body) <= self.MAX_CHARS:
            return msg.CONFIG_PROBLEM_HANDLE_LENGTH.format(
                value=self.text, minimum=self.MIN_CHARS, maximum=self.MAX_CHARS, length=len(body)
            )
        for char in body:
            if char.isspace() or ord(char) < CONTROL_CHAR_LIMIT or char in self.FORBIDDEN_CHARS:
                return msg.CONFIG_PROBLEM_HANDLE_CHAR.format(value=self.text, char=repr(char))
        return None


@dataclass(frozen=True)
class ChannelConfig:
    """Ровно шесть полей channels.json. handle — ник как в файле; key — ключ канала (`ChannelHandle.key`).
    google_account — почта аккаунта Google канала: подсказка браузеру при входе.
    """

    platform: Platform
    account_name: str
    handle: str
    google_account: str
    languages: tuple[str, ...]
    privacy: Privacy

    @classmethod
    def from_node(cls, node: JsonNode) -> ChannelConfig:
        """Канал из объекта списка: сначала вид каждого поля, затем смысл (`problem`) — ошибка с путём поля."""
        node.mapping(ChannelKey.leaves())
        channel: ChannelConfig = cls(
            platform=cls._platform(node.field(ChannelKey.PLATFORM.value)),
            account_name=unicodedata.normalize(UNICODE_FORM, node.field(ChannelKey.ACCOUNT_NAME.value).text()),
            handle=ChannelHandle.of(node.field(ChannelKey.HANDLE.value).text()).text,
            google_account=node.field(ChannelKey.GOOGLE_ACCOUNT.value).text(),
            languages=cls._languages(node.field(ChannelKey.LANGUAGES.value)),
            privacy=node.field(ChannelKey.PRIVACY.value).choice(Privacy),
        )
        node.check(channel.problem)
        return channel

    def to_data(self) -> dict[str, Any]:
        """Канал как объект channels.json, поля в порядке ключей."""
        return {leaf: json_value(getattr(self, leaf)) for leaf in ChannelKey.leaves()}

    @property
    def key(self) -> str:
        """Ключ канала: единственная нормализация ника (§6 инвариант 5)."""
        return ChannelHandle.of(self.handle).key

    @property
    def problem(self) -> SettingProblem | None:
        """Что не так с каналом по смыслу — первое по порядку полей: название, ник, почта аккаунта."""
        checks: tuple[tuple[ChannelKey, str | None], ...] = (
            (ChannelKey.ACCOUNT_NAME, self._account_name_problem),
            (ChannelKey.HANDLE, ChannelHandle.of(self.handle).problem),
            (ChannelKey.GOOGLE_ACCOUNT, self._google_account_problem),
        )
        for key, text in checks:
            if text is not None:
                return SettingProblem(key=key.value, text=text)
        return None

    @property
    def _account_name_problem(self) -> str | None:
        """Название — не длиннее предела YouTube, без управляющих символов и пробелов по краям."""
        name: str = self.account_name
        if len(name) > ACCOUNT_NAME_MAX_CHARS:
            return msg.CONFIG_PROBLEM_ACCOUNT_NAME_TOO_LONG.format(maximum=ACCOUNT_NAME_MAX_CHARS, length=len(name))
        if any(ord(char) < CONTROL_CHAR_LIMIT for char in name):
            return msg.CONFIG_PROBLEM_ACCOUNT_NAME_CONTROL
        if name.startswith(SPACE) or name.endswith(SPACE):
            return msg.CONFIG_PROBLEM_ACCOUNT_NAME_SPACE_EDGE.format(value=name)
        return None

    @property
    def _google_account_problem(self) -> str | None:
        """Минимальная честная проверка почты: local@domain, обе части непустые, пробелов нет."""
        local, separator, domain = self.google_account.partition(GOOGLE_ACCOUNT_SEPARATOR)
        broken: bool = not separator or not local or not domain or GOOGLE_ACCOUNT_SEPARATOR in domain
        if broken or any(char.isspace() for char in self.google_account):
            return msg.CONFIG_PROBLEM_GOOGLE_ACCOUNT.format(value=self.google_account)
        return None

    @classmethod
    def _platform(cls, node: JsonNode) -> Platform:
        value: str = node.text()
        try:
            return Platform(value)
        except ValueError:
            problem: str = msg.CONFIG_PROBLEM_PLATFORM_UNKNOWN.format(value=value, allowed=allowed_values(Platform))
            raise node.error(problem) from None

    @classmethod
    def _languages(cls, node: JsonNode) -> tuple[str, ...]:
        """Непустой список кодов ISO 639-1 из справочника pycountry без повторов.

        Код вне справочника («uk-ua», «ukr», «xx») канал молча оставил бы без слотов, поэтому он — проблема
        поля с первым негодным значением, а не тихий пропуск.
        """
        codes: tuple[Any, ...] = tuple(item.value for item in node.items(msg.CONFIG_PROBLEM_LANGUAGES))
        unknown: list[Any] = [code for code in codes if not isinstance(code, str) or not LanguageCode(code).is_known]
        if unknown:
            raise node.error(msg.CONFIG_PROBLEM_LANGUAGE_UNKNOWN.format(value=unknown[0]))
        repeated: list[str] = sorted({code for code in codes if codes.count(code) > 1})
        if repeated:
            raise node.error(msg.CONFIG_PROBLEM_LANGUAGE_DUPLICATE.format(value=repeated[0]))
        return codes


@dataclass(frozen=True)
class ChannelProblem:
    """Что не так со списком каналов: номер канала и проблема его поля."""

    index: int
    problem: SettingProblem


@dataclass(frozen=True)
class ConfiguredChannels:
    """Каналы файла по порядку: каждый уже годен сам по себе; список сам знает повтор ника и языки каналов."""

    channels: tuple[ChannelConfig, ...]

    @classmethod
    def from_node(cls, root: JsonNode) -> ConfiguredChannels:
        """Корень channels.json: непустой список каналов; повтор ника — ошибка у канала, который повторил."""
        root.mapping(tuple(key.value for key in ChannelsFileKey))
        items: tuple[JsonNode, ...] = root.field(ChannelsFileKey.CHANNELS.value).items(
            msg.CONFIG_PROBLEM_CHANNELS_EMPTY
        )
        configured: ConfiguredChannels = cls(channels=())
        for item in items:
            configured = cls(channels=(*configured.channels, ChannelConfig.from_node(item)))
            found: ChannelProblem | None = configured.problem
            if found is not None:
                items[found.index].check(found.problem)
        return configured

    @property
    def problem(self) -> ChannelProblem | None:
        """Ник — ключ канала: повтор без учёта регистра — проблема у повторившего канала. Названия могут совпадать."""
        for index, channel in enumerate(self.channels):
            for other in self.channels[:index]:
                if other.key == channel.key:
                    text: str = msg.CONFIG_PROBLEM_HANDLE_DUPLICATE.format(value=channel.handle, other=other.handle)
                    return ChannelProblem(index=index, problem=SettingProblem(key=ChannelKey.HANDLE.value, text=text))
        return None

    @property
    def served_languages(self) -> tuple[str, ...]:
        """Языки, которые обслуживают каналы, — без повторов, по алфавиту."""
        return tuple(sorted({language for channel in self.channels for language in channel.languages}))

    @property
    def by_handle(self) -> dict[str, ChannelConfig]:
        """Каналы по ключу ника (§6 инвариант 5)."""
        return {channel.key: channel for channel in self.channels}

    def to_data(self) -> dict[str, Any]:
        """Данные channels.json."""
        return {ChannelsFileKey.CHANNELS.value: [channel.to_data() for channel in self.channels]}
