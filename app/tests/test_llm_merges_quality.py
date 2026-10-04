from __future__ import annotations

import logging
import random

import pytest

from app.llm.merges import quality as quality_module
from app.llm.merges.description import MergedDescription
from app.llm.merges.quality import (
    BulletNormalization,
    CompactTrim,
    QualityDiagnostics,
    QualityGateStatus,
    QualityNormalization,
    QualityReasonCode,
    QualityRequest,
)
from app.llm.merges.merge_rules import MergeLexicons
from app.llm.merges.rules import COMPACT_BULLET_MAX
from app.observability.log_event import LogArea
from app.tests.conftest import REPO_ROOT
from app.tests.fixtures.logs import LogCapture
from app.tools.code_standard.source import ModuleSource, SourceTree

LEXICONS: MergeLexicons = MergeLexicons.load()
CLEAN_EN: str = (
    "This stream breaks down the budget decision and explains what it means for the regions and for families.\n\n"
    "In this stream you'll see:\n"
    "🔹 budget amendments and the final vote\n"
    "🔹 practical next steps for viewers\n\n"
    "🌐 Official links:\n"
    "https://example.org\n\n"
    "Watch the stream and share your thoughts."
)


def normalized(description: str, language: str, title: str = "", source_count: int = 0) -> QualityNormalization:
    request: QualityRequest = QualityRequest(language=language, title=title, source_count=source_count)
    return QualityNormalization.of(MergedDescription(description), request, LEXICONS)


def bullet_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith(("🔹 ", "📌 ", "🎤 "))]


# --- короткие служебные строки приводятся к языку блока
def test_short_service_lines_are_normalized_to_expected_language() -> None:
    result: QualityNormalization = normalized(
        "Це короткий вступ про головну тему!\n\n"
        "In this stream you'll see:\n"
        "📌 перший акцент\n"
        "🔹 другий пункт\n\n"
        "🌐 Official links:\n"
        "https://example.org\n\n"
        "Watch the stream and share your thoughts. #подія",
        "uk",
    )
    assert "У цьому стрімі ви побачите:" in result.description.text
    assert "🌐 Офіційні ресурси:" in result.description.text
    assert "Дивіться ефір і діліться думками. #подія" in result.description.text
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.NEEDS_NORMALIZATION
    assert result.diagnostics.wrong_language_heading_detected is True
    assert QualityReasonCode.OFFICIAL_LINKS_HEADING_MISMATCH in result.diagnostics.semantic_gate_reason_codes


# --- число акцентных значков ограничено, лишние снимаются
def test_every_bullet_gets_the_bullet_marker_whatever_the_model_put() -> None:
    """Все пункты описания — 🔹 (§14 решение 34): прежние акцентные маркеры, 🌐 у пункта, флаг и любой эмодзи."""
    result: QualityNormalization = normalized(
        "Focused hook paragraph with enough detail to stay valid!\n\n"
        "In this stream you'll see:\n📌 first\n🎤 second\n🎥 third\n⚖️ fourth\n🌐 fifth\n🇺🇦 sixth\n✨ seventh",
        "en",
    )
    assert bullet_lines(result.description.text) == [
        "🔹 first", "🔹 second", "🔹 third", "🔹 fourth", "🔹 fifth", "🔹 sixth", "🔹 seventh"
    ]
    assert (result.diagnostics.neutral_bullets_count, result.diagnostics.headings_count) == (7, 0)


# --- между блоками описания — ровно одна пустая строка
def test_block_spacing_is_stabilized() -> None:
    source: str = (
        "This hook stays factual and readable with enough context!\n"
        "In this stream you'll see:\n"
        "🎤 Pastor Vitaliy Orlov comments on the community response\n"
        "🔹 relief updates continue\n"
        "🌐 Official links:\n"
        "https://example.org\n"
        "Watch the stream and share your thoughts. #update"
    )
    result: QualityNormalization = normalized(source, "en")
    assert "\n\nIn this stream you'll see:\n" in result.description.text
    assert "\n\n🌐 Official links:\nhttps://example.org\n\n" in result.description.text
    assert "🔹 Pastor Vitaliy Orlov comments on the community response" in result.description.text
    assert result.diagnostics.block_spacing_ok is False
    assert QualityReasonCode.MISSING_BLOCK_SPACING in result.diagnostics.semantic_gate_reason_codes
    assert result.description.text != source


