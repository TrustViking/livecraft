"""Поля сейфа одной вкладки окна без окна (CLAUDE.md §8.2 п.2, п.3, §7).

Модель держит поля сейфа своей вкладки (`page.secret_fields`): на «Таблице плана» — таблицу плана, на «Нейросети» —
ключ OpenAI, на «Telegram» — токен бота. По каждому полю она знает, задано ли оно и откуда, что показать и какие действия
доступны; проверяет ввод через объект поля (`SecretInput`) и записывает только личный сейф — через
`SetupVault.save_local`, и только свои поля поверх личного слоя, каким его знает окно после своей последней записи:
сохранение одной вкладки не затирает поля другой. Файлов и шифрования она не знает (§8.2: настройщик работает с
`Vault`, а с диском — `VaultStore` за сейфом окна `SetupVault`, который читает файлы один раз и заново — после записи). Окно Tk только рисует её ответы; библиотека окна сюда не импортируется, и ничего здесь не печатается.

API модели тот же, что у остальных моделей вкладок: `title`, `notices`, `is_dirty`, `save`. Модель неизменяемая:
`replace`, `reset` и `save` отдают новую, прежняя остаётся тем, чем была — отказ от правки не надо «откатывать», как
и у самого `Vault`. Повреждённый или нечитаемый файл сейфа — не тупик: пустой слой и оговорка, что сделать (личный файл
заменит сохранение, файл токена — загрузка токена).

Строка поля никогда не несёт значения — ни чужого, ни своего: в статусе только короткая маска. Открытый показ своего
значения — действие «показать своё» (§8.2: «своё — открыто с переключателем»): окно по явному нажатию спрашивает
`own_value`, единственную точку раскрытия значения в настройщике (§7.4, §14 решение 11). Поле из токена
показывается только маской: иначе весь §7 обнуляется.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.json_node import SettingProblem
from app.secretsafe.store import VaultLayerState, VaultLoad
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault, VaultEntry
from app.setup.fields.secret_input import SecretInput
from app.setup.page import SetupPage
from app.setup.panels.panel_edit import PanelEdit
from app.setup.setup_vault import SetupVault
from app.ui.messages import msg


class RowAction(str, Enum):
    """Что можно сделать со строкой вкладки. Значение — английский идентификатор, подписи — у окна."""

    ENTER = "enter"      # ввести: поля нет ни из токена, ни своего
    REPLACE = "replace"  # заменить своим
    RESET = "reset"      # убрать своё значение: вернётся значение из токена, а если его нет — поле опустеет
    REVEAL = "show_own"  # показать своё: окно открывает значение, которое пользователь ввёл сам


# Оговорка вкладки о личном файле, который не дал значений; «первое сохранение заменит» — только при can_save_own.
_LOCAL_STATE_NOTICES: Final[dict[VaultLayerState, str]] = {
    VaultLayerState.UNREADABLE: msg.SETUP_KEYS_NOTICE_LOCAL_UNREADABLE,
    VaultLayerState.BROKEN: msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN,
}
# Файл токена есть, но значений не дал: заменит его загрузка токена.
_TOKEN_LOST_STATES: Final[frozenset[VaultLayerState]] = frozenset({VaultLayerState.UNREADABLE, VaultLayerState.BROKEN})

# Действия по происхождению поля; None — поля нет вовсе.
_ACTIONS_BY_ORIGIN: Final[dict[VaultOrigin | None, frozenset[RowAction]]] = {
    VaultOrigin.TOKEN: frozenset({RowAction.REPLACE}),
    VaultOrigin.OWN: frozenset({RowAction.REPLACE, RowAction.RESET, RowAction.REVEAL}),
    None: frozenset({RowAction.ENTER}),
}
# Действия, которые вписывают своё значение: без DPAPI вписать его некуда (§7.3, абзац про Dpapi).
_OWN_WRITING_ACTIONS: Final[frozenset[RowAction]] = frozenset({RowAction.ENTER, RowAction.REPLACE})
# Статус заданного поля по происхождению: {mask} — короткая маска значения.
_STATUS_BY_ORIGIN: Final[dict[VaultOrigin, str]] = {
    VaultOrigin.TOKEN: msg.SETUP_KEY_STATUS_TOKEN,
    VaultOrigin.OWN: msg.SETUP_KEY_STATUS_OWN,
}


@dataclass(frozen=True)
class KeyRow:
    """Строка вкладки для одного поля: подпись и серая подсказка, статус (задано своё, из токена или не задано;
    `is_set` — для цвета), доступные действия и есть ли под своим значением значение из токена (`has_token`)."""

    field: SecretField
    label: str
    hint: str
    status: str
    is_set: bool
    actions: frozenset[RowAction]
    has_token: bool

    @classmethod
    def of(cls, field: SecretField, entry: VaultEntry | None, can_save_own: bool, has_token: bool) -> KeyRow:
        """Строка поля по его записи в сейфе: действия решает происхождение и то, можно ли писать своё."""
        origin: VaultOrigin | None = None if entry is None else entry.origin
        actions: frozenset[RowAction] = _ACTIONS_BY_ORIGIN[origin]
        if not can_save_own:
            actions = actions - _OWN_WRITING_ACTIONS
        status: str = msg.SETUP_STATUS_NOT_SET
        if entry is not None:
            status = _STATUS_BY_ORIGIN[entry.origin].format(mask=entry.secret.short_mask)
        return cls(
            field=field,
            label=msg.SETUP_KEY_FIELD_LABELS[field.value],
            hint=msg.SETUP_KEY_FIELD_HINTS.get(field.value, ""),
            status=status,
            is_set=entry is not None,
            actions=actions,
            has_token=has_token,
        )

    @property
    def reset_label(self) -> str | None:
        """Что сделает сброс своего значения: под своим есть значение из токена — «вернуть значение из токена», нет —
        «удалить». None — сброса у строки нет."""
        if RowAction.RESET not in self.actions:
            return None
        return msg.SETUP_KEYS_BUTTON_RESET_TO_TOKEN if self.has_token else msg.SETUP_KEYS_BUTTON_DELETE_OWN

    @property
    def empty_input_problem(self) -> str:
        """Что сказать на пустой ввод: есть сброс своего значения — назвать его настоящую кнопку, нет — просить ввод."""
        reset_label: str | None = self.reset_label
        if reset_label is None:
            return msg.SETUP_INPUT_EMPTY
        return msg.SETUP_INPUT_EMPTY_RESET.format(button=reset_label)


@dataclass(frozen=True)
class KeysPanel:
    """Поля сейфа вкладки `page`: слой токена и личный слой сейфа, состояния их файлов и правила работы с ними.

    `loaded_own` — личный слой, каким он прочитан с диска: по нему модель знает, есть ли несохранённое.
    `setup_vault` — сейф окна: откуда модель читается и куда пишет.
    """

    page: SetupPage
    token: Vault
    own: Vault
    local_state: VaultLayerState
    token_state: VaultLayerState
    can_save_own: bool
    loaded_own: Vault
    setup_vault: SetupVault = dataclasses.field(compare=False)   # откуда модель, а не что в ней

    @classmethod
    def of(cls, setup_vault: SetupVault, page: SetupPage) -> KeysPanel:
        """Оба слоя сейфа, как их знает окно, и можно ли на этой машине писать значения.

        Мягкий итог чтения: повреждённый файл — пустой слой (BROKEN), и вкладка открывается, чтобы первое сохранение
        или загрузка токена его заменили.
        """
        loaded: VaultLoad = setup_vault.lenient
        return cls(
            page=page,
            token=loaded.token,
            own=loaded.own,
            local_state=loaded.local_state,
            token_state=loaded.token_state,
            can_save_own=setup_vault.can_save,
            loaded_own=loaded.own,
            setup_vault=setup_vault,
        )

    @property
    def title(self) -> str:
        return self.page.title

    @property
    def fields(self) -> tuple[SecretField, ...]:
        """Поля сейфа этой вкладки."""
        return self.page.secret_fields

    @property
    def vault(self) -> Vault:
        """Сейф, с которым будет работать запуск: личный слой поверх слоя токена (правило §7.3 — одно)."""
        return self.token.overlaid_by(self.own)

    @property
    def rows(self) -> tuple[KeyRow, ...]:
        """По строке на поле вкладки в порядке `fields`."""
        return tuple(self.row(field) for field in self.fields)

    def row(self, field: SecretField) -> KeyRow:
        """Строка одного поля: запись итогового сейфа и то, есть ли под ней значение из токена."""
        return KeyRow.of(field, self.vault.entry(field), self.can_save_own, has_token=self.token.get(field) is not None)

    @property
    def notices(self) -> tuple[str, ...]:
        """Строки вкладки для человека: оговорка §7.2 — когда на вкладке есть значение из токена; нет DPAPI — что
        сохранить нельзя; иначе — что с файлами сейфа, которые не дали значений."""
        lines: list[str] = []
        if any(self.vault.origin_of(field) is VaultOrigin.TOKEN for field in self.fields):
            lines.append(msg.SETUP_KEYS_NOTICE_PROTECTION)
        if not self.can_save_own:
            lines.append(msg.SETUP_KEYS_NOTICE_NO_OWN)
            return tuple(lines)
        # «Первое сохранение заменит» честно только там, где сохранение возможно.
        notice: str | None = _LOCAL_STATE_NOTICES.get(self.local_state)
        if notice is not None:
            lines.append(notice)
        if self.token_state in _TOKEN_LOST_STATES:
            lines.append(msg.SETUP_KEYS_NOTICE_TOKEN_UNREADABLE)
        return tuple(lines)

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённые изменения: своё значение какого-то поля вкладки отличается от прочитанного с диска."""
        return any(self.own.entry(field) != self.loaded_own.entry(field) for field in self.fields)

    def own_value(self, field: SecretField) -> str | None:
        """Открытое значение поля — только своё, для кнопки «показать» окна (§7.4, §14 решение 11).

        Единственная точка раскрытия значения в настройщике. Раскрывается только значение, которое человек
        ввёл сам: поле этой вкладки, его строка разрешает «показать своё», и значение взято из личного слоя.
        Значение из токена, отсутствующее поле и поле другой вкладки — None, и раскрытия не происходит. Ничего
        не пишет в лог: значение уходит только на экран, окну, которое его попросило.
        """
        if field not in self.fields or RowAction.REVEAL not in self.row(field).actions:
            return None
        secret: SecretValue | None = self.own.get(field)
        if secret is None:
            return None
        return secret.reveal()

    def replace(self, field: SecretField, raw: str) -> PanelEdit[KeysPanel]:
        """Вписать своё значение поля. Ввод негоден или писать своё некуда — модель прежняя, проблема названа.

        Проблема — без самого значения (§7.4); пустой ввод в нужное поле называет строка поля: она знает свою
        кнопку сброса.
        """
        if not self.can_save_own:
            return PanelEdit(panel=self, problem=SettingProblem(key=field.value, text=msg.SETUP_INPUT_OWN_UNAVAILABLE))
        entered: SecretInput = SecretInput(field=field, raw=raw)
        secret: SecretValue | None = entered.secret
        if secret is None:
            text: str | None = self.row(field).empty_input_problem if entered.is_empty else entered.problem
            return PanelEdit(panel=self, problem=SettingProblem(key=field.value, text=text))
        return PanelEdit(panel=dataclasses.replace(self, own=self.own.with_field(field, secret, VaultOrigin.OWN)))

    def reset(self, field: SecretField) -> KeysPanel:
        """Убрать своё значение поля: под ним снова видно значение из токена, а если его нет — поля нет."""
        return dataclasses.replace(self, own=self.own.without_field(field))

    def save(self) -> PanelEdit[KeysPanel]:
        """Записать свои поля вкладки поверх личного слоя, каким его знает окно, и вернуть модель, прочитанную заново.

        Поля других вкладок берутся из сейфа окна как есть (его сбрасывает каждая запись окна): сохранение одной
        вкладки не откатывает сохранённое другой. Файл токена не трогается (это правило `VaultStore.save_local`).
        DpapiUnavailable и OSError — наружу: сказать о них человеку — дело окна.
        """
        fresh: Vault = self.setup_vault.lenient.own
        others: dict[SecretField, VaultEntry] = {
            field: entry for field, entry in fresh.entries.items() if field not in self.fields
        }
        mine: dict[SecretField, VaultEntry] = {
            field: entry for field, entry in self.own.entries.items() if field in self.fields
        }
        self.setup_vault.save_local(Vault(entries={**others, **mine}))
        return PanelEdit(panel=KeysPanel.of(self.setup_vault, self.page))
