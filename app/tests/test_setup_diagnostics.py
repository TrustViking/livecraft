"""diagnostics.txt архива логов (§13 задача 7.2, §14 решение 20): версия, машина, снимок запуска и готовность — без
значений сейфа (§7.4)."""
from __future__ import annotations

import json
import platform
from datetime import datetime, timezone

from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField
from app.setup.diagnostics import Diagnostics
from app.setup.readiness import Readiness
from app.tests.fixtures.telegram import BOT_TOKEN
from app.tests.fixtures.vault import TOKEN_VALUES, save_own_values
from app.version import APP_VERSION

MOMENT: datetime = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)
DRIVE_FOLDER_ID: str = "1OwnDriveFolderAbCdEfGhIjKlMnOpQrSt"


def _text(paths: LivecraftPaths) -> str:
    return Diagnostics(Readiness.check(paths), MOMENT).text


def test_the_diagnostics_name_the_program_the_machine_and_the_snapshot(ready_paths: LivecraftPaths) -> None:
    lines: list[str] = _text(ready_paths).splitlines()
    assert lines[0].startswith(f"diagnostics_program version={APP_VERSION} moment={MOMENT.isoformat()} ")
    assert f"python={platform.python_version()}" in lines[0] and "ui_language=ru" in lines[0]
    assert [line.split(" ")[0] for line in lines[1:]] == [
        "run_snapshot_settings", "run_snapshot_lines", "run_snapshot_folders", "run_snapshot_channels",
        "run_snapshot_vault", "diagnostics_readiness",
    ]
    window_line: str = Readiness.check(ready_paths).window_line
    assert lines[-1] == "diagnostics_readiness line=" + json.dumps(window_line, ensure_ascii=False)


def test_no_value_of_the_vault_reaches_the_diagnostics(ready_paths: LivecraftPaths) -> None:
    """Значения из токена и свои значения — только ярлыками с отпечатками, как в логе."""
    save_own_values(ready_paths, {SecretField.TELEGRAM_BOT_TOKEN: BOT_TOKEN, SecretField.DRIVE_FOLDER: DRIVE_FOLDER_ID})
    text: str = _text(ready_paths)
    for value in (*TOKEN_VALUES.values(), BOT_TOKEN, DRIVE_FOLDER_ID):
        assert value not in text
