"""Кто пользуется свободными функциями app и какие классы app видит модуль (правила E1, E12).

Использование ищется по именам, а не по смыслу: имя в модуле, где функция объявлена; имя, взятое импортом
`from <модуль> import <функция>`, и сам этот импорт; `<псевдоним модуля>.<функция>`; строка в `__all__`.
Ссылка функции на саму себя использованием не считается. Имя, совпавшее с чужим (локальная переменная,
атрибут другого объекта), может засчитаться использованием — тогда правило пропустит нарушение, но
ложного не даст. Тесты (`app\\tests`) не считаются.
"""
from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from app.tools.code_standard.source import APP_PACKAGE, NAME_DOT, DefinitionSite, ModuleSource, SourceTree

EXPORTS_NAME: Final[str] = "__all__"
EVAL_MODE: Final[str] = "eval"


@dataclass(frozen=True)
class ImportedName:
    """Имя верхнего уровня модуля app: модуль (имя импорта) и имя в нём."""

    module: str
    name: str


@dataclass(frozen=True)
class ModuleImports:
    """Что модуль берёт из app: имена (псевдоним → модуль и имя) и сами модули (псевдоним → модуль)."""

    names: Mapping[str, ImportedName]
    modules: Mapping[str, str]

    @classmethod
    def of(cls, module: ModuleSource, tree: SourceTree) -> ModuleImports:
        """Импорты из app на любой глубине модуля, в том числе под `TYPE_CHECKING` и в функциях."""
        names: dict[str, ImportedName] = {}
        modules: dict[str, str] = {}
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Import):
                modules.update(cls._module_aliases(node))
            elif isinstance(node, ast.ImportFrom):
                base: str = cls.base_of(node, module)
                for alias in node.names if cls.is_app(base) else ():
                    full: str = NAME_DOT.join((base, alias.name))
                    if full in tree.by_name:
                        modules[alias.asname or alias.name] = full
                    else:
                        names[alias.asname or alias.name] = ImportedName(base, alias.name)
        return cls(names, modules)

    @classmethod
    def _module_aliases(cls, node: ast.Import) -> Mapping[str, str]:
        return {alias.asname: alias.name for alias in node.names if alias.asname and cls.is_app(alias.name)}

    @classmethod
    def base_of(cls, node: ast.ImportFrom, module: ModuleSource) -> str:
        """Модуль, из которого идёт импорт; относительный — от пакета модуля."""
        if not node.level:
            return node.module or ""
        parts: list[str] = module.key.package.split(NAME_DOT)
        parts = parts[:len(parts) - node.level + 1]
        return NAME_DOT.join(parts + ([node.module] if node.module else []))

    @classmethod
    def is_app(cls, name: str) -> bool:
        """Имя — пакет `app` или модуль внутри него."""
        return name == APP_PACKAGE or name.startswith(APP_PACKAGE + NAME_DOT)


@dataclass(frozen=True)
class FunctionUse:
    """Одно использование свободной функции: модуль и класс верхнего уровня, в котором оно стоит."""

    target: ImportedName
    module: str
    owner: str | None


@dataclass(frozen=True)
class UseWalker:
    """Обход одного модуля: использования функций-целей с классом верхнего уровня каждого."""

    module: ModuleSource
    imports: ModuleImports
    targets: frozenset[ImportedName]

    def uses(self) -> Iterator[FunctionUse]:
        yield from self._visit(self.module.tree, None, None)

    def _visit(self, node: ast.AST, owner: str | None, current: str | None) -> Iterator[FunctionUse]:
        """`owner` — класс верхнего уровня, `current` — функция верхнего уровня вокруг узла."""
        for child in ast.iter_child_nodes(node):
            for target in self._targets(child):
                if not (target.module == self.module.key.dotted and target.name == current):
                    yield FunctionUse(target, self.module.key.dotted, owner)
            is_top: bool = owner is None and current is None
            child_owner: str | None = child.name if is_top and isinstance(child, ast.ClassDef) else owner
            is_function: bool = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            child_current: str | None = child.name if is_top and is_function else current
            yield from self._visit(child, child_owner, child_current)

    def _targets(self, node: ast.AST) -> tuple[ImportedName, ...]:
        """Функции-цели, которые называет сам узел (без его потомков)."""
        return tuple(target for target in self._named(node) if target in self.targets)

    def _named(self, node: ast.AST) -> tuple[ImportedName, ...]:
        dotted: str = self.module.key.dotted
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
            return (self.imports.names.get(node.id, ImportedName(dotted, node.id)),)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in self.imports.modules:
            return (ImportedName(self.imports.modules[node.value.id], node.attr),)
        if isinstance(node, ast.ImportFrom):
            base: str = ModuleImports.base_of(node, self.module)
            return tuple(ImportedName(base, alias.name) for alias in node.names)
        if isinstance(node, ast.Assign) and self._is_exports(node):
            return tuple(ImportedName(dotted, item.value) for item in ast.walk(node.value) if self._is_text(item))
        return ()

    def _is_exports(self, node: ast.Assign) -> bool:
        return any(isinstance(target, ast.Name) and target.id == EXPORTS_NAME for target in node.targets)

    def _is_text(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, str)


