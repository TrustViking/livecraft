"""Файлы конфигов на диске: чтение, разбор, текст и запись (CLAUDE.md §5).

`SettingsFile` — `secrets\\livecraft.json`, `ChannelsFile` — `secrets\\channels.json` (прежний файл при записи
уходит в `channels.previous.json`). Файл не читает поля сам: он отдаёт корень JSON объекту, который строит себя
(`LivecraftSettings.from_node`, `ConfiguredChannels.from_node`), и тем же разбором проверяет черновики настройщика
(`parse`). Текст файла собирает только `render`, пишет только `save` — атомарно.

`ConfigRead` — итог чтения одним значением: объект файла или `ConfigError`. `ShippedSettings` — поставочный вид
livecraft.json (ресурс программы): файла в git нет, программа кладёт его сама, когда его нет (`install_shipped`).
"""
from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Generic, TypeVar

from app.config.channel import ChannelConfig, ChannelKey, ConfiguredChannels, Platform, Privacy
from app.config.json_node import ConfigError, JsonNode, allowed_values
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.text_format import NEWLINE, TEXT_ENCODING
from app.observability.log_event import LogEvent
from app.paths import LivecraftPaths, write_text_atomically
from app.resources.loader import TextResource
from app.ui import messages_ru as msg

SHIPPED_SETTINGS_RESOURCE: Final[str] = "settings_shipped.json"
SETTINGS_FILE_INDENT: Final[int] = 2
# Как ChannelsFile.render раскладывает канал: первая строка — первые четыре поля, вторая — остальные.
CHANNEL_FIRST_LINE_FIELDS: Final[int] = 4
CHANNELS_FILE_HEAD: Final[str] = '{\n  "channels": [\n'
CHANNELS_FILE_TAIL: Final[str] = "\n  ]\n}\n"
CHANNEL_LINES: Final[str] = "    {{{first},\n     {second}}}"
CHANNEL_FIELD: Final[str] = "{key}: {value}"
CHANNEL_FIELD_JOINER: Final[str] = json.JSONEncoder.item_separator   # поля канала в строке — разделителем JSON
CHANNEL_JOINER: Final[str] = ",\n"

ValueT = TypeVar("ValueT")


class ConfigFileEvent(str, Enum):
    """События файлов конфигов в логе."""

    MISSING = "config_missing"


@dataclass(frozen=True)
class ConfigRead(Generic[ValueT]):
    """Итог чтения файла конфига: объект или ошибка — одно значение, а не пара полей у читателя."""

    value: ValueT | None
    error: ConfigError | None

    @classmethod
    def of(cls, load: Callable[[], ValueT]) -> ConfigRead[ValueT]:
        try:
            return cls(value=load(), error=None)
        except ConfigError as error:
            return cls(value=None, error=error)

    @property
    def is_missing(self) -> bool:
        """Файла нет — программа ещё не настроена, а не сломана."""
        return self.error is not None and self.error.is_file_missing

    @property
    def is_broken(self) -> bool:
        """Файл есть, но не читается или в нём ошибка."""
        return self.error is not None and not self.error.is_file_missing

    def log(self, logger: logging.Logger) -> None:
        """Нет файла — строка «не настроено»; сломан — строка ошибки с путём ключа и причиной."""
        if self.error is None:
            return
        if self.is_missing:
            LogEvent.of(ConfigFileEvent.MISSING, path=self.error.config_path).emit(logger)
            return
        self.error.event.emit(logger, logging.ERROR)


@dataclass(frozen=True)
class SettingsFile:
    """livecraft.json: чтение, разбор черновика, текст и атомарная запись."""

    path: Path

    @classmethod
    def of(cls, paths: LivecraftPaths) -> SettingsFile:
        return cls(path=paths.config_file)

    def load(self) -> LivecraftSettings:
        """Настройки из файла; нет файла или поля — ConfigError с путём."""
        return LivecraftSettings.from_node(JsonNode.read(self.path))

    def read(self) -> ConfigRead[LivecraftSettings]:
        return ConfigRead.of(self.load)

    def parse(self, data: Any) -> LivecraftSettings:
        """Уже собранные данные файла (черновик настройщика) → настройки; путь файла — только для ошибки."""
        return LivecraftSettings.from_node(JsonNode(value=data, source=self.path))

    def render(self, settings: LivecraftSettings) -> str:
        """Текст livecraft.json: тот же вид, что у поставочного файла.

        Только стандартный JSON: настройки после разбора конечны всегда, а объект, собранный в обход разбора
        с NaN или бесконечностью, даёт ValueError, а не файл, который другие программы не прочитают.
        """
        text: str = json.dumps(settings.to_data(), indent=SETTINGS_FILE_INDENT, ensure_ascii=False, allow_nan=False)
        return text + NEWLINE

    def save(self, settings: LivecraftSettings) -> None:
        """Новый livecraft.json — атомарно; копии прежнего нет (§5 такого файла не называет). Сбой — OSError."""
        write_text_atomically(self.path, self.render(settings), TEXT_ENCODING)

    def install_shipped(self) -> bool:
        """Нет файла — записать поставочный вид и вернуть True; файл есть — ничего не трогать, False.

        Пишется разобранный шаблон тем же `render`, что и у настройщика: негодный шаблон на диск не попадает,
        а текст файла совпадает с шаблоном байт в байт (тест держит это равенство). Существующий файл не
        трогается никогда: в нём настройки человека, а сломанный файл называет разбор.
        """
        if self.path.exists():
            return False
        self.save(ShippedSettings().settings)
        return True


