"""Страница ответа формы: подтверждение по структуре, маркер и заголовок — только в лог."""
from __future__ import annotations

from app.form.response_page import CONFIRMATION_MARKERS, ResponsePage
from app.form.transport import HttpAnswer
from app.tests.fixtures.form import REFUSAL_PAGE, RESPONSE_URL, SUCCESS_PAGE

ENGLISH_CONFIRMATION: str = "Your response has been recorded."


def _page(status: int, text: str) -> ResponsePage:
    return ResponsePage.of(HttpAnswer(status=status, text=text, url=RESPONSE_URL))


def test_real_success_page_is_confirmed() -> None:
    page: ResponsePage = _page(200, SUCCESS_PAGE)
    assert page.is_confirmed
    assert (page.entry_fields, page.has_fbzx, page.is_form_page) == (0, False, True)
    assert page.marker == "your response has been recorded"


def test_real_refusal_page_is_not_confirmed() -> None:
    """Страница отказа — перерисованный раздел формы: в ней есть поле entry. и скрытый fbzx."""
    page: ResponsePage = _page(400, REFUSAL_PAGE)
    assert not page.is_confirmed
    assert page.entry_fields >= 1 and page.has_fbzx
    assert page.marker is None
    assert page.title == "TEST_Регистрация стрима (Stream registration)"


def test_refusal_page_is_not_confirmed_even_with_http_200() -> None:
    """Решает структура страницы: отказ с кодом 200 — тоже не подтверждение."""
    assert not _page(200, REFUSAL_PAGE).is_confirmed


def test_success_page_without_any_marker_is_confirmed() -> None:
    page: ResponsePage = _page(200, SUCCESS_PAGE.replace(ENGLISH_CONFIRMATION, "Válaszát rögzítettük."))
    assert (page.is_confirmed, page.marker) == (True, None)


def test_marker_is_a_log_signal_only_and_ignores_case() -> None:
    page: ResponsePage = _page(200, "<div>YOUR RESPONSE HAS BEEN RECORDED</div>")
    assert page.marker == "your response has been recorded"
    assert not page.is_confirmed                                  # не страница формы — не доставка
    assert all(marker == marker.lower() and not marker.endswith(".") for marker in CONFIRMATION_MARKERS)
