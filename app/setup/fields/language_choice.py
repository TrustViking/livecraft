"""Выбор языка канала на вкладке «Эфиры YouTube» без окна (CLAUDE.md §8.2 п.4, §6 инвариант 2).

Человек выбирает язык по названию, а не по коду ISO (CLAUDE.md §1, «Поведение программы»): `LanguageDirectory` —
все языки справочника pycountry с двухбуквенным кодом, названия — на языке окна из его каталога переводов `iso639-3`,
а где перевода нет — английские. Языки формы ключей идут первыми и помечены: в форму уходят только её варианты, и
эфир на языке не из формы допущен не будет. Код вне справочника ISO 639-1 (вариант формы, язык старого
channels.json) тоже есть в списке — с пометкой: загрузчик такой код не примет.

`LanguagePicker` — поле выбора языка канала: что в нём написано, какие коды у канала и что об этом сказать. У
канала ровно один язык (§14 решение 21): подпись из списка переводится обратно в код, любой другой текст —
строка поиска, которая сужает список, а на «добавить» — проблема поля. У канала, записанного раньше с
несколькими языками, остаётся первый. Tk здесь нет: окно только рисует эти объекты.
"""
from __future__ import annotations

import gettext
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Final

import pycountry

from app.config.channel import ChannelKey
from app.config.json_node import SettingProblem
from app.core.alphabet import YO_FOLD
from app.core.sequence import unique_in_order
from app.ui.messages import UI_LANGUAGE, msg

TRANSLATION_DOMAIN: Final[str] = "iso639-3"
ALPHA_2: Final[str] = "alpha_2"


@dataclass(frozen=True)
class LanguageOption:
    """Один язык списка: код, название для человека, есть ли он среди вариантов формы и в справочнике ISO 639-1."""

    code: str
    name: str
    in_form: bool
    is_translated: bool          # название на языке окна; иначе — английское из справочника
    is_standard: bool = True     # код есть в справочнике ISO 639-1

    @classmethod
    def outside_standard(cls, code: str) -> LanguageOption:
        """Код, которого нет в справочнике: показывается как есть и с пометкой, чтобы выбор не терялся."""
        return cls(code=code, name=code, in_form=False, is_translated=False, is_standard=False)

    @property
    def label(self) -> str:
        """Строка списка: «русский (ru)»; у языков формы — с пометкой формы, у кода вне ISO 639-1 — с пометкой."""
        if not self.is_standard:
            template: str = msg.SETUP_LANGUAGE_OPTION_NOT_ISO_IN_FORM if self.in_form else msg.SETUP_LANGUAGE_OPTION_NOT_ISO
            return template.format(code=self.code)
        template = msg.SETUP_LANGUAGE_OPTION_IN_FORM if self.in_form else msg.SETUP_LANGUAGE_OPTION
        return template.format(name=self.name, code=self.code)

    @property
    def sort_key(self) -> tuple[bool, str]:
        """Порядок языков не из формы: сначала с переведённым названием по алфавиту, затем с английским."""
        name: str = self.name.casefold().translate(YO_FOLD)      # «ё» в кодовой таблице стоит после «я»
        return (not self.is_translated, name)

    def matches(self, text: str) -> bool:
        """Подходит к строке поиска: часть названия или кода, без регистра."""
        needle: str = text.strip().casefold()
        return not needle or needle in self.name.casefold() or needle in self.code.casefold()


