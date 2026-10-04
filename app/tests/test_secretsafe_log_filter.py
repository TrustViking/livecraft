from __future__ import annotations

import logging
from datetime import timezone
from pathlib import Path

import pytest

from app.core.clock import Clock
from app.observability.log_event import LogArea, get_logger
from app.observability.logging_setup import RunLog
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.log_filter import SecretScrubber
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault

THIRD_PARTY_LOGGER: str = "googleapiclient.discovery_cache"
CLOCK: Clock = Clock(timezone.utc)
SHEETS_ID: str = "1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg"
FOLDER_URL: str = "https://drive.google.com/drive/folders/1secretFolderIdPart_abc"


def _vault_with_two_secrets() -> Vault:
    """Сейф с двумя полями: так его отдаст VaultStore боевому запуску."""
    return (
        Vault.empty()
        .with_field(
            SecretField.SHEETS_ID,
            SecretValue(field=SecretField.SHEETS_ID, value=SHEETS_ID),
            VaultOrigin.TOKEN,
        )
        .with_field(
            SecretField.DRIVE_FOLDER,
            SecretValue(field=SecretField.DRIVE_FOLDER, value=FOLDER_URL),
            VaultOrigin.OWN,
        )
    )


def _secret_of(vault: Vault, field: SecretField) -> SecretValue:
    secret: SecretValue | None = vault.get(field)
    assert secret is not None
    return secret


def _protected_log(tmp_path: Path, vault: Vault, debug: bool = False) -> RunLog:
    """Лог запуска с фильтром сейфа — так его ставит запуск сразу после чтения сейфа."""
    log: RunLog = RunLog.open(tmp_path, debug=debug, started=CLOCK.now())
    log.protect(vault.log_filter())
    return log


def test_the_vault_builds_a_scrubber_of_its_own_secrets() -> None:
    vault: Vault = _vault_with_two_secrets()
    log_filter: logging.Filter = vault.log_filter()
    assert isinstance(log_filter, SecretScrubber)
    assert log_filter.secrets == vault.secrets()


def test_a_secret_in_the_template_does_not_reach_the_log(tmp_path: Path) -> None:
    """LOGGER.info(url): значение пришло самим шаблоном записи."""
    vault: Vault = _vault_with_two_secrets()
    log: RunLog = _protected_log(tmp_path, vault)
    get_logger(LogArea.SHEETS).info(f"sheet_read {SHEETS_ID}")
    log.close()
    text: str = log.path.read_text(encoding="utf-8")
    assert SHEETS_ID not in text
    assert _secret_of(vault, SecretField.SHEETS_ID).log_label in text


def test_a_secret_in_an_argument_does_not_reach_the_log(tmp_path: Path) -> None:
    """LOGGER.info("url=%s", url): значение пришло аргументом, целиком оно есть только после подстановки."""
    vault: Vault = _vault_with_two_secrets()
    log: RunLog = _protected_log(tmp_path, vault)
    get_logger(LogArea.SETUP).info("folder_ready url=%s questions=%d", FOLDER_URL, 6)
    log.close()
    text: str = log.path.read_text(encoding="utf-8")
    assert FOLDER_URL not in text
    assert _secret_of(vault, SecretField.DRIVE_FOLDER).log_label in text
    assert "questions=6" in text                      # остальная часть записи не пострадала


def test_a_secret_written_by_a_third_party_logger_does_not_reach_the_log(tmp_path: Path) -> None:
    """Тот случай, ради которого фильтр и нужен: URL печатает googleapiclient, а не наш код."""
    vault: Vault = _vault_with_two_secrets()
    log: RunLog = _protected_log(tmp_path, vault)
    logging.getLogger(THIRD_PARTY_LOGGER).warning("URL being requested: GET %s", f"https://x/{SHEETS_ID}?alt=json")
    log.close()
    text: str = log.path.read_text(encoding="utf-8")
    assert SHEETS_ID not in text
    assert _secret_of(vault, SecretField.SHEETS_ID).log_label in text


