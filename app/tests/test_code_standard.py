"""Замок эталона кода (app\\tools\\code_standard, REFACTORING_STANDARD.md §5, §6).

Реестр долгов `app\\tests\\data\\code_standard\\debt.json` может только сокращаться: новое или выросшее
нарушение роняет тест, снятое в коде, но оставшееся в реестре, — тоже (обновить реестр — `--write-debt`).
Чувствительность каждого правила держат образцы строками через `SourceTree.from_texts`.
"""
from __future__ import annotations

import ast
import io
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest

from app.tools.code_standard.check import StandardCheck
from app.tools.code_standard.command import CommandAction, CommandExit, CommandRequest, StandardCommand
from app.tools.code_standard.exemptions import Exceptions
from app.tools.code_standard.json_file import StandardFileError
from app.tools.code_standard.ledger import ChangeKind, Ledger, LedgerDiff
from app.tools.code_standard.locations import LockFiles
from app.tools.code_standard.measurement import Measurement, Measurements
from app.tools.code_standard.rule import Rule, Sign
from app.tools.code_standard.source import SourceKey, SourceTree
from app.tools.code_standard.standard import Standard
from app.ui import messages_ru as msg

LOCK: LockFiles = LockFiles.repository()
PACKAGE: SourceKey = SourceKey.of("app/tools/code_standard")
# С задачи R2.1b замок проверяет все правила эталона.
ACTIVE_RULES: frozenset[Rule] = frozenset(Rule)
# Правила, у которых ключ реестра — не путь: значение (E8, E9) или пакеты и кольцо (E16).
VALUE_KEYED_RULES: frozenset[Rule] = frozenset({Rule.ONE_DECLARATION, Rule.PATTERNS, Rule.LAYERS})
ALLOWED_APP_IMPORTS: tuple[str, ...] = ("app.tools.code_standard", "app.ui.messages_ru")
# Возможности Python 3.11+ — замок работает на 3.10 без пакетов проекта (REFACTORING_STANDARD.md §6).
PYTHON_FLOOR: tuple[int, int] = (3, 10)
NEW_PYTHON_NAMES: frozenset[str] = frozenset({"StrEnum", "tomllib", "Self", "UTC", "ExceptionGroup", "BaseExceptionGroup"})
NEW_PYTHON_NODES: frozenset[str] = frozenset({"TryStar", "TypeAlias", "TypeVar", "ParamSpec", "TypeVarTuple"})


@pytest.fixture(scope="session")
def standard() -> Standard:
    return Standard.load(LOCK.standard)


@pytest.fixture(scope="session")
def measured(standard: Standard) -> Measurements:
    """Дерево репозитория разбирается и замеряется один раз на сессию теста."""
    return StandardCheck(SourceTree.from_root(LOCK.root), standard).measure()


@pytest.fixture(scope="session")
def exceptions() -> Exceptions:
    return Exceptions.load(LOCK.exceptions)


@pytest.fixture(scope="session")
def ledger_diff(measured: Measurements, exceptions: Exceptions) -> LedgerDiff:
    return Ledger.load(LOCK.ledger).diff(Ledger.of(measured.without(exceptions.keys)))


def _measure(standard: Standard, texts: Mapping[str, str], rule: Rule) -> Measurement:
    return StandardCheck(SourceTree.from_texts(texts), standard).measure().of(rule)


# --- (а), (б), (в): код против реестра и исключений

def test_the_lock_measures_every_rule_and_the_ledger_covers_them(measured: Measurements) -> None:
    assert frozenset(measured.rules) == ACTIVE_RULES == frozenset(Rule)
    assert frozenset(Ledger.load(LOCK.ledger).rules) == frozenset(Rule)


def test_no_debt_appeared_or_grown(ledger_diff: LedgerDiff) -> None:
    lines: list[str] = [change.line for change in ledger_diff.growth]
    assert not lines, "\n".join([msg.CODE_STANDARD_GROWTH, *lines])


def test_the_ledger_has_no_stale_entries(ledger_diff: LedgerDiff) -> None:
    lines: list[str] = [change.line for change in ledger_diff.reduction]
    assert not lines, "\n".join([msg.CODE_STANDARD_STALE_ENTRIES, *lines])
    assert "--write-debt" in msg.CODE_STANDARD_STALE_ENTRIES


def test_every_exception_is_still_caught_and_justified(measured: Measurements, exceptions: Exceptions) -> None:
    assert exceptions.items
    assert exceptions.problems(measured) == ()
    assert all(item.reason.strip() for item in exceptions.items)


def test_an_exception_the_rule_no_longer_catches_is_a_problem(measured: Measurements) -> None:
    stale: Exceptions = Exceptions.parse('{"E2": {"app\\\\x.py::Gone.method": "было"}}', "exceptions.json")
    empty: Exceptions = Exceptions.parse(
        '{"E1": {"app\\\\core\\\\safe_trim.py::safe_trim_right": " "}}', "exceptions.json"
    )
    assert stale.problems(measured) == (msg.CODE_STANDARD_EXEMPTION_NOT_CAUGHT.format(rule="E2", key="app\\x.py::Gone.method"),)
    assert empty.problems(measured) == (
        msg.CODE_STANDARD_EXEMPTION_NO_REASON.format(rule="E1", key="app\\core\\safe_trim.py::safe_trim_right"),
    )


