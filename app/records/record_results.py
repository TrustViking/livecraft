"""Результаты объекта в памяти — единственное, что программа читает из памяти обратно (CLAUDE.md §6 инварианты 0, 1a).

Эфир, поток и ключ, взятые с площадки, подтверждение формы и счёт отправок текущего ключа, которые форма не подтвердила
(`UnconfirmedSends`, §14 решение 49: одна такая отправка — ключ уйдёт повтором, две — сам больше не уйдёт). Задания из
памяти не берутся: что делать, каждый запуск решают свежая таблица или пакеты, форма и channels.json; истина о
существовании эфира и его ключе — YouTube.
Чтение терпимое, чтобы объект менялся без перестройки таблицы: неизвестные ключи игнорируются, отсутствующие и не той
формы — None. Ключ потока в памяти — полностью (secrets\\, как keys.txt); в строках лога — только маской.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from enum import Enum

from app.form.answers import FormAnswer


class AnswerKey(str, Enum):
    """Ключи подтверждённого ответа в JSON записи."""

    ENTRY_ID = "entry_id"
    TITLE = "title"
    VALUE = "value"


class ResultKey(str, Enum):
    """Поля результатов, которые читаются не как строка."""

    CONFIRMED_ANSWERS = "confirmed_answers"
    UNCONFIRMED = "unconfirmed"


class UnconfirmedKey(str, Enum):
    """Ключи счёта неподтверждённых отправок в JSON записи."""

    STREAM_KEY = "stream_key"
    FORM_URL = "form_url"
    COUNT = "count"


@dataclass(frozen=True)
class ConfirmedAnswer:
    """Ответ, который форма подтвердила: сравнивается entry_id → значение; вопрос — для человека."""

    entry_id: str
    title: str
    value: str

    @classmethod
    def of(cls, answer: FormAnswer) -> ConfirmedAnswer:
        """Из ответа, ушедшего в форму и подтверждённого ею."""
        return cls(entry_id=answer.entry_id, title=answer.title, value=answer.value)

    @classmethod
    def from_data(cls, raw: object) -> ConfirmedAnswer | None:
        """Ответ из JSON записи; без entry_id или значения — None, нет вопроса — пустой."""
        if not isinstance(raw, Mapping):
            return None
        entry_id: object = raw.get(AnswerKey.ENTRY_ID.value)
        title: object = raw.get(AnswerKey.TITLE.value)
        value: object = raw.get(AnswerKey.VALUE.value)
        if not isinstance(entry_id, str) or not isinstance(value, str):
            return None
        return cls(entry_id=entry_id, title=title if isinstance(title, str) else "", value=value)

    @classmethod
    def listed(cls, raw: object) -> tuple[ConfirmedAnswer, ...]:
        """Ответы из списка JSON записи; не список — ни одного, непонятные элементы пропускаются."""
        if not isinstance(raw, list):
            return ()
        answers: tuple[ConfirmedAnswer | None, ...] = tuple(cls.from_data(item) for item in raw)
        return tuple(answer for answer in answers if answer is not None)


@dataclass(frozen=True)
class UnconfirmedSends:
    """Сколько раз ключ потока уходил в форму (адрес formResponse) и форма это не подтвердила."""

    stream_key: str
    form_url: str
    count: int

    @classmethod
    def from_data(cls, raw: object) -> UnconfirmedSends | None:
        """Счёт из JSON записи; не объект, нет ключа, адреса или числа — None (счёта нет)."""
        if not isinstance(raw, Mapping):
            return None
        stream_key, form_url, count = (raw.get(key.value) for key in UnconfirmedKey)
        if not isinstance(stream_key, str) or not isinstance(form_url, str) or type(count) is not int:
            return None
        return cls(stream_key=stream_key, form_url=form_url, count=count)

    def of_key(self, stream_key: str, form_url: str) -> int:
        """Счёт этого ключа в этой форме; другой ключ или другая форма — ни одной отправки."""
        return self.count if self.stream_key == stream_key and self.form_url == form_url else 0


@dataclass(frozen=True)
class RecordResults:
    """Что память знает о результатах объекта; все поля необязательные. Моменты — DD-MM-YYYY HH:MM по поясу программы."""

    broadcast_id: str | None = None
    broadcast_url: str | None = None
    stream_id: str | None = None
    stream_url: str | None = None
    stream_key: str | None = None
    published_at: str | None = None
    confirmed_stream_key: str | None = None
    confirmed_form_url: str | None = None      # formResponse формы, которая подтвердила
    confirmed_answers: tuple[ConfirmedAnswer, ...] = ()
    confirmed_at: str | None = None
    thumbnail_broadcast_id: str | None = None  # эфир, которому программа поставила обложку
    thumbnail_set_at: str | None = None
    unconfirmed: UnconfirmedSends | None = None  # отправки текущего ключа, которые форма не подтвердила

    def unconfirmed_sends(self, stream_key: str | None, form_url: str) -> int:
        """Сколько раз этот ключ уходил в эту форму без подтверждения; ключа нет, другой ключ или форма — ни разу."""
        if not stream_key or self.unconfirmed is None:
            return 0
        return self.unconfirmed.of_key(stream_key, form_url)

    def with_unconfirmed_send(self, stream_key: str, form_url: str) -> RecordResults:
        """Ещё одна отправка ключа в форму без подтверждения: счёт этого ключа в этой форме +1, прежний счёт другого
        ключа или формы — заменяется."""
        count: int = self.unconfirmed_sends(stream_key, form_url) + 1
        return replace(self, unconfirmed=UnconfirmedSends(stream_key=stream_key, form_url=form_url, count=count))

    def confirms_key(self, stream_key: str | None) -> bool:
        """Подтверждение есть и оно про этот ключ (адрес и ответы не сравниваются)."""
        return bool(stream_key) and self.confirmed_stream_key == stream_key

    def to_data(self) -> dict[str, object]:
        """Поля для JSON записи; ответы — списком."""
        data: dict[str, object] = asdict(self)
        data[ResultKey.CONFIRMED_ANSWERS.value] = [asdict(answer) for answer in self.confirmed_answers]
        return data

    @classmethod
    def from_data(cls, raw: object) -> RecordResults:
        """Неизвестные ключи игнорируются (и `is_bootstrap` прежних записей), отсутствующие и не той формы — None; не
        словарь — пустые результаты."""
        if not isinstance(raw, Mapping):
            return cls()
        special: frozenset[str] = frozenset(key.value for key in ResultKey)
        given: dict[str, object] = {item.name: raw.get(item.name) for item in fields(cls) if item.name not in special}
        texts: dict[str, str | None] = {name: value if isinstance(value, str) else None for name, value in given.items()}
        return cls(
            confirmed_answers=ConfirmedAnswer.listed(raw.get(ResultKey.CONFIRMED_ANSWERS.value)),
            unconfirmed=UnconfirmedSends.from_data(raw.get(ResultKey.UNCONFIRMED.value)),
            **texts,
        )
