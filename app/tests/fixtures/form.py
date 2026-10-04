"""Форма ключей в тестах: массив FB_PUBLIC_LOAD_DATA_, подделка GET и POST, настройки формы, сохранённые страницы.

К настоящему Google Forms тесты не ходят: обмен строится только на `FakeForms.http`, где `get` и `post` — подделки,
а паузы повторов записываются, а не выжидаются. Настройки формы — раздел `form` поставочного livecraft.json со ссылкой
теста. Сохранённые страницы тренировочной формы (app\\tests\\data\\form\\) — с заглушкой вместо id формы: по id любой
пишет строки в форму, а репозиторий публичный.
"""
from __future__ import annotations

import dataclasses
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config.files import ShippedSettings
from app.config.settings import FormSettings
from app.form.book import FormBook
from app.form.diagnostic import FormDiagnostic
from app.form.question import PageQuestion, QuestionKind, SectionJump
from app.form.reader import FormReader
from app.form.structure import FormStructure
from app.form.transport import FormHttp
from app.tests.fixtures.clock import StoppedClock

FORM_DATA: Path = Path(__file__).resolve().parents[1] / "data" / "form"
VIEW_URL: str = "https://docs.google.com/forms/d/e/ABC/viewform"
RESPONSE_URL: str = "https://docs.google.com/forms/d/e/ABC/formResponse?hl=en"
SHORT_URL: str = "https://forms.gle/UjVo2gftZdHsEdpZ7"
OTHER_URL: str = "https://forms.gle/OtherForm"
FBZX: str = "-1234567890"
# Идентификаторы разрывов как в тренировочной форме 13-09-2026: большие числа, а не номера разделов.
YOUTUBE_SECTION_ID: int = 1281939289
FACEBOOK_SECTION_ID: int = 643928232
TRAINING_FORM_TITLE: str = "TEST_Регистрация стрима (Stream registration)"
KYIV_WINTER: timezone = timezone(timedelta(hours=2))
READ_MOMENT: datetime = datetime(2027, 3, 16, 12, 0, tzinfo=KYIV_WINTER)
STREAM_KEY: str = "abcd-abcd-abcd-abcd-abcd"
# Настоящие страницы ответа тренировочной формы (опыт planers 13-09-2026 16:27): успех — отправка с HTTP 200,
# отказ — отправка без обязательного «Stream-URL (YT)» с HTTP 400; страница отказа — перерисованная форма целиком.
SUCCESS_PAGE: str = (FORM_DATA / "form_response_success.html").read_text(encoding="utf-8")
REFUSAL_PAGE: str = (FORM_DATA / "form_response_refusal.html").read_text(encoding="utf-8")


def question(entry_id: int, title: str, type_code: int, options: list[Any] | None = None) -> list[Any]:
    """Элемент формы в раскладке FB_PUBLIC_LOAD_DATA_: [id, название, описание, вид, [[entry, варианты, обяз.]]]."""
    return [entry_id, title, None, type_code, [[entry_id, options, 1]]]


def page_break(section_id: int, title: str) -> list[Any]:
    """Разрыв страницы: item[0] — id раздела, на него ссылаются переходы вариантов."""
    return [section_id, title, None, 8, None]


def default_items() -> list[Any]:
    """Тренировочная форма: общий раздел, раздел YouTube и раздел Facebook."""
    return [
        question(1, "Язык стрима ( Language of stream)", 2, [["Русский ( Russian)"], ["Английский ( English)"]]),
        question(2, "Название канала ( Channel name)", 0),
        question(
            3,
            "Время стрима ( Stream time )",
            2,
            [["17.03.2027 Дата стрима (время стрима указано в объявлении)"], ["18.03.2027 Дата стрима"]],
        ),
        question(
            4, "Платформа (Platform)", 2, [["You Tube", None, YOUTUBE_SECTION_ID], ["Facebook", None, FACEBOOK_SECTION_ID]]
        ),
        page_break(YOUTUBE_SECTION_ID, "YouTube"),
        question(5, "You Tube Stream Key", 0),
        question(6, "Stream-URL (YT)", 2, [["rtmp://a.rtmp.youtube.com/live2/"], ["rtmp://x.rtmp.youtube.com/live2/"]]),
        page_break(FACEBOOK_SECTION_ID, "Facebook"),
        question(7, "Facebook Stream Key", 0),
    ]


