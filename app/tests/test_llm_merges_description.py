from __future__ import annotations

import pytest

from app.llm.merges.agenda import AgendaLexicon
from app.llm.merges.description import HomoglyphMap, HookParagraph, MergedDescription
from app.llm.merges.hook import BAD_HOOK_PATTERNS_RESOURCE, BadHookLexicon
from app.llm.merges.quality import QualityRequest, QualityRules
from app.resources.loader import TextResource
from app.texts.description_marks import CtaLexicon

# Список донора `merge_validation_helpers.py::_BAD_HOOK_PATTERNS` (restreamer 35324e5) — в том же порядке.
DONOR_BAD_HOOK_PATTERNS: tuple[str, ...] = (
    "наш канал", "наш некомерційний", "наш неприбутковий", "наш неприбутков", "не просуває", "не пропагує",
    "не продвигает", "не пропагандирует", "our channel", "our nonprofit", "if you want more", "if you'd like more",
    "хочете продовження", "хотите продолжения", "write in the comments", "напишіть у коментарях",
    "напишите в комментариях", "поширюйте", "поділіться", "приєднуйтесь", "stay tuned", "поделитесь",
    "смотрите полный", "watch the full", "follow the full", "если вы смотрели стрим",
    "если вы смотрели стрим, напишите",
    "матеріал подано", "матеріал представлено", "матеріал підготовлено", "матеріал розміщено",
    "цей матеріал є частиною", "цей матеріал подано", "матеріал публікується", "материал подан",
    "материал представлен", "материал подготовлен", "материал публикуется", "этот материал является частью",
    "данный материал", "this material is presented", "this material is part of", "this content is presented",
    "this video is part of", "presented as part of", "in the context of", "within the context of",
    "as part of an ongoing", "в контексті", "в рамках обговорення", "в рамках обсуждения", "в рамках розслідування",
    "в рамках расследования", "в рамках документального",
)
LONG_HOOK: str = (
    "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours "
    "and why the aid corridor schedule shifts across all active fronts."
)
MIXED_ZHAIVORONOK: str = "Жайворон" + "o" + "k"       # две последние буквы латинские
CYRILLIC_ZHAIVORONOK: str = "Жайворон" + "о" + "к"


def echo(text: str) -> bool:
    return MergedDescription(text).has_hook_echo_in_body


def repaired(text: str) -> str | None:
    result: MergedDescription | None = MergedDescription(text).hook_echo_repaired()
    return None if result is None else result.text


# --- ресурс признаков негодного первого абзаца
def test_bad_hook_resource_is_the_donor_list() -> None:
    assert BadHookLexicon.load().patterns == DONOR_BAD_HOOK_PATTERNS


def test_bad_hook_resource_starts_with_the_origin_comment() -> None:
    first_line: str = TextResource(BAD_HOOK_PATTERNS_RESOURCE).path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "# перенесено из restreamer merge_validation_helpers.py::_BAD_HOOK_PATTERNS"


# --- донор: test_audit_run_regressions.py::test_soft_cta_opener_is_rejected_by_merge_stage_validator (часть bad hook)
def test_soft_cta_opener_is_a_bad_hook() -> None:
    soft_cta_line: str = (
        "Если вы смотрели стрим, напишите, какие эпизоды февраля 2026 года показались вам самыми показательными."
    )
    assert BadHookLexicon.load().matches(soft_cta_line)


@pytest.mark.parametrize(
    ("paragraph", "expected"),
    [("OUR   CHANNEL is great", True), ("Факти дня про енергетику", False), ("", False), ("   ", False)],
)
def test_bad_hook_matches_ignoring_case_and_spacing(paragraph: str, expected: bool) -> None:
    assert BadHookLexicon.load().matches(paragraph) is expected


# --- донор: test_hook_echo_detection.py::HookEchoDetectionTests
def test_exact_duplicate_hook_is_an_echo() -> None:
    hook: str = "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours."
    assert echo(f"{hook}\n\n{hook}\n\n🔹 New facts appear only here.")


def test_rephrased_hook_in_body_opener_is_an_echo() -> None:
    assert echo(
        "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours and why the aid "
        "corridor schedule shifts.\n\n"
        "The sanctions vote changes transport risk windows in the next 48 hours and shifts the aid corridor schedule, "
        "so we map those operational consequences in detail.\n\n"
        "🔹 Additional source facts start after this line."
    )