# --- кириллица внутри английского тела — смесь алфавитов, жёсткий отказ
def test_script_mix_in_english_body_is_hard_reject() -> None:
    result: QualityNormalization = normalized(
        "This hook stays factual and readable with enough context about the main topic!\n\n"
        "In this stream you'll see:\n"
        "🔹 budget timeline and mиксed contamination inside the main bullet\n"
        "🔹 verified operational follow-up for the next debate window",
        "en",
    )
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.HARD_REJECT
    assert QualityReasonCode.SCRIPT_MIX_CONTAMINATION in result.diagnostics.semantic_gate_reason_codes
    assert "mиксed" in result.diagnostics.script_mix_suspects


# --- разрешённые бренды и ссылки в кириллическом тексте — не смесь алфавитов
def test_allowed_brands_and_urls_are_not_script_mix() -> None:
    result: QualityNormalization = normalized(
        "Цей вступ лишається фактичним і зрозумілим для глядачів.\n\n"
        "У цьому стрімі ви побачите:\n"
        "🔹 OpenAI та YouTube згадуються як бренди без зайвої мовної кари\n"
        "🔹 NASA і AI залишаються допустимими абревіатурами\n\n"
        "🌐 Офіційні ресурси:\n"
        "https://example.org/openai\n\n"
        "Дивіться ефір і діліться думками. #update",
        "uk",
    )
    assert result.diagnostics.script_mix_detected is False
    assert QualityReasonCode.SCRIPT_MIX_CONTAMINATION not in result.diagnostics.semantic_gate_reason_codes


# --- домен без схемы в кириллическом тексте — не смесь алфавитов
def test_bare_domain_in_cyrillic_text_is_not_script_mix() -> None:
    result: QualityNormalization = normalized(
        "После решения украинского суда антикультист дал ссылку на lstv.co.uk как ключевой эпизод.\n\n"
        "⚖ Конфликт фактов и манипуляций: что стоит за антикультовой риторикой.\n"
        "🔹 Луиджи Корвальо, член правления ФЕКРИС: реакция на реабилитацию.\n"
        "🔹 Техническая верификация lstv.co.uk: инфраструктура хостинга.\n"
        "🔹 Следы в открытых источниках и вывод расследования.\n\n"
        "Оставляйте комментарии по фактам. #расследование",
        "ru",
    )
    assert result.diagnostics.script_mix_detected is False
    assert QualityReasonCode.SCRIPT_MIX_CONTAMINATION not in result.diagnostics.semantic_gate_reason_codes


# --- многоуровневый домен без схемы — не смесь алфавитов
def test_multi_level_bare_domain_is_not_script_mix() -> None:
    result: QualityNormalization = normalized(
        "Ця новина була опублікована на news.bbc.co.uk та підтверджена.\n\n"
        "У цьому стрімі ви побачите:\n🔹 пункт один\n🔹 пункт два\n\nДивіться ефір. #новини",
        "uk",
    )
    assert result.diagnostics.script_mix_detected is False


# --- слово из двух алфавитов в названии ловится
def test_mixed_script_token_in_title_is_caught() -> None:
    result: QualityNormalization = normalized(
        "Антикульт под лупой: что стоит за риторикой.\n\n🔹 пункт один\n🔹 пункт два\n\nОставляйте комментарии. #тест",
        "ru",
        title="Антикульт под лупой: сайт lstv.co.uk, FЕКРИС и тени",
    )
    assert result.diagnostics.script_mix_detected is True
    assert QualityReasonCode.SCRIPT_MIX_CONTAMINATION in result.diagnostics.semantic_gate_reason_codes
    assert "FЕКРИС" in result.diagnostics.script_mix_suspects
    assert "lstv" not in result.diagnostics.script_mix_suspects


# --- тезис явно не на языке блока — жёсткий отказ
def test_wrong_language_hook_is_hard_reject() -> None:
    result: QualityNormalization = normalized(
        "This English hook is clearly not in the expected block language and stays unchanged.\n\n"
        "У цьому стрімі ви побачите:\n🔹 пункт один\n🔹 пункт два",
        "uk",
    )
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.HARD_REJECT
    assert QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE in result.diagnostics.semantic_gate_reason_codes
    assert result.diagnostics.language_consistency_ok is False


