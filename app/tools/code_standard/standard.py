"""Стандарт кода как данные: пороги, списки и карта слоёв из `standard.json` (REFACTORING_STANDARD.md §5, §6).

В коде замка порогов нет: каждое число и каждый список правила берутся отсюда. Правила значений в коде,
клонов, слоёв и тестов получают свою часть стандарта объектом: `ValueRules`, `CloneRules`, `LayerMap`,
`SuiteRules`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.tools.code_standard.json_file import JsonObject, JsonProblem, StandardFileError
from app.tools.code_standard.source import APP_PACKAGE, NAME_DOT, KeyPattern, SourceKey


class StandardKey(str, Enum):
    """Ключи `standard.json` и объектов его карты слоёв."""

    MAX_DEFINITION_LINES = "max_definition_lines"
    MAX_PARAMETERS = "max_parameters"
    MAX_MODULE_LINES = "max_module_lines"
    MAX_CLASS_MEMBERS = "max_class_members"
    MODULE_SIZE_EXEMPT = "module_size_exempt"
    WRAPPER_BUILTINS = "wrapper_builtins"
    ALLOWED_BODY_NUMBERS = "allowed_body_numbers"
    LOG_METHODS = "log_methods"
    CYRILLIC_MODULES = "cyrillic_modules"
    BOUNDARY_MODULES = "boundary_modules"
    CLOCK_MODULE = "clock_module"
    CLOCK_CALLS = "clock_calls"
    CLONE_WINDOW = "clone_window"
    CLONE_MIN_NODES = "clone_min_nodes"
    LOGGER_PACKAGE = "logger_package"
    LOG_AREA_CLASS = "log_area_class"
    ISOLATED_PACKAGES = "isolated_packages"
    TOOL_IMPORTS = "tool_imports"
    SEALED_MODULES = "sealed_modules"
    LAYERS = "layers"
    CHAIN_LEVEL = "chain_level"
    TEST_SHARED = "test_shared"
    TEST_FIXTURES = "test_fixtures"
    LOGGER_ROOT = "logger_root"
    LOGGER_FILE_NAMES = "logger_file_names"
    LEVEL = "level"
    PACKAGES = "packages"
    IMPORTS = "imports"


@dataclass(frozen=True)
class ValueRules:
    """Что правила значений в коде (E5–E10, E14, E15, E17) разрешают и где."""

    allowed_body_numbers: frozenset[int]
    log_methods: frozenset[str]
    cyrillic_modules: frozenset[str]
    boundary_modules: tuple[KeyPattern, ...]
    clock_module: str
    clock_calls: frozenset[str]
    logger_package: SourceKey
    log_area_class: str
    isolated_packages: tuple[SourceKey, ...]

    @classmethod
    def of(cls, data: JsonObject) -> ValueRules:
        return cls(
            allowed_body_numbers=frozenset(data.integers(StandardKey.ALLOWED_BODY_NUMBERS.value)),
            log_methods=frozenset(data.texts(StandardKey.LOG_METHODS.value)),
            cyrillic_modules=frozenset(SourceKey.of(raw).text for raw in data.texts(StandardKey.CYRILLIC_MODULES.value)),
            boundary_modules=tuple(KeyPattern.of(raw) for raw in data.texts(StandardKey.BOUNDARY_MODULES.value)),
            clock_module=SourceKey.of(data.text(StandardKey.CLOCK_MODULE.value)).text,
            clock_calls=frozenset(data.texts(StandardKey.CLOCK_CALLS.value)),
            logger_package=SourceKey.of(data.text(StandardKey.LOGGER_PACKAGE.value)),
            log_area_class=data.text(StandardKey.LOG_AREA_CLASS.value),
            isolated_packages=tuple(SourceKey.of(raw) for raw in data.texts(StandardKey.ISOLATED_PACKAGES.value)),
        )

    def is_boundary(self, key: SourceKey) -> bool:
        """Модуль-граница: ему можно `Any` и `str(x or "")` (E14, E15)."""
        return any(pattern.matches(key) for pattern in self.boundary_modules)

    def area_of(self, key: SourceKey) -> str:
        """Область повторов E8 и E9: изолированный пакет модуля или пусто — остальной app."""
        return next((package.text for package in self.isolated_packages if package.covers(key.text)), "")


@dataclass(frozen=True)
class CloneRules:
    """Окно структурных клонов (E11): число операторов подряд и наименьший размер в узлах ast."""

    window: int
    min_nodes: int

    @classmethod
    def of(cls, data: JsonObject) -> CloneRules:
        return cls(data.integer(StandardKey.CLONE_WINDOW.value), data.integer(StandardKey.CLONE_MIN_NODES.value))


@dataclass(frozen=True)
class SuiteRules:
    """Что правило тестов (E20) считает общим для тестов и что — именем логгера."""

    shared: tuple[KeyPattern, ...]
    fixtures: tuple[KeyPattern, ...]
    logger_root: str
    logger_file_names: frozenset[str]

    @classmethod
    def of(cls, data: JsonObject) -> SuiteRules:
        return cls(
            shared=tuple(KeyPattern.of(raw) for raw in data.texts(StandardKey.TEST_SHARED.value)),
            fixtures=tuple(KeyPattern.of(raw) for raw in data.texts(StandardKey.TEST_FIXTURES.value)),
            logger_root=data.text(StandardKey.LOGGER_ROOT.value),
            logger_file_names=frozenset(data.texts(StandardKey.LOGGER_FILE_NAMES.value)),
        )

    def is_shared(self, key: SourceKey) -> bool:
        """Общий модуль тестов: его можно импортировать из других модулей тестов."""
        return any(pattern.matches(key) for pattern in self.shared)

    def is_fixture(self, key: SourceKey) -> bool:
        """Заготовки тестов: там можно `dataclasses.replace`."""
        return any(pattern.matches(key) for pattern in self.fixtures)


@dataclass(frozen=True)
class Layer:
    """Уровень карты слоёв: имя, пакеты по порядку и уровни, из которых пакеты уровня импортируют."""

    level: str
    packages: tuple[str, ...]
    imports: frozenset[str]

    @classmethod
    def of(cls, data: JsonObject) -> Layer:
        return cls(
            level=data.text(StandardKey.LEVEL.value),
            packages=data.texts(StandardKey.PACKAGES.value),
            imports=frozenset(data.texts(StandardKey.IMPORTS.value)),
        )


@dataclass(frozen=True)
class AppName:
    """Имя модуля или пакета под app: `app.ui.messages_ru` → `ui.messages_ru`, пакет — `ui`."""

    dotted: str

    @property
    def inner(self) -> str:
        return self.dotted.partition(NAME_DOT)[-1] if self.dotted != APP_PACKAGE else ""

    @property
    def package(self) -> str:
        """Первое имя под app; у самого `app` — пусто."""
        return self.inner.partition(NAME_DOT)[0]

    def within(self, prefix: str) -> bool:
        """Модуль совпадает с `prefix` или лежит внутри него."""
        return self.dotted == prefix or self.dotted.startswith(prefix + NAME_DOT)


@dataclass(frozen=True)
class LayerMap:
    """Карта слоёв E16: уровни, звенья цепочки, модули без импортов app и изолированные пакеты."""

    layers: tuple[Layer, ...]
    chain_level: str
    sealed: tuple[str, ...]
    isolated: tuple[str, ...]
    tool_imports: tuple[str, ...]

    @classmethod
    def of(cls, data: JsonObject) -> LayerMap:
        """Карта из стандарта; уровень, на который ссылается карта, обязан быть в ней — иначе `StandardFileError`."""
        layers: tuple[Layer, ...] = tuple(Layer.of(item) for item in data.objects(StandardKey.LAYERS.value))
        known: frozenset[str] = frozenset(layer.level for layer in layers)
        chain: str = data.text(StandardKey.CHAIN_LEVEL.value)
        unknown: list[str] = sorted(frozenset({chain}).union(*(layer.imports for layer in layers)) - known)
        if unknown:
            raise StandardFileError(JsonProblem.UNKNOWN_LEVEL, data.origin, unknown[0])
        return cls(
            layers=layers,
            chain_level=chain,
            sealed=tuple(SourceKey.of(raw).dotted for raw in data.texts(StandardKey.SEALED_MODULES.value)),
            isolated=tuple(SourceKey.of(raw).dotted for raw in data.texts(StandardKey.ISOLATED_PACKAGES.value)),
            tool_imports=data.texts(StandardKey.TOOL_IMPORTS.value),
        )

    def layer_of(self, package: str) -> Layer | None:
        return next((layer for layer in self.layers if package in layer.packages), None)

    def unit_of(self, name: AppName) -> str:
        """Как пакет модуля называется в ключе: модуль без импортов и изолированный пакет — целиком."""
        special: str | None = next((unit for unit in self.sealed + self.isolated if name.within(unit)), None)
        return AppName(special).inner if special else name.package

    def allows(self, source: AppName, target: AppName) -> bool:
        """Может ли модуль `source` импортировать модуль `target`."""
        if any(source.within(module) for module in self.sealed):
            return False
        isolated: str | None = next((package for package in self.isolated if source.within(package)), None)
        if isolated is not None:
            return target.within(isolated) or any(target.within(module) for module in self.tool_imports)
        if source.package == target.package:
            return True
        return self._level_allows(source.package, target.package)

    def _level_allows(self, source: str, target: str) -> bool:
        source_layer: Layer | None = self.layer_of(source)
        target_layer: Layer | None = self.layer_of(target)
        if source_layer is None or target_layer is None:
            return False
        if source_layer is target_layer and source_layer.level == self.chain_level:
            return source_layer.packages.index(target) < source_layer.packages.index(source)
        return target_layer.level in source_layer.imports


@dataclass(frozen=True)
class Standard:
    """Пороги правил формы (E3, E4, E18), списки, которые меняют их прочтение (E12, E18), и части стандарта
    для правил значений, клонов, слоёв и тестов.

    Пути модулей-исключений приводятся к ключу с обратной косой чертой, как ключи реестра.
    """

    max_definition_lines: int
    max_parameters: int
    max_module_lines: int
    max_class_members: int
    module_size_exempt: frozenset[str]
    wrapper_builtins: frozenset[str]
    values: ValueRules
    clones: CloneRules
    layers: LayerMap
    suite: SuiteRules

    @classmethod
    def load(cls, path: Path) -> Standard:
        """Стандарт из файла; нет ключа или не тот тип — `StandardFileError`."""
        data: JsonObject = JsonObject.read(path)
        return cls(
            max_definition_lines=data.integer(StandardKey.MAX_DEFINITION_LINES.value),
            max_parameters=data.integer(StandardKey.MAX_PARAMETERS.value),
            max_module_lines=data.integer(StandardKey.MAX_MODULE_LINES.value),
            max_class_members=data.integer(StandardKey.MAX_CLASS_MEMBERS.value),
            module_size_exempt=frozenset(
                SourceKey.of(exempt).text for exempt in data.texts(StandardKey.MODULE_SIZE_EXEMPT.value)
            ),
            wrapper_builtins=frozenset(data.texts(StandardKey.WRAPPER_BUILTINS.value)),
            values=ValueRules.of(data),
            clones=CloneRules.of(data),
            layers=LayerMap.of(data),
            suite=SuiteRules.of(data),
        )