@dataclass(frozen=True)
class ChannelsFile:
    """channels.json и копия прежнего файла: чтение, разбор черновика, текст и запись с копией."""

    path: Path
    previous: Path

    @classmethod
    def of(cls, paths: LivecraftPaths) -> ChannelsFile:
        return cls(path=paths.channels_file, previous=paths.channels_previous_file)

    def load(self) -> ConfiguredChannels:
        """Каналы из файла; нет файла, поля или повтор ника — ConfigError с путём."""
        return ConfiguredChannels.from_node(JsonNode.read(self.path))

    def read(self) -> ConfigRead[ConfiguredChannels]:
        return ConfigRead.of(self.load)

    def parse(self, data: Any) -> ConfiguredChannels:
        """Уже собранные данные файла (черновик настройщика) → каналы; путь файла — только для ошибки."""
        return ConfiguredChannels.from_node(JsonNode(value=data, source=self.path))

    def render(self, channels: ConfiguredChannels) -> str:
        """Текст channels.json в том виде, в каком его пишет человек: канал — две строки."""
        body: str = CHANNEL_JOINER.join(self._channel_lines(channel) for channel in channels.channels)
        return CHANNELS_FILE_HEAD + body + CHANNELS_FILE_TAIL

    def save(self, channels: ConfiguredChannels) -> None:
        """Прежний файл байт в байт — в `previous` (перезаписывается), если он есть; новый — атомарно.

        Сбой — OSError.
        """
        text: str = self.render(channels)
        if self.path.is_file():
            shutil.copyfile(self.path, self.previous)
        write_text_atomically(self.path, text, TEXT_ENCODING)

    @property
    def template_lines(self) -> tuple[str, ...]:
        """Что вписать в каждое поле и точный шаблон файла — для лога, когда файл сломан."""
        rules: tuple[str, ...] = tuple(
            line.format(
                languages=msg.CONFIG_LANGUAGES_RULE, privacy=allowed_values(Privacy), platform=allowed_values(Platform)
            )
            for line in msg.CONFIG_CHANNELS_FIELDS
        )
        return (*rules, msg.CONFIG_CHANNELS_TEMPLATE)

    def _channel_lines(self, channel: ChannelConfig) -> str:
        values: dict[str, Any] = channel.to_data()
        fields: list[str] = [self._field(key, values[key]) for key in ChannelKey.leaves()]
        first: str = CHANNEL_FIELD_JOINER.join(fields[:CHANNEL_FIRST_LINE_FIELDS])
        second: str = CHANNEL_FIELD_JOINER.join(fields[CHANNEL_FIRST_LINE_FIELDS:])
        return CHANNEL_LINES.format(first=first, second=second)

    def _field(self, key: str, value: Any) -> str:
        return CHANNEL_FIELD.format(key=json.dumps(key), value=json.dumps(value, ensure_ascii=False))


@dataclass(frozen=True)
class ShippedSettings:
    """Поставочный вид livecraft.json (§5) — ресурс программы без чьих-либо данных: ссылка на форму пуста (§14
    решение 16). Шаблон разбирается тем же разбором, что и файл; негодный шаблон — ConfigError, ошибка программы.
    """

    resource: TextResource = field(default_factory=lambda: TextResource(SHIPPED_SETTINGS_RESOURCE))

    @property
    def template(self) -> str:
        """Текст шаблона как в ресурсе."""
        return self.resource.body

    @property
    def settings(self) -> LivecraftSettings:
        return LivecraftSettings.from_node(JsonNode.parse(self.template, self.resource.path))

    @property
    def clock(self) -> Clock:
        """Часы в поясе шаблона: ими программа ставит отметки времени, пока настройки ещё не прочитаны."""
        return Clock(self.settings.zone)
