"""Каналы вкладки «Эфиры YouTube» без окна (CLAUDE.md §8.2 п.4).

Вкладка держит список каналов, каким он будет записан, и то, каким он прочитан с диска. Своих правил
проверки у неё нет: каждая правка переводит весь будущий список в данные channels.json и разбирает его
тем же разбором, что читает файл (`ChannelsFile.parse`); ошибка разбора и есть проблема поля. Список может быть
пустым (§14 решение 69): удаляется и последний канал; что каналов нет, говорит строка готовности линии «Эфиры YouTube».
Пишет только файл каналов (`ChannelsFile.save`): прежний файл уходит в channels.previous.json, свой JSON вкладка не
собирает.

API вкладки тот же, что у остальных моделей вкладок: `title`, `notices`, `is_dirty`, `save`. Вкладка неизменяемая:
`add`, `update`, `remove` и `save` отдают новую, прежняя остаётся тем, чем была; каналы списка уже прошли разбор,
поэтому `remove` и `save` отказов не знают. Окно Tk только рисует её ответы; библиотека окна сюда не импортируется,
ничего не печатается.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from app.config.channel import ChannelConfig, ChannelsFileKey, ConfiguredChannels
from app.config.files import ChannelsFile
from app.config.json_node import ConfigError, SettingProblem
from app.paths import LivecraftPaths
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.page import SetupPage
from app.setup.panels.panel_edit import PanelEdit
from app.ui.messages import msg


@dataclass(frozen=True)
class ChannelsPanel:
    """Каналы вкладки «Эфиры YouTube».

    `channels` — список, каким он будет записан; каждый канал уже прошёл разбор. `loaded` — как прочитано
    с диска (None — не прочитано). `load_problem` — почему файл не прочитан; файла нет — не проблема: каналов
    просто нет. `file` — файл каналов: его разбор проверяет правки, и ошибки те же, что у загрузки файла.
    """

    channels: tuple[ChannelConfig, ...]
    loaded: tuple[ChannelConfig, ...] | None
    load_problem: SettingProblem | None
    file: ChannelsFile

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> ChannelsPanel:
        """Вкладка на channels.json этой установки."""
        return cls.from_file(ChannelsFile.of(paths))

    @classmethod
    def from_file(cls, file: ChannelsFile) -> ChannelsPanel:
        """Прочитать файл каналов. Нет файла — вкладка без каналов; не прочитался — без каналов и с причиной от
        разбора."""
        try:
            channels: tuple[ChannelConfig, ...] = file.load().channels
        except ConfigError as error:
            problem: SettingProblem | None = (
                None if error.is_file_missing else SettingProblem(key=error.key_path, text=error.problem)
            )
            return cls(channels=(), loaded=None, load_problem=problem, file=file)
        return cls(channels=channels, loaded=channels, load_problem=None, file=file)

    @property
    def title(self) -> str:
        return SetupPage.BROADCASTS.title

    @property
    def drafts(self) -> tuple[ChannelDraft, ...]:
        """Строки таблицы каналов текстом — что окно показывает и отдаёт обратно на правку."""
        return tuple(ChannelDraft.of(channel) for channel in self.channels)

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённое: список отличается от прочитанного (не прочитано — от пустого)."""
        return self.channels != (self.loaded if self.loaded is not None else ())

    @property
    def notices(self) -> tuple[str, ...]:
        """Строки вкладки для человека: файл не прочитался."""
        if self.load_problem is None:
            return ()
        return (msg.SETUP_CHANNELS_NOTICE_UNREADABLE.format(key=self.load_problem.key, problem=self.load_problem.text),)

    def add(self, draft: ChannelDraft) -> PanelEdit[ChannelsPanel]:
        """Добавить канал в конец списка."""
        return self._edit([*self._data, draft.to_data()])

    def update(self, index: int, draft: ChannelDraft) -> PanelEdit[ChannelsPanel]:
        """Заменить канал с номером index. Номера нет — IndexError: это ошибка окна, а не ввода."""
        data: list[dict[str, object]] = self._data
        data[index] = draft.to_data()
        return self._edit(data)

    def remove(self, index: int) -> ChannelsPanel:
        """Убрать канал с номером index; остальные каналы годны и так, пустой список — тоже."""
        channels: list[ChannelConfig] = list(self.channels)
        del channels[index]
        return dataclasses.replace(self, channels=tuple(channels))

    def save(self) -> PanelEdit[ChannelsPanel]:
        """Записать список через загрузчик, в том числе пустой, и вернуть вкладку, прочитанную заново (отказа нет).

        OSError — наружу: сказать о нём человеку — дело окна.
        """
        self.file.save(ConfiguredChannels(channels=self.channels))
        return PanelEdit(panel=ChannelsPanel.from_file(self.file))

    @property
    def _data(self) -> list[dict[str, object]]:
        """Текущий список как данные channels.json."""
        return [channel.to_data() for channel in self.channels]

    def _edit(self, data: list[dict[str, object]]) -> PanelEdit[ChannelsPanel]:
        """Разобрать будущий список разбором файла: годен — новая вкладка с его каналами (NFC), иначе — та же.

        Проблема строки — путь внутри канала (`channels[i].поле` → `поле`).
        """
        try:
            channels: tuple[ChannelConfig, ...] = self.file.parse({ChannelsFileKey.CHANNELS.value: data}).channels
        except ConfigError as error:
            problem: SettingProblem = SettingProblem(key=error.key.within_item.text, text=error.problem)
            return PanelEdit(panel=self, problem=problem)
        return PanelEdit(panel=dataclasses.replace(self, channels=channels))