# --- (г): чувствительность каждого правила

# Чистый образец лежит в пакете карты слоёв (E16) и несёт модуль тестов без признаков E20.
CLEAN_SAMPLE: dict[str, str] = {
    "app/core/__init__.py": (
        '"""Пакет образца."""\nfrom __future__ import annotations\n\nfrom app.core.item import Item\n\n__all__ = ["Item"]\n'
    ),
    "app/core/item.py": (
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n\n\n"
        "def normalize(text: str) -> str:\n"
        "    return text.strip().lower()\n\n\n"
        "@dataclass(frozen=True)\n"
        "class Item:\n"
        "    name: str\n\n"
        "    @property\n"
        "    def key(self) -> str:\n"
        "        return normalize(self.name)\n\n"
        "    def names(self) -> tuple[str, ...]:\n"
        "        return (self.name,)\n"
    ),
    "app/core/user.py": "from app.core.item import normalize\n\nLABEL = normalize(' A ')\n",
    "app/tests/conftest.py": "SAMPLE = 'x'\n",
    "app/tests/test_item.py": (
        "from app.core.item import Item\nfrom app.tests.conftest import SAMPLE\n\n\n"
        "def test_item(monkeypatch):\n    monkeypatch.setattr(Item, 'public', 1)\n    assert Item(SAMPLE).key\n"
    ),
}


@pytest.mark.parametrize("rule", sorted(ACTIVE_RULES, key=lambda rule: rule.order))
def test_the_clean_sample_breaks_no_rule(standard: Standard, rule: Rule) -> None:
    assert dict(_measure(standard, CLEAN_SAMPLE, rule).values) == {}


def test_free_functions_are_caught_by_each_sign(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/shop/item.py": "class Item:\n    pass\n",
        "app/shop/free.py": (
            "from app.shop.item import Item\n"
            "def price(item: Item) -> int:\n    return 1\n"
            "def helper() -> int:\n    return 1\n"
            "def orphan() -> int:\n    return 1\n"
            "def shared() -> int:\n    return 1\n"
            "def plain(text: 'str') -> str:\n    return text\n"
            "class Box:\n    def run(self) -> int:\n        return helper() + shared() + len(plain(''))\n"
            "TOTAL = price(Item()) + shared()\n"
        ),
        "app/shop/user.py": "from app.shop.free import plain, shared\n",
        "app/tests/test_shop.py": "from app.shop.free import orphan\n\n\ndef test_orphan():\n    assert orphan()\n",
    }
    measurement: Measurement = _measure(standard, texts, Rule.FREE_FUNCTIONS)
    assert dict(measurement.values) == {
        "app\\shop\\free.py::helper": 1,
        "app\\shop\\free.py::orphan": 1,
        "app\\shop\\free.py::price": 1,
    }
    assert measurement.signs_of("app\\shop\\free.py::price") == (Sign.NAMES_APP_CLASS,)
    assert measurement.signs_of("app\\shop\\free.py::helper") == (Sign.ONE_CLASS_USE,)
    assert measurement.signs_of("app\\shop\\free.py::orphan") == (Sign.UNUSED,)


def test_a_class_named_through_a_module_alias_or_a_string_is_caught(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/shop/item.py": "class Item:\n    pass\n",
        "app/shop/free.py": (
            "from app.shop import item as shop_item\n"
            "def first(value: shop_item.Item) -> None:\n    return None\n"
            "def second(value: 'list[Local]') -> None:\n    return None\n"
            "class Local:\n    pass\n"
            "VALUES = (first, second)\n"
        ),
    }
    assert dict(_measure(standard, texts, Rule.FREE_FUNCTIONS).values) == {
        "app\\shop\\free.py::first": 1,
        "app\\shop\\free.py::second": 1,
    }


def test_static_methods_are_caught(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/s.py": (
            "class A:\n"
            "    @staticmethod\n    def f(x):\n        return x\n"
            "    @classmethod\n    def g(cls):\n        return cls\n"
            "    class Inner:\n        @staticmethod\n        def h():\n            return 0\n"
        ),
    }
    assert dict(_measure(standard, texts, Rule.STATIC_METHODS).values) == {"app\\s.py::A.Inner.h": 1, "app\\s.py::A.f": 1}


def test_long_definitions_are_caught_with_their_length(standard: Standard) -> None:
    limit: int = standard.max_definition_lines
    long_body: str = "".join("    x = 1\n" for _ in range(limit))
    ok_body: str = "".join("    x = 1\n" for _ in range(limit - 1))
    texts: dict[str, str] = {"app/s.py": f"def long():\n{long_body}\n\ndef fits():\n{ok_body}"}
    assert dict(_measure(standard, texts, Rule.DEFINITION_LENGTH).values) == {"app\\s.py::long": limit + 1}


