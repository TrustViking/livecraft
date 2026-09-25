"""Импорты между модулями app и слои: правило E16 (REFACTORING_STANDARD.md §5, карта — `standard.json`).

Считается каждый импорт модуля app на любой глубине: под `TYPE_CHECKING`, внутри функций, относительный.
`from <модуль> import <имя>` ведёт в `<модуль>.<имя>`, если такой модуль есть, иначе — в сам `<модуль>`.
Проверяется код app без `app\\tests`: рёбра «пакет -> пакет» против карты, пакеты вне карты и кольца модулей.
"""
from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from typing import Final

from app.tools.code_standard.measurement import GROUP_JOINER, Finding, Measurement
from app.tools.code_standard.rule import Rule, Sign
from app.tools.code_standard.source import NAME_DOT, ModuleSource, SourceTree
from app.tools.code_standard.standard import AppName, LayerMap
from app.tools.code_standard.usage import ModuleImports
from app.ui import messages_ru as msg

EDGE_JOINER: Final[str] = " -> "


@dataclass(frozen=True)
class ImportTarget:
    """Один импорт: модуль, который называет оператор, модуль, куда импорт ведёт, и сам оператор."""

    origin: str
    target: str
    statement: ast.stmt

    @property
    def name(self) -> AppName:
        return AppName(self.target)


@dataclass(frozen=True)
class ImportedModules:
    """Все импорты модуля на любой глубине, в том числе относительные."""

    module: ModuleSource
    tree: SourceTree

    @cached_property
    def targets(self) -> tuple[ImportTarget, ...]:
        """По импорту на каждое имя оператора."""
        found: list[ImportTarget] = []
        for node in ast.walk(self.module.tree):
            if isinstance(node, ast.Import):
                found.extend(ImportTarget(alias.name, alias.name, node) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base: str = ModuleImports.base_of(node, self.module)
                found.extend(ImportTarget(base, self._resolved(base, alias.name), node) for alias in node.names)
        return tuple(found)

    @property
    def origins(self) -> tuple[str, ...]:
        """Модули, которые называют операторы: `import x` — `x`, `from x import y` — `x` один раз на оператор."""
        seen: dict[tuple[int, str], str] = {}
        for item in self.targets:
            seen.setdefault((id(item.statement), item.origin), item.origin)
        return tuple(seen.values())

    @property
    def app_targets(self) -> tuple[ImportTarget, ...]:
        """Импорты модулей app, кроме самого пакета `app`."""
        return tuple(item for item in self.targets if item.name.package and ModuleImports.is_app(item.target))

    def _resolved(self, base: str, name: str) -> str:
        full: str = NAME_DOT.join((base, name))
        return full if full in self.tree.by_name else base


@dataclass
class RingSearch:
    """Кольца графа модулей — сильно связные компоненты больше одного модуля (обход без рекурсии)."""

    graph: Mapping[str, frozenset[str]]
    seen: set[str] = field(default_factory=set)

    def rings(self) -> tuple[tuple[str, ...], ...]:
        order: list[str] = self._finish_order()
        reverse: dict[str, set[str]] = {}
        for node, targets in self.graph.items():
            for target in targets:
                reverse.setdefault(target, set()).add(node)
        self.seen = set()
        components: list[frozenset[str]] = [self._reach(node, reverse) for node in reversed(order) if node not in self.seen]
        return tuple(sorted(tuple(sorted(component)) for component in components if len(component) > 1))

    def _finish_order(self) -> list[str]:
        """Модули в порядке завершения обхода в глубину."""
        order: list[str] = []
        for start in sorted(self.graph):
            if start in self.seen:
                continue
            self.seen.add(start)
            stack: list[tuple[str, Iterator[str]]] = [(start, iter(sorted(self.graph.get(start, ()))))]
            while stack:
                node, children = stack[-1]
                child: str | None = next(children, None)
                if child is None:
                    stack.pop()
                    order.append(node)
                elif child not in self.seen:
                    self.seen.add(child)
                    stack.append((child, iter(sorted(self.graph.get(child, ())))))
        return order

    def _reach(self, start: str, graph: Mapping[str, set[str]]) -> frozenset[str]:
        """Всё, что достижимо из `start` среди ещё не пройденных модулей."""
        found: set[str] = {start}
        self.seen.add(start)
        pending: list[str] = [start]
        while pending:
            for target in graph.get(pending.pop(), set()) - self.seen:
                self.seen.add(target)
                found.add(target)
                pending.append(target)
        return frozenset(found)


@dataclass(frozen=True)
class ImportGraph:
    """Импорты модулей app вне тестов против карты слоёв: рёбра, пакеты вне карты, кольца модулей."""

    tree: SourceTree
    layers: LayerMap

    @cached_property
    def _imports(self) -> Mapping[str, tuple[ImportTarget, ...]]:
        """Ключ модуля → его импорты модулей app."""
        return {module.key.text: ImportedModules(module, self.tree).app_targets for module in self.tree.production}

    def measurements(self) -> tuple[Measurement, ...]:
        findings: list[Finding] = [*self._edges(), *self._unmapped(), *self._rings()]
        return (Measurement.of(Rule.LAYERS, findings),)

    def _edges(self) -> Iterator[Finding]:
        """Импорт против карты: ключ `пакет -> пакет`, величина — число импортов."""
        counts: dict[str, int] = {}
        places: dict[str, set[str]] = {}
        for module in self.tree.production:
            source: AppName = AppName(module.key.dotted)
            for item in self._imports[module.key.text] if source.package else ():
                if self.layers.allows(source, item.name):
                    continue
                key: str = EDGE_JOINER.join((self.layers.unit_of(source), item.name.package))
                counts[key] = counts.get(key, 0) + 1
                places.setdefault(key, set()).add(module.key.text)
        return (Finding(key, count, frozenset({Sign.EDGE}), places=frozenset(places[key])) for key, count in counts.items())

    def _unmapped(self) -> Iterator[Finding]:
        """Пакет, которого нет в карте: величина — число его модулей."""
        places: dict[str, set[str]] = {}
        for module in self.tree.production:
            package: str = AppName(module.key.dotted).package
            if package and self.layers.layer_of(package) is None:
                places.setdefault(package, set()).add(module.key.text)
        for package, modules in places.items():
            key: str = msg.CODE_STANDARD_UNMAPPED_KEY.format(package=package)
            yield Finding(key, len(modules), frozenset({Sign.UNMAPPED}), places=frozenset(modules))

    def _rings(self) -> Iterator[Finding]:
        """Кольцо модулей: ключ — модули по алфавиту, величина — их число."""
        for ring in RingSearch(self._module_graph()).rings():
            key: str = msg.CODE_STANDARD_RING_KEY.format(modules=GROUP_JOINER.join(ring))
            yield Finding(key, len(ring), frozenset({Sign.RING}), places=frozenset(ring))

    def _module_graph(self) -> Mapping[str, frozenset[str]]:
        """Ключ модуля → ключи модулей, которые он импортирует (ближайший существующий модуль имени)."""
        graph: dict[str, frozenset[str]] = {}
        for key, targets in self._imports.items():
            found: set[str] = {self._module_key(item.target) for item in targets}
            graph[key] = frozenset(found - {key, ""})
        return graph

    def _module_key(self, dotted: str) -> str:
        """Ключ модуля по имени; имени нет среди модулей — ближайший существующий пакет или пусто."""
        name: str = dotted
        while name and name not in self.tree.by_name:
            name = name.rpartition(NAME_DOT)[0]
        return self.tree.by_name[name].key.text if name else ""
