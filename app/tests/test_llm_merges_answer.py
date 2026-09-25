from __future__ import annotations

import json
import logging
import random

import pytest

from app.llm.backend import LlmResponse
from app.llm.merges import answer as answer_module
from app.llm.merges import description as description_module
from app.llm.merges.answer import AnswerParseMode, MergeAnswer
from app.llm.merges.layout import TailBlock
from app.llm.merges.reject import MergeReject, MergeRejectCode, MergeRejectStage
from app.tests.conftest import REPO_ROOT
from app.tools.code_standard.module_shape import TopLevelNames
from app.tools.code_standard.source import SourceKey, SourceTree

TWO_PARAGRAPHS: str = "Paragraph one.\n\nParagraph two."


def response(text: str = "", structured: dict[str, object] | None = None) -> LlmResponse:
    return LlmResponse(text=text, structured=structured, model="gpt-test", incomplete_reason="", usage=None, attempts=1)


def parse(text: str, max_body_paragraphs: int = 4) -> MergeAnswer | MergeReject:
    return MergeAnswer.parse(response(text), max_body_paragraphs)


def accepted(text: str, max_body_paragraphs: int = 4) -> MergeAnswer:
    result: MergeAnswer | MergeReject = parse(text, max_body_paragraphs)
    assert isinstance(result, MergeAnswer), result
    return result


def rejected(text: str, max_body_paragraphs: int = 4) -> MergeReject:
    result: MergeAnswer | MergeReject = parse(text, max_body_paragraphs)
    assert isinstance(result, MergeReject), result
    return result


def body(count: int) -> str:
    return "\n\n".join(f"Body paragraph {index} with facts." for index in range(1, count + 1))


# --- донор: test_merge_contract_parser.py
def test_valid_single_object_json_passes() -> None:
    answer: MergeAnswer = accepted('{"title":"Final title","description":"Paragraph one.\\n\\nParagraph two."}')
    assert answer.title == "Final title"
    assert answer.paragraph_count == 2
    assert answer.parse_mode is AnswerParseMode.DIRECT
    assert answer.model == "gpt-test"
    assert answer.description.text == TWO_PARAGRAPHS


def test_missing_required_key_fails() -> None:
    reject: MergeReject = rejected('{"title":"Final title"}')
    assert reject.code is MergeRejectCode.MISSING_KEYS
    assert reject.detail == "description"


def test_extra_key_fails() -> None:
    reject: MergeReject = rejected(
        '{"title":"Final title","description":"Paragraph one.\\n\\nParagraph two.","cta":"Watch live."}'
    )
    assert reject.code is MergeRejectCode.EXTRA_KEYS
    assert reject.detail == "cta"


@pytest.mark.parametrize(
    ("payload_text", "detail"),
    [
        ('{"title ":"Final title","description":"Paragraph one.\\n\\nParagraph two."}', "title"),
        ('{"title":"Final title"," description":"Paragraph one.\\n\\nParagraph two."}', "description"),
        ('{"Title":"Final title","description":"Paragraph one.\\n\\nParagraph two."}', "title"),
    ],
)
def test_exact_keys_reject_whitespace_and_case_variants(payload_text: str, detail: str) -> None:
    reject: MergeReject = rejected(payload_text)
    assert reject.code is MergeRejectCode.MISSING_KEYS
    assert reject.detail == detail


def test_multi_variant_response_is_invalid() -> None:
    """У донора ключ-вариант ловится проверкой лишних ключей раньше отдельного правила вариантов."""
    reject: MergeReject = rejected(
        '{"variants":[{"title":"A"}],"description":"Paragraph one.\\n\\nParagraph two.","title":"A"}'
    )
    assert reject.code is MergeRejectCode.EXTRA_KEYS
    assert reject.detail == "variants"


def test_title_is_limited_to_99_characters() -> None:
    answer: MergeAnswer = accepted(json.dumps({"title": "A" * 120, "description": TWO_PARAGRAPHS}))
    assert len(answer.title) == 99


def test_title_whitespace_is_collapsed() -> None:
    assert accepted(json.dumps({"title": "  A \n\t B  ", "description": TWO_PARAGRAPHS})).title == "A B"


def test_title_with_emoji_is_rejected() -> None:
    reject: MergeReject = rejected('{"title":"Final title 🔥","description":"Paragraph one.\\n\\nParagraph two."}')
    assert reject.code is MergeRejectCode.INVALID_TITLE
    assert reject.detail == "emoji"


