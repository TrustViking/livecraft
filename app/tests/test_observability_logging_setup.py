from __future__ import annotations

import logging
import re
import shutil
import warnings
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from app.core.dates import FILE_STAMP_FORMAT
from app.observability.logging_setup import (
    ROOT_LOGGER_NAME,
    SecretScrubber,
    close_logging,
    get_logger,
    install_secret_filter,
    mask_stream_key,
    setup_logging,
)
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin

THIRD_PARTY_LOGGER: str = "googleapiclient.discovery_cache"
STREAM_KEY: str = "abcd-efgh-ijkl-mnop-qrst"
LOG_NAME_PATTERN: re.Pattern[str] = re.compile(r"^\d{2}-\d{2}-\d{4}_\d{6}_livecraft\.log$")


@pytest.fixture(autouse=True)
def _closed_logging() -> Iterator[None]:
    yield
    close_logging()


def _emit() -> None:
    get_logger("youtube").warning("broadcast_not_found slot_id=16-09-2026_1900_uk")
    get_logger("youtube").info("run_report mode=full")
    logging.getLogger(THIRD_PARTY_LOGGER).warning("file_cache is only supported with oauth2client<4.0.0")
    logging.getLogger(THIRD_PARTY_LOGGER).info("third party chatter")


def test_root_logger_is_named_livecraft() -> None:
    """Имя корневого логгера — константа, дочерние — livecraft.<домен> (CLAUDE.md §11)."""
    assert ROOT_LOGGER_NAME == "livecraft"
    assert get_logger("sheets").name == "livecraft.sheets"


def test_log_file_is_date_time_livecraft(tmp_path: Path) -> None:
    """logs\\{DD-MM-YYYY}_{HHMMSS}_livecraft.log (CLAUDE.md §5)."""
    log_path: Path = setup_logging(tmp_path, debug=False)
    assert log_path.parent == tmp_path
    assert LOG_NAME_PATTERN.fullmatch(log_path.name), log_path.name
    stamp: str = log_path.name.split("_livecraft.log")[0]
    assert datetime.strptime(stamp, FILE_STAMP_FORMAT) is not None


