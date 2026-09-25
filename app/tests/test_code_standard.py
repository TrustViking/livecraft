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
# Правила, которые замок проверяет с задачи R2.1a; R2.1b добавит E5–E11, E14–E17, E20.
ACTIVE_RULES: frozenset[Rule] = frozenset({
    Rule.FREE_FUNCTIONS, Rule.STATIC_METHODS, Rule.DEFINITION_LENGTH, Rule.PARAMETERS, Rule.EMPTY_WRAPPERS,
    Rule.STATE_TUPLES, Rule.SIZES, Rule.PACKAGE_INIT, Rule.REPEATED_NAMES,
})
ALLOWED_APP_IMPORTS: tuple[str, ...] = ("app.tools.code_standard", "app.ui.messages_ru")
# Возможности Python 3.11+ — замок работает на 3.10 без пакетов проекта (REFACTORING_STANDARD.md §6).
PYTHON_FLOOR: tuple[int, int] = (3, 10)
NEW_PYTHON_NAMES: frozenset[str] = frozenset({"StrEnum", "tomllib", "Self", "UTC", "ExceptionGroup", "BaseExceptionGroup"})
NEW_PYTHON_NODES: frozenset[str] = frozenset({"TryStar", "TypeAlias", "TypeVar", "ParamSpec", "TypeVarTuple"})


@pytest.fixture(scope="module")
def standard() -> Standard:
    return Standard.load(LOCK.standard)


@pytest.fixture(scope="module")
def measured(standard: Standard) -> Measurements:
    return StandardCheck(SourceTree.from_root(LOCK.root), standard).measure()


@pytest.fixture(scope="module")
def exceptions() -> Exceptions:
    return Exceptions.load(LOCK.exceptions)


@pytest.fixture(scope="module")
def ledger_diff(measured: Measurements, exceptions: Exceptions) -> LedgerDiff:
    return Ledger.load(LOCK.ledger).diff(Ledger.of(measured.without(exceptions.keys)))


def _measure(standard: Standard, texts: Mapping[str, str], rule: Rule) -> Measurement:
    return StandardCheck(SourceTree.from_texts(texts), standard).measure().of(rule)


# --- (а), (б), (в): код против реестра и исключений

def test_the_lock_measures_exactly_the_rules_of_this_stage(measured: Measurements) -> None:
    assert frozenset(measured.rules) == ACTIVE_RULES
    assert frozenset(Ledger.load(LOCK.ledger).rules) == ACTIVE_RULES


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

CLEAN_SAMPLE: dict[str, str] = {
    "app/pkg/__init__.py": (
        '"""Пакет образца."""\nfrom __future__ import annotations\n\nfrom app.pkg.item import Item\n\n__all__ = ["Item"]\n'
    ),
    "app/pkg/item.py": (
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
    "app/pkg/user.py": "from app.pkg.item import normalize\n\nLABEL = normalize(' A ')\n",
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


def test_every_key_of_the_repository_uses_a_backslash(measured: Measurements) -> None:
    keys: list[str] = [key for rule in Ledger.load(LOCK.ledger).rules for key in Ledger.load(LOCK.ledger).section(rule)]
    keys.extend(item.key for item in Exceptions.load(LOCK.exceptions).items)
    keys.extend(key for item in measured.items for key in item.values)
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