def test_wide_signatures_are_caught_without_the_receiver(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/s.py": (
            "def wide(a, b, c, *args, **kwargs):\n    pass\n"
            "def keyword(a, b, c, d, *, e):\n    pass\n"
            "def fits(a, b, c, d):\n    pass\n"
            "class A:\n"
            "    def method(self, a, b, c, d):\n        pass\n"
            "    @classmethod\n    def build(cls, a, b, c, d):\n        pass\n"
            "    @staticmethod\n    def static(a, b, c, d, e):\n        pass\n"
        ),
    }
    assert dict(_measure(standard, texts, Rule.PARAMETERS).values) == {
        "app\\s.py::A.static": 5,
        "app\\s.py::keyword": 5,
        "app\\s.py::wide": 5,
    }


def test_empty_wrappers_are_caught_by_each_kind(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/s.py": (
            "from app.other import helper, Item\n"
            "def forward(a, b):\n    '''Докстрока не мешает.'''\n    return helper(b, a)\n"
            "def changed(a, b):\n    return helper(b + 1, a)\n"
            "def builtin(a):\n    return len(a)\n"
            "def build(a):\n    return Item(a)\n"
            "def private_rule(x):\n    return x * 2\n"
            "class C:\n"
            "    factor = 2\n"
            "    @property\n    def value(self):\n        return self._value()\n"
            "    def _value(self):\n        return 1\n"
            "    def doubled(self):\n        return private_rule(self.factor)\n"
            "    def uses_self(self, x):\n        return helper(self, x)\n"
            "    def argument(self, x):\n        return self._value(x)\n"
        ),
    }
    measurement: Measurement = _measure(standard, texts, Rule.EMPTY_WRAPPERS)
    assert dict(measurement.values) == {"app\\s.py::C.doubled": 1, "app\\s.py::C.value": 1, "app\\s.py::forward": 1}
    assert measurement.signs_of("app\\s.py::forward") == (Sign.FORWARDING,)
    assert measurement.signs_of("app\\s.py::C.value") == (Sign.TWO_LAYERS,)
    assert measurement.signs_of("app\\s.py::C.doubled") == (Sign.FOREIGN_BODY,)


def test_fixed_tuple_results_are_caught(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/s.py": (
            "def pair() -> tuple[int, str]:\n    pass\n"
            "def nested() -> 'tuple[int, tuple[str, ...]]':\n    pass\n"
            "def many() -> tuple[int, ...]:\n    pass\n"
            "def single() -> tuple[int]:\n    pass\n"
            "def argument(value: tuple[int, str]) -> None:\n    pass\n"
        ),
    }
    assert dict(_measure(standard, texts, Rule.STATE_TUPLES).values) == {"app\\s.py::nested": 1, "app\\s.py::pair": 1}


def test_large_modules_and_classes_are_caught(standard: Standard) -> None:
    long_module: str = "".join(f"X{index} = {index}\n" for index in range(standard.max_module_lines + 1))
    members: str = "".join(f"    def m{index}(self):\n        pass\n" for index in range(standard.max_class_members))
    texts: dict[str, str] = {
        "app/long.py": long_module,
        "app/ui/messages_ru.py": long_module,
        "app/big.py": f"class Big:\n    field: int\n{members}\nclass Fits:\n{members}",
    }
    measurement: Measurement = _measure(standard, texts, Rule.SIZES)
    assert dict(measurement.values) == {
        "app\\big.py::Big": standard.max_class_members + 1,
        "app\\long.py": standard.max_module_lines + 1,
    }
    assert measurement.signs_of("app\\long.py") == (Sign.MODULE,)
    assert measurement.signs_of("app\\big.py::Big") == (Sign.CLASS,)


def test_code_in_package_init_is_caught(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/pkg/__init__.py": (
            '"""Пакет."""\nfrom __future__ import annotations\nfrom app.pkg.mod import X\n__all__ = ["X"]\n'
            "VALUE = 1\ndef helper():\n    pass\n"
        ),
        "app/other/__init__.py": '"""Пакет."""\n',
    }
    assert dict(_measure(standard, texts, Rule.PACKAGE_INIT).values) == {"app\\pkg\\__init__.py": 2}


def test_a_name_defined_twice_is_caught_in_app_and_in_tests(standard: Standard) -> None:
    """Перенос `test_finder_reports_second_definition`: и тесты, и присваивание верхнего уровня."""
    texts: dict[str, str] = {
        "app/s.py": "def f(a, b):\n    pass\n\n\nclass C:\n    pass\n\n\ndef f(a):\n    pass\n",
        "app/tests/test_s.py": "LIMIT = 1\nLIMIT: int = 2\n",
    }
    assert dict(_measure(standard, texts, Rule.REPEATED_NAMES).values) == {
        "app\\s.py::f": 2,
        "app\\tests\\test_s.py::LIMIT": 2,
    }