def test_a_hook_whose_language_is_undecided_is_not_a_language_reject() -> None:
    """Язык тезиса не определился (`unknown`: в тезисе нет букв) — это не «язык явно не тот»: правило одно со
    служебными строками. Отказа по языку нет; раньше такой тезис давал жёсткий отказ."""
    result: QualityNormalization = normalized(
        "2026-10-16 19:00 — 12 345 / 67 890 — 100 %!\n\nУ цьому стрімі ви побачите:\n🔹 пункт один\n🔹 пункт два",
        "uk",
    )
    assert result.diagnostics.hook_language_detected == "unknown"
    assert QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE not in result.diagnostics.semantic_gate_reason_codes
    assert result.diagnostics.language_consistency_ok is True
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.OK


# --- пункт в роли вводной строки не получает второй маркер
def test_bullet_is_not_prefixed_twice() -> None:
    result: QualityNormalization = normalized(
        "Hook paragraph with a question?\n\n🔹 First bullet as lead-in\n🔹 Second bullet\n🔹 Third bullet", "en"
    )
    assert all(not line.strip().startswith("🔹 🔹") for line in result.description.text.splitlines())


# --- сжатый контракт: лишние пункты снимаются, порядок сохраняется
def compact_description(bullet_count: int, lead_in: bool = False) -> tuple[str, list[str]]:
    texts: list[str] = [f"Point {index} stays in original order with concrete detail." for index in range(1, bullet_count + 1)]
    lines: list[str] = ["Tonight we map concrete outcomes from linked source agendas.", ""]
    if lead_in:
        lines.append("In this stream you'll see:")
    lines.extend(f"🔹 {text}" for text in texts)
    return "\n".join(lines), texts


def test_eight_bullets_two_sources_trimmed_to_seven() -> None:
    description, texts = compact_description(8)
    with LogCapture.on(LogArea.LLM, logging.INFO) as capture:
        result: QualityNormalization = normalized(description, "en", source_count=2)
    assert len(bullet_lines(result.description.text)) == 7
    assert all(text in result.description.text for text in texts[:7])
    assert texts[7] not in result.description.text
    assert result.description.text != description
    assert capture.messages() == [
        "merge_compact_bullet_trimmed source_count=2 bullets_before=8 bullets_after=7 cap=7"
    ]


def test_seven_bullets_two_sources_unchanged() -> None:
    description, texts = compact_description(7)
    result: QualityNormalization = normalized(description, "en", source_count=2)
    assert len(bullet_lines(result.description.text)) == 7
    assert result.description.text == description


def test_eight_bullets_three_sources_unchanged() -> None:
    description, texts = compact_description(8)
    result: QualityNormalization = normalized(description, "en", source_count=3)
    assert len(bullet_lines(result.description.text)) == 8
    assert all(text in result.description.text for text in texts)


def test_unknown_source_count_does_not_trim() -> None:
    description, texts = compact_description(8)
    result: QualityNormalization = normalized(description, "en")
    assert len(bullet_lines(result.description.text)) == 8


def test_trim_preserves_lead_in_line() -> None:
    description, texts = compact_description(8, lead_in=True)
    result: QualityNormalization = normalized(description, "en", source_count=2)
    assert "In this stream you'll see:" in result.description.text
    assert len(bullet_lines(result.description.text)) == 7
    assert texts[7] not in result.description.text


def test_compact_trim_keeps_non_bullet_lines_in_place() -> None:
    lines: tuple[str, ...] = ("Lead:", *(f"🔹 p{index}" for index in range(9)), "tail line")
    trim: CompactTrim = CompactTrim.of(lines, source_count=1)
    assert trim.applied is True
    assert trim.lines == ("Lead:", *(f"🔹 p{index}" for index in range(COMPACT_BULLET_MAX)), "tail line")
    assert (trim.bullets_before, trim.bullets_after) == (9, 7)


# --- простой маркер пункта снимается, первое слово пункта остаётся
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- first point here", "🔹 first point here"),
        ("1) third one", "🔹 third one"),
        ("– sanctions timeline", "🔹 sanctions timeline"),
        ("- word", "🔹 word"),
        ("plain line without marker", "🔹 plain line without marker"),
    ],
)
def test_plain_marker_is_replaced_without_losing_the_first_word(line: str, expected: str) -> None:
    bullets: BulletNormalization = BulletNormalization.of(("Lead-in:", line))
    assert bullets.lines == ("Lead-in:", expected)