def build_payload(items: list[Any] | None = None) -> list[Any]:
    return [None, [None, items if items is not None else default_items()], None, FBZX]


def build_html(payload: list[Any] | None = None, with_fbzx: bool = True) -> str:
    body: str = json.dumps(payload if payload is not None else build_payload())
    hidden: str = f'<input type="hidden" name="fbzx" value="{FBZX}">' if with_fbzx else ""
    return f"<html><body>{hidden}<script>var FB_PUBLIC_LOAD_DATA_ = {body};</script></body></html>"


def form_settings(url: str = SHORT_URL, **changes: Any) -> FormSettings:
    """Раздел `form` поставочного livecraft.json со ссылкой теста и изменёнными полями `changes`."""
    return dataclasses.replace(ShippedSettings().settings.form, url=url, **changes)


def as_text_question(question: PageQuestion) -> PageQuestion:
    """Тот же вопрос, но с вводом текста вместо вариантов."""
    return dataclasses.replace(question, kind=QuestionKind.TEXT, options=())


def with_question(structure: FormStructure, old: PageQuestion, new: PageQuestion) -> FormStructure:
    """Та же структура, где вопрос `old` заменён вопросом `new`."""
    questions: tuple[PageQuestion, ...] = tuple(new if item == old else item for item in structure.questions)
    return dataclasses.replace(structure, questions=questions)


def with_navigation(structure: FormStructure, navigation: dict[str, dict[str, SectionJump]]) -> FormStructure:
    """Та же структура с другими переходами вариантов — так разбор «ошибается» ради проверки маршрута."""
    return dataclasses.replace(structure, navigation=navigation)


@dataclass
class FakeFormResponse:
    """Ответ requests: код, текст и конечный адрес (после редиректа)."""

    text: str
    status_code: int = 200
    url: str = VIEW_URL


@dataclass(frozen=True)
class FormCall:
    """Одно обращение: адрес и именованные параметры requests."""

    url: str
    options: dict[str, Any]

    @property
    def body(self) -> dict[str, list[str]]:
        data: object = self.options["data"]
        assert isinstance(data, dict)
        return data


@dataclass
class FakeForms:
    """Подделка Google Forms: ответы по порядку (ответ, исключение requests или обрыв запуска); последний ответ
    повторяется, когда ответы кончились. Обращения GET и POST и паузы повторов записываются."""

    outcomes: list[FakeFormResponse | BaseException]
    gets: list[FormCall] = field(default_factory=list)
    posts: list[FormCall] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)

    @classmethod
    def answering(cls, *outcomes: FakeFormResponse | BaseException | str) -> FakeForms:
        """Строка — страница с ответом 200."""
        return cls([FakeFormResponse(item) if isinstance(item, str) else item for item in outcomes])

    def get(self, url: str, **options: Any) -> FakeFormResponse:
        self.gets.append(FormCall(url, options))
        return self._next()

    def post(self, url: str, **options: Any) -> FakeFormResponse:
        self.posts.append(FormCall(url, options))
        return self._next()

    @property
    def http(self) -> FormHttp:
        return FormHttp(get=self.get, post=self.post, rng=random.Random(0), sleep=self.sleeps.append)

    def reader(self, logs_dir: Path) -> FormReader:
        return FormReader(http=self.http, diagnostic=FormDiagnostic(logs_dir, StoppedClock.at(READ_MOMENT)))

    def book(self, logs_dir: Path) -> FormBook:
        return FormBook(reader=self.reader(logs_dir))

    def _next(self) -> FakeFormResponse:
        outcome: FakeFormResponse | BaseException = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
