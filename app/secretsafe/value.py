"""Секрет в памяти: обёртка, которая не вытекает ни в один вывод (CLAUDE.md §7.3, §7.4).

Правило §7.4 дословно: расшифрованное значение живёт **только** в `SecretValue` и только в памяти.
Получить его можно единственным методом доступа (он ниже, один во всём проекте), и зовут его только в точках
применения, перечисленных в §7.4: заголовок `Authorization` клиента OpenAI, параметры клиента Sheets, адрес
Bot API, кнопка «показать своё» настройщика и временный перенос ссылки формы из сейфа. Поэтому имя этого метода встречается в пакете ровно один раз — там, где он объявлен;
поиск по нему показывает все точки применения и стережёт правило §7.4.

Всё остальное, что делают с секретом, должно давать маску. Поэтому `__str__`, `__repr__` и `__format__`
переопределены все три: секрет, случайно попавший в `f"{...}"`, в `logging.info("%s", …)`, в `repr`
объекта-владельца или в текст исключения, выходит маской. `__format__` намеренно **игнорирует**
спецификатор: без этого `f"{secret:>40}"` ушёл бы в `str.__format__` и напечатал значение.

Ни одной свободной функции с доступом к значению в этом модуле нет (§7.3): смотреть на значение умеет
только сам `SecretValue`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

from app.core.text_format import TEXT_ENCODING
from app.secretsafe.crypto import EncryptedField, VaultCrypto
from app.secretsafe.field import MaskStyle, SecretField
from app.ui import messages_ru as msg

FINGERPRINT_CHARS: Final[int] = 4      # первые 4 hex sha256: различить два значения — да, восстановить — нет
TAIL_HEAD_CHARS: Final[int] = 3        # у ключа API показываем начало…
TAIL_CHARS: Final[int] = 4             # …и хвост, чтобы владелец узнал свой ключ
TAIL_MIN_LENGTH: Final[int] = 8        # короче — показывать нечего, скрываем целиком
MASK_ELLIPSIS: Final[str] = "…"
MASK_HIDDEN: Final[str] = "…"          # значение целиком скрыто
LOG_LABEL_TEMPLATE: Final[str] = "{label}({fingerprint})"


@dataclass(frozen=True)
class SecretValue:
    """Секретная строка и всё, что о ней можно сказать не раскрывая её.

    `value` приватно по смыслу: наружу оно не отдаётся ничем, кроме единственного метода доступа. `repr`
    тоже маска — иначе `dataclass` печатал бы поле `value` в каждой трассировке.
    """

    field: SecretField
    value: str

    def reveal(self) -> str:
        """Единственный способ получить значение. Зовётся только в точке применения (§7.4)."""
        return self.value

    @property
    def masked(self) -> str:
        """То, что видят люди: по `mask_style` своего поля."""
        if self.field.mask_style is MaskStyle.TAIL:
            return self._tail_mask
        return msg.VAULT_MASK_FINGERPRINT.format(label=self.field.human_label, fingerprint=self.fingerprint)

    @property
    def fingerprint(self) -> str:
        """Первые 4 hex sha256 от значения (§7.4): различить две формы в одном запуске — да, восстановить — нет."""
        return hashlib.sha256(self.value.encode(TEXT_ENCODING)).hexdigest()[:FINGERPRINT_CHARS]

    @property
    def log_label(self) -> str:
        """Что уходит в лог вместо значения: `key-form(9c2b)` (§7.4)."""
        return LOG_LABEL_TEMPLATE.format(label=self.field.log_label, fingerprint=self.fingerprint)

    def scrub(self, text: str) -> str:
        """Вычеркнуть своё значение из готовой строки, подставив вместо него ярлык с отпечатком.

        Вычёркиванием занимается сам секрет, а не фильтр логов: так значение не покидает объект — фильтру
        незачем знать, что именно он вычёркивает (§7.4, первый пункт). Пустое значение строку не меняет:
        пустая подстрока нашлась бы в любом тексте.
        """
        if not self.value:
            return text
        return text.replace(self.value, self.log_label)

    def encrypt(self, crypto: VaultCrypto) -> EncryptedField:
        """Зашифровать себя переданным шифратором и отдать зашифрованное поле.

        Шифрование — операция внутри сейфа, а не выдача значения наружу, поэтому правило принадлежит самому
        секрету (§0): значение объект не покидает, наружу уходит только шифротекст. Своё поле секрет тоже
        называет сам — от него зависит привязка блоба к месту (AAD в VaultCrypto), и перепутать её вызывающий
        уже не может.
        """
        return crypto.encrypt(self.field, self.value)

    @property
    def _tail_mask(self) -> str:
        """«sk-…dc7f»; короткое значение скрывается целиком — из трёх символов складывается весь секрет."""
        if len(self.value) < TAIL_MIN_LENGTH:
            return MASK_HIDDEN
        return f"{self.value[:TAIL_HEAD_CHARS]}{MASK_ELLIPSIS}{self.value[-TAIL_CHARS:]}"

    def __str__(self) -> str:
        return self.masked

    def __repr__(self) -> str:
        return self.masked

    def __format__(self, format_spec: str) -> str:
        """Спецификатор игнорируется намеренно: f"{secret:>40}" не должен обойти маску."""
        return self.masked