def test_overloads_and_nested_names_are_not_repeats(standard: Standard) -> None:
    """Перенос `test_finder_ignores_overloads_and_nested_names`."""
    texts: dict[str, str] = {
        "app/s.py": (
            "import typing\n"
            "from typing import overload\n"
            "@overload\n"
            "def f(a: int) -> int: ...\n"
            "@typing.overload\n"
            "def f(a: str) -> str: ...\n"
            "def f(a):\n"
            "    return a\n"
            "class A:\n"
            "    def run(self): ...\n"
            "class B:\n"
            "    def run(self): ...\n"
        ),
    }
    assert dict(_measure(standard, texts, Rule.REPEATED_NAMES).values) == {}


def test_no_module_of_app_defines_a_name_twice(measured: Measurements) -> None:
    """Перенос `test_no_module_defines_a_name_twice`: весь app, включая тесты, без исключений."""
    assert dict(measured.of(Rule.REPEATED_NAMES).values) == {}


def test_body_literals_are_caught_by_kind(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/core/s.py": (
            "LIMIT = 'module level is not a body'\n"
            "@decorate('decorators are not counted')\n"
            "def f(text: 'Annotated' = 'dflt', size=2):\n"
            "    '''Докстрока не считается.'''\n"
            "    LOGGER.info('done', text)\n"
            "    joined = ', '.join(['name', 'two words', 'key=%s'])\n"
            "    width: 'Annotated' = 3 + 0 - 1\n"
            "    return f'x{text:>4}' + '' + str(-1)\n"
            "def outer():\n"
            "    def inner(value=0.5):\n"
            "        return 'inner'\n"
            "    return 'outer'\n"
            "def clean(flag=True, empty='', none=None):\n"
            "    return (0, 1, 1.0, flag, empty, none, ...)\n"
        ),
    }
    measurement: Measurement = _measure(standard, texts, Rule.BODY_LITERALS)
    assert dict(measurement.values) == {"app\\core\\s.py::f": 10, "app\\core\\s.py::outer": 1, "app\\core\\s.py::outer.inner": 2}
    assert dict(measurement.parts_of("app\\core\\s.py::f")) == {
        Sign.NUMBER: 2, Sign.LOG: 2, Sign.SEPARATOR: 1, Sign.IDENTIFIER: 3, Sign.TEXT: 2,
    }
    assert measurement.sign_counts()[Sign.NUMBER] == 3


def test_cyrillic_in_code_is_caught_outside_the_text_modules(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/core/s.py": (
            "'''Докстрока модуля не считается.'''\n"
            "LABEL = 'метка'\n"
            "def f():\n    '''Докстрока функции.'''\n    return f'итого {LABEL}'\n"
            "LATIN = 'label'\n"
        ),
        "app/ui/messages_ru.py": "TEXT = 'текст'\n",
        "app/core/alphabet.py": "LETTERS = 'абв'\n",
    }
    assert dict(_measure(standard, texts, Rule.CYRILLIC_IN_CODE).values) == {"app\\core\\s.py": 2}


def test_exception_texts_are_caught(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/core/s.py": (
            "def f(x):\n"
            "    if x:\n        raise ValueError('text')\n"
            "    if x > 1:\n        raise ValueError(f'{x}')\n"
            "    raise KindError(Reason.BAD, detail='named')\n"
            "def clean(x):\n"
            "    if x:\n        raise KindError(Reason.BAD)\n"
            "    raise ValueError(TEXT) from None\n"
            "raise RuntimeError('module level')\n"
        ),
    }
    assert dict(_measure(standard, texts, Rule.EXCEPTION_TEXT).values) == {"app\\core\\s.py": 1, "app\\core\\s.py::f": 3}


def test_one_value_one_declaration_counts_areas_apart(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/core/a.py": (
            "from enum import Enum, IntEnum\n"
            "SEP = ','\nLIMIT = 5\nlowercase = 'x'\nALONE = 'alone'\n"
            "class Kind(str, Enum):\n    COMMA = ','\n    DOT = '.'\n"
        ),
        "app/core/b.py": "COMMA: str = ','\nLIMIT = 5\nOTHER = 5\nlowercase = 'x'\nDOT = '.'\n",
        "app/core/c.py": "from enum import IntEnum\nclass Code(IntEnum):\n    LIMIT = 5\n",
        "app/tools/code_standard/x.py": "MARK = '!'\nSTAR = '*'\n",
        "app/tools/code_standard/y.py": "BANG = '!'\n",
        "app/core/d.py": "STAR = '*'\n",
    }
    measurement: Measurement = _measure(standard, texts, Rule.ONE_DECLARATION)
    assert dict(measurement.values) == {"','": 2, "'!'": 2, "LIMIT=5": 3}
    assert measurement.signs_of("','") == (Sign.TEXT_CONSTANT,)
    assert measurement.signs_of("LIMIT=5") == (Sign.NUMBER_CONSTANT,)
    assert measurement.sites_of("'!'") == frozenset({"app\\tools\\code_standard\\x.py", "app\\tools\\code_standard\\y.py"})
    assert dict(measurement.under((PACKAGE,)).values) == {"'!'": 2}


