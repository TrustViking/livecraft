"""Выбор языков канала на вкладке «Каналы YouTube» (CLAUDE.md §8.2 п.2, §6 инвариант 2).

Человек выбирает язык по названию, а не по коду ISO (Предназначение, п. 4): `LanguageCatalog` — все языки
справочника pycountry с двухбуквенным кодом, названия — русские из его каталога переводов `iso639-3`,
а где перевода нет — английские. Языки формы ключей идут первыми и помечены: в форму уходят только её
варианты, и эфир на языке не из формы допущен не будет. `LanguageSelection` — выбранные коды в порядке
выбора; фильтр поиска выбор не сбрасывает. Tk здесь нет: окно только рисует эти объекты.
"""
from __future__ import annotations

import gettext
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Final

import pycountry

from app.setup.fields.channel_draft import LANGUAGES_DISPLAY_JOINER, LANGUAGES_SEPARATOR
from app.ui import messages_ru as msg

TRANSLATION_DOMAIN: Final[str] = "iso639-3"
TRANSLATION_LOCALE: Final[str] = "ru"
ALPHA_2: Final[str] = "alpha_2"
SORT_REPLACEMENTS: Final[dict[str, str]] = {"ё": "е"}     # «ё» в кодовой таблице стоит после «я»


@dataclass(frozen=True)
class LanguageOption:
    """Один язык списка: код ISO 639-1, название для человека и есть ли он среди вариантов формы."""

    code: str
    name: str
    in_form: bool
    is_translated: bool          # название русское; иначе — английское из справочника

    @property
    def label(self) -> str:
        """Строка списка: «русский (ru)», у языков формы — с пометкой."""
        template: str = msg.SETUP_LANGUAGE_OPTION_IN_FORM if self.in_form else msg.SETUP_LANGUAGE_OPTION
        return template.format(name=self.name, code=self.code)

    @property
    def sort_key(self) -> tuple[bool, str]:
        """Порядок языков не из формы: сначала с русским названием по алфавиту, затем с английским."""
        name: str = self.name.casefold()
        for source, target in SORT_REPLACEMENTS.items():
            name = name.replace(source, target)
        return (not self.is_translated, name)

    def matches(self, text: str) -> bool:
        """Подходит к строке поиска: часть названия или кода, без регистра."""
        needle: str = text.strip().casefold()
        return not needle or needle in self.name.casefold() or needle in self.code.casefold()


@dataclass(frozen=True)
class LanguageCatalog:
    """Все языки списка в порядке показа: языки формы в порядке формы, затем остальные по алфавиту."""

    options: tuple[LanguageOption, ...]

    @classmethod
    def load(cls, form_codes: Iterable[str]) -> LanguageCatalog:
        """Справочник pycountry; код формы, которого в справочнике нет, — отдельной строкой с кодом вместо имени."""
        translation: gettext.NullTranslations = gettext.translation(
            TRANSLATION_DOMAIN, pycountry.LOCALES_DIR, languages=[TRANSLATION_LOCALE], fallback=True
        )
        known: dict[str, LanguageOption] = {}
        for language in pycountry.languages:
            code: str | None = getattr(language, ALPHA_2, None)
            if code is None:
                continue
            name: str = translation.gettext(language.name)
            known[code] = LanguageOption(
                code=code, name=name, in_form=False, is_translated=name != language.name
            )
        form: list[LanguageOption] = []
        for code in dict.fromkeys(form_codes):
            option: LanguageOption = known.pop(code, None) or cls._unknown(code)
            form.append(replace(option, in_form=True))
        rest: list[LanguageOption] = sorted(known.values(), key=lambda item: item.sort_key)
        return cls(options=(*form, *rest))

    @staticmethod
    def _unknown(code: str) -> LanguageOption:
        """Код, которого нет в справочнике: показывается как есть, чтобы выбор не терялся."""
        return LanguageOption(code=code, name=code, in_form=False, is_translated=False)

    @property
    def has_form(self) -> bool:
        """Языки формы известны: без них пометок нет и о языке не из формы сказать нечего."""
        return any(option.in_form for option in self.options)

    def including(self, codes: Iterable[str]) -> LanguageCatalog:
        """Каталог, в котором есть и эти коды: незнакомый код канала добавляется в конец, выбор не теряется."""
        present: set[str] = {option.code for option in self.options}
        extra: tuple[LanguageOption, ...] = tuple(
            self._unknown(code) for code in dict.fromkeys(codes) if code not in present
        )
        return self if not extra else LanguageCatalog(options=(*self.options, *extra))

    def search(self, text: str) -> tuple[LanguageOption, ...]:
        """Языки, подходящие к строке поиска, в порядке каталога; пустая строка — все."""
        return tuple(option for option in self.options if option.matches(text))

    def option(self, code: str) -> LanguageOption | None:
        return next((option for option in self.options if option.code == code), None)

    def name(self, code: str) -> str:
        """Название языка для человека; незнакомый код — сам код."""
        option: LanguageOption | None = self.option(code)
        return code if option is None else option.name

    def names(self, codes: Sequence[str]) -> str:
        """Языки канала названиями — для таблицы каналов."""
        return LANGUAGES_DISPLAY_JOINER.join(self.name(code) for code in codes)

    def foreign(self, codes: Sequence[str]) -> tuple[str, ...]:
        """Выбранные коды, которых нет среди вариантов формы; языки формы неизвестны — пусто."""
        if not self.has_form:
            return ()
        form_codes: set[str] = {option.code for option in self.options if option.in_form}
        return tuple(code for code in codes if code not in form_codes)


@dataclass(frozen=True)
class LanguageSelection:
    """Выбранные языки канала — коды в порядке выбора."""

    codes: tuple[str, ...]

    @classmethod
    def from_text(cls, text: str) -> LanguageSelection:
        """Языки из текста черновика канала («uk, ru»): тот же разделитель, что у черновика."""
        return cls(codes=tuple(dict.fromkeys(code for code in LANGUAGES_SEPARATOR.split(text) if code)))

    @property
    def text(self) -> str:
        """Текст поля языков черновика канала — в том виде, в каком его показывает черновик."""
        return LANGUAGES_DISPLAY_JOINER.join(self.codes)

    def with_visible(self, visible: Sequence[str], chosen: Iterable[str]) -> LanguageSelection:
        """Выбор после щелчка в отфильтрованном списке: видимые коды — как отмечено в списке, скрытые — как были.

        Прежний порядок сохраняется, новые коды — в конце.
        """
        shown: set[str] = set(visible)
        picked: set[str] = set(chosen)
        kept: list[str] = [code for code in self.codes if code not in shown or code in picked]
        added: list[str] = [code for code in visible if code in picked and code not in kept]
        return LanguageSelection(codes=(*kept, *added))
