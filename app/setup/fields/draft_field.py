"""Поле черновика вкладки настройщика: что за поле, знает модель, а не окно (CLAUDE.md §8.2).

`DraftField` называет поле черновика ключом файла (`SettingKey` или `ChannelKey`): по пути ключа окно берёт
подпись и подсказку поля, по тому же пути загрузчик называет проблему. Вид поля (`DraftKind`) решает и то,
каким виджетом окно его рисует, и то, во что введённое переводится для файла (`data`). Варианты выбора, их
подписи для человека и ширина поля — тоже поля модели: окно показывает подпись варианта, в черновик и файл
уходит сам вариант.

Своих проверок у поля нет: годность значения решает загрузчик файла. Текст, который не переводится в число,
уходит текстом — и загрузчик назовёт ошибку с именем поля.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, TypeAlias

from app.config.channel import ChannelHandle, ChannelKey
from app.config.setting_key import SettingKey
from app.core.text_format import SPACE

# Дробная часть числа в окне пишется как удобно человеку: «0,5» и «0.5» — одно число.
DECIMAL_COMMA: Final[str] = ","
DECIMAL_POINT: Final[str] = "."
# Запас в знаках у поля выбора сверх самой длинной подписи: знаки подписи шире среднего знака шрифта.
CHOICE_WIDTH_MARGIN: Final[int] = 2

# Значение поля черновика: текст, «да / нет» или коды языков канала.
DraftValue: TypeAlias = str | bool | tuple[str, ...]
# Значение переменной окна: текст поля ввода или состояние флажка.
ShownValue: TypeAlias = str | bool


class DraftKind(str, Enum):
    """Вид поля: какой виджет его рисует и во что введённое переводится для файла."""

    TEXT = "entry"          # поле ввода; пробелы по краям срезаются
    INTEGER = "integer"     # поле ввода целого числа
    NUMBER = "number"       # поле ввода числа, дробная часть — через точку или запятую
    FLAG = "flag"           # «да / нет»: ползунок
    CHOICE = "choice"       # выбор из вариантов модели
    HANDLE = "handle"       # ник канала: «@» в начале дописывается
    LANGUAGE = "language"   # язык канала: выбор из списка языков с поиском


@dataclass(frozen=True)
class DraftField:
    """Поле черновика: ключ файла, вид, варианты выбора, их подписи (пусто — показываются сами варианты) и ширина в
    знаках (None — ширина виджета по умолчанию; поле выбора не уже своих подписей — `input_width`).

    Имя поля в черновике — имя члена ключа строчными (`SettingKey.LLM_MODEL` → `llm_model`).
    """

    key: SettingKey | ChannelKey
    kind: DraftKind
    choices: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    width: int | None = None

    @property
    def name(self) -> str:
        """Имя поля в черновике."""
        return self.key.name.lower()

    @property
    def key_path(self) -> str:
        """Путь ключа в файле: по нему подпись, подсказка и проблема поля."""
        return self.key.value

    @property
    def options(self) -> tuple[str, ...]:
        """Что окно предлагает на выбор: подписи вариантов, а без них — сами варианты."""
        return self.labels or self.choices

    @property
    def input_width(self) -> int | None:
        """Ширина поля в знаках: у выбора — не уже самой длинной подписи варианта, иначе — `width`."""
        if not self.options:
            return self.width
        return max(self.width or 0, max(len(option) for option in self.options) + CHOICE_WIDTH_MARGIN)

    def shown(self, value: DraftValue) -> ShownValue:
        """Значение черновика в переменной окна: коды языков — через пробел, вариант с подписью — подписью, прочее —
        как есть."""
        if isinstance(value, tuple):
            return SPACE.join(value)
        if self.labels and value in self.choices:
            return self.labels[self.choices.index(value)]
        return value

    def draft_value(self, shown: ShownValue) -> DraftValue:
        """Значение переменной окна в черновике: у языка — кортеж кодов, подпись варианта — сам вариант, прочее — как
        есть."""
        if self.kind is DraftKind.LANGUAGE and isinstance(shown, str):
            return tuple(shown.split())
        if shown in self.labels:
            return self.choices[self.labels.index(shown)]
        return shown

    def data(self, value: DraftValue) -> object:
        """Значение для файла: текст без пробелов по краям, число — числом, ник — с «@», языки — списком."""
        if not isinstance(value, str):
            return list(value) if isinstance(value, tuple) else value
        if self.kind is DraftKind.INTEGER:
            return self._integer(value)
        if self.kind is DraftKind.NUMBER:
            return self._number(value)
        if self.kind is DraftKind.HANDLE:
            return self._handle(value.strip())
        return value.strip()

    def _integer(self, text: str) -> int | str:
        """Целое из текста поля; не вышло — текст как есть, на ошибку загрузчика."""
        try:
            return int(text.strip())
        except ValueError:
            return text

    def _number(self, text: str) -> float | str:
        """Число, запятая допустима; nan и бесконечность — тоже числом, не число — текстом.

        Конечность и минимум проверяет только загрузчик: у него точный текст на каждый случай.
        """
        try:
            return float(text.strip().replace(DECIMAL_COMMA, DECIMAL_POINT))
        except ValueError:
            return text

    def _handle(self, text: str) -> str:
        """Ник с «@» в начале; пустой ввод остаётся пустым, чтобы загрузчик назвал его пустым, а не коротким."""
        if not text or text.startswith(ChannelHandle.PREFIX):
            return text
        return ChannelHandle.PREFIX + text