def test_patterns_are_caught_repeated_or_inside_functions(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/core/a.py": "import re\nSPACES = re.compile(r'\\s+')\ndef f(text):\n    return re.sub('x+', '', text)\n",
        "app/core/b.py": "import re\nclass C:\n    SPACES = re.compile(r'\\s+')\nONCE = re.compile(r'\\d+')\nBUILT = re.compile(PATTERN)\n",
        "app/core/c.py": "import re\nQUOTE = re.compile('q')\n",
        "app/tools/code_standard/x.py": "import re\nQUOTE = re.compile('q')\n",
    }
    measurement: Measurement = _measure(standard, texts, Rule.PATTERNS)
    assert dict(measurement.values) == {repr("\\s+"): 2, "app\\core\\a.py::f": 1}
    assert measurement.signs_of(repr("\\s+")) == (Sign.REPEATED_PATTERN,)
    assert measurement.signs_of("app\\core\\a.py::f") == (Sign.PATTERN_IN_FUNCTION,)


def test_loggers_are_caught(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/core/a.py": (
            "import logging\n"
            "from app.observability.logging_setup import LogArea, get_logger\n"
            "LOGGER = get_logger('sample.area')\nGOOD = get_logger(LogArea.CORE)\nRAW = logging.getLogger('x')\n"
        ),
        "app/core/b.py": "from app.observability import logging_setup\nGOOD = logging_setup.get_logger(LogArea.CORE)\n",
        "app/observability/logging_setup.py": "import logging\nROOT = logging.getLogger('root')\n",
    }
    measurement: Measurement = _measure(standard, texts, Rule.LOGGERS)
    assert dict(measurement.values) == {"app\\core\\a.py": 2}
    assert measurement.signs_of("app\\core\\a.py") == (Sign.AREA_MISSING, Sign.RAW_LOGGER)


FIRST_CLONE: str = (
    "def first(items, limit):\n"
    "    total = sum(item.size * 2 for item in items if item.size > limit)\n"
    "    names = [item.name.strip().lower() for item in items if item.name]\n"
    "    result = {'total': total, 'names': names, 'count': len(items)}\n"
    "    return result\n"
)
SECOND_CLONE: str = (
    "class Box:\n"
    "    def second(self, rows, floor):\n"
    "        if rows:\n"
    "            amount = sum(row.weight * 3 for row in rows if row.weight > floor)\n"
    "            labels = [row.title.strip().lower() for row in rows if row.title]\n"
    "            output = {'sum': amount, 'labels': labels, 'size': len(rows)}\n"
    "        return None\n"
)


def test_structural_clones_are_caught_across_functions(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/core/a.py": FIRST_CLONE,
        "app/core/b.py": SECOND_CLONE,
        "app/core/c.py": (
            "def small(a):\n    x = a\n    y = x\n    return y\n"
            "def other(a):\n    x = a\n    y = x\n    return y\n"
        ),
    }
    measurement: Measurement = _measure(standard, texts, Rule.STRUCTURAL_CLONES)
    key: str = "app\\core\\a.py::first | app\\core\\b.py::Box.second"
    assert dict(measurement.values) == {key: 2}
    assert measurement.sites_of(key) == frozenset({"app\\core\\a.py", "app\\core\\b.py"})


def test_a_window_repeated_inside_one_function_is_not_a_clone(standard: Standard) -> None:
    body: str = "".join(line for line in FIRST_CLONE.splitlines(keepends=True)[1:4])
    texts: dict[str, str] = {"app/core/a.py": f"def twice(items, limit):\n{body}{body}    return None\n"}
    assert dict(_measure(standard, texts, Rule.STRUCTURAL_CLONES).values) == {}


def test_raw_data_is_caught_outside_boundary_modules(standard: Standard) -> None:
    sample: str = (
        "from typing import Any\nimport typing\n"
        "def f(value: Any) -> 'dict[str, Any]':\n    return {}\n"
        "class C:\n    field: typing.Any\n"
        "Json = dict[str, Any]\n"
        "def clean(value: object) -> dict[str, object]:\n    return {}\n"
    )
    texts: dict[str, str] = {
        "app/core/s.py": sample,
        "app/config/loader.py": sample,
        "app/llm/backends/openai_model.py": sample,
    }
    assert dict(_measure(standard, texts, Rule.RAW_DATA).values) == {
        "app\\core\\s.py": 1, "app\\core\\s.py::C": 1, "app\\core\\s.py::f": 2,
    }


def test_defensive_casts_are_caught_outside_boundary_modules(standard: Standard) -> None:
    sample: str = (
        "def f(x):\n    return str(x or '') + str(x.name or '')\n"
        "def clean(x):\n    return str(x or '-') + str(x) + text(x or '')\n"
    )
    texts: dict[str, str] = {"app/core/s.py": sample, "app/sheets/client.py": sample}
    assert dict(_measure(standard, texts, Rule.DEFENSIVE_CASTS).values) == {"app\\core\\s.py::f": 2}


