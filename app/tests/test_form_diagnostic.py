"""Страница формы в logs\\: имя по отметке и хешу ссылки, ключ потока — только маской."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.form.diagnostic import DiagnosticKind, DiagnosticPage, FormDiagnostic
from app.observability.log_event import LogArea
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.form import KYIV_WINTER, SHORT_URL, STREAM_KEY
from app.tests.fixtures.logs import LogCapture

MOMENT: datetime = datetime(2027, 3, 16, 12, 0, 5, tzinfo=KYIV_WINTER)


def test_page_is_saved_under_the_stamp_kind_and_link_hash(tmp_path: Path) -> None:
    diagnostic: FormDiagnostic = FormDiagnostic(tmp_path / "logs", StoppedClock.at(MOMENT))
    saved: Path | None = diagnostic.save(DiagnosticPage(DiagnosticKind.PAGE, SHORT_URL, "<html>страница</html>"))
    assert saved is not None and saved.parent == tmp_path / "logs"
    assert saved.name.startswith("16-03-2027_120005_form_page_") and len(saved.stem.rsplit("_", 1)[-1]) == 8
    assert saved.read_text(encoding="utf-8") == "<html>страница</html>"


def test_stream_key_is_masked_before_writing(tmp_path: Path) -> None:
    page: DiagnosticPage = DiagnosticPage(DiagnosticKind.RESPONSE, SHORT_URL, f"key={STREAM_KEY};", STREAM_KEY)
    saved: Path | None = FormDiagnostic(tmp_path, StoppedClock.at(MOMENT)).save(page)
    assert saved is not None and saved.read_text(encoding="utf-8") == "key=****-abcd;"


def test_page_that_cannot_be_written_is_a_log_line_not_a_crash(tmp_path: Path) -> None:
    blocker: Path = tmp_path / "logs"
    blocker.write_text("not a folder", encoding="utf-8")
    with LogCapture.on(LogArea.FORM) as capture:
        saved: Path | None = FormDiagnostic(blocker, StoppedClock.at(MOMENT)).save(
            DiagnosticPage(DiagnosticKind.PAGE, SHORT_URL, "x")
        )
    assert saved is None
    assert any(message.startswith("form_diagnostic_not_saved ") for message in capture.messages())