def test_allowed_tail_blocks_do_not_break_body_paragraph_count() -> None:
    answer: MergeAnswer = accepted(
        '{"title":"Final title","description":"Hook paragraph.\\n\\n'
        'In this stream you will see:\\n🔹 point one\\n🔹 point two\\n\\n'
        'https://youtu.be/aaaaaaaaaaa\\n\\n'
        '🌐 Official links:\\nhttps://example.org\\n\\n'
        '#stream #topic"}'
    )
    assert answer.paragraph_count == 2
    assert "https://youtu.be/aaaaaaaaaaa" in answer.description.text
    assert "🌐 Official links:" in answer.description.text


def test_body_paragraph_count_ignores_realistic_service_tail_mass() -> None:
    answer: MergeAnswer = accepted(
        '{"title":"Final title","description":"Hook paragraph with the core conflict and verified context.\\n\\n'
        "In this stream you\\u0027ll see:\\n🔹 point one\\n🔹 point two\\n🔹 point three\\n\\n"
        "Paragraph three keeps the broader context and timeline grounded in the sources.\\n\\n"
        "Paragraph four closes with the practical context and concrete next developments.\\n\\n"
        "https://youtu.be/aaaaaaaaaaa\\nhttps://www.youtube.com/watch?v=bbbbbbbbbbb\\n\\n"
        "🌐 Official links:\\nhttps://example.org/official\\nhttps://allatra.org/resource\\n\\n"
        '#stream #topic"}'
    )
    assert answer.paragraph_count == 4
    assert len([part for part in answer.description.text.split("\n\n") if part.strip()]) == 7
    assert "https://www.youtube.com/watch?v=bbbbbbbbbbb" in answer.description.text
    assert "#stream #topic" in answer.description.text


def test_body_only_recovery_accepts_near_good_body() -> None:
    answer: MergeAnswer = accepted(
        '{"title":"Recovered title","description":"Paragraph one.\\n\\nParagraph two.\\n\\n'
        'Paragraph three.\\n\\nParagraph four.\\n\\nParagraph five.\\n\\n#topic"}'
    )
    assert answer.paragraph_count == 4
    assert "Paragraph one." in answer.description.text
    assert "#topic" in answer.description.text
    assert answer.tail_recovery_applied


def test_body_that_stays_invalid_after_tail_split_and_recovery_is_rejected() -> None:
    reject: MergeReject = rejected(
        '{"title":"Bad title","description":"Paragraph one.\\n\\nParagraph two.\\n\\n'
        'Paragraph three.\\n\\nParagraph four.\\n\\nParagraph five.\\n\\n'
        'Paragraph six.\\n\\nParagraph seven.\\n\\nParagraph eight.\\n\\n'
        'Paragraph nine.\\n\\n#topic"}'
    )
    assert reject.code is MergeRejectCode.PARAGRAPH_OVERFLOW
    assert reject.detail == "body_paragraphs=9 allowed=2..4"


def test_realistic_merge_output_with_five_service_tail_paragraphs_is_accepted() -> None:
    answer: MergeAnswer = accepted(
        '{"title":"Conference and initiative briefing tonight","description":"Tonight we track the conference agenda and initiative updates with concrete facts.\\n\\n'
        "In this stream you\\u0027ll see:\\n🔹 conference timeline and priorities\\n🎤 speaker remarks and context\\n✅ practical next steps for viewers\\n\\n"
        "The second body paragraph keeps the legal and organizational context tied to the sources.\\n\\n"
        "The third body paragraph highlights what changed since the previous stream and why it matters.\\n\\n"
        "https://youtu.be/aaaaaaaaaaa\\n\\n"
        "https://www.youtube.com/watch?v=bbbbbbbbbbb\\n\\n"
        "🌐 Official links:\\nhttps://interfaithconf.org/about\\nhttps://spiritualdiplomats.org/resources\\n\\n"
        '#conference #initiative"}'
    )
    assert answer.paragraph_count == 4
    assert answer.layout.raw_paragraph_count == 8
    assert answer.layout.body_paragraph_count_after_recovery == 4
    assert answer.layout.tail_blocks == (
        TailBlock.YOUTUBE_LINKS, TailBlock.YOUTUBE_LINKS, TailBlock.OFFICIAL_LINKS, TailBlock.HASHTAGS
    )


# --- донор: test_opener_cta_raw_check.py
def test_opener_cta_is_rejected_before_tail_recovery() -> None:
    reject: MergeReject = rejected(
        '{"title":"CTA opener","description":"'
        "Підпишіться та напишіть у коментарях, яку тему розібрати наступною. "
        "Далі ми пояснюємо наслідки рішення, що впливає на логістику і терміни. "
        "Окремо розкриваємо позиції сторін і практичні кроки для глядачів. "
        "Наприкінці фіксуємо, що змінюється вже сьогодні."
        '"}'
    )
    assert reject.code is MergeRejectCode.CTA_AS_FIRST_PARAGRAPH
    assert reject.reason_codes == ("cta_as_first_paragraph",)