LAYERED_SAMPLE: dict[str, str] = {
    "app/core/a.py": (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    from ..slots import slot\n"
        "def later():\n    import app.slots.slot\n"
        "from app.core import b\n"
    ),
    "app/core/b.py": "X = 1\n",
    "app/slots/slot.py": "from app.core.b import X\nfrom app.paths import Y\n",
    "app/paths.py": "from app.core.b import X\n",
    "app/texts/t.py": "from app.sheets.p import P\n",
    "app/sheets/p.py": "from app.texts.u import U\nfrom app.slots.slot import S\n",
    "app/texts/u.py": "U = 1\n",
    "app/ui/messages_ru.py": "from app.core.b import X\n",
    "app/ui/other.py": "from app.core.b import X\n",
    "app/tools/code_standard/z.py": "from app.ui import messages_ru\nfrom app.tools.code_standard import w\nfrom app.core import b\n",
    "app/tools/code_standard/w.py": "W = 1\n",
    "app/setup/any.py": "from app.tools.code_standard import w\nfrom app.main import run\n",
    "app/main.py": "from app.setup.any import thing\n",
    "app/newpkg/m.py": "M = 1\n",
    "app/sources/r1.py": "from app.sources import r2\n",
    "app/sources/r2.py": "from app.sources.r1 import A\n",
    "app/tests/test_x.py": "from app.slots.slot import S\n",
}


def test_layers_catch_edges_unmapped_packages_and_rings(standard: Standard) -> None:
    measurement: Measurement = _measure(standard, LAYERED_SAMPLE, Rule.LAYERS)
    ring: str = msg.CODE_STANDARD_RING_KEY.format(modules="app\\main.py | app\\setup\\any.py")
    sources_ring: str = msg.CODE_STANDARD_RING_KEY.format(modules="app\\sources\\r1.py | app\\sources\\r2.py")
    unmapped: str = msg.CODE_STANDARD_UNMAPPED_KEY.format(package="newpkg")
    assert dict(measurement.values) == {
        "core -> slots": 2,
        "texts -> sheets": 1,
        "ui.messages_ru -> core": 1,
        "tools.code_standard -> core": 1,
        ring: 2,
        sources_ring: 2,
        unmapped: 1,
    }
    assert measurement.signs_of("core -> slots") == (Sign.EDGE,)
    assert measurement.signs_of(ring) == (Sign.RING,)
    assert measurement.signs_of(unmapped) == (Sign.UNMAPPED,)
    assert measurement.sites_of("tools.code_standard -> core") == frozenset({"app\\tools\\code_standard\\z.py"})


def test_the_layer_map_refuses_an_unknown_level(tmp_path: Path) -> None:
    broken: str = LOCK.standard.read_text(encoding="utf-8").replace('"imports": ["0"]', '"imports": ["9"]', 1)
    path: Path = tmp_path / "standard.json"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(StandardFileError) as caught:
        Standard.load(path)
    assert caught.value.human == msg.CODE_STANDARD_FILE_PROBLEMS["unknown_level"].format(file="standard.json", key="9")


def test_clock_calls_are_caught_outside_the_clock_module(standard: Standard) -> None:
    sample: str = (
        "import time\nfrom datetime import date, datetime\n"
        "def f():\n    return datetime.now(), date.today()\n"
        "class C:\n    clock = time.monotonic\n"
        "def clean(moment):\n    return moment.now() if moment else time.sleep(0)\n"
    )
    texts: dict[str, str] = {"app/core/s.py": sample, "app/core/clock.py": sample}
    assert dict(_measure(standard, texts, Rule.TIME).values) == {"app\\core\\s.py::C": 1, "app\\core\\s.py::f": 2}


def test_tests_are_checked_by_every_sign(standard: Standard) -> None:
    texts: dict[str, str] = {
        "app/tests/conftest.py": "SHARED = 1\n",
        "app/tests/fixtures/make.py": "import dataclasses\n\n\ndef make(item):\n    return dataclasses.replace(item)\n",
        "app/tests/test_b.py": "def helper():\n    return 1\n",
        "app/tests/test_a.py": (
            "import dataclasses\nimport os\n"
            "from dataclasses import replace as swap\n"
            "from app.tests.test_b import helper\n"
            "from app.tests import test_b\n"
            "from app.tests.conftest import SHARED\n"
            "from app.tests.fixtures.make import make\n"
            "AREA = 'livecraft' + '.sheets'\n"
            "NAMES = ('livecraft.json', 'livecraft.exe', 'livecraft')\n"
            "def test_it(monkeypatch, item):\n"
            "    monkeypatch.setattr(item, '_private', 1)\n"
            "    monkeypatch.setattr('app.module._hidden', 1)\n"
            "    monkeypatch.setattr(os, 'replace', helper)\n"
            "    monkeypatch.setattr(item, 'public', 1)\n"
            "    assert dataclasses.replace(item) and swap(item) and make(item) and SHARED and test_b\n"
        ),
        "app/tests/test_c.py": "LOGGER_NAME = " + repr("livecraft" + ".llm") + "\n",
        "app/core/s.py": "import dataclasses\nNAME = " + repr("livecraft" + ".llm") + "\n",
    }
    measurement: Measurement = _measure(standard, texts, Rule.TESTS)
    assert dict(measurement.values) == {
        "app\\tests\\test_a.py::dataclass_replace": 2,
        "app\\tests\\test_a.py::global_patch": 1,
        "app\\tests\\test_a.py::private_patch": 2,
        "app\\tests\\test_a.py::test_import": 2,
        "app\\tests\\test_c.py::logger_name": 1,
    }
    assert measurement.signs_of("app\\tests\\test_c.py::logger_name") == (Sign.LOGGER_NAME,)


