"""Формы запуска: одно чтение на ссылку — и для прочитанной формы, и для той, что не прочиталась."""
from __future__ import annotations

from pathlib import Path

from app.config.settings import FormSettings
from app.form.book import FormBook
from app.form.failure import FormFailure, FormProblem
from app.form.key_form import KeyForm
from app.observability.log_event import LogArea
from app.tests.fixtures.form import OTHER_URL, SHORT_URL, FakeForms, build_html, form_settings
from app.tests.fixtures.logs import LogCapture


def test_second_form_for_the_same_link_does_not_read_again(tmp_path: Path) -> None:
    fake: FakeForms = FakeForms.answering(build_html())
    book: FormBook = fake.book(tmp_path)
    first: KeyForm | FormFailure = book.form_for(form_settings())
    assert isinstance(first, KeyForm)
    assert book.form_for(form_settings()) is first
    assert [call.url for call in fake.gets] == [SHORT_URL]


def test_unreadable_form_gives_the_same_failure_without_a_new_read(tmp_path: Path) -> None:
    fake: FakeForms = FakeForms.answering("<html>нет скрипта</html>")
    book: FormBook = fake.book(tmp_path)
    with LogCapture.on(LogArea.FORM) as capture:
        first: KeyForm | FormFailure = book.form_for(form_settings())
        second: KeyForm | FormFailure = book.form_for(form_settings())
    assert isinstance(first, FormFailure) and first is second
    assert first.problem is FormProblem.STRUCTURE_UNREADABLE
    assert len(fake.gets) == 1
    assert sum(1 for message in capture.messages() if message.startswith("form_unreadable ")) == 1


def test_two_links_are_read_separately(tmp_path: Path) -> None:
    """Два пакета могут вести в разные формы — это нормально."""
    fake: FakeForms = FakeForms.answering(build_html(), build_html())
    book: FormBook = fake.book(tmp_path)
    book.form_for(form_settings())
    book.form_for(form_settings(OTHER_URL))
    assert [call.url for call in fake.gets] == [SHORT_URL, OTHER_URL]


def test_package_with_the_same_link_gets_the_read_form_with_its_own_settings(tmp_path: Path) -> None:
    fake: FakeForms = FakeForms.answering(build_html())
    book: FormBook = fake.book(tmp_path)
    first: KeyForm | FormFailure = book.form_for(form_settings())
    package: FormSettings = form_settings(date_format="%d.%m.%y")
    other: KeyForm | FormFailure = book.form_for(package)
    assert isinstance(first, KeyForm) and isinstance(other, KeyForm)
    assert other.settings == package and other.route is first.route
    assert len(fake.gets) == 1


def test_read_form_is_logged_as_ready_once(tmp_path: Path) -> None:
    book: FormBook = FakeForms.answering(build_html()).book(tmp_path)
    with LogCapture.on(LogArea.FORM) as capture:
        book.form_for(form_settings())
        book.form_for(form_settings())
    assert sum(1 for message in capture.messages() if message.startswith("form_ready ")) == 1