@dataclass(frozen=True)
class LanguageDirectory:
    """Все языки списка в порядке показа: языки формы в порядке формы, затем остальные по алфавиту."""

    options: tuple[LanguageOption, ...]

    @classmethod
    def load(cls, form_codes: Iterable[str]) -> LanguageDirectory:
        """Справочник pycountry; код формы, которого в справочнике нет, — отдельной строкой с пометкой."""
        translation: gettext.NullTranslations = gettext.translation(
            TRANSLATION_DOMAIN, pycountry.LOCALES_DIR, languages=[UI_LANGUAGE.value], fallback=True
        )
        known: dict[str, LanguageOption] = {}
        for language in pycountry.languages:
            code: str | None = getattr(language, ALPHA_2, None)
            if code is None:
                continue
            name: str = translation.gettext(language.name)
            known[code] = LanguageOption(code=code, name=name, in_form=False, is_translated=name != language.name)
        form: list[LanguageOption] = []
        for code in unique_in_order(form_codes):
            option: LanguageOption = known.pop(code, None) or LanguageOption.outside_standard(code)
            form.append(replace(option, in_form=True))
        rest: list[LanguageOption] = sorted(known.values(), key=lambda item: item.sort_key)
        return cls(options=(*form, *rest))

    @property
    def has_form(self) -> bool:
        """Языки формы известны: без них пометок нет и о языке не из формы сказать нечего."""
        return any(option.in_form for option in self.options)

    def including(self, codes: Iterable[str]) -> LanguageDirectory:
        """Справочник, в котором есть и эти коды: незнакомый код канала добавляется в конец, выбор не теряется."""
        present: set[str] = {option.code for option in self.options}
        extra: tuple[LanguageOption, ...] = tuple(
            LanguageOption.outside_standard(code) for code in unique_in_order(codes) if code not in present
        )
        return self if not extra else LanguageDirectory(options=(*self.options, *extra))

    def search(self, text: str) -> tuple[LanguageOption, ...]:
        """Языки, подходящие к строке поиска, в порядке справочника; пустая строка — все."""
        return tuple(option for option in self.options if option.matches(text))

    def option(self, code: str) -> LanguageOption | None:
        return next((option for option in self.options if option.code == code), None)

    def label_of(self, code: str) -> str:
        """Подпись языка в поле выбора; незнакомый справочнику код — подписью с пометкой."""
        option: LanguageOption | None = self.option(code)
        return (LanguageOption.outside_standard(code) if option is None else option).label

    def code_of(self, label: str) -> str | None:
        """Код по точной подписи из поля выбора; любой другой текст — None."""
        return next((option.code for option in self.options if option.label == label), None)

    def labels(self, options: Iterable[LanguageOption]) -> tuple[str, ...]:
        """Подписи для значений поля выбора — в том порядке, в каком даны языки."""
        return tuple(option.label for option in options)

    def text_problem(self, text: str) -> SettingProblem | None:
        """Текст поля выбора, который не подпись языка, — проблема поля языка; пусто — не проблема выбора
        (что язык обязателен, скажет загрузчик)."""
        if not text.strip() or self.code_of(text) is not None:
            return None
        return SettingProblem(key=ChannelKey.LANGUAGES.value, text=msg.SETUP_LANGUAGE_PICK_FROM_LIST)

    def name(self, code: str) -> str:
        """Название языка для человека; незнакомый код — сам код."""
        option: LanguageOption | None = self.option(code)
        return code if option is None else option.name

    def names(self, codes: Sequence[str]) -> str:
        """Языки канала названиями — для таблицы каналов."""
        return msg.LIST_JOINER.join(self.name(code) for code in codes)

    def foreign(self, codes: Sequence[str]) -> tuple[str, ...]:
        """Выбранные коды, которых нет среди вариантов формы; языки формы неизвестны — пусто."""
        if not self.has_form:
            return ()
        form_codes: set[str] = {option.code for option in self.options if option.in_form}
        return tuple(code for code in codes if code not in form_codes)