# --- (д), (е), (и): сам замок

def test_the_lock_package_has_no_debt(measured: Measurements) -> None:
    found: dict[str, dict[str, int]] = {
        item.rule.value: dict(item.values) for item in measured.under((PACKAGE,)).items if item.values
    }
    assert found == {}


def _package_trees() -> dict[str, ast.Module]:
    """Модули замка, разобранные грамматикой Python 3.10: синтаксис 3.11+ даёт `SyntaxError`."""
    root: Path = LOCK.root.joinpath(*PACKAGE.parts)
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"), feature_version=PYTHON_FLOOR)
        for path in sorted(root.glob("*.py"))
    }


def test_the_lock_imports_from_app_only_itself_and_the_texts() -> None:
    problems: list[str] = []
    for name, tree in _package_trees().items():
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [f"{node.module}.{alias.name}" for alias in node.names]
            problems.extend(
                f"{name}: {module}" for module in modules
                if module.split(".")[0] == "app" and not module.startswith(ALLOWED_APP_IMPORTS)
            )
    assert problems == []


def test_the_lock_uses_nothing_newer_than_python_3_10() -> None:
    problems: list[str] = []
    for name, tree in _package_trees().items():
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names] + [node.module or ""]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            problems.extend(f"{name}:{node.lineno}: {item}" for item in names if item in NEW_PYTHON_NAMES)
            if type(node).__name__ in NEW_PYTHON_NODES or getattr(node, "type_params", None):
                problems.append(f"{name}:{node.lineno}: {type(node).__name__}")
    assert problems == []


# --- (ж): ключи с обратной косой чертой

def test_keys_use_a_backslash_whatever_the_separator() -> None:
    tree: SourceTree = SourceTree.from_texts({"app/a/b.py": "", "app\\c\\d.py": "", "./app/e/f.py": ""})
    assert [module.key.text for module in tree.modules] == ["app\\a\\b.py", "app\\c\\d.py", "app\\e\\f.py"]
    assert SourceKey.of("app/tools/code_standard/").text == "app\\tools\\code_standard"
    assert SourceKey.of("app/x/__init__.py").dotted == "app.x"


def test_every_path_key_of_the_repository_uses_a_backslash(measured: Measurements) -> None:
    """Ключи-пути реестра, исключений и замеров; у ключей-значений E8, E9, E16 пути — в местах нарушений."""
    ledger: Ledger = Ledger.load(LOCK.ledger)
    keys: list[str] = [key for rule in ledger.rules if rule not in VALUE_KEYED_RULES for key in ledger.section(rule)]
    keys.extend(item.key for item in Exceptions.load(LOCK.exceptions).items)
    keys.extend(key for item in measured.items if item.rule not in VALUE_KEYED_RULES for key in item.values)
    keys.extend(site for item in measured.items for key in item.values for site in item.sites_of(key))
    assert keys
    assert all(key.startswith("app\\") and "/" not in key for key in keys)


# --- (з): разница реестров и команда

def test_the_ledger_diff_sorts_changes_by_kind() -> None:
    before: Ledger = Ledger({Rule.DEFINITION_LENGTH: {"a": 40, "b": 35, "c": 33}, Rule.STATIC_METHODS: {"d": 1}})
    after: Ledger = Ledger({Rule.DEFINITION_LENGTH: {"a": 41, "b": 34, "e": 31}, Rule.STATIC_METHODS: {"d": 1}})
    diff: LedgerDiff = before.diff(after)
    assert [(change.key, change.before, change.after) for change in diff.new] == [("e", 0, 31)]
    assert [(change.key, change.before, change.after) for change in diff.grown] == [("a", 40, 41)]
    assert [(change.key, change.before, change.after) for change in diff.shrunk] == [("b", 35, 34)]
    assert [(change.key, change.before, change.after) for change in diff.gone] == [("c", 33, 0)]
    assert all(change.kind is not ChangeKind.SAME for change in diff.changes)
    assert before.diff(before).changes == ()


def test_a_ledger_file_with_an_unknown_rule_is_refused() -> None:
    with pytest.raises(StandardFileError) as caught:
        Ledger.parse('{"E99": {}}', "debt.json")
    assert "E99" in caught.value.human


@pytest.fixture
def sandbox(tmp_path: Path) -> LockFiles:
    """Корень с одним модулем app и стандартом репозитория."""
    files: LockFiles = LockFiles(tmp_path)
    files.standard.parent.mkdir(parents=True)
    shutil.copyfile(LOCK.standard, files.standard)
    (tmp_path / "app" / "shop.py").write_text("def used():\n    return 1\n\n\nVALUE = used()\n", encoding="utf-8")
    return files