def test_the_filter_cleans_rather_than_drops_records(tmp_path: Path) -> None:
    """Фильтр не выбрасывает записи: строк в логе столько же, сколько без него."""
    log: RunLog = _protected_log(tmp_path, _vault_with_two_secrets())
    get_logger(LogArea.SHEETS).info("sheet_read id=%s", SHEETS_ID)
    get_logger(LogArea.SETUP).info("folder_ready url=%s", FOLDER_URL)
    get_logger(LogArea.MAIN).info("run_finished exit_code=0")
    log.close()
    lines: list[str] = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert SHEETS_ID not in "".join(lines) and FOLDER_URL not in "".join(lines)


def test_both_secrets_are_scrubbed_from_one_record(tmp_path: Path) -> None:
    vault: Vault = _vault_with_two_secrets()
    log: RunLog = _protected_log(tmp_path, vault)
    get_logger(LogArea.SHEETS).info("pair %s and %s", SHEETS_ID, FOLDER_URL)
    log.close()
    text: str = log.path.read_text(encoding="utf-8")
    assert SHEETS_ID not in text and FOLDER_URL not in text
    assert _secret_of(vault, SecretField.SHEETS_ID).log_label in text
    assert _secret_of(vault, SecretField.DRIVE_FOLDER).log_label in text


def test_a_record_with_mismatched_arguments_still_loses_the_secret() -> None:
    """Шаблон и аргументы не сошлись: запись не отформатируется, но значение не должно попасть и в stderr."""
    vault: Vault = _vault_with_two_secrets()
    record: logging.LogRecord = logging.LogRecord(
        name=get_logger(LogArea.SHEETS).name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="sheet_read id=%s range=%s",
        args=(SHEETS_ID,),
        exc_info=None,
    )
    assert vault.log_filter().filter(record) is True
    assert SHEETS_ID not in str(record.msg)
    assert SHEETS_ID not in str(record.args)


def test_an_empty_vault_filter_changes_nothing(tmp_path: Path) -> None:
    """Пустой сейф — фильтр без секретов: записи проходят как есть."""
    log: RunLog = _protected_log(tmp_path, Vault.empty())
    get_logger(LogArea.MAIN).info("run_started version=%s", "0.1.0")
    log.close()
    assert "run_started version=0.1.0" in log.path.read_text(encoding="utf-8")


def test_debug_terminal_output_loses_the_secret_too(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """С --debug сырой лог идёт в stderr — фильтр стоит и там."""
    log: RunLog = _protected_log(tmp_path, _vault_with_two_secrets(), debug=True)
    get_logger(LogArea.SHEETS).info("sheet_read id=%s", SHEETS_ID)
    err: str = capsys.readouterr().err
    log.close()
    assert SHEETS_ID not in err and "sheets-plan(" in err


BOT_TOKEN: str = "7000000001:AAHown-Ab3dEfGhIjKlMnOpQrStUvWxYz_0123"


def test_the_bot_token_in_a_urllib3_request_line_does_not_reach_the_log(tmp_path: Path) -> None:
    """Токен бота стоит в пути запроса Bot API, и urllib3 печатает этот путь в DEBUG — фильтр сейфа его вычёркивает."""
    secret: SecretValue = SecretValue(field=SecretField.TELEGRAM_BOT_TOKEN, value=BOT_TOKEN)
    vault: Vault = Vault.empty().with_field(SecretField.TELEGRAM_BOT_TOKEN, secret, VaultOrigin.OWN)
    log: RunLog = _protected_log(tmp_path, vault, debug=True)
    logging.getLogger("urllib3.connectionpool").warning(
        '%s://%s:%s "%s %s %s" %s %s', "https", "api.telegram.org", 443, "POST", f"/bot{BOT_TOKEN}/sendMessage",
        "HTTP/1.1", 200, None,
    )
    log.close()
    text: str = log.path.read_text(encoding="utf-8")
    assert f'"POST /bot{secret.log_label}/sendMessage HTTP/1.1" 200' in text
    assert BOT_TOKEN not in text
