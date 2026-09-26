"""Вкладка «Каналы YouTube» без окна (CLAUDE.md §8.2 п.2).

Вкладка держит список каналов, каким он будет записан, и то, каким он прочитан с диска. Своих правил
проверки у неё нет: каждая правка переводит весь будущий список в данные channels.json и разбирает его
тем же разбором, что читает файл (`ChannelsFile.parse`); ошибка разбора и есть проблема поля. Пишет только
файл каналов (`ChannelsFile.save`): прежний файл уходит в channels.previous.json, свой JSON вкладка не собирает.

API вкладки тот же, что у двух других моделей: `title`, `notices`, `is_dirty`, `save`. Вкладка неизменяемая:
`add`, `update`, `remove` и `save` отдают новую, прежняя остаётся тем, чем была. Окно Tk только рисует её
ответы; библиотека окна сюда не импортируется, ничего не печатается.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from app.config.channel import ChannelConfig, ChannelsFileKey, ConfiguredChannels
from app.config.files import ChannelsFile
from app.config.json_node import ConfigError, SettingProblem
from app.paths import LivecraftPaths
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.panels.panel_edit import PanelEdit
from app.ui import messages_ru as msg


@dataclass(frozen=True)
class ChannelsPanel:
    """Вкладка «Каналы YouTube».

    `channels` — список, каким он будет записан; каждый канал уже прошёл разбор. `loaded` — как прочитано
    с диска (None — не прочитано). `load_problem` — почему не прочитано; `is_file_missing` — потому что файла
    нет. `file` — файл каналов: его разбор проверяет правки, и ошибки те же, что у загрузки файла.
    """

    channels: tuple[ChannelConfig, ...]
    loaded: tuple[ChannelConfig, ...] | None
    load_problem: SettingProblem | None
    is_file_missing: bool
    file: ChannelsFile

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> ChannelsPanel:
        """Вкладка на channels.json этой установки."""
        return cls.from_file(ChannelsFile.of(paths))

    @classmethod
    def from_file(cls, file: ChannelsFile) -> ChannelsPanel:
        """Прочитать файл каналов. Не прочитался — вкладка без каналов и с причиной от разбора."""
        try:
            channels: tuple[ChannelConfig, ...] = file.load().channels
        except ConfigError as error:
            return cls(
                channels=(),
                loaded=None,
                load_problem=SettingProblem(key=error.key_path, text=error.problem),
                is_file_missing=error.is_file_missing,
                file=file,
            )
        return cls(channels=channels, loaded=channels, load_problem=None, is_file_missing=False, file=file)

    @property
    def title(self) -> str:
        return msg.SETUP_TAB_CHANNELS

    @property
    def drafts(self) -> tuple[ChannelDraft, ...]:
        """Строки таблицы каналов текстом — что окно показывает и отдаёт обратно на правку."""
        return tuple(ChannelDraft.of(channel) for channel in self.channels)

    @property
    def problem(self) -> SettingProblem | None:
        """Годен ли список к записи — по правилу загрузчика (пустой список, например, не годен)."""
        return self._edit(self._data).problem

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённое: список отличается от прочитанного (не прочитано — от пустого)."""
        return self.channels != (self.loaded if self.loaded is not None else ())

    @property
    def notices(self) -> tuple[str, ...]:
        """Строки вкладки для человека: файла нет или он не прочитался."""
        if self.is_file_missing:
            return (msg.SETUP_CHANNELS_NOTICE_FILE_MISSING,)
        if self.load_problem is not None:
            return (
                msg.SETUP_CHANNELS_NOTICE_UNREADABLE.format(key=self.load_problem.key, problem=self.load_problem.text),
            )
        return ()

    def add(self, draft: ChannelDraft) -> PanelEdit[ChannelsPanel]:
        """Добавить канал в конец списка."""
        return self._edit([*self._data, draft.to_data()])

    def update(self, index: int, draft: ChannelDraft) -> PanelEdit[ChannelsPanel]:
        """Заменить канал с номером index. Номера нет — IndexError: это ошибка окна, а не ввода."""
        data: list[dict[str, object]] = self._data
        data[index] = draft.to_data()
        return self._edit(data)

    def remove(self, index: int) -> ChannelsPanel:
        """Убрать канал с номером index. Остальные каналы годны и так; пустой список покажет `problem`."""
        channels: list[ChannelConfig] = list(self.channels)
        del channels[index]
        return dataclasses.replace(self, channels=tuple(channels))

    def save(self) -> PanelEdit[ChannelsPanel]:
        """Записать список через загрузчик и вернуть вкладку, прочитанную заново. Негоден — не пишет ничего.

        OSError — наружу: сказать о нём человеку — дело окна.
        """
        problem: SettingProblem | None = self.problem
        if problem is not None:
            return PanelEdit(panel=self, problem=problem)
        self.file.save(ConfiguredChannels(channels=self.channels))
        return PanelEdit(panel=ChannelsPanel.from_file(self.file))

    @property
    def _data(self) -> list[dict[str, object]]:
        """Текущий список как данные channels.json."""
        return [channel.to_data() for channel in self.channels]

    def _edit(self, data: list[dict[str, object]]) -> PanelEdit[ChannelsPanel]:
        """Разобрать будущий список разбором файла: годен — новая вкладка с его каналами (NFC), иначе — та же.

        Проблема строки — путь внутри канала (`channels[i].поле` → `поле`); путь без номера канала (весь список,
        например пустой) остаётся как есть.
        """
        try:
            channels: tuple[ChannelConfig, ...] = self.file.parse({ChannelsFileKey.CHANNELS.value: data}).channels
        except ConfigError as error:
            problem: SettingProblem = SettingProblem(key=error.key.within_item.text, text=error.problem)
            return PanelEdit(panel=self, problem=problem)
        return PanelEdit(panel=dataclasses.replace(self, channels=channels))
