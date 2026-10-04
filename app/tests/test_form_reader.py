"""Чтение формы по ссылке: GET с редиректом, повторы, отказы и страница для разбора в logs\\."""
from __future__ import annotations

from pathlib import Path

import requests

from app.form.failure import FormFailure, FormProblem
from app.form.structure import FormStructure
from app.tests.fixtures.form import FBZX, SHORT_URL, FakeFormResponse, FakeForms, build_html, build_payload


def _failure(fake: FakeForms, tmp_path: Path) -> FormFailure:
    result: FormStructure | FormFailure = fake.reader(tmp_path / "logs").read(SHORT_URL)
    assert isinstance(result, FormFailure)
    return result


def test_page_is_read_with_redirects_by_the_short_link(tmp_path: Path) -> None:
    fake: FakeForms = FakeForms.answering(build_html())
    assert isinstance(fake.reader(tmp_path).read(SHORT_URL), FormStructure)
    [call] = fake.gets
    assert call.url == SHORT_URL and call.options["allow_redirects"] is True


def test_page_without_script_is_saved_for_analysis(tmp_path: Path) -> None:
    failure: FormFailure = _failure(FakeForms.answering("<html>нет скрипта</html>"), tmp_path)
    assert (failure.problem, failure.form) == (FormProblem.STRUCTURE_UNREADABLE, SHORT_URL)
    assert failure.diagnostic is not None and failure.diagnostic.exists()
    assert failure.diagnostic.name.startswith("16-03-2027_120000_form_page_")
    assert "нет скрипта" in failure.diagnostic.read_text(encoding="utf-8")


def test_broken_json_is_also_unreadable(tmp_path: Path) -> None:
    html: str = "<html><script>var FB_PUBLIC_LOAD_DATA_ = [не json];</script></html>"
    assert _failure(FakeForms.answering(html), tmp_path).problem is FormProblem.STRUCTURE_UNREADABLE


def test_empty_question_list_is_unreadable(tmp_path: Path) -> None:
    failure: FormFailure = _failure(FakeForms.answering(build_html(build_payload([]))), tmp_path)
    assert failure.problem is FormProblem.STRUCTURE_UNREADABLE and failure.diagnostic is not None


def test_server_error_is_retried_then_transport_failure(tmp_path: Path) -> None:
    fake: FakeForms = FakeForms.answering(FakeFormResponse("", status_code=503))
    failure: FormFailure = _failure(fake, tmp_path)
    assert failure.problem is FormProblem.TRANSPORT_FAILED and failure.detail.endswith("503")
    assert len(fake.gets) == 5
    assert [int(delay) for delay in fake.sleeps] == [2, 4, 8, 16]


def test_network_failure_and_server_error_are_retried(tmp_path: Path) -> None:
    fake: FakeForms = FakeForms.answering(
        requests.ConnectionError("нет сети"), FakeFormResponse("", status_code=502), build_html()
    )
    structure: FormStructure | FormFailure = fake.reader(tmp_path).read(SHORT_URL)
    assert isinstance(structure, FormStructure) and structure.fbzx == FBZX
    assert len(fake.gets) == 3 and len(fake.sleeps) == 2


def test_client_error_is_not_retried(tmp_path: Path) -> None:
    fake: FakeForms = FakeForms.answering(FakeFormResponse("", status_code=404))
    failure: FormFailure = _failure(fake, tmp_path)
    assert (failure.problem, failure.log_detail) == (FormProblem.TRANSPORT_FAILED, "HTTP 404")
    assert len(fake.gets) == 1 and fake.sleeps == []


def test_request_error_that_is_not_a_network_failure_is_not_retried(tmp_path: Path) -> None:
    fake: FakeForms = FakeForms.answering(requests.exceptions.InvalidURL("bad"))
    failure: FormFailure = _failure(fake, tmp_path)
    assert failure.problem is FormProblem.TRANSPORT_FAILED and "InvalidURL" in failure.log_detail
    assert failure.detail == "" and len(fake.gets) == 1 and fake.sleeps == []
