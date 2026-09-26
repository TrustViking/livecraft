"""Вкладка «Ключи и ссылки» без окна (CLAUDE.md §8.2 п.1, §7).

Вкладка знает по каждому полю сейфа, откуда оно, что показать и какие действия доступны; проверяет ввод
через объект поля (`SecretInput`) и записывает только личный сейф — через `VaultStore.save_local`. Файлов
и шифрования она не знает (§8.2: настройщик работает с `Vault`, а с диском — `VaultStore`). Окно Tk только
рисует её ответы; библиотека окна сюда не импортируется, и ничего здесь не печатается.

API вкладки тот же, что у двух других моделей: `title`, `notices`, `is_dirty`, `save`. Вкладка неизменяемая:
`replace`, `reset` и `save` отдают новую, прежняя остаётся тем, чем была — отказ от правки не надо
«откатывать», как и у самого `Vault`. Файл сейфа программы повреждён — вкладка всё равно есть: без строк, с
причиной (`load_problem`) в оговорках, и ничего не даёт править.

Строка вкладки никогда не несёт значения — ни чужого, ни своего: в `display` только маска. Открытый показ
своего значения — действие «показать своё» (§8.2: «своё — открыто с переключателем»): окно по явному нажатию
спрашивает `own_value`, единственную точку раскрытия значения в настройщике (§7.4, §14 решение 11).
Поле из поставки показывается только маской: иначе весь §7 обнуляется.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.json_node import SettingProblem
from app.paths import LivecraftPaths
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import LocalVaultState, VaultLoad, VaultStore
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault, VaultEntry
from app.setup.fields.secret_input import SecretInput
from app.setup.panels.panel_edit import PanelEdit
from app.ui import messages_ru as msg


class RowAction(str, Enum):
    """Что можно сделать со строкой вкладки. Значение — английский идентификатор, подписи — у окна."""

    ENTER = "enter"      # ввести: поля нет ни в поставке, ни своего
    REPLACE = "replace"  # заменить своим
    RESET = "reset"      # убрать своё значение: вернётся поставочное, а если его нет — поле опустеет
    REVEAL = "show_own"  # показать своё: окно открывает значение, которое пользователь ввёл сам


# Оговорка вкладки о личном файле, который не дал значений; «первое сохранение заменит» — только при can_save_own.
_LOCAL_STATE_NOTICES: Final[dict[LocalVaultState, str]] = {
    LocalVaultState.UNREADABLE: msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE,
    LocalVaultState.BROKEN: msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN,
}

# Действия по происхождению поля; None — поля нет вовсе.
_ACTIONS_BY_ORIGIN: Final[dict[VaultOrigin | None, frozenset[RowAction]]] = {
    VaultOrigin.SUPPLIED: frozenset({RowAction.REPLACE}),
    VaultOrigin.OWN: frozenset({RowAction.REPLACE, RowAction.RESET, RowAction.REVEAL}),
    None: frozenset({RowAction.ENTER}),
}
# Действия, которые вписывают своё значение: без DPAPI вписать его некуда (§7.3, абзац про Dpapi).
_OWN_WRITING_ACTIONS: Final[frozenset[RowAction]] = frozenset({RowAction.ENTER, RowAction.REPLACE})


@dataclass(frozen=True)
class KeyRow:
    """Строка вкладки для одного поля: название, происхождение, маска, доступные действия и есть ли под своим
    значением поставочное (`has_supplied`)."""

    field: SecretField
    label: str
    origin_label: str
    display: str
    actions: frozenset[RowAction]
    has_supplied: bool

    @classmethod
    def of(cls, field: SecretField, entry: VaultEntry | None, can_save_own: bool, has_supplied: bool) -> KeyRow:
        """Строка поля по его записи в сейфе: действия решает происхождение и то, можно ли писать своё."""
        origin: VaultOrigin | None = None if entry is None else entry.origin
        actions: frozenset[RowAction] = _ACTIONS_BY_ORIGIN[origin]
        if not can_save_own:
            actions = actions - _OWN_WRITING_ACTIONS
        return cls(
            field=field,
            label=field.human_label,
            origin_label=msg.NONE_TEXT if origin is None else origin.human_label,
            display=msg.NONE_TEXT if entry is None else entry.masked,
            actions=actions,
            has_supplied=has_supplied,
        )

    @property
    def reset_label(self) -> str | None:
        """Что сделает сброс своего значения: под своим есть поставочное — «вернуть значение программы», нет —
        «удалить своё значение». None — сброса у строки нет."""
        if RowAction.RESET not in self.actions:
            return None
        return msg.SETUP_KEYS_BUTTON_RESET_TO_SUPPLIED if self.has_supplied else msg.SETUP_KEYS_BUTTON_DELETE_OWN

    @property
    def empty_input_problem(self) -> str:
        """Что сказать на пустой ввод: есть сброс своего значения — назвать его настоящую кнопку, нет — просить ввод."""
        reset_label: str | None = self.reset_label
        if reset_label is None:
            return msg.SETUP_INPUT_EMPTY
        return msg.SETUP_INPUT_EMPTY_RESET.format(button=reset_label)


@dataclass(frozen=True)
class KeysPanel:
    """Вкладка «Ключи и ссылки»: поставочный и личный слои сейфа и правила работы с ними.

    `loaded_own` — личный слой, каким он прочитан с диска: по нему вкладка знает, есть ли несохранённое.
    `store` — сейф этой установки на диске. `load_problem` — почему файл сейфа программы не прочитан (None —
    прочитан): тогда слои пусты, строк нет и писать некуда.
    """

    supplied: Vault
    own: Vault
    local_state: LocalVaultState
    can_save_own: bool
    loaded_own: Vault
    store: VaultStore = dataclasses.field(compare=False)   # где сейф лежит, а не что в нём
    load_problem: VaultFormatError | None = None

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> KeysPanel:
        """Вкладка на сейфе этой установки."""
        return cls.from_store(VaultStore.open(paths))

    @classmethod
    def from_store(cls, store: VaultStore) -> KeysPanel:
        """Прочитать оба файла сейфа и узнать, можно ли на этой машине писать свои значения.

        Читается путём настройщика: повреждённый личный файл — пустой личный слой (BROKEN), и вкладка
        открывается, чтобы первое сохранение его заменило. Повреждён файл программы — вкладка с причиной.
        """
        try:
            loaded: VaultLoad = store.load_for_setup()
        except VaultFormatError as error:
            empty: Vault = Vault.empty()
            return cls(
                supplied=empty, own=empty, local_state=LocalVaultState.ABSENT, can_save_own=False, loaded_own=empty,
                store=store, load_problem=error,
            )
        return cls(
            supplied=loaded.supplied,
            own=loaded.own,
            local_state=loaded.local_state,
            can_save_own=store.can_save_local,
            loaded_own=loaded.own,
            store=store,
        )

    @property
    def title(self) -> str:
        return msg.SETUP_TAB_KEYS

    @property
    def vault(self) -> Vault:
        """Сейф, с которым будет работать запуск: личный слой поверх поставочного (правило §7.3 — одно)."""
        return self.supplied.overlaid_by(self.own)

    @property
    def rows(self) -> tuple[KeyRow, ...]:
        """По строке на нужное поле сейфа в порядке SecretField; устаревшие поля вкладка не показывает.
        Сейф программы не прочитан — строк нет."""
        if self.load_problem is not None:
            return ()
        return tuple(self.row(field) for field in SecretField.current())

    def row(self, field: SecretField) -> KeyRow:
        """Строка одного поля: запись итогового сейфа и то, есть ли под ней поставочное значение."""
        return KeyRow.of(
            field,
            self.vault.entry(field),
            self.can_save_own,
            has_supplied=self.supplied.get(field) is not None,
        )

    @property
    def notices(self) -> tuple[str, ...]:
        """Строки вкладки для человека: сейф программы не прочитан — причина; иначе оговорка §7.2 — всегда,
        остальное — по состоянию сейфа."""
        if self.load_problem is not None:
            return (self.load_problem.human,)
        lines: list[str] = [msg.SETUP_KEYS_NOTICE_PROTECTION]
        if not self.can_save_own:
            lines.append(msg.SETUP_KEYS_NOTICE_NO_OWN)
            return tuple(lines)
        # «Первое сохранение заменит» честно только там, где сохранение возможно.
        notice: str | None = _LOCAL_STATE_NOTICES.get(self.local_state)
        if notice is not None:
            lines.append(notice)
        return tuple(lines)

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённые изменения: личный слой отличается от прочитанного с диска."""
        return self.own != self.loaded_own

    def own_value(self, field: SecretField) -> str | None:
        """Открытое значение поля — только своё, для кнопки «показать» окна (§7.4, §14 решение 11).

        Единственная точка раскрытия значения в настройщике. Раскрывается только значение, которое человек
        ввёл сам: строка поля разрешает «показать своё», и значение взято из личного слоя. Поставочное
        значение и отсутствующее поле — None, и раскрытия не происходит. Ничего не пишет в лог: значение
        уходит только на экран, окну, которое его попросило.
        """
        if RowAction.REVEAL not in self.row(field).actions:
            return None
        secret: SecretValue | None = self.own.get(field)
        if secret is None:
            return None
        return secret.reveal()

    def replace(self, field: SecretField, raw: str) -> PanelEdit[KeysPanel]:
        """Вписать своё значение поля. Ввод негоден или писать своё некуда — вкладка прежняя, проблема названа.

        Проблема — без самого значения (§7.4); пустой ввод в нужное поле называет строка поля: она знает свою
        кнопку сброса.
        """
        if not self.can_save_own:
            return PanelEdit(panel=self, problem=SettingProblem(key=field.value, text=msg.SETUP_INPUT_OWN_UNAVAILABLE))
        entered: SecretInput = SecretInput(field=field, raw=raw)
        secret: SecretValue | None = entered.secret
        if secret is None:
            is_blank: bool = entered.is_empty and not field.is_legacy
            text: str | None = self.row(field).empty_input_problem if is_blank else entered.problem
            return PanelEdit(panel=self, problem=SettingProblem(key=field.value, text=text))
        return PanelEdit(panel=dataclasses.replace(self, own=self.own.with_field(field, secret, VaultOrigin.OWN)))

    def reset(self, field: SecretField) -> KeysPanel:
        """Убрать своё значение поля: под ним снова видно поставочное, а если его нет — поля нет."""
        return dataclasses.replace(self, own=self.own.without_field(field))

    def save(self) -> PanelEdit[KeysPanel]:
        """Записать личный слой в личный сейф и вернуть вкладку, прочитанную заново.

        Поставочный файл не трогается (это правило `VaultStore.save_local`). DpapiUnavailable и OSError —
        наружу: сказать о них человеку — дело окна.
        """
        self.store.save_local(self.own)
        return PanelEdit(panel=KeysPanel.from_store(self.store))