def test_first_non_bullet_line_only_collapses_spaces() -> None:
    bullets: BulletNormalization = BulletNormalization.of(("In  this   stream:", "🔹 point"))
    assert bullets.lines == ("In this stream:", "🔹 point")
    assert bullets.neutral_bullets_count == 1


def test_single_cta_paragraph_is_not_repeated_as_hook_and_cta() -> None:
    result: QualityNormalization = normalized("Subscribe to the channel and leave a comment below #stream", "en")
    assert result.description.text == "Subscribe to the channel and leave a comment below #stream"


def test_second_paragraph_repeating_the_hook_keeps_one_hook() -> None:
    text: str = "Short single paragraph about the budget vote.\n\nShort single paragraph about the budget vote."
    result: QualityNormalization = normalized(text, "en")
    assert result.description.text == text


# --- статусы и коды
def test_clean_description_is_ok_and_unchanged() -> None:
    result: QualityNormalization = normalized(CLEAN_EN, "en")
    assert result.description.text == CLEAN_EN
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.OK
    assert result.diagnostics.semantic_gate_reason_codes == ()


def test_every_reason_code_and_status_is_reachable() -> None:
    samples: list[QualityDiagnostics] = [
        normalized(CLEAN_EN, "en").diagnostics,
        normalized("Hook paragraph long enough here!\n\nWhat we cover:\n📌 a\n🎤 b\n🎥 c\n✅ d", "en").diagnostics,
        normalized(CLEAN_EN.replace("🌐 Official links:", "🌐 Links:"), "en").diagnostics,
        normalized(CLEAN_EN.replace("In this stream you'll see:", "В этом стриме вы увидите:"), "en").diagnostics,
        normalized(CLEAN_EN.replace("budget amendments", "бюджетні поправки"), "en").diagnostics,
        normalized(CLEAN_EN, "uk").diagnostics,
    ]
    codes: set[QualityReasonCode] = {code for sample in samples for code in sample.semantic_gate_reason_codes}
    statuses: set[QualityGateStatus] = {sample.semantic_gate_status for sample in samples}
    assert codes == set(QualityReasonCode)
    assert statuses == set(QualityGateStatus)


def test_reason_codes_keep_their_order() -> None:
    result: QualityNormalization = normalized(
        "This English hook is clearly not in the expected block language and stays unchanged.\n\n"
        "In this stream you'll see:\n📌 a\n🎤 b\n🎥 c\n✅ d\n\n🌐 Links:\nhttps://example.org",
        "uk",
    )
    assert result.diagnostics.semantic_gate_reason_codes == tuple(QualityReasonCode)


def test_quality_normalization_returns_a_new_description() -> None:
    result: QualityNormalization = normalized("Hook paragraph with enough words here.\n\n- one point\n- two point", "en")
    assert result.description.text == "Hook paragraph with enough words here.\n\n🔹 one point\n🔹 two point"


@pytest.mark.parametrize(
    ("codes", "status"),
    [
        ((), QualityGateStatus.OK),
        ((QualityReasonCode.MISSING_BLOCK_SPACING,), QualityGateStatus.NEEDS_NORMALIZATION),
        ((QualityReasonCode.MISSING_BLOCK_SPACING, QualityReasonCode.SCRIPT_MIX_CONTAMINATION), QualityGateStatus.HARD_REJECT),
        ((QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE,), QualityGateStatus.HARD_REJECT),
    ],
)
def test_the_status_follows_from_the_codes(codes: tuple[QualityReasonCode, ...], status: QualityGateStatus) -> None:
    assert QualityGateStatus.of(codes) is status


def test_empty_description_is_not_normalized_but_title_is_checked() -> None:
    result: QualityNormalization = normalized(" \r\n ", "ru", title="Проверка FЕКРИС")
    assert result.description.text == ""
    assert result.diagnostics.block_spacing_ok is True
    assert result.diagnostics.hook_language_detected == "none"
    assert result.diagnostics.script_mix_suspects == ("FЕКРИС",)


def test_windows_line_breaks_are_normalized() -> None:
    result: QualityNormalization = normalized(CLEAN_EN.replace("\n", "\r\n"), "en")
    assert result.description.text == CLEAN_EN