@dataclass(frozen=True)
class LanguagePicker:
    """Поле выбора языка канала: справочник, коды канала в порядке записи и текст, который видит человек.

    Выбирается ровно один язык; лишние коды — только у канала из старого файла, пока его не пересохранят.
    Неизменяемое: каждое действие отдаёт новое поле.
    """

    directory: LanguageDirectory
    codes: tuple[str, ...] = ()
    text: str = ""

    @classmethod
    def of(cls, form_codes: Iterable[str]) -> LanguagePicker:
        """Пустое поле над всеми языками; языки формы — первыми и с пометкой."""
        return cls(directory=LanguageDirectory.load(form_codes))

    @property
    def first(self) -> str | None:
        """Язык, который остаётся у канала; языков нет — None."""
        return self.codes[0] if self.codes else None

    @property
    def chosen_label(self) -> str:
        """Подпись выбранного языка; языка нет — пусто."""
        first: str | None = self.first
        return "" if first is None else self.directory.label_of(first)

    @property
    def draft_codes(self) -> tuple[str, ...]:
        """Коды для черновика канала: ровно тот язык, что остаётся у канала."""
        return self.codes[:1]

    @property
    def is_label(self) -> bool:
        """В поле — подпись языка из списка."""
        return self.directory.code_of(self.text) is not None

    @property
    def is_search(self) -> bool:
        """В поле — строка поиска: не пусто и не подпись языка."""
        return bool(self.text.strip()) and not self.is_label

    @property
    def choices(self) -> tuple[str, ...]:
        """Строки списка: при поиске — подходящие языки, иначе — все."""
        found: tuple[LanguageOption, ...] = self.directory.search(self.text) if self.is_search else self.directory.options
        return self.directory.labels(found)

    @property
    def problem(self) -> SettingProblem | None:
        """Текст поля — не строка списка: черновик с ним модели не отдаётся."""
        return self.directory.text_problem(self.text)

    @property
    def note(self) -> str | None:
        """У канала из старого файла несколько языков: какой останется при сохранении."""
        first: str | None = self.first
        if first is None or len(self.codes) == 1:
            return None
        return msg.SETUP_LANGUAGE_SEVERAL.format(name=self.directory.name(first))

    @property
    def warning(self) -> str | None:
        """Язык не из формы: сохранению не мешает, но эфиры на нём допущены не будут (§6 инвариант 2)."""
        foreign: tuple[str, ...] = self.directory.foreign(self.draft_codes)
        return msg.SETUP_LANGUAGE_NOT_IN_FORM.format(names=self.directory.names(foreign)) if foreign else None

    def chose(self, codes: Sequence[str]) -> LanguagePicker:
        """Языки канала целиком (строка таблицы, новый канал): в поле — подпись первого; незнакомые коды —
        в справочник."""
        chosen: tuple[str, ...] = unique_in_order(codes)
        picker: LanguagePicker = LanguagePicker(directory=self.directory.including(chosen), codes=chosen)
        return replace(picker, text=picker.chosen_label)

    def typed(self, text: str) -> LanguagePicker:
        """Текст поля изменился: подпись из списка — выбор этого языка, пусто — языка нет, прочее — поиск.

        Подпись того же языка выбор не меняет: лишние коды старой записи остаются до сохранения.
        """
        code: str | None = self.directory.code_of(text)
        if code is None and text.strip():
            return replace(self, text=text)
        codes: tuple[str, ...] = self.codes if code == self.first else (() if code is None else (code,))
        return replace(self, codes=codes, text=text)

    def restored(self) -> LanguagePicker:
        """Набранное отброшено: в поле — подпись выбранного языка."""
        return replace(self, text=self.chosen_label)

    def including(self, codes: Iterable[str]) -> LanguagePicker:
        """Коды каналов таблицы — в справочник, чтобы их названия и подписи не терялись."""
        return replace(self, directory=self.directory.including(codes))

    def with_form(self, form_codes: Iterable[str], known_codes: Iterable[str]) -> LanguagePicker:
        """Варианты формы сменились: справочник заново с новыми пометками, выбор тот же, подпись — по новой форме."""
        directory: LanguageDirectory = LanguageDirectory.load(form_codes).including((*known_codes, *self.codes))
        return replace(self, directory=directory).chose(self.codes)