@dataclass(frozen=True)
class FunctionUses:
    """Использования каждой свободной функции app вне `app\\tests` по всему коду app вне тестов."""

    tree: SourceTree

    @cached_property
    def free_functions(self) -> Mapping[ImportedName, DefinitionSite]:
        """Свободные функции по модулю и имени."""
        return {
            ImportedName(site.module.key.dotted, site.name): site for site in self.tree.functions if site.is_free_function
        }

    @cached_property
    def _index(self) -> Mapping[ImportedName, tuple[FunctionUse, ...]]:
        targets: frozenset[ImportedName] = frozenset(self.free_functions)
        found: dict[ImportedName, list[FunctionUse]] = {target: [] for target in targets}
        for module in self.tree.production:
            for use in UseWalker(module, ModuleImports.of(module, self.tree), targets).uses():
                found[use.target].append(use)
        return {target: tuple(uses) for target, uses in found.items()}

    def of(self, site: DefinitionSite) -> tuple[FunctionUse, ...]:
        """Использования свободной функции; у прочих определений — пусто."""
        return self._index.get(ImportedName(site.module.key.dotted, site.name), ())

    def function(self, module: ModuleSource, name: str) -> DefinitionSite | None:
        """Свободная функция модуля по имени."""
        return self.free_functions.get(ImportedName(module.key.dotted, name))


@dataclass(frozen=True)
class NameRef:
    """Имя в аннотации: `Name` или `<база>.<имя>`."""

    base: str | None
    name: str


@dataclass(frozen=True)
class Annotation:
    """Выражение аннотации; строковая аннотация разбирается как выражение."""

    expr: ast.expr

    @classmethod
    def parsed(cls, text: str) -> Annotation | None:
        try:
            return cls(ast.parse(text, mode=EVAL_MODE).body)
        except SyntaxError:
            return None

    @property
    def refs(self) -> tuple[NameRef, ...]:
        """Все имена выражения, в том числе внутри строковых частей."""
        found: list[NameRef] = []
        for node in ast.walk(self.expr):
            if isinstance(node, ast.Name):
                found.append(NameRef(None, node.id))
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                found.append(NameRef(node.value.id, node.attr))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                inner: Annotation | None = self.parsed(node.value)
                found.extend(inner.refs if inner else ())
        return tuple(found)

    @property
    def resolved(self) -> ast.expr:
        """Выражение; строковая аннотация целиком — разобранной."""
        if isinstance(self.expr, ast.Constant) and isinstance(self.expr.value, str):
            inner: Annotation | None = self.parsed(self.expr.value)
            return inner.expr if inner else self.expr
        return self.expr


@dataclass(frozen=True)
class ClassScope:
    """Классы app, которые модуль может назвать в аннотации: свои, взятые импортом и через псевдоним модуля."""

    local: frozenset[str]
    imported: frozenset[str]
    module_aliases: frozenset[str]
    app_classes: frozenset[str]

    @classmethod
    def of(cls, module: ModuleSource, tree: SourceTree) -> ClassScope:
        imports: ModuleImports = ModuleImports.of(module, tree)
        imported: frozenset[str] = frozenset(
            alias for alias, target in imports.names.items() if target.name in tree.class_names
        )
        return cls(module.class_names, imported, frozenset(imports.modules), tree.class_names)

    def names_class(self, annotation: Annotation) -> bool:
        """В аннотации назван класс app."""
        return any(self._is_class(ref) for ref in annotation.refs)

    def _is_class(self, ref: NameRef) -> bool:
        if ref.base is None:
            return ref.name in self.local or ref.name in self.imported
        return ref.base in self.module_aliases and ref.name in self.app_classes