def test_normalization_never_raises_on_arbitrary_text() -> None:
    rng: random.Random = random.Random(3110)
    alphabet: str = "abcXYZабвіїєЁ 🔹📌🌐#@.:-–—*•1)\n\r\t/"
    for _ in range(300):
        text: str = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 160)))
        language: str = rng.choice(["uk", "ru", "en", "de", ""])
        result: QualityNormalization = normalized(text, language, title=text[:20], source_count=rng.randint(0, 4))
        assert isinstance(result.diagnostics.semantic_gate_status, QualityGateStatus)


def test_merge_patterns_have_no_literal_range_characters() -> None:
    """Диапазоны и символы в шаблонах merge записаны экранированием: литеральный символ не виден глазом."""
    package: str = quality_module.__name__.rpartition(".")[0]
    modules: list[ModuleSource] = [module for module in SourceTree.from_root(REPO_ROOT).modules if module.key.package == package]
    assert modules
    offenders: list[tuple[str, int]] = [
        (module.key.parts[-1], number)
        for module in modules
        for number, line in enumerate(module.text.splitlines(), 1)
        if ("compile(" in line or line.lstrip().startswith(('r"', "r'")))
        and any(0x2000 <= ord(char) <= 0x2BFF or ord(char) >= 0x1F000 for char in line)
    ]
    assert offenders == []


# --- маркеры по ролям (§14 решение 34): пункт — 🔹, заголовок — 📌, 🌐 — только блок официальных ссылок

# Ответы модели прогона 28-09-2026 (пакет plan_17-03-2027_18-03-2027_gen28-09-2026-1714.bcast): тезис, пункты, хештеги.
RU_RUN_HOOK: str = (
    "До 40% экономии без потери комфорта: Daikin делает ставку на контроль влажности, а Mitsubishi Heavy Industries "
    "превращает избыток возобновляемой энергии в водород для часов повышенного спроса."
)
RU_RUN_BULLETS: tuple[str, ...] = (
    "🔹 Дзюн Ито в Японском павильоне COP30 наглядно показывает, как влажность меняет ощущение комфорта и почему "
    "регулировать только температуру недостаточно.",
    "🔹 Системы вентиляции и климат-контроля Daikin позволяют поддерживать комфорт в помещениях при меньшем "
    "потреблении электроэнергии.",
    "📌 Дзюн Ито объясняет, почему энергоэффективность зданий критически важна: кондиционирование воздуха остаётся "
    "одной из самых энергоёмких систем в мире.",
    "🔹 Daikin почти 100 лет разрабатывает технологии отопления, вентиляции, кондиционирования и охлаждения.",
    "🔹 Сёго Хасимото рассказывает, как Mitsubishi Heavy Industries объединяет разные технологии производства водорода "
    "в комплексные и масштабируемые решения для чистой энергетики.",
    "🔹 Более чем 140-летний инженерный опыт Mitsubishi Heavy Industries охватывает энергетику, инфраструктуру, "
    "мобильность и промышленные системы; отдельная тема — впечатления Сёго Хасимото от COP30.",
    "🌐 Обе компании подчёркивают значение международного сотрудничества и обмена знаниями для решения климатических "
    "задач.",
)
RU_RUN_HASHTAGS: str = "#COP30 #Энергоэффективность #Водород #КлиматическиеТехнологии"
UK_RUN_HOOK: str = (
    "Викрадені Росією українські діти досі не вдома: Крістофер Андерсон називає їхнє повернення до родин невідкладним "
    "гуманітарним завданням. Водночас допомога прямує туди, де обстріли залишають людей без світла й тепла."
)
UK_RUN_BULLETS: tuple[str, ...] = (
    "🔹 Крістофер Андерсон із Держдепартаменту США — про двопартійну співпрацю, всебічну допомогу Україні та "
    "скоординовані міжнародні зусилля заради справедливого й сталого миру.",
    "🔹 Постійні ракетні й дронові атаки на цивільних, відповідальність Росії за воєнні злочини та довгострокова "
    "міжнародна підтримка відбудови України.",
    "🔹 Сергій Шутов: фонд «Шляхетна справа» від перших днів повномасштабного вторгнення системно підтримує "
    "військовослужбовців і цивільне населення.",
    "🔹 Продукти, теплий одяг, засоби обігріву й медикаменти доставляють постраждалим, зокрема в регіони під постійними "
    "обстрілами та зі складною логістикою.",
    "🔹 Навіть за умов виснаження допомога людям у найбільшій зоні ризику має залишатися пріоритетом, заснованим на "
    "відповідальності та людяності.",
    "🔹 Українці борються за власний дім, свободу й майбутнє дітей; віра, єдність і взаємна підтримка допомагають "
    "суспільству вистояти.",
    "📌 Інтерв’ю записані 5 лютого 2026 року на конференції «Свобода має ім’я — Україна» в Rayburn House Office "
    "Building у Вашингтоні під лідерством пастора Марка Бернса, на платформі руху «АЛЛАТРА», за участю представників "
    "влади США, депутатів Верховної Ради України, військових офіцерів, духовних лідерів і гуманітарних діячів.",
)
UK_RUN_HASHTAGS: str = "#ПідтримкаУкраїни #УкраїнськіДіти #ГуманітарнаДопомога #СвободаУкраїни"


