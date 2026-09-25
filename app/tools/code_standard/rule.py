"""Правила эталона кода и признаки нарушений (REFACTORING_STANDARD.md §5).

Код правила (`E1`) — ключ раздела реестра долгов и исключений; подписи для человека — в `messages_ru`.
"""
from __future__ import annotations

from enum import Enum

from app.ui import messages_ru as msg


class Rule(str, Enum):
    """Правило эталона; порядок членов — порядок строк отчёта и разделов реестра."""

    FREE_FUNCTIONS = "E1"
    STATIC_METHODS = "E2"
    DEFINITION_LENGTH = "E3"
    PARAMETERS = "E4"
    BODY_LITERALS = "E5"
    CYRILLIC_IN_CODE = "E6"
    EXCEPTION_TEXT = "E7"
    ONE_DECLARATION = "E8"
    PATTERNS = "E9"
    LOGGERS = "E10"
    STRUCTURAL_CLONES = "E11"
    EMPTY_WRAPPERS = "E12"
    STATE_TUPLES = "E13"
    RAW_DATA = "E14"
    DEFENSIVE_CASTS = "E15"
    LAYERS = "E16"
    TIME = "E17"
    SIZES = "E18"
    PACKAGE_INIT = "E19"
    TESTS = "E20"
    REPEATED_NAMES = "E21"

    @classmethod
    def codes(cls) -> frozenset[str]:
        """Коды всех правил: допустимые ключи разделов реестра и исключений."""
        return frozenset(rule.value for rule in cls)

    @property
    def label(self) -> str:
        """Подпись правила для человека."""
        return msg.CODE_STANDARD_RULE_LABELS[self.value]

    @property
    def order(self) -> int:
        """Место правила в перечислении: E2 идёт раньше E10."""
        return tuple(type(self)).index(self)


class Sign(str, Enum):
    """Признак нарушения внутри правила: виден в отчёте разбивкой и в `--files`; в ключ реестра входит только у E20."""

    NAMES_APP_CLASS = "names_app_class"        # E1 (а): в аннотациях назван класс app
    ONE_CLASS_USE = "one_class_use"            # E1 (б): все использования — в одном классе того же модуля
    UNUSED = "unused"                          # E1 (в): в коде app никто не использует
    FORWARDING = "forwarding"                  # E12 (а): пересылка параметров как есть
    TWO_LAYERS = "two_layers"                  # E12 (б): `return self._<имя>()`
    FOREIGN_BODY = "foreign_body"              # E12 (в): тело — вызов свободной функции без других пользователей
    MODULE = "module"                          # E18: модуль длиннее предела
    CLASS = "class"                            # E18: класс больше предела членов
    NUMBER = "number"                          # E5: числовой литерал
    LOG = "log"                                # E5: строка лога
    SEPARATOR = "separator"                    # E5: строка из пробелов и знаков препинания
    IDENTIFIER = "identifier"                  # E5: одно слово-идентификатор
    TEXT = "text"                              # E5: прочий текст
    TEXT_CONSTANT = "text_constant"            # E8: строка объявлена в нескольких модулях
    NUMBER_CONSTANT = "number_constant"        # E8: число под тем же именем в нескольких модулях
    REPEATED_PATTERN = "repeated_pattern"      # E9: шаблон объявлен больше одного раза
    PATTERN_IN_FUNCTION = "pattern_in_function"  # E9: шаблон-литерал внутри функции
    AREA_MISSING = "area_missing"              # E10: `get_logger` без члена `LogArea`
    RAW_LOGGER = "raw_logger"                  # E10: `logging.getLogger` вне пакета логов
    EDGE = "edge"                              # E16: импорт между пакетами против карты
    RING = "ring"                              # E16: кольцо импорта модулей
    UNMAPPED = "unmapped"                      # E16: пакета нет в карте слоёв
    TEST_IMPORT = "test_import"                # E20: модуль тестов импортирует другой модуль тестов
    LOGGER_NAME = "logger_name"                # E20: строка с именем логгера
    PRIVATE_PATCH = "private_patch"            # E20: подмена приватного имени
    GLOBAL_PATCH = "global_patch"              # E20: подмена глобальных `os` / `shutil`
    DATACLASS_REPLACE = "dataclass_replace"    # E20: `dataclasses.replace` вне общих заготовок тестов

    @property
    def label(self) -> str:
        """Подпись признака для человека."""
        return msg.CODE_STANDARD_SIGN_LABELS[self.value]
