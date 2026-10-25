"""Подпись и тело функции глазами правил формы (E1, E4, E12, E13)."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from app.tools.code_standard.source import DefinitionSite
from app.tools.code_standard.usage import Annotation

CLASS_RECEIVER: Final[str] = "cls"
PRIVATE_PREFIX: Final[str] = "_"
TUPLE_NAMES: Final[frozenset[str]] = frozenset({"tuple", "Tuple"})


@dataclass(frozen=True)
class CalleeName:
    """Последнее имя выражения: `name` и `obj.name` дают `name`, прочее — `None`."""

    expr: ast.expr

    @property
    def name(self) -> str | None:
        if isinstance(self.expr, ast.Name):
            return self.expr.id
        return self.expr.attr if isinstance(self.expr, ast.Attribute) else None


@dataclass(frozen=True)
class Signature:
    """Параметры функции: получатель метода (`self` / `cls`) отдельно от остальных."""

    site: DefinitionSite

    @cached_property
    def _arguments(self) -> tuple[ast.arg, ...]:
        """Все параметры по порядку: позиционные, `*args`, именованные, `**kwargs`."""
        spec: ast.arguments = self.site.node.args
        extra: tuple[ast.arg | None, ...] = (spec.vararg, *spec.kwonlyargs, spec.kwarg)
        return tuple(spec.posonlyargs) + tuple(spec.args) + tuple(arg for arg in extra if arg is not None)

    @cached_property
    def receiver(self) -> str | None:
        """Первый позиционный параметр метода, кроме `@staticmethod`."""
        spec: ast.arguments = self.site.node.args
        positional: list[ast.arg] = spec.posonlyargs + spec.args
        if not self.site.is_method or self.site.is_static or not positional:
            return None
        return positional[0].arg

    @property
    def parameters(self) -> tuple[ast.arg, ...]:
        """Параметры без получателя."""
        return self._arguments[1:] if self.receiver is not None else self._arguments

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(arg.arg for arg in self.parameters)

    @property
    def annotations(self) -> tuple[Annotation, ...]:
        """Аннотации параметров и результата."""
        exprs: list[ast.expr | None] = [arg.annotation for arg in self._arguments] + [self.site.node.returns]
        return tuple(Annotation(expr) for expr in exprs if expr is not None)

    @property
    def returns_fixed_tuple(self) -> bool:
        """Результат — `tuple[A, B, …]` из двух и больше элементов без `...` на верхнем уровне."""
        if self.site.node.returns is None:
            return False
        expr: ast.expr = Annotation(self.site.node.returns).resolved
        if not isinstance(expr, ast.Subscript) or CalleeName(expr.value).name not in TUPLE_NAMES:
            return False
        items: list[ast.expr] = expr.slice.elts if isinstance(expr.slice, ast.Tuple) else [expr.slice]
        return len(items) > 1 and not any(isinstance(item, ast.Constant) and item.value is Ellipsis for item in items)


@dataclass(frozen=True)
class FunctionBody:
    """Тело функции без докстроки и то, что правило E12 в нём ищет."""

    site: DefinitionSite
    signature: Signature

    @cached_property
    def statements(self) -> tuple[ast.stmt, ...]:
        body: list[ast.stmt] = self.site.node.body
        first: ast.stmt | None = body[0] if body else None
        is_doc: bool = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
        return tuple(body[1:] if is_doc and isinstance(first.value.value, str) else body)

    @cached_property
    def returned_call(self) -> ast.Call | None:
        """Вызов, если тело — один `return <вызов>`."""
        if len(self.statements) != 1 or not isinstance(self.statements[0], ast.Return):
            return None
        value: ast.expr | None = self.statements[0].value
        return value if isinstance(value, ast.Call) else None

    def forwards(self, builtins: frozenset[str]) -> bool:
        """E12 (а): аргументы вызова — ровно параметры по разу, без получателя; не встроенная и не конструктор."""
        call: ast.Call | None = self.returned_call
        if call is None or self._uses_receiver(call) or self._is_excluded(call.func, builtins):
            return False
        values: list[ast.expr] = call.args + [keyword.value for keyword in call.keywords]
        passed: list[str] = [name for name in (self._passed(value) for value in values) if name is not None]
        return len(passed) == len(values) and sorted(passed) == sorted(self.signature.names)

    @property
    def is_two_layers(self) -> bool:
        """E12 (б): метод без параметров, тело — `return self._<имя>()` без аргументов."""
        call: ast.Call | None = self.returned_call
        receiver: str | None = self.signature.receiver
        if call is None or receiver is None or self.signature.names or call.args or call.keywords:
            return False
        func: ast.expr = call.func
        is_own: bool = isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == receiver
        return is_own and func.attr.startswith(PRIVATE_PREFIX)

    @property
    def called_name(self) -> str | None:
        """Имя вызываемого, если тело — `return <имя>(…)`: кандидат E12 (в)."""
        call: ast.Call | None = self.returned_call
        return call.func.id if call is not None and isinstance(call.func, ast.Name) else None

    def _uses_receiver(self, call: ast.Call) -> bool:
        receiver: str | None = self.signature.receiver
        return receiver is not None and any(isinstance(node, ast.Name) and node.id == receiver for node in ast.walk(call))

    def _is_excluded(self, func: ast.expr, builtins: frozenset[str]) -> bool:
        """Встроенная функция из стандарта, конструктор класса или вызов без имени."""
        name: str | None = CalleeName(func).name
        return name is None or name in builtins or name[0].isupper() or name == CLASS_RECEIVER

    def _passed(self, arg: ast.expr) -> str | None:
        """Имя параметра, переданного как есть (`name`, `*args`, `**kwargs`); иначе `None`."""
        inner: ast.expr = arg.value if isinstance(arg, ast.Starred) else arg
        return inner.id if isinstance(inner, ast.Name) else None