def test_without_debug_nothing_goes_to_the_terminal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Терминал — только тексты оператора: ни WARNING livecraft, ни чужой WARNING, ни lastResort."""
    log_path: Path = setup_logging(tmp_path, debug=False)
    _emit()
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        logging.captureWarnings(True)      # catch_warnings вернул свой showwarning — повторяем то, что делает setup
        warnings.warn("library deprecation", DeprecationWarning, stacklevel=1)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert captured.err == "" and captured.out == ""
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert " | WARNING | livecraft.youtube | broadcast_not_found" in text
    assert " | INFO | livecraft.youtube | run_report" in text        # файл livecraft — DEBUG
    assert f" | WARNING | {THIRD_PARTY_LOGGER} | file_cache" in text
    assert "third party chatter" not in text                        # чужие — от WARNING
    assert "library deprecation" in text


def test_debug_prints_the_log_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(tmp_path, debug=True)
    _emit()
    err: str = capsys.readouterr().err
    assert " | WARNING | livecraft.youtube | broadcast_not_found" in err
    assert " | INFO | livecraft.youtube | run_report" in err
    assert f" | WARNING | {THIRD_PARTY_LOGGER} | file_cache" in err


def test_close_removes_only_own_handlers_from_the_python_root(tmp_path: Path) -> None:
    python_root: logging.Logger = logging.getLogger()
    before: list[logging.Handler] = list(python_root.handlers)
    setup_logging(tmp_path, debug=False)
    assert len(python_root.handlers) == len(before) + 1
    close_logging()
    assert python_root.handlers == before
    assert logging.getLogger(ROOT_LOGGER_NAME).handlers == []


def test_close_releases_the_log_file(tmp_path: Path) -> None:
    """На Windows открытый файл лога не даёт удалить папку: close_logging обязан его закрыть."""
    logs_dir: Path = tmp_path / "logs"
    logs_dir.mkdir()
    setup_logging(logs_dir, debug=False)
    get_logger("main").info("run_started version=0.1.0")
    close_logging()
    shutil.rmtree(logs_dir)
    assert not logs_dir.exists()


def test_setup_twice_leaves_one_set_of_handlers(tmp_path: Path) -> None:
    """Повторный setup сначала закрывает прежний: строка не двоится в двух файлах."""
    setup_logging(tmp_path, debug=False)
    second: Path = setup_logging(tmp_path, debug=False)
    assert len(logging.getLogger(ROOT_LOGGER_NAME).handlers) == 1
    get_logger("main").info("run_started version=0.1.0")
    close_logging()
    assert "run_started" in second.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "-"), ("", "****"), ("ab", "****"), ("abc", "****"), ("abcd", "****-abcd"), (STREAM_KEY, "****-qrst")],
)
def test_mask_stream_key_shows_at_most_the_last_four_characters(value: str | None, expected: str) -> None:
    """Ключ потока в логе — только маской; полностью он есть только в keys.txt (§6, инвариант 6)."""
    assert mask_stream_key(value) == expected


def test_masked_key_does_not_contain_the_key(tmp_path: Path) -> None:
    log_path: Path = setup_logging(tmp_path, debug=False)
    get_logger("youtube").info("stream_key=%s", mask_stream_key(STREAM_KEY))
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert STREAM_KEY not in text and "stream_key=****-qrst" in text


# --- SecretScrubber: последний рубеж §7.4 на случай чужой библиотеки


SHEETS_ID: str = "1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg"
FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-secret/viewform"


def _vault_with_two_secrets() -> Vault:
    """Сейф с двумя полями: так его отдаст VaultStore боевому запуску."""
    return (
        Vault.empty()
        .with_field(
            SecretField.SHEETS_ID,
            SecretValue(field=SecretField.SHEETS_ID, value=SHEETS_ID),
            VaultOrigin.SUPPLIED,
        )
        .with_field(
            SecretField.KEY_FORM_URL,
            SecretValue(field=SecretField.KEY_FORM_URL, value=FORM_URL),
            VaultOrigin.OWN,
        )
    )


def _secret_of(vault: Vault, field: SecretField) -> SecretValue:
    secret: SecretValue | None = vault.get(field)
    assert secret is not None
    return secret


def test_a_secret_in_the_template_does_not_reach_the_log(tmp_path: Path) -> None:
    """LOGGER.info(url): значение пришло самим шаблоном записи."""
    vault: Vault = _vault_with_two_secrets()
    log_path: Path = setup_logging(tmp_path, debug=False)
    install_secret_filter(vault)
    get_logger("sheets").info(f"sheet_read {SHEETS_ID}")
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert SHEETS_ID not in text
    assert _secret_of(vault, SecretField.SHEETS_ID).log_label in text


def test_a_secret_in_an_argument_does_not_reach_the_log(tmp_path: Path) -> None:
    """LOGGER.info("url=%s", url): значение пришло аргументом, целиком оно есть только после подстановки."""
    vault: Vault = _vault_with_two_secrets()
    log_path: Path = setup_logging(tmp_path, debug=False)
    install_secret_filter(vault)
    get_logger("form").info("form_ready url=%s questions=%d", FORM_URL, 6)
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert FORM_URL not in text
    assert _secret_of(vault, SecretField.KEY_FORM_URL).log_label in text
    assert "questions=6" in text                      # остальная часть записи не пострадала


def test_a_secret_written_by_a_third_party_logger_does_not_reach_the_log(tmp_path: Path) -> None:
    """Тот случай, ради которого фильтр и нужен: URL печатает googleapiclient, а не наш код."""
    vault: Vault = _vault_with_two_secrets()
    log_path: Path = setup_logging(tmp_path, debug=False)
    install_secret_filter(vault)
    logging.getLogger(THIRD_PARTY_LOGGER).warning("URL being requested: GET %s", f"https://x/{SHEETS_ID}?alt=json")
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert SHEETS_ID not in text
    assert _secret_of(vault, SecretField.SHEETS_ID).log_label in text


def test_the_filter_cleans_rather_than_drops_records(tmp_path: Path) -> None:
    """Фильтр не выбрасывает записи: строк в логе столько же, сколько без него."""
    vault: Vault = _vault_with_two_secrets()
    log_path: Path = setup_logging(tmp_path, debug=False)
    install_secret_filter(vault)
    get_logger("sheets").info("sheet_read id=%s", SHEETS_ID)
    get_logger("form").info("form_ready url=%s", FORM_URL)
    get_logger("main").info("run_finished exit_code=0")
    close_logging()
    lines: list[str] = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert SHEETS_ID not in "".join(lines) and FORM_URL not in "".join(lines)


def test_both_secrets_are_scrubbed_from_one_record(tmp_path: Path) -> None:
    vault: Vault = _vault_with_two_secrets()
    log_path: Path = setup_logging(tmp_path, debug=False)
    install_secret_filter(vault)
    get_logger("sheets").info("pair %s and %s", SHEETS_ID, FORM_URL)
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert SHEETS_ID not in text and FORM_URL not in text
    assert _secret_of(vault, SecretField.SHEETS_ID).log_label in text
    assert _secret_of(vault, SecretField.KEY_FORM_URL).log_label in text


def test_a_record_with_mismatched_arguments_still_loses_the_secret(tmp_path: Path) -> None:
    """Шаблон и аргументы не сошлись: запись не отформатируется, но значение не должно попасть и в stderr."""
    vault: Vault = _vault_with_two_secrets()
    setup_logging(tmp_path, debug=False)
    install_secret_filter(vault)
    record: logging.LogRecord = logging.LogRecord(
        name="livecraft.sheets",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="sheet_read id=%s range=%s",
        args=(SHEETS_ID,),
        exc_info=None,
    )
    scrubber: SecretScrubber = SecretScrubber(vault.secrets())
    assert scrubber.filter(record) is True
    assert SHEETS_ID not in str(record.msg)
    assert SHEETS_ID not in str(record.args)
    close_logging()


def test_close_logging_takes_the_filter_away_with_the_handlers(tmp_path: Path) -> None:
    """Фильтр живёт на обработчиках: сняли обработчики — фильтра нет, и новый запуск ставит его заново."""
    vault: Vault = _vault_with_two_secrets()
    setup_logging(tmp_path, debug=False)
    install_secret_filter(vault)
    close_logging()
    second: Path = setup_logging(tmp_path, debug=False)
    get_logger("sheets").info("sheet_read id=%s", SHEETS_ID)
    close_logging()
    assert SHEETS_ID in second.read_text(encoding="utf-8")   # без фильтра значение проходит — он и нужен


def test_an_empty_vault_hangs_no_filter_and_does_not_fail(tmp_path: Path) -> None:
    log_path: Path = setup_logging(tmp_path, debug=False)
    before: int = len(logging.getLogger(ROOT_LOGGER_NAME).handlers[0].filters)
    install_secret_filter(Vault.empty())
    assert len(logging.getLogger(ROOT_LOGGER_NAME).handlers[0].filters) == before
    get_logger("main").info("run_started version=0.1.0")
    close_logging()
    assert "run_started" in log_path.read_text(encoding="utf-8")


def test_the_filter_is_hung_on_every_handler_once(tmp_path: Path) -> None:
    """Обработчики логгера livecraft и корневого логгера Python — одни и те же объекты: фильтр по одному."""
    setup_logging(tmp_path, debug=True)
    install_secret_filter(_vault_with_two_secrets())
    for handler in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        assert sum(isinstance(item, SecretScrubber) for item in handler.filters) == 1
    for handler in logging.getLogger().handlers:
        assert sum(isinstance(item, SecretScrubber) for item in handler.filters) <= 1
    close_logging()


def test_debug_terminal_output_loses_the_secret_too(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """С --debug сырой лог идёт в stderr — фильтр стоит и там."""
    setup_logging(tmp_path, debug=True)
    install_secret_filter(_vault_with_two_secrets())
    get_logger("sheets").info("sheet_read id=%s", SHEETS_ID)
    err: str = capsys.readouterr().err
    close_logging()
    assert SHEETS_ID not in err and "sheets-plan(" in err