@pytest.mark.parametrize(
    ("hook", "run_bullets", "hashtags", "language"),
    [(RU_RUN_HOOK, RU_RUN_BULLETS, RU_RUN_HASHTAGS, "ru"), (UK_RUN_HOOK, UK_RUN_BULLETS, UK_RUN_HASHTAGS, "uk")],
)
def test_the_run_descriptions_get_the_bullet_marker_on_every_point(
    hook: str, run_bullets: tuple[str, ...], hashtags: str, language: str
) -> None:
    """Прогон 28-09-2026: у ru пункты 🔹🔹📌🔹🔹🔹🌐, у uk — 📌 у последнего; после нормализации — все 🔹."""
    source: str = f"{hook}\n\n" + "\n".join(run_bullets) + f"\n\n{hashtags}"
    result: QualityNormalization = normalized(source, language, source_count=2)
    points: list[str] = [line for line in result.description.text.splitlines() if line.startswith(("🔹", "📌", "🌐"))]
    assert points == ["🔹 " + line.split(" ", 1)[1] for line in run_bullets]
    assert (result.diagnostics.neutral_bullets_count, result.diagnostics.headings_count) == (7, 0)
    assert result.description.text.startswith(hook) and result.description.text.endswith(hashtags)


@pytest.mark.parametrize("line", ["📌 Главное:", "🔹 Главное:", "🎤 Главное:", "- Главное:", "📌   Главное: "])
def test_a_line_ending_with_a_colon_after_the_marker_is_a_heading(line: str) -> None:
    bullets: BulletNormalization = BulletNormalization.of(("Lead-in:", "🔹 first", line, "⚖ second"))
    assert bullets.lines == ("Lead-in:", "🔹 first", "📌 Главное:", "🔹 second")
    assert (bullets.neutral_bullets_count, bullets.headings_count) == (2, 1)


def test_a_heading_is_not_a_point_for_the_count_and_the_compact_trim() -> None:
    points: list[str] = [f"🔹 Point {index} with a concrete detail." for index in range(1, COMPACT_BULLET_MAX + 1)]
    source: str = "Hook paragraph with enough words about the vote!\n\n📌 Главное:\n" + "\n".join(points)
    result: QualityNormalization = normalized(source, "en", source_count=2)
    assert result.description.text == source
    assert (result.diagnostics.neutral_bullets_count, result.diagnostics.headings_count) == (COMPACT_BULLET_MAX, 1)
    trim: CompactTrim = CompactTrim.of(("📌 Главное:", *points), source_count=2)
    assert trim.applied is False and trim.bullets_before == COMPACT_BULLET_MAX


def test_the_first_heading_line_is_a_heading_not_a_lead_in() -> None:
    bullets: BulletNormalization = BulletNormalization.of(("🔹 Главное:", "🎥 point"))
    assert bullets.lines == ("📌 Главное:", "🔹 point")


def test_the_official_links_block_keeps_its_web_marker() -> None:
    result: QualityNormalization = normalized(
        "Hook paragraph with enough words about the vote!\n\n🌐 fact about the web\n🔹 second fact\n\n"
        "🌐 Official links:\nhttps://example.org",
        "en",
    )
    assert result.description.text == (
        "Hook paragraph with enough words about the vote!\n\n🔹 fact about the web\n🔹 second fact\n\n"
        "🌐 Official links:\nhttps://example.org"
    )