def _run(files: LockFiles, *argv: str) -> tuple[CommandExit, str]:
    out: io.StringIO = io.StringIO()
    exit_code: CommandExit = StandardCommand(files, CommandRequest.parse(argv), out).run()
    return exit_code, out.getvalue()


def test_write_debt_refuses_growth_and_keeps_the_ledger(sandbox: LockFiles) -> None:
    assert _run(sandbox, "--init")[0] is CommandExit.OK
    saved: bytes = sandbox.ledger.read_bytes()
    (sandbox.root / "app" / "shop.py").write_text("def orphan():\n    return 1\n", encoding="utf-8")
    exit_code, output = _run(sandbox, "--write-debt")
    assert exit_code is CommandExit.REFUSED
    assert msg.CODE_STANDARD_WRITE_REFUSED in output
    assert "app\\shop.py::orphan" in output
    assert sandbox.ledger.read_bytes() == saved


def test_write_debt_drops_a_debt_removed_from_the_code(sandbox: LockFiles) -> None:
    (sandbox.root / "app" / "shop.py").write_text("def orphan():\n    return 1\n", encoding="utf-8")
    assert _run(sandbox, "--init")[0] is CommandExit.OK
    assert Ledger.load(sandbox.ledger).section(Rule.FREE_FUNCTIONS) == {"app\\shop.py::orphan": 1}
    (sandbox.root / "app" / "shop.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert _run(sandbox, "--write-debt")[0] is CommandExit.OK
    assert Ledger.load(sandbox.ledger).section(Rule.FREE_FUNCTIONS) == {}
    assert sandbox.ledger.read_bytes().endswith(b"}\n") and b"\r\n" not in sandbox.ledger.read_bytes()


def test_init_only_adds_sections_of_rules_the_ledger_lacks(sandbox: LockFiles) -> None:
    (sandbox.root / "app" / "shop.py").write_text("def orphan():\n    return 1\n", encoding="utf-8")
    assert _run(sandbox, "--init")[0] is CommandExit.OK
    exit_code, output = _run(sandbox, "--init")
    assert exit_code is CommandExit.REFUSED
    assert output.strip() == msg.CODE_STANDARD_INIT_EXISTS.format(file="debt.json")
    Ledger({Rule.STATIC_METHODS: {}}).save(sandbox.ledger)
    assert _run(sandbox, "--init")[0] is CommandExit.OK
    extended: Ledger = Ledger.load(sandbox.ledger)
    assert frozenset(extended.rules) == ACTIVE_RULES
    assert extended.section(Rule.FREE_FUNCTIONS) == {"app\\shop.py::orphan": 1}


def test_compare_names_growth_against_an_earlier_ledger(sandbox: LockFiles, tmp_path: Path) -> None:
    assert _run(sandbox, "--init")[0] is CommandExit.OK
    earlier: Path = tmp_path / "earlier.json"
    shutil.copyfile(sandbox.ledger, earlier)
    Ledger({Rule.FREE_FUNCTIONS: {"app\\shop.py::orphan": 1}}).with_sections_of(Ledger.load(earlier)).save(sandbox.ledger)
    exit_code, output = _run(sandbox, "--compare", str(earlier))
    assert exit_code is CommandExit.REFUSED
    assert "app\\shop.py::orphan" in output
    exit_code, output = _run(sandbox, "--compare", str(sandbox.ledger))
    assert exit_code is CommandExit.OK
    assert _run(sandbox, "--compare", "no-such-version-of-the-ledger")[0] is CommandExit.BROKEN


def test_files_lists_the_debts_of_a_file_or_folder(sandbox: LockFiles) -> None:
    (sandbox.root / "app" / "shop.py").write_text("def orphan():\n    return 1\n", encoding="utf-8")
    assert _run(sandbox, "--files", "app/shop.py")[0] is CommandExit.REFUSED
    assert _run(sandbox, "--init")[0] is CommandExit.OK
    exit_code, output = _run(sandbox, "--files", "app")
    assert exit_code is CommandExit.OK
    assert "app\\shop.py::orphan" in output and Sign.UNUSED.label in output
    assert msg.CODE_STANDARD_FILES_NONE.format(paths="app\\other") in _run(sandbox, "--files", "app/other")[1]


def test_the_report_has_a_row_for_every_measured_rule(sandbox: LockFiles) -> None:
    exit_code, output = _run(sandbox)
    assert exit_code is CommandExit.OK
    assert msg.CODE_STANDARD_REPORT_NO_LEDGER in output
    for rule in ACTIVE_RULES:
        assert rule.label in output


def test_the_command_line_picks_one_action() -> None:
    assert CommandRequest.parse([]).action is CommandAction.REPORT
    assert CommandRequest.parse(["--write-debt"]).action is CommandAction.WRITE_DEBT
    assert CommandRequest.parse(["--compare", "HEAD"]).target == "HEAD"
    assert CommandRequest.parse(["--files", "app/a.py", "app/b"]).paths == ("app/a.py", "app/b")
    with pytest.raises(SystemExit):
        CommandRequest.parse(["--init", "--write-debt"])
