"""Вкладка «Ключи и ссылки» без окна (CLAUDE.md §8.2 п.1, §7).

Вкладка знает по каждому полю сейфа, откуда оно, что показать и какие действия доступны; проверяет ввод
через объект поля (`SecretInput`) и записывает только личный сейф — через `VaultStore.save_local`. Файлов
и шифрования она не знает (§8.2: настройщик работает с `Vault`, а с диском — `VaultStore`). Окно Tk
(задача 2.3) только рисует её ответы; библиотека окна сюда не импортируется, и ничего здесь не печатается.

Вкладка неизменяемая: `replace`, `reset` и `save` отдают новую, прежняя остаётся тем, чем была — отказ от
правки не надо «откатывать», как и у самого `Vault`.

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

from app.secretsafe.store import LocalVaultState, VaultLoad, VaultStore
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultEntry, VaultOrigin
from app.setup.fields.secret_input import SecretInput
from app.ui import messages_ru as msg


class RowAction(str, Enum):
    """Что можно сделать со строкой вкладки. Значение — английский идентификатор, подписи — у окна."""

    ENTER = "enter"      # ввести: поля нет ни в поставке, ни своего
    REPLACE = "replace"  # заменить своим
    RESET = "reset"      # сбросить к поставке: убрать своё значение
    REVEAL = "show_own"  # показать своё: окно открывает значение, которое пользователь ввёл сам


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
    """Строка вкладки для одного поля: название, происхождение, маска и доступные действия."""

    field: SecretField
    label: str
    origin_label: str
    display: str
    actions: frozenset[RowAction]

    @classmethod
    def of(cls, field: SecretField, entry: VaultEntry | None, can_save_own: bool) -> KeyRow:
        """Строка поля по его записи в сейфе: действия решает происхождение и то, можно ли писать своё."""
        origin: VaultOrigin | None = None if entry is None else entry.origin
        actions: frozenset[RowAction] = _ACTIONS_BY_ORIGIN[origin]
        if not can_save_own:
            actions = actions - _OWN_WRITING_ACTIONS
        return cls(
            field=field,
            label=field.human_label,
            origin_label=msg.READINESS_FIELD_ABSENT if origin is None else origin.human_label,
            display=msg.READINESS_FIELD_ABSENT if entry is None else entry.masked,
            actions=actions,
        )


@dataclass(frozen=True)
class KeysPanelEdit:
    """Итог правки поля: вкладка после неё и проблема ввода.

    Ввод негоден — `panel` та же, что была до правки, а `problem` называет, что не так: исключение здесь
    не годится, потому что негодный ввод — обычный исход работы с формой, а не сбой.
    """

    panel: KeysPanel
    problem: str | None

    @property
    def is_applied(self) -> bool:
        """Правка принята: вкладка содержит новое значение."""
        return self.problem is None


@dataclass(frozen=True)
class KeysPanel:
    """Вкладка «Ключи и ссылки»: поставочный и личный слои сейфа и правила работы с ними.

    `loaded_own` — личный слой, каким он прочитан с диска: по нему вкладка знает, есть ли несохранённое.
    """

    supplied: Vault
    own: Vault
    local_state: LocalVaultState
    can_save_own: bool
    loaded_own: Vault

    @classmethod
    def from_store(cls, store: VaultStore) -> KeysPanel:
        """Прочитать оба файла сейфа и узнать, можно ли на этой машине писать свои значения."""
        loaded: VaultLoad = store.load()
        return cls(
            supplied=loaded.supplied,
            own=loaded.own,
            local_state=loaded.local_state,
            can_save_own=store.can_save_local,
            loaded_own=loaded.own,
        )

    @property
    def vault(self) -> Vault:
        """Сейф, с которым будет работать запуск: личный слой поверх поставочного (правило §7.3 — одно)."""
        return VaultLoad.from_layers(supplied=self.supplied, own=self.own, local_state=self.local_state).vault

    @property
    def rows(self) -> tuple[KeyRow, ...]:
        """По строке на поле сейфа в порядке SecretField."""
        vault: Vault = self.vault
        return tuple(KeyRow.of(field, vault.entries.get(field), self.can_save_own) for field in SecretField)

    @property
    def notices(self) -> tuple[str, ...]:
        """Строки вкладки для человека: оговорка §7.2 — всегда, остальное — по состоянию сейфа."""
        lines: list[str] = [msg.SETUP_KEYS_NOTICE_PROTECTION]
        if not self.can_save_own:
            lines.append(msg.SETUP_KEYS_NOTICE_NO_OWN)
        elif self.local_state is LocalVaultState.UNREADABLE:
            # «Первое сохранение заменит» честно только там, где сохранение возможно.
            lines.append(msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE)
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
        if RowAction.REVEAL not in KeyRow.of(field, self.vault.entries.get(field), self.can_save_own).actions:
            return None
        secret: SecretValue | None = self.own.get(field)
        if secret is None:
            return None
        return secret.reveal()

    def replace(self, field: SecretField, raw: str) -> KeysPanelEdit:
        """Вписать своё значение поля. Ввод негоден или писать своё некуда — вкладка прежняя, проблема названа."""
        if not self.can_save_own:
            return KeysPanelEdit(panel=self, problem=msg.SETUP_INPUT_OWN_UNAVAILABLE)
        entered: SecretInput = SecretInput(field=field, raw=raw)
        secret: SecretValue | None = entered.secret
        if secret is None:
            return KeysPanelEdit(panel=self, problem=entered.problem)
        own: Vault = self.own.with_field(field, secret, VaultOrigin.OWN)
        return KeysPanelEdit(panel=self._with_own(own), problem=None)

    def reset(self, field: SecretField) -> KeysPanel:
        """Убрать своё значение поля: под ним снова видно поставочное, а если его нет — поля нет."""
        return self._with_own(self.own.without_field(field))

    def save(self, store: VaultStore) -> KeysPanel:
        """Записать личный слой в личный сейф и вернуть вкладку, прочитанную заново.

        Поставочный файл не трогается (это правило `VaultStore.save_local`). DpapiUnavailable — наружу:
        сказать о нём человеку — дело окна (задача 2.3).
        """
        store.save_local(self.own)
        return KeysPanel.from_store(store)

    def _with_own(self, own: Vault) -> KeysPanel:
        """Копия вкладки с другим личным слоем; прочитанное с диска и всё прочее — как было."""
        return dataclasses.replace(self, own=own)
