"""Файлы конфигов на диске: чтение, разбор, текст и запись (CLAUDE.md §5).

`SettingsFile` — `secrets\\livecraft.json`, `ChannelsFile` — `secrets\\channels.json` (прежний файл при записи
уходит в `channels.previous.json`). Файл не читает поля сам: он отдаёт корень JSON объекту, который строит себя
(`LivecraftSettings.from_node`, `ConfiguredChannels.from_node`), и тем же разбором проверяет черновики настройщика
(`parse`). Текст файла собирает только `render`, пишет только `save` — атомарно.

`ConfigRead` — итог чтения одним значением: объект файла или `ConfigError`. `ShippedSettings` — поставочный вид
livecraft.json (ресурс программы): файла в git нет, программа кладёт его сама, когда его нет (`install_shipped`), а
раздел верхнего уровня, который добавила новая версия, дописывает в файл из шаблона (`complete_sections`). Раздел
`broadcasts` пишется поверх свежего файла одним правилом (`save_broadcasts`): его меняют и окно, и запуск.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Generic, TypeVar

from app.config.broadcasts import BroadcastSettings
from app.config.channel import ChannelConfig, ChannelKey, ConfiguredChannels, Platform, Privacy
from app.config.json_node import ConfigError, JsonNode, allowed_values
from app.config.setting_key import LegacySettingKey
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.text_format import NEWLINE, TEXT_ENCODING
from app.observability.log_event import LogEvent
from app.paths import FileName, LivecraftPaths, write_text_atomically
from app.resources.loader import TextResource
from app.ui.messages import msg

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
        return cls(path=paths.file(FileName.CONFIG))

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

    def save_broadcasts(self, broadcasts: BroadcastSettings) -> None:
        """Раздел broadcasts — поверх файла, как он сейчас на диске: переключатели окна (§14 решения 35, 36) и
        выключение повторной передачи после запуска не откатывают сохранённое другими. Сбой — OSError."""
        self.save(dataclasses.replace(self.latest, broadcasts=broadcasts))

    @property
    def latest(self) -> LivecraftSettings:
        """Настройки файла, как они сейчас на диске; файл не читается — поставочный вид.

        Поверх них вкладки окна пишут свои поля: сохранение одной вкладки не откатывает сохранённое другой.
        """
        fresh: LivecraftSettings | None = self.read().value
        return ShippedSettings().settings if fresh is None else fresh

    def complete_sections(self) -> tuple[str, ...]:
        """Дописать из поставочного шаблона разделы верхнего уровня, которых в файле нет; вернуть их имена.

        Раздел — целиком, как в шаблоне; поля внутри существующего раздела не дописываются: их отсутствие называет
        разбор. Файл, который не читается как объект JSON, не трогается — о нём тоже скажет разбор. Порядок полей —
        как в шаблоне, чужие поля файла остаются в конце (их назовёт разбор); запись атомарна.
        """
        data: dict[str, Any] | None = self._data()
        if data is None:
            return ()
        shipped: dict[str, Any] = ShippedSettings().data
        added: tuple[str, ...] = tuple(
            key for key, value in shipped.items() if isinstance(value, dict) and key not in data
        )
        if not added:
            return ()
        completed: dict[str, Any] = {
            key: data.get(key, value) for key, value in shipped.items() if key in data or key in added
        }
        completed.update({key: value for key, value in data.items() if key not in shipped})
        self._write_data(completed)
        return added

    def legacy_value(self, key: LegacySettingKey) -> str | None:
        """Значение ключа, которого в настройках больше нет, как оно лежит в файле (не строка — её текстом JSON); нет
        файла, раздела или ключа — None. Файл не разбирается: с таким ключом разбор его отвергает."""
        section: object = (self._data() or {}).get(key.section)
        if not isinstance(section, dict) or key.leaf not in section:
            return None
        value: object = section[key.leaf]
        return value if isinstance(value, str) else json.dumps(value)

    def drop_legacy(self, key: LegacySettingKey) -> None:
        """Убрать из файла ключ, которого в настройках больше нет; остальное — как есть, запись атомарна. Ключа нет —
        файл не трогается. Сбой — OSError."""
        data: dict[str, Any] | None = self._data()
        section: object = None if data is None else data.get(key.section)
        if data is None or not isinstance(section, dict) or key.leaf not in section:
            return
        self._write_data({**data, key.section: {leaf: value for leaf, value in section.items() if leaf != key.leaf}})

    def _data(self) -> dict[str, Any] | None:
        """Данные файла как они есть, без разбора; нет файла, не JSON или не объект — None."""
        try:
            data: object = JsonNode.read(self.path).value
        except ConfigError:
            return None
        return data if isinstance(data, dict) else None

    def _write_data(self, data: dict[str, Any]) -> None:
        """Данные файла — тем же видом, что у поставочного шаблона, атомарно."""
        text: str = json.dumps(data, indent=SETTINGS_FILE_INDENT, ensure_ascii=False)
        write_text_atomically(self.path, text + NEWLINE, TEXT_ENCODING)

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
        return cls(path=paths.file(FileName.CHANNELS), previous=paths.file(FileName.CHANNELS_PREVIOUS))

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
    def data(self) -> dict[str, Any]:
        """Данные шаблона JSON: из них файл дописывает недостающие разделы (`SettingsFile.complete_sections`)."""
        loaded: dict[str, Any] = json.loads(self.template)
        return loaded

    @property
    def settings(self) -> LivecraftSettings:
        return LivecraftSettings.from_node(JsonNode.parse(self.template, self.resource.path))

    @property
    def clock(self) -> Clock:
        """Часы в поясе шаблона: ими программа ставит отметки времени, пока настройки ещё не прочитаны."""
        return Clock(self.settings.zone)