def test_different_hook_and_body_is_not_an_echo() -> None:
    assert not echo(
        "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours.\n\n"
        "🔹 Geneva timeline updates with new WHO cargo batches and hospital routing details.\n\n"
        "🔹 Lviv repair crews report transformer queue reductions after midnight."
    )


def test_short_paragraphs_are_skipped() -> None:
    assert not echo("Short opener line.\n\nShort opener line.\n\nAnother short line.")


def test_common_prefix_over_half_is_an_echo() -> None:
    hook: str = "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours."
    body_opener: str = hook[: int(len(hook) * 0.55)] + " — additional context that makes this paragraph long enough to pass the 40-char gate."
    assert echo(f"{hook}\n\n{body_opener}\n\n🔹 Some new bullet fact here.")


def test_last_sentence_echo_in_body_opener() -> None:
    assert echo(
        "«Він робив нам уколи і прикасався до нас» — 32 жертви Якуба Яхла вперше дають свідчення на камеру. "
        "⚖ Центральний конфлікт — безпека дітей і питання відповідальності.\n\n"
        "⚖ Центральний конфлікт — безпека дітей і питання відповідальності.\n"
        "🔹 Юридичне оновлення у справі.\n🔹 Свідчення дітей та міжнародний тиск.\n\n"
        "Дивіться ефір і діліться думками."
    )


def test_hook_thesis_not_repeated() -> None:
    assert not echo(
        "«Він робив нам уколи і прикасався до нас» — 32 жертви Якуба Яхла вперше дають свідчення на камеру. "
        "⚖ Центральний конфлікт — безпека дітей і питання відповідальності.\n\n"
        "🔹 Юридичне оновлення: суд визнав докази неналежними.\n🔹 Свідчення дітей та міжнародний тиск.\n\n"
        "Дивіться ефір і діліться думками."
    )


# --- донор: test_hook_echo_detection.py::HookEchoRepairTests
def test_repair_removes_echo_paragraph_and_preserves_bullets() -> None:
    result: str | None = repaired(f"{LONG_HOOK}\n\n{LONG_HOOK}\n\n🔹 Geneva timeline updated.\n🔹 Lviv repair crews active.")
    assert result is not None
    assert result.startswith(LONG_HOOK)
    assert "🔹 Geneva timeline updated." in result
    assert len(result.split("\n\n")) == 2


def test_repair_trims_echo_prefix_within_paragraph() -> None:
    echo_with_bullets: str = f"{LONG_HOOK}\n🔹 New cargo batch update.\n🔹 Hospital routing adjusted."
    result: str | None = repaired(f"{LONG_HOOK}\n\n{echo_with_bullets}\n\nSubscribe for more updates.")
    assert result is not None
    assert "🔹 New cargo batch update." in result
    assert f"{LONG_HOOK}\n🔹" not in result


def test_repair_returns_none_when_no_bullets_after_echo() -> None:
    prose: str = "This is another prose paragraph with no bullet markers at all in it anywhere."
    assert repaired(f"{LONG_HOOK}\n\n{LONG_HOOK}\n\n{prose}") is None


def test_repair_returns_none_for_short_description() -> None:
    assert repaired(f"{LONG_HOOK}\n\n{LONG_HOOK}") is None


def test_repair_handles_compact_two_paragraph_echo() -> None:
    first_bullet: str = "🔹 Geneva timeline updated with new WHO cargo batches and routing details."
    echo_with_bullets: str = f"{LONG_HOOK}\n{first_bullet}\n🔹 Lviv repair crews report transformer queue reductions after midnight."
    result: str | None = repaired(f"{LONG_HOOK}\n\n{echo_with_bullets}")
    assert result is not None
    assert not echo(result)
    assert result.count(first_bullet) == 1


def test_repair_handles_bullet_fused_into_hook() -> None:
    hook_clean: str = "«Он делал нам уколы и прикасался к нам» — свидетельства жертв Якуба Яхла становятся срочными."
    fused_bullet: str = "🔹 Встреча с послом Лазаро Ньяланду обсуждает обвинения"
    echo_body: str = (
        f"{hook_clean}\n{fused_bullet}\n"
        "🔹 По имеющимся данным, расследование расширяется на другие страны.\n"
        "📌 Сообщение со встречи дипломатического корпуса."
    )
    result: str | None = repaired(f"{hook_clean} {fused_bullet}\n\n{echo_body}\n\n#Танзания #ЯкубЯхл")
    assert result is not None
    assert not echo(result)
    assert result.count("🔹 Встреча с послом Лазаро Ньяланду") == 1
    assert "🔹 По имеющимся данным" in result
    assert "📌 Сообщение со встречи" in result