# --- донор: test_audit_run_regressions.py::test_tail_separation_recovery_increments_paragraph_recovery_used (разбор)
def test_tail_recovery_is_reported() -> None:
    raw_text: str = json.dumps(
        {
            "title": "Recovered title",
            "description": (
                "Paragraph one explains the key conflict with concrete evidence.\n\n"
                "Paragraph two keeps the timeline and actors explicit.\n\n"
                "Paragraph three adds downstream effects and risks.\n\n"
                "Paragraph four records practical implications for the audience.\n\n"
                "Paragraph five captures additional verified details from the same broadcast."
            ),
        },
        ensure_ascii=False,
    )
    assert accepted(raw_text, 4).tail_recovery_applied


# --- донор: MergeExecutor._enforce_single_step_overflow_policy (предварительная проверка)
def test_limit_seven_rejects_exactly_eight_body_paragraphs_before_recovery() -> None:
    reject: MergeReject = rejected(json.dumps({"title": "Expanded", "description": body(8)}), 7)
    assert reject.code is MergeRejectCode.PARAGRAPH_OVERFLOW
    assert reject.detail == "body_paragraphs=8 allowed=2..7"


def test_limit_seven_collapses_nine_body_paragraphs() -> None:
    answer: MergeAnswer = accepted(json.dumps({"title": "Expanded", "description": body(9)}), 7)
    assert answer.paragraph_count == 7
    assert answer.tail_recovery_applied


def test_limit_four_collapses_five_body_paragraphs_without_the_preflight() -> None:
    assert accepted(json.dumps({"title": "Compact", "description": body(5)}), 4).paragraph_count == 4


def test_preflight_runs_before_key_checks() -> None:
    """Донор проверяет перебор на единицу раньше ключей: лишний ключ при восьми абзацах — перебор, а не лишний ключ."""
    reject: MergeReject = rejected(json.dumps({"title": "T", "description": body(8), "cta": "x"}), 7)
    assert reject.code is MergeRejectCode.PARAGRAPH_OVERFLOW


# --- каждый код достижим разбором
REACHABILITY_CASES: list[tuple[LlmResponse, MergeRejectCode]] = [
    (response("not json"), MergeRejectCode.NOT_JSON_OBJECT),
    (response('{"title": "T"}'), MergeRejectCode.MISSING_KEYS),
    (response(json.dumps({"title": "T", "description": TWO_PARAGRAPHS, "x": 1})), MergeRejectCode.EXTRA_KEYS),
    (response(json.dumps({"title": "  ", "description": TWO_PARAGRAPHS})), MergeRejectCode.INVALID_TITLE),
    (response(json.dumps({"title": "T", "description": None})), MergeRejectCode.INVALID_DESCRIPTION),
    (response(json.dumps({"title": "T", "description": "Subscribe now.\n\nTwo."})), MergeRejectCode.CTA_AS_FIRST_PARAGRAPH),
    (
        response(json.dumps({"title": "T", "description": "\n\n".join(["Same long text here with enough tokens."] * 5)})),
        MergeRejectCode.DUPLICATE_PARAGRAPH,
    ),
    (response(json.dumps({"title": "T", "description": "Title: only meta"})), MergeRejectCode.DESCRIPTION_EMPTY),
    (response(json.dumps({"title": "T", "description": "Only one."})), MergeRejectCode.PARAGRAPH_UNDERFLOW),
    (response(json.dumps({"title": "T", "description": body(12)})), MergeRejectCode.PARAGRAPH_OVERFLOW),
    (response(json.dumps({"title": ["T"], "description": TWO_PARAGRAPHS})), MergeRejectCode.UNEXPECTED),
]


@pytest.mark.parametrize(("result", "code"), REACHABILITY_CASES)
def test_every_code_is_reachable(result: LlmResponse, code: MergeRejectCode) -> None:
    reject: MergeAnswer | MergeReject = MergeAnswer.parse(result, 4)
    assert isinstance(reject, MergeReject)
    assert reject.code is code


def test_all_codes_are_covered_by_the_reachability_cases() -> None:
    """Случаи покрывают ровно коды шага разбора ответа (`MergeRejectCode.stages`)."""
    assert {code for _, code in REACHABILITY_CASES} == {
        code for code in MergeRejectCode if MergeRejectStage.ANSWER in code.stages
    }


