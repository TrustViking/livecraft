"""Исходники app для замка: каждый файл читается и разбирается один раз (REFACTORING_STANDARD.md §6).

Ключ модуля — путь от корня репозитория с обратной косой чертой при любом разделителе ОС (`app\\x\\y.py`):
так реестр долгов совпадает на Windows и в контейнере. Ключ определения — `путь::квалифицированное имя`.
"""
from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import Final

APP_PACKAGE: Final[str] = "app"
TESTS_PACKAGE: Final[str] = "tests"
TESTS_PREFIX: Final[tuple[str, ...]] = (APP_PACKAGE, TESTS_PACKAGE)
CACHE_DIR: Final[str] = "__pycache__"
SOURCE_GLOB: Final[str] = "*.py"
SOURCE_SUFFIX: Final[str] = ".py"
PACKAGE_STEM: Final[str] = "__init__"
KEY_SLASH: Final[str] = "\\"
POSIX_SLASH: Final[str] = "/"
NAME_DOT: Final[str] = "."
KEY_JOINER: Final[str] = "::"
STATIC_DECORATOR: Final[str] = "staticmethod"

FUNCTION_NODES: Final[tuple[type[ast.AST], ...]] = (ast.FunctionDef, ast.AsyncFunctionDef)
DEFINITION_NODES: Final[tuple[type[ast.AST], ...]] = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
DefinitionNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass(frozen=True)
class SourceKey:
    """Путь модуля или папки от корня репозитория: части через обратную косую черту."""

    text: str

    @classmethod
    def of(cls, raw: str) -> SourceKey:
        """Любой разделитель, `./` и косая черта в конце — к одному виду."""
        return cls(KEY_SLASH.join(PurePosixPath(raw.replace(KEY_SLASH, POSIX_SLASH)).parts))

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.text.split(KEY_SLASH))

    @property
    def is_test(self) -> bool:
        """Модуль тестов: `app\\tests\\…`."""
        return self.parts[:len(TESTS_PREFIX)] == TESTS_PREFIX

    @property
    def is_package_init(self) -> bool:
        return self.parts[-1] == PACKAGE_STEM + SOURCE_SUFFIX

    @property
    def dotted(self) -> str:
        """Имя модуля для импорта: `app.config.loader`; у `__init__.py` — имя пакета."""
        names: list[str] = list(self.parts)
        names[-1] = names[-1].removesuffix(SOURCE_SUFFIX)
        if names[-1] == PACKAGE_STEM:
            names.pop()
        return NAME_DOT.join(names)

    @property
    def package(self) -> str:
        """Пакет модуля: у `__init__.py` — сам пакет, у прочих — папка модуля."""
        return self.dotted if self.is_package_init else self.dotted.rpartition(NAME_DOT)[0]

    def site(self, qualname: str) -> str:
        """Ключ определения этого модуля: `путь::имя`."""
        return KEY_JOINER.join((self.text, qualname))

    def covers(self, key: str) -> bool:
        """Ключ нарушения относится к этому файлу или к файлу внутри этой папки."""
        path: str = key.partition(KEY_JOINER)[0]
        return path == self.text or path.startswith(self.text + KEY_SLASH)


@dataclass(frozen=True, eq=False)
class ModuleSource:
    """Модуль app: ключ, текст и дерево разбора."""

    key: SourceKey
    text: str

    @cached_property
    def tree(self) -> ast.Module:
        return ast.parse(self.text, filename=self.key.text)

    @property
    def line_count(self) -> int:
        return len(self.text.splitlines())

    @cached_property
    def definitions(self) -> tuple[DefinitionSite, ...]:
        """Все функции, методы и классы модуля на любой глубине, в порядке файла."""
        return tuple(self._sites(self.tree, (), False))

    @cached_property
    def class_names(self) -> frozenset[str]:
        """Имена классов, объявленных в модуле на любой глубине."""
        return frozenset(site.name for site in self.definitions if site.is_class)

    def _sites(self, node: ast.AST, scope: tuple[str, ...], in_class: bool) -> Iterator[DefinitionSite]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, DEFINITION_NODES):
                yield DefinitionSite(self, child, scope, in_class)
                yield from self._sites(child, scope + (child.name,), isinstance(child, ast.ClassDef))
            else:
                yield from self._sites(child, scope, in_class)


@dataclass(frozen=True, eq=False)
class DefinitionSite:
    """Определение в модуле: узел, имена охватывающих определений и то, лежит ли оно прямо в классе."""

    module: ModuleSource
    node: DefinitionNode
    scope: tuple[str, ...]
    in_class: bool

    @property
    def name(self) -> str:
        return self.node.name

    @property
    def qualname(self) -> str:
        return NAME_DOT.join(self.scope + (self.node.name,))

    @property
    def key(self) -> str:
        return self.module.key.site(self.qualname)

    @property
    def is_class(self) -> bool:
        return isinstance(self.node, ast.ClassDef)

    @property
    def is_function(self) -> bool:
        return isinstance(self.node, FUNCTION_NODES)

    @property
    def is_free_function(self) -> bool:
        """Функция уровня модуля (в том числе под `if` уровня модуля)."""
        return self.is_function and not self.scope

    @property
    def is_method(self) -> bool:
        return self.is_function and self.in_class

    @property
    def is_static(self) -> bool:
        return self.is_method and STATIC_DECORATOR in self.decorators

    @cached_property
    def decorators(self) -> frozenset[str]:
        """Имена декораторов: `name`, `module.name` и `name(...)` дают `name`."""
        names: set[str] = set()
        for decorator in self.node.decorator_list:
            target: ast.expr = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
        return frozenset(names)

    @property
    def line_count(self) -> int:
        """От строки `def` или `class` до последней строки определения, включая докстроку."""
        return (self.node.end_lineno or self.node.lineno) - self.node.lineno + 1


@dataclass(frozen=True)
class SourceTree:
    """Все модули `app\\**\\*.py` без `__pycache__`, в порядке ключей."""

    modules: tuple[ModuleSource, ...]

    @classmethod
    def from_root(cls, root: Path) -> SourceTree:
        """Модули app в корне репозитория."""
        paths: list[Path] = [path for path in (root / APP_PACKAGE).rglob(SOURCE_GLOB) if CACHE_DIR not in path.parts]
        return cls.from_texts({path.relative_to(root).as_posix(): path.read_bytes().decode() for path in paths})

    @classmethod
    def from_texts(cls, texts: Mapping[str, str]) -> SourceTree:
        """Модули из словаря «путь → текст»: образцы тестов замка; разделитель пути любой."""
        modules: list[ModuleSource] = [ModuleSource(SourceKey.of(path), text) for path, text in texts.items()]
        return cls(tuple(sorted(modules, key=lambda module: module.key.text)))

    @cached_property
    def production(self) -> tuple[ModuleSource, ...]:
        """Модули app без `app\\tests`: то, что проверяет большинство правил."""
        return tuple(module for module in self.modules if not module.key.is_test)

    @cached_property
    def by_name(self) -> Mapping[str, ModuleSource]:
        """Модули по имени импорта."""
        return {module.key.dotted: module for module in self.modules}

    @cached_property
    def class_names(self) -> frozenset[str]:
        """Имена классов, объявленных в app вне `app\\tests`."""
        return frozenset(name for module in self.production for name in module.class_names)

    @cached_property
    def functions(self) -> tuple[DefinitionSite, ...]:
        """Все функции и методы app вне `app\\tests`."""
        return tuple(site for module in self.production for site in module.definitions if site.is_function)