def test_repair_compact_two_paragraphs_without_bullets_returns_none() -> None:
    prose_echo: str = (
        f"{LONG_HOOK} — this is a prose restatement of the hook without any bullet markers "
        "and without any new facts or additional content that would allow repair."
    )
    assert repaired(f"{LONG_HOOK}\n\n{prose_echo}") is None


def test_repair_preserves_bullets_in_echo_paragraph_and_later_paragraphs() -> None:
    echo_with_bullets: str = f"{LONG_HOOK}\n🔹 Bullet from echo paragraph.\n🔹 Second bullet from echo paragraph."
    later: str = "🔹 Bullet from paragraph three.\n🔹 Another later fact."
    result: str | None = repaired(f"{LONG_HOOK}\n\n{echo_with_bullets}\n\n{later}")
    assert result is not None
    assert "🔹 Bullet from echo paragraph." in result
    assert "🔹 Bullet from paragraph three." in result


def test_no_echo_means_no_repair() -> None:
    assert repaired("First paragraph that is long enough to be checked by the rule.\n\n🔹 Different fact entirely here now.") is None


# --- вклеенный в тезис пункт
def test_hook_paragraph_multiline_split() -> None:
    assert HookParagraph("Hook line.\nmore\n🔹 bullet").split_trailing_bullet() == ("Hook line.\nmore", "🔹 bullet")
    assert HookParagraph("Hook line.\nmore").split_trailing_bullet() == ("Hook line.\nmore", None)


def test_hook_paragraph_single_line_split_needs_a_sentence_end_after_the_40th_char() -> None:
    long_sentence: str = "This hook sentence is definitely longer than forty chars."
    assert HookParagraph(f"{long_sentence} 🔹 fused").split_trailing_bullet() == (long_sentence, "🔹 fused")
    assert HookParagraph("Short. 🔹 fused").split_trailing_bullet() == ("Short. 🔹 fused", None)
    assert HookParagraph(f"{long_sentence} word 🔹 fused").split_trailing_bullet()[1] is None


# --- призыв в начале и служебные строки
def test_opener_cta_looks_only_at_the_first_non_empty_line() -> None:
    cta: CtaLexicon = CtaLexicon.load()
    assert MergedDescription("  \nПідпишіться на канал.\n\nДалі.").opens_with_cta(cta)
    assert not MergedDescription("Факти дня.\nПідпишіться на канал.").opens_with_cta(cta)
    assert not MergedDescription("").opens_with_cta(cta)


def test_meta_lines_are_removed() -> None:
    text: str = "Title: x\r\nBody line.  \n  sources : a\nDescription:y\nTitles: kept"
    assert MergedDescription(text).without_meta_lines().text == "Body line.\nTitles: kept"


def test_duplicate_paragraphs_rule() -> None:
    assert MergedDescription("Same long text here enough tokens.\n\nSame long text here enough tokens.").has_duplicate_paragraphs
    assert not MergedDescription("Hi.\n\nHi.").has_duplicate_paragraphs


def test_repr_hides_the_text() -> None:
    assert "secret words" not in repr(MergedDescription("secret words"))


# --- донор: test_script_mix_repair.py
def test_zhaivoronok_uk() -> None:
    repair = MergedDescription(f"🔹 Тарас Іванов, Владислав {MIXED_ZHAIVORONOK} («Вікіпедія»)").with_homoglyphs_repaired("uk")
    assert repair.tokens_repaired == 1
    assert repair.tokens_before == (MIXED_ZHAIVORONOK,)
    assert repair.tokens_after == (CYRILLIC_ZHAIVORONOK,)
    assert MIXED_ZHAIVORONOK not in repair.description.text
    assert CYRILLIC_ZHAIVORONOK in repair.description.text
    assert repair.tokens_after[0][-1] == "к" and repair.tokens_after[0][-2] == "о"


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Hello twork world", "uk"),
        ("Звичайний український текст", "uk"),
        ("Кириллица" + "def", "uk"),
        ("Some english text with cyrillicа", "en"),
        ("", "uk"),
    ],
)
def test_texts_that_are_not_repaired(text: str, language: str) -> None:
    repair = MergedDescription(text).with_homoglyphs_repaired(language)
    assert repair.tokens_repaired == 0
    assert repair.description.text == text