def test_list_value_detail_names_the_key() -> None:
    reject: MergeReject = rejected(json.dumps({"title": "T", "description": {"a": 1}}))
    assert reject.code is MergeRejectCode.UNEXPECTED
    assert reject.detail == "invalid_type:description"


def test_structured_payload_wins_over_text() -> None:
    answer: MergeAnswer | MergeReject = MergeAnswer.parse(
        response("garbage", structured={"title": "S", "description": TWO_PARAGRAPHS}), 4
    )
    assert isinstance(answer, MergeAnswer)
    assert answer.parse_mode is AnswerParseMode.STRUCTURED


def test_single_object_inside_text_is_a_candidate() -> None:
    answer: MergeAnswer = accepted('Answer: {"title":"T","description":"One.\\n\\nTwo."} end')
    assert answer.parse_mode is AnswerParseMode.CANDIDATE


def test_meta_lines_are_stripped_from_the_accepted_description() -> None:
    answer: MergeAnswer = accepted(json.dumps({"title": "T", "description": "One.\nTitle: meta\n\nTwo."}))
    assert answer.description.text == "One.\n\nTwo."


def test_deeply_nested_json_is_not_an_object_and_does_not_raise() -> None:
    assert rejected("[" * 100000 + "]" * 100000).code is MergeRejectCode.NOT_JSON_OBJECT


def test_parse_never_raises_on_arbitrary_text() -> None:
    rng: random.Random = random.Random(311)
    alphabet: str = '{}[]":,\\ntitledescription 🔹#🌐https://youtu.be/ абв\n\r\t0123'
    for _ in range(3000):
        text: str = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 200)))
        assert isinstance(MergeAnswer.parse(response(text), rng.choice([4, 7])), (MergeAnswer, MergeReject))
        wrapped: str = json.dumps({"title": text[:50], "description": text})
        assert isinstance(MergeAnswer.parse(response(wrapped), rng.choice([4, 7])), (MergeAnswer, MergeReject))


def test_log_lines_have_donor_keys_and_no_text(caplog: pytest.LogCaptureFixture) -> None:
    secret_words: str = "Уникальнаяфразаописания"
    description: str = f"{secret_words} one.\n\n{secret_words} two.\n\n#tag"
    with caplog.at_level(logging.INFO, logger="livecraft.llm"):
        accepted(json.dumps({"title": "Название эфира", "description": description}, ensure_ascii=False))
        rejected(json.dumps({"title": "T", "description": "\n\n".join([f"{secret_words} long text here tokens."] * 6)}))
    messages: list[str] = [record.getMessage() for record in caplog.records]
    assert any(line.startswith("merge_payload_parsed model=gpt-test parse_mode=direct title_length=14 ") for line in messages)
    assert any("merge_description_tail_analysis" in line and "final_status=accepted" in line for line in messages)
    assert any("final_status=rejected reject_reason=duplicate_paragraph" in line for line in messages)
    assert any(line.startswith("merge_answer_rejected model=gpt-test reason_code=duplicate_paragraph") for line in messages)
    assert all(secret_words not in line and "Название" not in line for line in messages)


def test_repr_of_the_answer_hides_texts() -> None:
    answer: MergeAnswer = accepted(json.dumps({"title": "Скрытое название", "description": TWO_PARAGRAPHS}))
    assert "Скрытое" not in repr(answer) and "Paragraph one" not in repr(answer)


def test_a_paragraph_count_reject_carries_the_count() -> None:
    overflow: MergeReject = rejected(json.dumps({"title": "T", "description": body(9)}))
    assert overflow.code is MergeRejectCode.PARAGRAPH_OVERFLOW and overflow.paragraph_count == 9
    underflow: MergeReject = rejected(json.dumps({"title": "T", "description": "Only one."}))
    assert underflow.code is MergeRejectCode.PARAGRAPH_UNDERFLOW and underflow.paragraph_count == 1
    preflight: MergeReject = rejected(json.dumps({"title": "T", "description": body(8)}), max_body_paragraphs=7)
    assert preflight.code is MergeRejectCode.PARAGRAPH_OVERFLOW and preflight.paragraph_count == 8
    assert rejected("not json").paragraph_count is None


def test_the_emoji_pattern_has_one_source() -> None:
    """Шаблон объявлен на верхнем уровне ровно одного модуля app; остальные берут его импортом."""
    declared: list[str] = [
        module.key.text for module in SourceTree.from_root(REPO_ROOT).production
        if "EMOJI_PATTERN" in TopLevelNames(module).names()
    ]
    assert declared == [SourceKey.of("app/llm/merges/description.py").text]
    assert answer_module.EMOJI_PATTERN is description_module.EMOJI_PATTERN
