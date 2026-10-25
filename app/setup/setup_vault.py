"""Сейф окна настройщика: прочитан один раз, заново — только после записи окна (CLAUDE.md §8.2, §7.3).

Окно спрашивает сейф на каждом шаге: готовность при открытии и после каждой записи (`SetupWindow.refresh`), поля сейфа
вкладок, папка Диска на двух вкладках, что войдёт в токен, бот вкладки «Логи». Каждое чтение — два файла, DPAPI и
расшифровка; пять-тринадцать таких чтений подряд в главном потоке Tk замораживали окно до 4 с (лог 30-09-2026_200119).
`SetupVault` читает файлы при первом вопросе и держит итог, пока окно само не записало сейф: пишет сейф только окно
(запуск при открытом окне не идёт — замок одного экземпляра), поэтому свежее, чем прочитанное, на диске взяться неоткуда.
Запись своих значений идёт через `save_local` и сбрасывает прочитанное; слой токена пишет загрузка токена в фоновом
потоке — о ней окно сообщает `changed()` в главном потоке по итогу загрузки.

Два итога чтения — те же, что у `VaultStore`: строгий (`strict`, `VaultRead`) для готовности — повреждённый файл там
ошибка; мягкий (`lenient`, `VaultLoad`) для вкладок — повреждённый файл там пустой слой BROKEN. Когда строгое чтение
прошло, мягкое совпадает с ним (они расходятся только на повреждённом файле), и второй раз файлы не читаются.
Объект — только для главного потока; проверки по кнопкам в фоновых потоках читают сейф сами.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.paths import LivecraftPaths
from app.secretsafe.store import VaultLoad, VaultRead, VaultStore
from app.secretsafe.vault import Vault


@dataclass
class SetupVault:
    """Сейф установки (`store`) и то, что окно из него прочитало: строгий итог (`read`) и мягкий (`loaded`); None —
    ещё не прочитано или окно с тех пор записало сейф."""

    store: VaultStore
    read: VaultRead | None = field(default=None, compare=False)
    loaded: VaultLoad | None = field(default=None, compare=False)

    @classmethod
    def open(cls, paths: LivecraftPaths) -> SetupVault:
        return cls(VaultStore.open(paths))

    @property
    def can_save(self) -> bool:
        """Можно ли на этой машине записать сейф (DPAPI)."""
        return self.store.can_save

    @property
    def strict(self) -> VaultRead:
        """Строгий итог — для готовности: прочитанный сейф или ошибка файла сейфа."""
        if self.read is None:
            self.read = VaultRead.of(self.store)
        return self.read

    @property
    def lenient(self) -> VaultLoad:
        """Мягкий итог — для вкладок: повреждённый файл — пустой слой BROKEN. Строгое чтение прошло — оно и есть."""
        if self.loaded is None:
            self.loaded = self.strict.load or self.store.load_for_setup()
        return self.loaded

    def save_local(self, vault: Vault) -> None:
        """Записать свои значения (`VaultStore.save_local`); прочитанное устарело. DpapiUnavailable и OSError — наружу."""
        self.store.save_local(vault)
        self.changed()

    def changed(self) -> None:
        """Сейф записан мимо `save_local` (загрузка токена): следующий вопрос читает файлы заново."""
        self.read = None
        self.loaded = None