def test_russian_i_and_c_repair() -> None:
    repair = MergedDescription("текст" + "i" + "c").with_homoglyphs_repaired("ru")
    assert repair.tokens_repaired == 1
    assert repair.tokens_after == ("текст" + "и" + "с",)


def test_two_mixed_tokens_both_repaired() -> None:
    mixed: str = "К" + "o" + "зел"
    repair = MergedDescription(f"{MIXED_ZHAIVORONOK} і {mixed}").with_homoglyphs_repaired("uk")
    assert repair.tokens_repaired == 2
    assert CYRILLIC_ZHAIVORONOK in repair.description.text and "Козел" in repair.description.text
    assert repair.log_line == f"tokens_repaired=2 before_tokens={MIXED_ZHAIVORONOK},{mixed} after_tokens={CYRILLIC_ZHAIVORONOK},Козел"


def test_latin_i_depends_on_the_language() -> None:
    assert HomoglyphMap.of("uk").repair_token("Кiев") == "Кіев"   # type: ignore[union-attr]
    assert HomoglyphMap.of("ru").repair_token("Кiев") == "Киев"   # type: ignore[union-attr]
    assert HomoglyphMap.of("en") is None


def test_token_with_equal_latin_and_cyrillic_is_left() -> None:
    assert HomoglyphMap.of("uk").repair_token("Кo") is None   # type: ignore[union-attr]


def test_no_repair_log_line() -> None:
    assert MergedDescription("x").with_homoglyphs_repaired("uk").log_line == "tokens_repaired=0 before_tokens=none after_tokens=none"


# --- 3.11b: перегруженные пункты, повестка, выгрузка по источникам (донор: quality_diagnostics.py, merge_text_utils.py)
def test_very_long_bullet_is_overloaded_without_names() -> None:
    """Донор: test_compact_bullet_overflow.py::test_very_long_bullet_is_overloaded_without_names."""
    assert MergedDescription(f"Hook paragraph.\n\n🔹 {'слово ' * 85}\n🔹 Short bullet.").overloaded_bullet_count >= 1


def test_medium_bullet_without_names_is_not_overloaded() -> None:
    """Донор: test_compact_bullet_overflow.py::test_medium_bullet_without_names_is_not_overloaded."""
    assert MergedDescription(f"Hook paragraph.\n\n🔹 {'слово ' * 50}\n🔹 Short.").overloaded_bullet_count == 0


def test_medium_bullet_with_three_names_is_overloaded() -> None:
    names: str = "John Smith, Maria Ivanova and Luigi Corvaglia"
    long_bullet: str = f"📌 {names} {'discuss the budget ' * 15}"
    plain_bullet: str = f"- {names} {'discuss the budget ' * 15}"
    assert MergedDescription(f"Hook.\n\n{long_bullet}\n{plain_bullet}").overloaded_bullet_count == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hook.\n\nЧто в этом стриме:\n🔹 a", True),
        ("Hook.\n\n  In   this stream — budget", True),
        ("Hook.\n\nПро що поговоримо", True),
        ("Hook.\n\nwhat’s in this stream!", True),
        ("Hook.\n\nIn this stream you'll see:", False),
        ("In this streamline", False),
    ],
)
def test_agenda_heading(text: str, expected: bool) -> None:
    assert MergedDescription(text).contains_agenda_heading(AgendaLexicon.load()) is expected


def test_agenda_lexicon_is_the_donor_file() -> None:
    assert AgendaLexicon.load().headings == (
        "что в этом стриме", "в этом выпуске", "о чем поговорим", "що в цьому стрімі", "про що поговоримо",
        "what's in this stream", "what’s in this stream", "in this stream",
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Source 1: a\nSource 2: b", True),
        ("video 1) a\r\nVIDEO 2 - b", True),
        ("We compare source 1 and source 2 today.", True),
        ("Source 1: a only", False),
        ("Video 1 and source 2", False),
    ],
)
def test_per_source_dump(text: str, expected: bool) -> None:
    assert MergedDescription(text).looks_like_per_source_dump is expected


def test_quality_normalized_returns_a_new_description() -> None:
    result = MergedDescription("Hook paragraph with enough words here.\n\n- one point\n- two point").quality_normalized(
        QualityRequest(language="en"), QualityRules.load()
    )
    assert result.description.text == "Hook paragraph with enough words here.\n\n🔹 one point\n🔹 two point"
    assert result.normalization_applied is True
